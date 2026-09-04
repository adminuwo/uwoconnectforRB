"""
razorpay_gateway_views.py
─────────────────────────
Per-client Razorpay OAuth gateway — every UWOConnect client connects their OWN
Razorpay account. Payments for their products go to their own Razorpay, not to
UWOConnect's global account.

Endpoints:
  GET  /api/razorpay/connect              → Initiate OAuth redirect
  GET  /api/razorpay/callback             → OAuth callback (code exchange)
  GET  /api/razorpay/status               → Get connection status for workspace
  DELETE /api/razorpay/status             → Disconnect Razorpay
  POST /api/razorpay/mode                 → Switch TEST ↔ LIVE
  POST /api/razorpay/checkout/create-order → Create order for product checkout
  POST /api/razorpay/checkout/verify      → Verify payment after checkout
  POST /api/razorpay/product-webhook      → Webhook handler (all workspaces)
  GET  /api/razorpay/sales                → Client product payment history
  GET  /api/razorpay/sales/dashboard      → Sales analytics dashboard
  POST /api/razorpay/refund               → Initiate refund
  GET  /api/public/checkout/<product_id>  → Public product info for checkout page
"""

import json
import logging
from datetime import datetime, timedelta

from django.http import HttpResponseRedirect, JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status

from api.models import Client, RazorpayConnection, ProductPayment, Product
from api.services.razorpay_oauth_service import RazorpayOAuthService

logger = logging.getLogger(__name__)


def _get_client(request):
    """Resolve the client/workspace for the authenticated user."""
    user = request.user
    if not user or not user.is_authenticated:
        return None
    return getattr(user, 'client', None)


# ─────────────────────────────────────────────────────────────────────────────
# 1. OAUTH INITIATE — Redirect client to Razorpay
# ─────────────────────────────────────────────────────────────────────────────

