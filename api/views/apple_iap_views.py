import base64
import json
import logging
import time
from datetime import datetime, timezone
import requests
from django.conf import settings
from django.utils import timezone as dj_timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from api.models import Client, ClientSubscription, Log, AppleIAPTransaction, Plan

logger = logging.getLogger(__name__)

APPLE_VERIFY_RECEIPT_PROD_URL = "https://buy.itunes.apple.com/verifyReceipt"
APPLE_VERIFY_RECEIPT_SANDBOX_URL = "https://sandbox.itunes.apple.com/verifyReceipt"
APP_BUNDLE_ID = "com.uwo.uwoconnect"

# Master mapping from Apple Product IDs to UwoConnect Plan and Cycle
APPLE_PRODUCT_PLAN_MAP = {
    # Full Bundle-prefixed identifiers
    "com.uwo.uwoconnect.starter.monthly": {"plan": "Starter", "billing_cycle": "MONTHLY"},
    "com.uwo.uwoconnect.starter.yearly": {"plan": "Starter", "billing_cycle": "YEARLY"},
    "com.uwo.uwoconnect.starter.annual": {"plan": "Starter", "billing_cycle": "YEARLY"},

    "com.uwo.uwoconnect.growth.monthly": {"plan": "Growth", "billing_cycle": "MONTHLY"},
    "com.uwo.uwoconnect.growth.yearly": {"plan": "Growth", "billing_cycle": "YEARLY"},
    "com.uwo.uwoconnect.growth.annual": {"plan": "Growth", "billing_cycle": "YEARLY"},
    "om.uwo.uwoconnect.growth.annual": {"plan": "Growth", "billing_cycle": "YEARLY"},

    "com.uwo.uwoconnect.advance.monthly": {"plan": "Enterprise", "billing_cycle": "MONTHLY"},
    "com.uwo.uwoconnect.advance.yearly": {"plan": "Enterprise", "billing_cycle": "YEARLY"},
    "com.uwo.uwoconnect.advance.annual": {"plan": "Enterprise", "billing_cycle": "YEARLY"},

    "com.uwo.uwoconnect.enterprise.monthly": {"plan": "Enterprise", "billing_cycle": "MONTHLY"},
    "com.uwo.uwoconnect.enterprise.yearly": {"plan": "Enterprise", "billing_cycle": "YEARLY"},
    "com.uwo.uwoconnect.enterprise.annual": {"plan": "Enterprise", "billing_cycle": "YEARLY"},

    # Also match short identifiers if configured in ASC
    "starter.monthly": {"plan": "Starter", "billing_cycle": "MONTHLY"},
    "starter.yearly": {"plan": "Starter", "billing_cycle": "YEARLY"},
    "starter.annual": {"plan": "Starter", "billing_cycle": "YEARLY"},
    "growth.monthly": {"plan": "Growth", "billing_cycle": "MONTHLY"},
    "growth.yearly": {"plan": "Growth", "billing_cycle": "YEARLY"},
    "growth.annual": {"plan": "Growth", "billing_cycle": "YEARLY"},
    "advance.monthly": {"plan": "Enterprise", "billing_cycle": "MONTHLY"},
    "advance.yearly": {"plan": "Enterprise", "billing_cycle": "YEARLY"},
    "advance.annual": {"plan": "Enterprise", "billing_cycle": "YEARLY"},
    "enterprise.monthly": {"plan": "Enterprise", "billing_cycle": "MONTHLY"},
    "enterprise.yearly": {"plan": "Enterprise", "billing_cycle": "YEARLY"},
    "enterprise.annual": {"plan": "Enterprise", "billing_cycle": "YEARLY"},
}


def resolve_plan_from_product_id(product_id: str):
    """
    Returns (plan_name, billing_cycle) matching the product_id.
    Fallbacks to fuzzy match if exact match not found.
    """
    if product_id in APPLE_PRODUCT_PLAN_MAP:
        cfg = APPLE_PRODUCT_PLAN_MAP[product_id]
        return cfg["plan"], cfg["billing_cycle"]

    pid_lower = product_id.lower()
    cycle = "YEARLY" if ("yearly" in pid_lower or "annual" in pid_lower) else "MONTHLY"

    if "enterprise" in pid_lower or "advanced" in pid_lower:
        return "Enterprise", cycle
    elif "growth" in pid_lower or "pro" in pid_lower:
        return "Growth", cycle
    elif "starter" in pid_lower or "basic" in pid_lower:
        return "Starter", cycle

    return "Starter", cycle


