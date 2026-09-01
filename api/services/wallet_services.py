import time
import logging
import uuid
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta
from django.db.models import Sum

from api.models import (
    Client, User, ClientSubscription, ClientWallet, WalletLedger, UsageRate, WalletRechargeOrder
)
from api.services.razorpay_service import RazorpayService

logger = logging.getLogger(__name__)

# Fallback Rate Card in Paise (minor units)
DEFAULT_RATES = {
    'MARKETING': 78,       # ₹0.78 per message
    'UTILITY': 35,         # ₹0.35 per message
    'AUTHENTICATION': 15,  # ₹0.15 per message
    'SERVICE': 40,         # ₹0.40 per conversation
    'AI_TOKENS': 10,       # ₹0.10 per completion request
}

class SubscriptionService:
    @staticmethod
    def get_or_create_subscription(client: Client) -> ClientSubscription:
        subscription, created = ClientSubscription.objects.get_or_create(
            client=client,
            defaults={
                'plan_name': 'UwoConnect Pro',
                'price_monthly': 499.00,
                'status': 'ACTIVE',
                'current_period_start': timezone.now(),
                'current_period_end': timezone.now() + timedelta(days=30),
                'auto_renew': True
            }
        )
        return subscription

    @staticmethod
    def update_status(client: Client, new_status: str) -> ClientSubscription:
        sub = SubscriptionService.get_or_create_subscription(client)
        sub.status = new_status
        sub.save()
        return sub


class PricingService:
    @staticmethod
    def get_unit_rate_paise(country_code: str = 'IN', service_category: str = 'SERVICE') -> int:
        category_key = str(service_category).upper().strip()
        active_rate = UsageRate.objects.filter(
            country_code=country_code.upper(),
            service_category=category_key,
            status='ACTIVE'
        ).first()

        if active_rate:
            return active_rate.unit_price_paise

        return DEFAULT_RATES.get(category_key, 50)


class WalletService:
    @staticmethod
    def get_or_create_wallet(client: Client) -> ClientWallet:
        wallet, created = ClientWallet.objects.get_or_create(
            client=client,
            defaults={
                'balance_paise': 0,
                'low_balance_threshold_paise': 10000 # ₹100
            }
        )
        return wallet

    @staticmethod
    def get_wallet_summary(client: Client):
        wallet = WalletService.get_or_create_wallet(client)
        subscription = SubscriptionService.get_or_create_subscription(client)

        # Calculate Usage This Month
        now = timezone.now()
        start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        month_usage_paise = WalletLedger.objects.filter(
            client=client,
            type='USAGE',
            status='SUCCESS',
            created_at__gte=start_of_month
        ).aggregate(total=Sum('amount_paise'))['total'] or 0

        # Note: amount_paise is negative for debits
        month_usage_inr = round(abs(month_usage_paise) / 100.0, 2)

        return {
            'wallet_balance_inr': wallet.balance_inr,
            'wallet_balance_paise': wallet.balance_paise,
            'low_balance_threshold_inr': wallet.low_balance_threshold_inr,
            'is_low_balance': wallet.is_low_balance,
            'is_zero_balance': wallet.is_zero_balance,
            'usage_this_month_inr': month_usage_inr,
            'subscription': {
                'plan_name': subscription.plan_name,
                'price_monthly': str(subscription.price_monthly),
                'status': subscription.status,
                'current_period_end': subscription.current_period_end.isoformat() if subscription.current_period_end else None
            }
        }


class WalletLedgerService:
    @staticmethod
    @transaction.atomic
    def record_transaction(
        client: Client,
        tx_type: str,
        amount_paise: int,
        description: str,
        service_category: str = 'GENERAL',
        reference_id: str = None,
        user: User = None
    ) -> WalletLedger:
        """
        Atomic ledger transaction runner with DB row locking (select_for_update)
        Guarantees concurrency safety & prevents double debits/credits.
        """
        wallet, _ = ClientWallet.objects.select_for_update().get_or_create(
            client=client,
            defaults={'balance_paise': 0, 'low_balance_threshold_paise': 10000}
        )

        # Check for duplicate processing if reference_id is supplied
        if reference_id and tx_type in ['RECHARGE', 'REFUND']:
            existing = WalletLedger.objects.filter(client=client, reference_id=reference_id, status='SUCCESS').first()
            if existing:
                logger.warning(f"[WalletLedger] Duplicate transaction attempt for reference_id: {reference_id}")
                return existing

        balance_before = wallet.balance_paise

        # For usage debits, verify sufficient balance
        if tx_type == 'USAGE' and amount_paise < 0:
            debit_amount = abs(amount_paise)
            if balance_before < debit_amount:
                logger.warning(f"[WalletLedger] Insufficient balance for {client.business_name}. Balance: {balance_before}, Attempted: {debit_amount}")
                # Create failed ledger record
                tx_id = f"tx_{int(time.time())}_{uuid.uuid4().hex[:6]}"
                failed_entry = WalletLedger.objects.create(
                    transaction_id=tx_id,
                    client=client,
                    user=user,
                    type=tx_type,
                    amount_paise=amount_paise,
                    balance_before_paise=balance_before,
                    balance_after_paise=balance_before,
                    description=f"FAILED: Insufficient balance ({description})",
                    service_category=service_category,
                    reference_id=reference_id,
                    status='FAILED'
                )
                raise ValueError("Insufficient wallet balance for usage deduction.")

        balance_after = balance_before + amount_paise

        # Update wallet balance
        wallet.balance_paise = balance_after
        wallet.save()

        # Generate unique transaction ID
        tx_id = f"tx_{int(time.time())}_{uuid.uuid4().hex[:6]}"

        entry = WalletLedger.objects.create(
            transaction_id=tx_id,
            client=client,
            user=user,
            type=tx_type,
            amount_paise=amount_paise,
            balance_before_paise=balance_before,
            balance_after_paise=balance_after,
            description=description,
            service_category=service_category,
            reference_id=reference_id or tx_id,
            status='SUCCESS'
        )

        logger.info(f"[WalletLedger] Success: {client.business_name} | Type: {tx_type} | Amount: ₹{round(amount_paise/100.0, 2)} | New Balance: ₹{round(balance_after/100.0, 2)}")
        return entry