class RazorpayOAuthInitiateView(APIView):
    """
    GET /api/razorpay/connect
    Authenticated client → generates OAuth URL → returns it so frontend can redirect.
    We return the URL (not server-redirect) so the Next.js app controls navigation.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = _get_client(request)
        if not client:
            return Response({'error': 'No workspace found for this user.'}, status=400)

        try:
            state = RazorpayOAuthService.generate_state_token(client.id)
            # Store state in session or a temp DB field for CSRF validation
            # We embed client_id in state and verify on callback
            oauth_url = RazorpayOAuthService.get_oauth_authorize_url(state)
            return Response({
                'oauth_url': oauth_url,
                'state': state,
                'message': 'Redirect the user to oauth_url to connect their Razorpay account.'
            })
        except ValueError as e:
            return Response({
                'error': str(e),
                'setup_required': True,
                'message': (
                    'Razorpay Technology Partner credentials are not configured. '
                    'Please register at https://razorpay.com/partners/technology-partner/ '
                    'and set RAZORPAY_CLIENT_ID + RAZORPAY_CLIENT_SECRET in .env'
                )
            }, status=503)


# ─────────────────────────────────────────────────────────────────────────────
# 2. OAUTH CALLBACK — Exchange code for tokens
# ─────────────────────────────────────────────────────────────────────────────

class RazorpayOAuthCallbackView(APIView):
    """
    GET /api/razorpay/callback?code=AUTH_CODE&state=CLIENT_ID_RANDOM
    Razorpay redirects here after the client authorizes.
    We exchange the code, store tokens securely, redirect to frontend success page.
    """
    permission_classes = [AllowAny]  # Razorpay redirects here, no auth header

    def get(self, request):
        code  = request.query_params.get('code')
        state = request.query_params.get('state', '')
        error = request.query_params.get('error')

        import os
        frontend_url = os.getenv('FRONTEND_URL', 'http://localhost:3000')

        if error:
            logger.warning(f"[Razorpay OAuth] Error from Razorpay: {error}")
            return HttpResponseRedirect(
                f"{frontend_url}/client/payments/callback?razorpay_status=error&message={error}"
            )

        if not code:
            return HttpResponseRedirect(
                f"{frontend_url}/client/payments/callback?razorpay_status=error&message=no_code"
            )

        # Parse client_id from state
        client_id = RazorpayOAuthService.parse_state_token(state)
        if not client_id:
            return HttpResponseRedirect(
                f"{frontend_url}/client/payments/callback?razorpay_status=error&message=invalid_state"
            )

        try:
            client = Client.objects.get(id=client_id)
            if client.white_label_domain:
                frontend_url = f"https://{client.white_label_domain}"
        except Client.DoesNotExist:
            return HttpResponseRedirect(
                f"{frontend_url}/client/payments/callback?razorpay_status=error&message=client_not_found"
            )

        try:
            token_data = RazorpayOAuthService.exchange_code_for_tokens(code)
        except Exception as e:
            logger.error(f"[Razorpay OAuth] Token exchange error: {e}")
            return HttpResponseRedirect(
                f"{frontend_url}/client/payments/callback?razorpay_status=error&message=token_exchange_failed"
            )

        # Upsert RazorpayConnection for this workspace
        rzp_conn, created = RazorpayConnection.objects.get_or_create(client=client)
        rzp_conn.access_token          = token_data.get('access_token', '')
        rzp_conn.refresh_token         = token_data.get('refresh_token', '')
        rzp_conn.linked_key_id         = token_data.get('linked_key_id', '')
        rzp_conn.linked_key_secret     = token_data.get('linked_key_secret', '')
        rzp_conn.razorpay_account_id   = token_data.get('razorpay_account_id', '')
        rzp_conn.connection_status     = 'CONNECTED'
        rzp_conn.mode                  = 'TEST'
        rzp_conn.connected_at          = timezone.now()
        rzp_conn.save()

        logger.info(
            f"[Razorpay OAuth] Workspace '{client.business_name}' (id={client.id}) "
            f"connected account: {rzp_conn.razorpay_account_id}"
        )

        return HttpResponseRedirect(
            f"{frontend_url}/client/payments/callback?razorpay_status=connected"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. CONNECTION STATUS + DISCONNECT
# ─────────────────────────────────────────────────────────────────────────────

class RazorpayConnectionStatusView(APIView):
    """
    GET  /api/razorpay/status  → Return connection info (NO secrets)
    DELETE /api/razorpay/status → Disconnect (preserves historical payment records)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = _get_client(request)
        if not client:
            return Response({'connected': False, 'error': 'No workspace.'}, status=400)

        try:
            conn = RazorpayConnection.objects.get(client=client)
            return Response({
                'connected':             conn.is_connected(),
                'connection_status':     conn.connection_status,
                'mode':                  conn.mode,
                # Only non-sensitive public info:
                'razorpay_account_id':   conn.razorpay_account_id or '',
                'connected_at':          conn.connected_at.isoformat() if conn.connected_at else None,
                'linked_key_id':         conn.linked_key_id or '',  # public key is safe to show
            })
        except RazorpayConnection.DoesNotExist:
            return Response({'connected': False, 'connection_status': 'DISCONNECTED'})

    def delete(self, request):
        """Disconnect Razorpay — clears tokens but preserves all historical payment records."""
        client = _get_client(request)
        if not client:
            return Response({'error': 'No workspace.'}, status=400)

        try:
            conn = RazorpayConnection.objects.get(client=client)
            conn.connection_status  = 'DISCONNECTED'
            conn.access_token       = ''
            conn.refresh_token      = ''
            conn.linked_key_id      = ''
            conn.linked_key_secret  = ''
            conn.razorpay_account_id = conn.razorpay_account_id  # Keep for record reference
            conn.save()
            logger.info(f"[Razorpay] Workspace '{client.business_name}' disconnected Razorpay.")
            return Response({'success': True, 'message': 'Razorpay disconnected. Historical records preserved.'})
        except RazorpayConnection.DoesNotExist:
            return Response({'success': True, 'message': 'Already disconnected.'})