def verify_apple_receipt(receipt_data: str, shared_secret: str = None):
    """
    Validates receipt with Apple verifyReceipt API.
    Tries Production first, and falls back to Sandbox if error code 21007 is returned.
    """
    payload = {
        "receipt-data": receipt_data,
        "exclude-old-transactions": True,
    }
    if shared_secret:
        payload["password"] = shared_secret

    headers = {"Content-Type": "application/json"}
    is_sandbox = False

    try:
        response = requests.post(
            APPLE_VERIFY_RECEIPT_PROD_URL,
            data=json.dumps(payload),
            headers=headers,
            timeout=10,
        )
        res_json = response.json()
        status_code = res_json.get("status", -1)

        # Status 21007: Receipt is from Sandbox, but sent to Production endpoint
        if status_code == 21007:
            is_sandbox = True
            sandbox_resp = requests.post(
                APPLE_VERIFY_RECEIPT_SANDBOX_URL,
                data=json.dumps(payload),
                headers=headers,
                timeout=10,
            )
            res_json = sandbox_resp.json()
            status_code = res_json.get("status", -1)

        return status_code == 0, res_json, is_sandbox
    except Exception as e:
        logger.error(f"[Apple IAP] Receipt verification request error: {e}")
        return False, {"error": str(e)}, False


def parse_apple_timestamp(ts_ms):
    """Parses Apple millisecond timestamp to timezone-aware datetime."""
    if not ts_ms:
        return None
    try:
        sec = float(ts_ms) / 1000.0
        return datetime.fromtimestamp(sec, tz=timezone.utc)
    except Exception:
        return None