class UsageBillingService:
    @staticmethod
    def bill_event(
        client: Client,
        service_category: str,
        usage_category: str = 'SERVICE',
        quantity: int = 1,
        country_code: str = 'IN',
        description: str = '',
        user: User = None
    ):
        """
        Deducts metered usage cost from customer wallet using dynamic pricing engine.
        """
        unit_rate_paise = PricingService.get_unit_rate_paise(country_code, usage_category)
        total_cost_paise = unit_rate_paise * quantity
        debit_amount_paise = -abs(total_cost_paise)

        formatted_cost = round(total_cost_paise / 100.0, 2)
        desc = description or f"{service_category.capitalize()} Usage ({usage_category} x{quantity})"

        try:
            ledger_entry = WalletLedgerService.record_transaction(
                client=client,
                tx_type='USAGE',
                amount_paise=debit_amount_paise,
                description=desc,
                service_category=service_category.upper(),
                user=user
            )
            return {
                'success': True,
                'ledger_id': ledger_entry.id,
                'transaction_id': ledger_entry.transaction_id,
                'cost_inr': formatted_cost
            }
        except ValueError as err:
            return {'success': False, 'error': str(err), 'cost_inr': formatted_cost}


class PaymentService:
    @staticmethod
    def create_wallet_recharge_order(client: Client, user: User, amount_inr: float):
        if amount_inr < 1:
            raise ValueError("Recharge amount must be at least ₹1.00")

        amount_paise = int(round(amount_inr * 100))
        receipt_id = f"rcpt_w_{client.id}_{int(time.time())}"

        rzp_service = RazorpayService()
        rzp_res = rzp_service.create_order(
            amount_in_inr=amount_inr,
            receipt_id=receipt_id,
            notes={
                'client_id': str(client.id),
                'user_email': user.email or '',
                'type': 'WALLET_RECHARGE',
                'amount_inr': str(amount_inr)
            }
        )

        razorpay_order_id = rzp_res.get('razorpay_order_id') or receipt_id

        recharge_order = WalletRechargeOrder.objects.create(
            order_id=receipt_id,
            razorpay_order_id=razorpay_order_id,
            client=client,
            user=user,
            amount_inr=amount_inr,
            amount_paise=amount_paise,
            status='PENDING'
        )

        return {
            'order_id': receipt_id,
            'razorpay_order_id': razorpay_order_id,
            'razorpay_key_id': rzp_res.get('razorpay_key_id'),
            'amount_inr': amount_inr,
            'amount_paise': amount_paise,
            'currency': 'INR',
            'is_mock': rzp_res.get('is_mock', False)
        }

    @staticmethod
    @transaction.atomic
    def verify_and_credit_recharge(
        order_id: str,
        razorpay_payment_id: str,
        razorpay_signature: str,
        force_mock_success: bool = False
    ):
        try:
            recharge_order = WalletRechargeOrder.objects.select_for_update().get(order_id=order_id)
        except WalletRechargeOrder.DoesNotExist:
            try:
                recharge_order = WalletRechargeOrder.objects.select_for_update().get(razorpay_order_id=order_id)
            except WalletRechargeOrder.DoesNotExist:
                raise ValueError("Wallet recharge order not found")

        if recharge_order.status == 'PAID':
            return {'success': True, 'message': 'Recharge order already credited.', 'amount_inr': float(recharge_order.amount_inr)}

        rzp_service = RazorpayService()
        is_valid = force_mock_success or rzp_service.verify_signature(
            razorpay_order_id=recharge_order.razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature
        )

        if is_valid:
            recharge_order.status = 'PAID'
            recharge_order.razorpay_payment_id = razorpay_payment_id or f"pay_mock_{int(time.time())}"
            recharge_order.save()

            # Atomically credit client wallet
            ledger_entry = WalletLedgerService.record_transaction(
                client=recharge_order.client,
                tx_type='RECHARGE',
                amount_paise=recharge_order.amount_paise,
                description=f"Wallet Recharge (₹{recharge_order.amount_inr})",
                service_category='SYSTEM',
                reference_id=recharge_order.order_id,
                user=recharge_order.user
            )

            return {
                'success': True,
                'message': f"Successfully credited ₹{recharge_order.amount_inr} to your wallet!",
                'amount_inr': float(recharge_order.amount_inr),
                'ledger_id': ledger_entry.id,
                'transaction_id': ledger_entry.transaction_id,
                'new_balance_inr': ledger_entry.balance_after_inr
            }
        else:
            recharge_order.status = 'FAILED'
            recharge_order.save()
            raise ValueError("Razorpay signature verification failed")