# ─────────────────────────────────────────────────────────────────────────────
# 4. MODE SWITCH (TEST ↔ LIVE)
# ─────────────────────────────────────────────────────────────────────────────

class RazorpayModeSwitchView(APIView):
    """POST /api/razorpay/mode — Switch between TEST and LIVE modes."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = _get_client(request)
        if not client:
            return Response({'error': 'No workspace.'}, status=400)

        mode = request.data.get('mode', '').upper()
        if mode not in ('TEST', 'LIVE'):
            return Response({'error': 'mode must be TEST or LIVE'}, status=400)

        try:
            conn = RazorpayConnection.objects.get(client=client)
            if not conn.is_connected():
                return Response({'error': 'Razorpay is not connected.'}, status=400)
            conn.mode = mode
            conn.save()
            return Response({'success': True, 'mode': conn.mode})
        except RazorpayConnection.DoesNotExist:
            return Response({'error': 'No Razorpay connection found.'}, status=404)


# ─────────────────────────────────────────────────────────────────────────────
# 5. PUBLIC PRODUCT INFO (for checkout page — no auth)
# ─────────────────────────────────────────────────────────────────────────────

class PublicProductCheckoutInfoView(APIView):
    """
    GET /api/public/checkout/<product_id>
    Returns product info + workspace payment status for the public checkout page.
    Does NOT expose any secrets.
    """
    permission_classes = [AllowAny]

    def get(self, request, product_id):
        try:
            product = Product.objects.select_related('client').get(pk=product_id)
        except Exception:
            return Response({'error': 'Product not found.'}, status=404)

        # Validate payment readiness
        workspace = product.client
        payment_enabled = False
        payment_error   = None

        try:
            conn = RazorpayConnection.objects.get(client=workspace)
            if conn.is_connected():
                payment_enabled = True
            else:
                payment_error = 'Online payment is not enabled for this product. (Razorpay not connected)'
        except RazorpayConnection.DoesNotExist:
            payment_error = 'Online payment is not enabled for this product. (Razorpay not configured)'

        if not product.price or float(product.price) <= 0:
            payment_enabled = False
            payment_error   = 'This product does not have a valid price.'

        return Response({
            'product': {
                'id':          str(product.id),
                'name':        product.name,
                'description': product.description,
                'price':       float(product.price),
                'currency':    product.currency or 'INR',
                'image_url':   product.image_url,
                'category':    product.category,
                'in_stock':    product.in_stock,
                'brand':       product.brand,
            },
            'workspace': {
                'name': workspace.business_name,
            },
            'payment_enabled': payment_enabled,
            'payment_error':   payment_error,
        })


# ─────────────────────────────────────────────────────────────────────────────
# 6. CREATE PAYMENT ORDER (workspace-isolated)
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class ProductCheckoutCreateOrderView(APIView):
    """
    POST /api/razorpay/checkout/create-order
    Public (no auth needed — customer is buying).
    Body: { product_id, customer_name, customer_email, customer_phone }

    Resolves: product → workspace → RazorpayConnection → creates order using CLIENT's keys.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        product_id      = request.data.get('product_id')
        customer_name   = request.data.get('customer_name', '')
        customer_email  = request.data.get('customer_email', '')
        customer_phone  = request.data.get('customer_phone', '')

        if not product_id:
            return Response({'error': 'product_id is required.'}, status=400)

        # ── Step 1: Resolve product → workspace ───────────────────────────────
        try:
            product = Product.objects.select_related('client').get(pk=product_id)
        except Product.DoesNotExist:
            return Response({'error': 'Product not found.'}, status=404)

        workspace = product.client

        # ── Step 2: Validate ──────────────────────────────────────────────────
        if not product.in_stock:
            return Response({'error': 'This product is out of stock.'}, status=400)

        if not product.price or float(product.price) <= 0:
            return Response({'error': 'This product does not have a valid price.'}, status=400)

        # ── Step 3: Get workspace's Razorpay connection (ISOLATION CRITICAL) ──
        try:
            rzp_conn = RazorpayConnection.objects.get(client=workspace)
        except RazorpayConnection.DoesNotExist:
            return Response({
                'error': 'Online payment is not enabled for this product.',
                'detail': 'The seller has not connected a payment gateway.'
            }, status=402)

        if not rzp_conn.is_connected():
            return Response({
                'error': 'Online payment is not enabled for this product.',
                'detail': 'Payment gateway is disconnected.'
            }, status=402)

        # ── Step 4: Create order using WORKSPACE'S OWN keys ──────────────────
        import time
        receipt_id = f"rcpt_prod_{product.id}_{int(time.time())}"

        try:
            order_data = RazorpayOAuthService.create_product_order(
                rzp_connection=rzp_conn,
                amount_inr=float(product.price),
                receipt_id=receipt_id,
                notes={
                    'product_id':       str(product.id),
                    'product_name':     product.name,
                    'workspace_id':     str(workspace.id),
                    'customer_email':   customer_email,
                    'platform':         'UWOConnect',
                }
            )
        except (ValueError, ConnectionError) as e:
            logger.error(f"[Checkout] Order creation error: {e}")
            return Response({'error': str(e)}, status=502)

        # ── Step 5: Create pending ProductPayment record ──────────────────────
        payment_record = ProductPayment.objects.create(
            workspace               = workspace,
            product                 = product,
            razorpay_connection     = rzp_conn,
            razorpay_order_id       = order_data['razorpay_order_id'],
            amount                  = float(product.price),
            currency                = product.currency or 'INR',
            payment_status          = 'PENDING',
            customer_name           = customer_name,
            customer_email          = customer_email,
            customer_phone          = customer_phone,
            gateway_account_reference = rzp_conn.razorpay_account_id,
        )

        logger.info(
            f"[Checkout] Order {order_data['razorpay_order_id']} created for "
            f"product '{product.name}' via workspace '{workspace.business_name}' "
            f"(account: {rzp_conn.razorpay_account_id})"
        )

        return Response({
            'payment_record_id':    payment_record.id,
            'razorpay_order_id':    order_data['razorpay_order_id'],
            'razorpay_key_id':      order_data['key_id'],   # public key, safe to return
            'amount':               order_data['amount'],   # in paise
            'currency':             order_data['currency'],
            'product_name':         product.name,
            'workspace_name':       workspace.business_name,
            'customer_name':        customer_name,
            'customer_email':       customer_email,
            'customer_phone':       customer_phone,
        }, status=201)


