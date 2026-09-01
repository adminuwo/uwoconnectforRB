import logging
import uuid
import time
from django.db import transaction
from django.utils import timezone

from api.models import (
    Client, User, ClientSubscription, ClientWallet, WalletLedger,
    UsageRate, BroadcastEntitlement, BroadcastUsage, Plan
)
from api.services.wallet_services import WalletLedgerService, PricingService, WalletService

logger = logging.getLogger(__name__)

class BroadcastEntitlementService:
    @staticmethod
    def get_broadcast_rate_paise(country_code: str = 'IN') -> int:
        """
        Retrieves configurable additional broadcast rate (defaults to 94 paise = ₹0.94).
        """
        rate_obj = UsageRate.objects.filter(
            country_code=country_code,
            service_category='BROADCAST',
            status='ACTIVE'
        ).first()
        if rate_obj:
            return rate_obj.unit_price_paise
        return 94  # ₹0.94 default

    @staticmethod
    def get_included_quota_for_client(client: Client) -> int:
        """
        Determines included broadcast quota based on active subscription or plan metadata.
        ₹499 Starter = 1, ₹1599 Growth = 2, ₹2499 Pro/Advanced = 3.
        """
        try:
            subscription = ClientSubscription.objects.filter(client=client).first()
            if subscription and subscription.plan_name:
                p_name = subscription.plan_name.lower()
                if 'growth' in p_name:
                    return 2
                elif 'pro' in p_name or 'advanced' in p_name or 'enterprise' in p_name:
                    return 3
                elif 'starter' in p_name:
                    return 1

            # Fallback check on Client.plan
            if hasattr(client, 'plan') and client.plan:
                return getattr(client.plan, 'included_broadcasts', 1)
        except Exception as err:
            logger.warning(f"[BroadcastEntitlementService] Error determining quota: {err}")
        return 1

    @classmethod
    @transaction.atomic
    def get_or_create_period_entitlement(cls, client: Client) -> BroadcastEntitlement:
        """
        Ensures an active INCLUDED entitlement exists for the current subscription billing period.
        Resets included count when billing period rolls over.
        """
        now = timezone.now()
        subscription = ClientSubscription.objects.filter(client=client).first()

        period_start = subscription.current_period_start if (subscription and subscription.current_period_start) else now
        period_end = subscription.current_period_end if (subscription and subscription.current_period_end) else None

        # Check existing entitlement for current period
        entitlement = BroadcastEntitlement.objects.select_for_update().filter(
            client=client,
            type='INCLUDED',
            source='SUBSCRIPTION',
            billing_period_start=period_start
        ).first()

        included_qty = cls.get_included_quota_for_client(client)

        if not entitlement:
            entitlement = BroadcastEntitlement.objects.create(
                client=client,
                subscription=subscription,
                billing_period_start=period_start,
                billing_period_end=period_end,
                type='INCLUDED',
                source='SUBSCRIPTION',
                included_quantity=included_qty,
                used_quantity=0,
                remaining_quantity=included_qty,
                status='AVAILABLE',
                price_paise=0
            )
        else:
            # Sync quota if plan was upgraded/updated within period
            if entitlement.included_quantity < included_qty:
                diff = included_qty - entitlement.included_quantity
                entitlement.included_quantity = included_qty
                entitlement.remaining_quantity += diff
                if entitlement.remaining_quantity > 0:
                    entitlement.status = 'AVAILABLE'
                entitlement.save()

        return entitlement

    @classmethod
    def get_entitlement_summary(cls, client: Client) -> dict:
        """
        Compiles complete audit & entitlement summary for frontend & API.
        """
        entitlement = cls.get_or_create_period_entitlement(client)
        wallet_summary = WalletService.get_wallet_summary(client)
        rate_paise = cls.get_broadcast_rate_paise()
        rate_inr = round(rate_paise / 100.0, 2)

        has_included = entitlement.remaining_quantity > 0
        has_wallet_funds = wallet_summary['wallet_balance_inr'] >= rate_inr

        return {
            'included_quantity': entitlement.included_quantity,
            'used_quantity': entitlement.used_quantity,
            'remaining_quantity': entitlement.remaining_quantity,
            'is_included_available': has_included,
            'broadcast_rate_paise': rate_paise,
            'broadcast_rate_inr': rate_inr,
            'wallet_balance_inr': wallet_summary['wallet_balance_inr'],
            'wallet_balance_paise': wallet_summary['wallet_balance_paise'],
            'next_broadcast_cost_inr': 0.00 if has_included else rate_inr,
            'next_broadcast_source': 'INCLUDED' if has_included else 'WALLET',
            'can_broadcast': has_included or has_wallet_funds,
            'subscription_status': wallet_summary['subscription']['status'],
            'plan_name': wallet_summary['subscription']['plan_name']
        }

    @classmethod
    @transaction.atomic
    def consume_or_reserve_broadcast(
        cls,
        client: Client,
        broadcast_id: str,
        idempotency_key: str,
        user: User = None
    ) -> dict:
        """
        Atomic entitlement consumer & wallet reservation.
        Idempotent: Duplicate requests return existing result without re-charging.
        """
        # 1. Idempotency Guard
        existing_usage = BroadcastUsage.objects.filter(idempotency_key=idempotency_key).first()
        if existing_usage:
            logger.info(f"[BroadcastEntitlement] Duplicate request handled for idempotency key {idempotency_key}")
            return {
                'success': True,
                'is_duplicate': True,
                'broadcast_usage_id': existing_usage.id,
                'charged_via': 'INCLUDED' if existing_usage.amount_paise == 0 else 'WALLET',
                'amount_inr': existing_usage.amount_inr
            }

        # 2. Lock & Fetch Included Entitlement
        entitlement = cls.get_or_create_period_entitlement(client)

        # 3. If Included Quota Available -> Consume 1 Included Broadcast
        if entitlement.remaining_quantity > 0:
            entitlement.used_quantity += 1
            entitlement.remaining_quantity -= 1
            if entitlement.remaining_quantity <= 0:
                entitlement.status = 'EXHAUSTED'
            entitlement.save()

            usage = BroadcastUsage.objects.create(
                client=client,
                entitlement=entitlement,
                broadcast_id=broadcast_id,
                amount_paise=0,
                status='EXECUTED',
                idempotency_key=idempotency_key
            )

            logger.info(f"[BroadcastEntitlement] Consumed INCLUDED broadcast for {client.business_name}. Remaining: {entitlement.remaining_quantity}")
            return {
                'success': True,
                'charged_via': 'INCLUDED',
                'amount_inr': 0.00,
                'broadcast_usage_id': usage.id,
                'remaining_included': entitlement.remaining_quantity
            }

        # 4. If Included Quota Exhausted -> Charge Additional Broadcast from Wallet
        rate_paise = cls.get_broadcast_rate_paise()
        rate_inr = round(rate_paise / 100.0, 2)

        wallet_summary = WalletService.get_wallet_summary(client)
        if wallet_summary['wallet_balance_paise'] < rate_paise:
            raise ValueError(
                f"Insufficient wallet balance. Additional broadcast requires ₹{rate_inr}, "
                f"but current balance is ₹{wallet_summary['wallet_balance_inr']}. Please top up."
            )

        # Deduct wallet atomically
        tx_id = f"tx_brd_{int(time.time())}_{uuid.uuid4().hex[:6]}"
        ledger_entry = WalletLedgerService.record_transaction(
            client=client,
            tx_type='USAGE',
            amount_paise=-abs(rate_paise),
            description=f"Additional Broadcast ({broadcast_id})",
            service_category='BROADCAST',
            reference_id=broadcast_id,
            user=user
        )

        # Create Purchased Entitlement Record
        purchased_entitlement = BroadcastEntitlement.objects.create(
            client=client,
            subscription=entitlement.subscription,
            type='PURCHASED',
            source='WALLET',
            included_quantity=1,
            used_quantity=1,
            remaining_quantity=0,
            status='EXHAUSTED',
            price_paise=rate_paise,
            wallet_transaction_id=ledger_entry.transaction_id
        )

        usage = BroadcastUsage.objects.create(
            client=client,
            entitlement=purchased_entitlement,
            wallet_ledger=ledger_entry,
            broadcast_id=broadcast_id,
            amount_paise=rate_paise,
            status='EXECUTED',
            idempotency_key=idempotency_key
        )

        logger.info(f"[BroadcastEntitlement] Charged WALLET ₹{rate_inr} for additional broadcast {broadcast_id} ({client.business_name})")
        return {
            'success': True,
            'charged_via': 'WALLET',
            'amount_inr': rate_inr,
            'broadcast_usage_id': usage.id,
            'wallet_ledger_id': ledger_entry.id,
            'new_wallet_balance_inr': ledger_entry.balance_after_inr
        }

    @classmethod
    @transaction.atomic
    def refund_failed_broadcast(cls, broadcast_usage_id: int, reason: str = 'Broadcast execution failed') -> dict:
        """
        Atomically refunds wallet deduction if broadcast execution fails.
        """
        try:
            usage = BroadcastUsage.objects.select_for_update().get(id=broadcast_usage_id)
        except BroadcastUsage.DoesNotExist:
            raise ValueError("Broadcast usage record not found")

        if usage.status == 'REFUNDED':
            return {'success': True, 'message': 'Already refunded.'}

        # If it was an included entitlement broadcast, restore 1 included quota
        if usage.amount_paise == 0:
            entitlement = usage.entitlement
            entitlement.used_quantity = max(0, entitlement.used_quantity - 1)
            entitlement.remaining_quantity += 1
            entitlement.status = 'AVAILABLE'
            entitlement.save()

            usage.status = 'REFUNDED'
            usage.save()
            return {'success': True, 'refunded_via': 'INCLUDED_QUOTA_RESTORED'}

        # If it was a wallet-paid broadcast, refund the wallet
        ref_id = f"ref_{usage.broadcast_id}_{int(time.time())}"
        ledger_entry = WalletLedgerService.record_transaction(
            client=usage.client,
            tx_type='REFUND',
            amount_paise=usage.amount_paise,
            description=f"Refund: {reason} ({usage.broadcast_id})",
            service_category='BROADCAST',
            reference_id=ref_id
        )

        usage.status = 'REFUNDED'
        usage.save()

        entitlement = usage.entitlement
        entitlement.status = 'REFUNDED'
        entitlement.save()

        return {
            'success': True,
            'refunded_via': 'WALLET_CREDIT',
            'amount_inr': usage.amount_inr,
            'new_balance_inr': ledger_entry.balance_after_inr
        }