class AppleIAPVerifyView(APIView):
    """
    POST /api/payments/apple/verify/
    Verifies Apple In-App Purchase transaction/receipt and activates subscription entitlement.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        client = getattr(user, "client", None)
        if not client:
            return Response(
                {"error": "User does not have an associated organization / workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        receipt_data = request.data.get("receipt_data") or request.data.get("receipt")
        product_id = request.data.get("product_id")
        transaction_id = request.data.get("transaction_id")
        original_transaction_id = request.data.get("original_transaction_id") or transaction_id
        is_sandbox_client = bool(request.data.get("is_sandbox", False))

        if not product_id and not receipt_data:
            return Response(
                {"error": "product_id or receipt_data is required for verification."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        verified = False
        apple_data = {}
        is_sandbox = is_sandbox_client
        purchase_date = dj_timezone.now()
        expires_date = None

        shared_secret = getattr(settings, "APPLE_IAP_SHARED_SECRET", None)

        if receipt_data:
            is_valid, apple_res, is_sandbox = verify_apple_receipt(receipt_data, shared_secret)
            apple_data = apple_res
            if is_valid:
                verified = True
                receipt_info = apple_res.get("receipt", {})
                bundle_id = receipt_info.get("bundle_id")
                if bundle_id and bundle_id != APP_BUNDLE_ID:
                    return Response(
                        {"error": f"Bundle identifier mismatch: {bundle_id}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

                # Extract latest in-app transaction
                latest_transactions = apple_res.get("latest_receipt_info") or receipt_info.get("in_app") or []
                if latest_transactions:
                    # Sort by purchase_date_ms descending
                    latest_tx = sorted(
                        latest_transactions,
                        key=lambda x: int(x.get("purchase_date_ms", 0)),
                        reverse=True,
                    )[0]

                    product_id = latest_tx.get("product_id") or product_id
                    transaction_id = latest_tx.get("transaction_id") or transaction_id
                    original_transaction_id = latest_tx.get("original_transaction_id") or original_transaction_id
                    purchase_date = parse_apple_timestamp(latest_tx.get("purchase_date_ms")) or purchase_date
                    expires_date = parse_apple_timestamp(latest_tx.get("expires_date_ms"))
            else:
                # Receipt verification failed on Apple side
                err_msg = f"Apple receipt verification failed (status: {apple_res.get('status')})"
                logger.warning(f"[Apple IAP] {err_msg}")
                return Response(
                    {"error": err_msg, "apple_response": apple_res},
                    status=status.HTTP_400_BAD_REQUEST,
                )
        else:
            # Direct StoreKit 2 transaction payload (validated client-side with native verificationResult)
            if transaction_id and product_id:
                verified = True
                apple_data = {
                    "source": "storekit_2_signed_transaction",
                    "transaction_id": transaction_id,
                    "original_transaction_id": original_transaction_id,
                }
                raw_exp = request.data.get("expires_date")
                if raw_exp:
                    expires_date = parse_apple_timestamp(raw_exp)

        if not verified or not product_id:
            return Response(
                {"error": "Unable to verify transaction authenticity with Apple."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Resolve plan name & cycle
        plan_name, billing_cycle = resolve_plan_from_product_id(product_id)

        # 1. Update Client entitlement
        client.plan = plan_name
        client.billing_period = billing_cycle
        client.status = "ACTIVE"
        
        # Link assigned_plan if Plan model matches
        matching_plan = Plan.objects.filter(name__iexact=plan_name).first()
        if matching_plan:
            client.assigned_plan = matching_plan

        client.save()

        # 2. Update ClientSubscription
        sub, _ = ClientSubscription.objects.get_or_create(client=client)
        sub.plan_name = plan_name
        sub.status = "ACTIVE"
        sub.current_period_start = purchase_date
        if expires_date:
            sub.current_period_end = expires_date
        sub.auto_renew = True
        sub.save()

        # 3. Record in AppleIAPTransaction
        orig_id = original_transaction_id or transaction_id or f"tx_{int(time.time())}"
        tx_id = transaction_id or orig_id

        iap_record, _ = AppleIAPTransaction.objects.update_or_create(
            original_transaction_id=orig_id,
            defaults={
                "client": client,
                "user": user,
                "transaction_id": tx_id,
                "product_id": product_id,
                "plan_name": plan_name,
                "billing_cycle": billing_cycle,
                "status": "ACTIVE",
                "purchase_date": purchase_date,
                "expires_date": expires_date,
                "is_sandbox": is_sandbox,
                "raw_data": apple_data,
            },
        )

        # 4. Audit Log
        Log.objects.create(
            client=client,
            user=user,
            action="SUBSCRIPTION_UPGRADED",
            details=f"Upgraded to {plan_name} ({billing_cycle}) via Apple In-App Purchase #{orig_id}"
        )

        return Response({
            "success": True,
            "message": f"Successfully upgraded to {plan_name} plan!",
            "plan": client.plan,
            "billing_cycle": client.billing_period,
            "status": "ACTIVE",
            "expires_date": expires_date.isoformat() if expires_date else None,
            "is_sandbox": is_sandbox,
        }, status=status.HTTP_200_OK)


class AppleIAPRestoreView(APIView):
    """
    POST /api/payments/apple/restore/
    Restores active Apple purchases for the authenticated user and syncs entitlement.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        client = getattr(user, "client", None)
        if not client:
            return Response(
                {"error": "User does not have an associated organization / workspace."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transactions = request.data.get("transactions") or []
        receipt_data = request.data.get("receipt_data")

        # If receipt data passed, verify through Apple
        if receipt_data:
            shared_secret = getattr(settings, "APPLE_IAP_SHARED_SECRET", None)
            is_valid, apple_res, is_sandbox = verify_apple_receipt(receipt_data, shared_secret)
            if is_valid:
                receipt_info = apple_res.get("receipt", {})
                latest_transactions = apple_res.get("latest_receipt_info") or receipt_info.get("in_app") or []
                for tx in latest_transactions:
                    product_id = tx.get("product_id")
                    if product_id:
                        transactions.append({
                            "product_id": product_id,
                            "original_transaction_id": tx.get("original_transaction_id"),
                            "transaction_id": tx.get("transaction_id"),
                            "purchase_date_ms": tx.get("purchase_date_ms"),
                            "expires_date_ms": tx.get("expires_date_ms"),
                        })

        if not transactions:
            # Check if we already have an existing record for this user/client
            existing_record = AppleIAPTransaction.objects.filter(
                client=client,
                status="ACTIVE"
            ).order_by("-created_at").first()

            if existing_record:
                return Response({
                    "success": True,
                    "restored": True,
                    "plan": existing_record.plan_name,
                    "billing_cycle": existing_record.billing_cycle,
                    "status": existing_record.status,
                    "expires_date": existing_record.expires_date.isoformat() if existing_record.expires_date else None,
                })

            return Response({
                "success": False,
                "restored": False,
                "message": "No eligible Apple subscriptions found to restore.",
            }, status=status.HTTP_200_OK)

        # Pick the highest/latest transaction
        latest_tx = transactions[0]
        product_id = latest_tx.get("product_id")
        orig_id = latest_tx.get("original_transaction_id") or latest_tx.get("transaction_id")
        plan_name, billing_cycle = resolve_plan_from_product_id(product_id)

        # Update client
        client.plan = plan_name
        client.billing_period = billing_cycle
        client.status = "ACTIVE"
        matching_plan = Plan.objects.filter(name__iexact=plan_name).first()
        if matching_plan:
            client.assigned_plan = matching_plan
        client.save()

        # Update subscription
        sub, _ = ClientSubscription.objects.get_or_create(client=client)
        sub.plan_name = plan_name
        sub.status = "ACTIVE"
        sub.auto_renew = True
        sub.save()

        # Record or update transaction
        AppleIAPTransaction.objects.update_or_create(
            original_transaction_id=orig_id,
            defaults={
                "client": client,
                "user": user,
                "transaction_id": latest_tx.get("transaction_id") or orig_id,
                "product_id": product_id,
                "plan_name": plan_name,
                "billing_cycle": billing_cycle,
                "status": "ACTIVE",
            }
        )

        return Response({
            "success": True,
            "restored": True,
            "plan": client.plan,
            "billing_cycle": client.billing_period,
            "status": "ACTIVE",
            "message": f"Successfully restored {plan_name} subscription!",
        }, status=status.HTTP_200_OK)


class AppleIAPNotificationWebhookView(APIView):
    """
    POST /api/payments/apple/notifications/
    Apple App Store Server Notifications V2 webhook.
    Handles events such as renewals, expirations, cancellations, and refunds.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        try:
            payload = request.data
            logger.info(f"[Apple IAP Webhook] Received notification: {payload}")

            # App Store Server Notifications V2 sends signedPayload (JWS)
            signed_payload = payload.get("signedPayload")
            if signed_payload:
                parts = signed_payload.split(".")
                if len(parts) >= 2:
                    # Base64 decode middle component (claims)
                    padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
                    decoded_bytes = base64.urlsafe_b64decode(padded)
                    data = json.loads(decoded_bytes.decode("utf-8"))
                    notification_type = data.get("notificationType")
                    subtype = data.get("subtype")
                    logger.info(f"[Apple IAP Webhook] Notification type: {notification_type}, subtype: {subtype}")

                    tx_info = data.get("data", {}).get("signedTransactionInfo")
                    if tx_info:
                        tx_parts = tx_info.split(".")
                        if len(tx_parts) >= 2:
                            tx_padded = tx_parts[1] + "=" * ((4 - len(tx_parts[1]) % 4) % 4)
                            tx_bytes = base64.urlsafe_b64decode(tx_padded)
                            tx_data = json.loads(tx_bytes.decode("utf-8"))

                            orig_id = tx_data.get("originalTransactionId")
                            if orig_id:
                                record = AppleIAPTransaction.objects.filter(original_transaction_id=orig_id).first()
                                if record:
                                    if notification_type in ["EXPIRED", "DID_FAIL_TO_RENEW"]:
                                        record.status = "EXPIRED"
                                        record.save()
                                        record.client.plan = "FREE"
                                        record.client.save()
                                    elif notification_type == "REVOKE":
                                        record.status = "REFUNDED"
                                        record.save()
                                        record.client.plan = "FREE"
                                        record.client.save()
                                    elif notification_type in ["DID_RENEW", "SUBSCRIBED"]:
                                        record.status = "ACTIVE"
                                        record.save()

            return Response({"received": True}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"[Apple IAP Webhook] Error processing notification: {e}")
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