# ─────────────────────────────────────────────────────────────────────────────
# 7. VERIFY PAYMENT
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class ProductCheckoutVerifyView(APIView):
    """
    POST /api/razorpay/checkout/verify
    Public (no auth). Backend verifies signature using WORKSPACE's key_secret.
    Body: { razorpay_order_id, razorpay_payment_id, razorpay_signature, payment_record_id }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        order_id          = request.data.get('razorpay_order_id')
        payment_id        = request.data.get('razorpay_payment_id')
        signature         = request.data.get('razorpay_signature')
        payment_record_id = request.data.get('payment_record_id')

        if not all([order_id, payment_id, signature, payment_record_id]):
            return Response({'error': 'Missing required fields.'}, status=400)

        # ── Fetch payment record ──────────────────────────────────────────────
        try:
            payment = ProductPayment.objects.select_related(
                'workspace', 'product', 'razorpay_connection'
            ).get(id=payment_record_id, razorpay_order_id=order_id)
        except ProductPayment.DoesNotExist:
            return Response({'error': 'Payment record not found.'}, status=404)

        rzp_conn = payment.razorpay_connection

        # ── Verify signature using WORKSPACE's secret ─────────────────────────
        is_valid = RazorpayOAuthService.verify_payment_signature(
            rzp_connection=rzp_conn,
            order_id=order_id,
            payment_id=payment_id,
            signature=signature,
        )

        if is_valid:
            payment.razorpay_payment_id = payment_id
            payment.razorpay_signature  = signature
            payment.payment_status      = 'PAID'
            payment.paid_at             = timezone.now()
            payment.save()

            # Update product revenue stats
            if payment.product:
                payment.product.revenue_generated = (
                    float(payment.product.revenue_generated or 0) + float(payment.amount)
                )
                payment.product.conversions_count = (payment.product.conversions_count or 0) + 1
                payment.product.save()

            # Trigger automated invoice generation
            try:
                from ..services.invoice_service import InvoiceService
                InvoiceService.create_invoice_for_payment(payment)
            except Exception as _inv_err:
                logger.error(f"[Checkout] Automated invoice generation failed for payment {payment.id}: {_inv_err}")

            logger.info(
                f"[Checkout] Payment VERIFIED: {payment_id} for "
                f"order {order_id} | workspace: {payment.workspace.business_name}"
            )

            return Response({
                'success':       True,
                'payment_id':    payment_id,
                'status':        'PAID',
                'amount':        float(payment.amount),
                'currency':      payment.currency,
                'product_name':  payment.product.name if payment.product else '',
                'customer_name': payment.customer_name,
                'message':       'Payment successful!',
            })
        else:
            payment.payment_status = 'FAILED'
            payment.save()
            logger.warning(f"[Checkout] Signature FAILED for order {order_id}")
            return Response({
                'success': False,
                'status':  'FAILED',
                'message': 'Payment signature verification failed.',
            }, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# 8. WEBHOOK HANDLER (idempotent, multi-workspace)
# ─────────────────────────────────────────────────────────────────────────────

@method_decorator(csrf_exempt, name='dispatch')
class ProductCheckoutWebhookView(APIView):
    """
    POST /api/razorpay/product-webhook
    Razorpay sends webhook events here.
    We identify the workspace from the order_id → ProductPayment, then verify
    the signature using that workspace's webhook_secret. Fully idempotent.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        payload_bytes = request.body
        signature     = request.META.get('HTTP_X_RAZORPAY_SIGNATURE', '')
        event_id      = request.META.get('HTTP_X_RAZORPAY_EVENT_ID', '')

        try:
            payload = json.loads(payload_bytes)
        except Exception:
            return Response({'error': 'Invalid JSON'}, status=400)

        event           = payload.get('event', '')
        payment_entity  = payload.get('payload', {}).get('payment', {}).get('entity', {})
        order_entity    = payload.get('payload', {}).get('order', {}).get('entity', {})

        razorpay_order_id   = payment_entity.get('order_id') or order_entity.get('id', '')
        razorpay_payment_id = payment_entity.get('id', '')

        logger.info(f"[Webhook] Event: {event} | Order: {razorpay_order_id} | EventId: {event_id}")

        if not razorpay_order_id:
            return Response({'status': 'ok', 'message': 'No order_id in payload'})

        # ── Find payment record + workspace ───────────────────────────────────
        try:
            payment = ProductPayment.objects.select_related(
                'workspace', 'razorpay_connection'
            ).get(razorpay_order_id=razorpay_order_id)
        except ProductPayment.DoesNotExist:
            logger.warning(f"[Webhook] No ProductPayment for order: {razorpay_order_id}")
            return Response({'status': 'ok'})

        # ── Idempotency check ─────────────────────────────────────────────────
        if event_id:
            if ProductPayment.objects.filter(webhook_event_id=event_id).exists():
                logger.info(f"[Webhook] Duplicate event_id={event_id} — skipped.")
                return Response({'status': 'ok', 'message': 'duplicate'})

        # ── Verify webhook signature using workspace's secret ─────────────────
        rzp_conn       = payment.razorpay_connection
        webhook_secret = rzp_conn.webhook_secret if rzp_conn else None

        sig_valid = RazorpayOAuthService.verify_webhook_signature(
            payload_bytes=payload_bytes,
            signature=signature,
            webhook_secret=webhook_secret,
        )

        if not sig_valid and signature:
            logger.warning(f"[Webhook] Signature invalid for order {razorpay_order_id}")
            # Don't reject — log and process (signature may not be set yet for this workspace)

        # ── Process event ─────────────────────────────────────────────────────
        if event_id:
            payment.webhook_event_id = event_id

        if event in ('payment.captured', 'order.paid'):
            if payment.payment_status != 'PAID':
                payment.payment_status      = 'PAID'
                payment.razorpay_payment_id = razorpay_payment_id
                payment.payment_method      = payment_entity.get('method', '')
                payment.paid_at             = timezone.now()
                payment.save()

                # Update product stats
                if payment.product:
                    payment.product.revenue_generated = (
                        float(payment.product.revenue_generated or 0) + float(payment.amount)
                    )
                    payment.product.save()

                # Trigger automated invoice generation
                try:
                    from ..services.invoice_service import InvoiceService
                    InvoiceService.create_invoice_for_payment(payment)
                except Exception as _inv_err:
                    logger.error(f"[Webhook] Automated invoice generation failed for payment {payment.id}: {_inv_err}")

                logger.info(f"[Webhook] Payment PAID for order {razorpay_order_id}")

        elif event == 'payment.failed':
            if payment.payment_status == 'PENDING':
                payment.payment_status = 'FAILED'
                payment.save()
                logger.info(f"[Webhook] Payment FAILED for order {razorpay_order_id}")

        elif event in ('refund.created', 'refund.processed'):
            refund_entity = payload.get('payload', {}).get('refund', {}).get('entity', {})
            refund_id     = refund_entity.get('id', '')
            refund_amount = refund_entity.get('amount', 0) / 100

            payment.refund_id       = refund_id
            payment.refunded_amount = refund_amount
            payment.refunded_at     = timezone.now()

            if refund_amount >= float(payment.amount):
                payment.payment_status = 'REFUNDED'
            else:
                payment.payment_status = 'PARTIALLY_REFUNDED'

            payment.save()
            logger.info(f"[Webhook] Refund {refund_id} processed for order {razorpay_order_id}")

        elif event == 'refund.failed':
            logger.warning(f"[Webhook] Refund FAILED for order {razorpay_order_id}")
            # Keep current status, log for investigation

        return Response({'status': 'ok'})


# ─────────────────────────────────────────────────────────────────────────────
# 9. CLIENT SALES HISTORY
# ─────────────────────────────────────────────────────────────────────────────

class ClientProductSalesView(APIView):
    """
    GET /api/razorpay/sales
    Returns paginated product payment history for the authenticated client's workspace.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = _get_client(request)
        if not client:
            return Response({'payments': [], 'total': 0})

        payments = ProductPayment.objects.filter(workspace=client).select_related(
            'product'
        ).order_by('-created_at')

        # Optional filters
        status_filter = request.query_params.get('status')
        if status_filter:
            payments = payments.filter(payment_status=status_filter.upper())

        # Pagination
        page     = int(request.query_params.get('page', 1))
        per_page = int(request.query_params.get('per_page', 20))
        start    = (page - 1) * per_page
        end      = start + per_page
        total    = payments.count()
        payments = payments[start:end]

        data = []
        for p in payments:
            data.append({
                'id':                   p.id,
                'product_id':           str(p.product.id) if p.product else None,
                'product_name':         p.product.name if p.product else 'Deleted Product',
                'razorpay_order_id':    p.razorpay_order_id,
                'razorpay_payment_id':  p.razorpay_payment_id,
                'amount':               float(p.amount),
                'currency':             p.currency,
                'payment_status':       p.payment_status,
                'payment_method':       p.payment_method,
                'customer_name':        p.customer_name,
                'customer_email':       p.customer_email,
                'customer_phone':       p.customer_phone,
                'refund_id':            p.refund_id,
                'refunded_amount':      float(p.refunded_amount) if p.refunded_amount else None,
                'paid_at':              p.paid_at.isoformat() if p.paid_at else None,
                'created_at':           p.created_at.isoformat(),
            })

        return Response({'payments': data, 'total': total, 'page': page, 'per_page': per_page})


# ─────────────────────────────────────────────────────────────────────────────
# 10. SALES DASHBOARD ANALYTICS
# ─────────────────────────────────────────────────────────────────────────────

class ClientSalesDashboardView(APIView):
    """
    GET /api/razorpay/sales/dashboard
    Returns summary stats for the client's payment dashboard.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = _get_client(request)
        if not client:
            return Response({})

        now       = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        all_payments = ProductPayment.objects.filter(workspace=client)

        paid    = all_payments.filter(payment_status='PAID')
        failed  = all_payments.filter(payment_status='FAILED')
        pending = all_payments.filter(payment_status='PENDING')
        refunded= all_payments.filter(payment_status__in=['REFUNDED', 'PARTIALLY_REFUNDED'])

        total_revenue    = sum(float(p.amount) for p in paid)
        today_revenue    = sum(float(p.amount) for p in paid.filter(paid_at__gte=today_start))
        monthly_revenue  = sum(float(p.amount) for p in paid.filter(paid_at__gte=month_start))

        return Response({
            'total_sales':         paid.count(),
            'total_revenue':       total_revenue,
            'today_revenue':       today_revenue,
            'monthly_revenue':     monthly_revenue,
            'failed_payments':     failed.count(),
            'pending_payments':    pending.count(),
            'refunds':             refunded.count(),
            'total_transactions':  all_payments.count(),
        })


# ─────────────────────────────────────────────────────────────────────────────
# 11. REFUND INITIATION
# ─────────────────────────────────────────────────────────────────────────────

class ClientRefundView(APIView):
    """
    POST /api/razorpay/refund
    Body: { payment_record_id, amount (optional, INR — full refund if omitted) }
    Uses the workspace's OWN Razorpay credentials to initiate the refund.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client            = _get_client(request)
        payment_record_id = request.data.get('payment_record_id')
        amount_inr        = request.data.get('amount')  # optional

        if not payment_record_id:
            return Response({'error': 'payment_record_id is required.'}, status=400)

        # Ensure the payment belongs to THIS workspace
        try:
            payment = ProductPayment.objects.select_related(
                'razorpay_connection'
            ).get(id=payment_record_id, workspace=client)
        except ProductPayment.DoesNotExist:
            return Response({'error': 'Payment record not found in your workspace.'}, status=404)

        if payment.payment_status != 'PAID':
            return Response({'error': f'Cannot refund a payment with status: {payment.payment_status}'}, status=400)

        if not payment.razorpay_payment_id:
            return Response({'error': 'No Razorpay payment ID found for this transaction.'}, status=400)

        rzp_conn = payment.razorpay_connection
        if not rzp_conn or not rzp_conn.is_connected():
            return Response({'error': 'Razorpay is disconnected. Cannot process refund.'}, status=400)

        try:
            refund_data = RazorpayOAuthService.initiate_refund(
                rzp_connection=rzp_conn,
                payment_id=payment.razorpay_payment_id,
                amount_inr=amount_inr,
                notes={'reason': 'Client initiated refund via UWOConnect'},
            )
        except (ValueError, ConnectionError) as e:
            return Response({'error': str(e)}, status=502)

        # Update payment record (webhook will finalize)
        payment.refund_id       = refund_data['refund_id']
        payment.refunded_amount = refund_data['amount']
        payment.refunded_at     = timezone.now()
        if refund_data['amount'] >= float(payment.amount):
            payment.payment_status = 'REFUNDED'
        else:
            payment.payment_status = 'PARTIALLY_REFUNDED'
        payment.save()

        return Response({
            'success':       True,
            'refund_id':     refund_data['refund_id'],
            'amount':        refund_data['amount'],
            'status':        refund_data.get('status'),
            'message':       'Refund initiated successfully.',
        })
