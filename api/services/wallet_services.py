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
        subscription = ClientSubscription.objects.filter(client=client).first()
        if not subscription:
            plan_str = (client.plan or 'STARTER').upper()
            cycle_str = getattr(client, 'billing_period', 'MONTHLY').upper()
            is_lifetime = cycle_str in ['LIFETIME', 'ONE_TIME', 'PERPETUAL', 'NEVER'] or (
                client.assigned_plan and (client.assigned_plan.billing_cycle or '').upper() in ['ONE_TIME', 'LIFETIME']
            )
            duration_days = 365 if cycle_str in ['YEARLY', 'ANNUAL'] else 30
            now = timezone.now()
            subscription = ClientSubscription.objects.create(
                client=client,
                plan_name=plan_str,
                price_monthly=499.00 if 'STARTER' in plan_str else (1499.00 if 'GROWTH' in plan_str else 2999.00),
                status='ACTIVE',
                current_period_start=now,
                current_period_end=None if is_lifetime else (now + timedelta(days=duration_days)),
                auto_renew=not is_lifetime
            )
        return subscription

    @staticmethod
    def update_status(client: Client, new_status: str) -> ClientSubscription:
        sub = SubscriptionService.get_or_create_subscription(client)
        sub.status = new_status
        sub.save()
        return sub

    @staticmethod
    def activate_or_renew_subscription(client: Client, plan_name: str, billing_cycle: str = 'MONTHLY', channels=None, amount=None) -> ClientSubscription:
        """
        Activates or renews client subscription upon verified payment.
        Calculates expiration period (30 days for Monthly, 365 days for Yearly/Annual).
        Extends existing active time if renewed early.
        Supports LIFETIME/ONE_TIME perpetual plans without expiration.
        """
        now = timezone.now()
        clean_plan = str(plan_name or client.plan or 'STARTER').upper()
        clean_cycle = str(billing_cycle or getattr(client, 'billing_period', 'MONTHLY')).upper()
        duration_days = 365 if clean_cycle in ['YEARLY', 'ANNUAL'] else 30
        is_lifetime = clean_cycle in ['LIFETIME', 'ONE_TIME', 'PERPETUAL', 'NEVER'] or (
            client.assigned_plan and (client.assigned_plan.billing_cycle or '').upper() in ['ONE_TIME', 'LIFETIME']
        )

        sub = ClientSubscription.objects.filter(client=client).first()
        price = amount or (499.00 if 'STARTER' in clean_plan else (1499.00 if 'GROWTH' in clean_plan else 2999.00))

        if is_lifetime:
            new_end = None
        else:
            if sub and sub.current_period_end and sub.current_period_end > now and sub.plan_name.upper() == clean_plan:
                new_end = sub.current_period_end + timedelta(days=duration_days)
            else:
                new_end = now + timedelta(days=duration_days)

        if not sub:
            sub = ClientSubscription.objects.create(
                client=client,
                plan_name=clean_plan,
                price_monthly=price,
                status='ACTIVE',
                current_period_start=now,
                current_period_end=new_end,
                auto_renew=not is_lifetime
            )
        else:
            sub.plan_name = clean_plan
            sub.status = 'ACTIVE'
            sub.current_period_start = now
            sub.current_period_end = new_end
            if amount:
                try:
                    sub.price_monthly = float(amount)
                except (ValueError, TypeError):
                    pass
            sub.save()

        # Update client workspace model
        client.plan = clean_plan
        client.billing_period = clean_cycle
        client.status = 'ACTIVE'

        if channels:
            if isinstance(channels, str):
                channels = [c.strip().lower() for c in channels.split(',') if c.strip()]
            if isinstance(channels, list):
                client.selected_channels = [str(c).strip().lower() for c in channels if str(c).strip()]

        client.save()
        return sub

    @staticmethod
    def get_subscription_details(client: Client) -> dict:
        """
        Returns status, is_expired, days_remaining, and formatted dates.
        Properly handles Lifetime / One-Time / No-Expiry plans.
        """
        now = timezone.now()
        if not client:
            return {
                'plan_name': 'Free',
                'status': 'INACTIVE',
                'is_expired': False,
                'days_remaining': None,
                'current_period_start': None,
                'current_period_end': None,
                'expires_at': None,
                'can_renew': False,
                'billing_period': 'MONTHLY'
            }

        plan_str = (client.plan or '').strip().upper()
        if plan_str in ['FREE', '']:
            return {
                'plan_name': 'Free',
                'status': 'ACTIVE',
                'is_expired': False,
                'days_remaining': None,
                'current_period_start': None,
                'current_period_end': None,
                'expires_at': None,
                'can_renew': False,
                'billing_period': getattr(client, 'billing_period', 'MONTHLY')
            }

        sub = ClientSubscription.objects.filter(client=client).first()
        clean_cycle = getattr(client, 'billing_period', 'MONTHLY').upper()
        duration_days = 365 if clean_cycle in ['YEARLY', 'ANNUAL'] else 30

        # Check if plan or billing cycle represents lifetime / perpetual access
        is_lifetime = clean_cycle in ['LIFETIME', 'ONE_TIME', 'PERPETUAL', 'NEVER'] or (
            client.assigned_plan and (client.assigned_plan.billing_cycle or '').upper() in ['ONE_TIME', 'LIFETIME']
        )

        if is_lifetime:
            if sub and sub.status != 'ACTIVE':
                sub.status = 'ACTIVE'
                sub.save(update_fields=['status'])
            return {
                'plan_name': sub.plan_name if sub else plan_str,
                'status': 'ACTIVE',
                'is_expired': False,
                'days_remaining': None,
                'current_period_start': sub.current_period_start.isoformat() if (sub and sub.current_period_start) else None,
                'current_period_end': None,
                'expires_at': None,
                'can_renew': False,
                'billing_period': clean_cycle
            }

        if not sub:
            sub = ClientSubscription.objects.create(
                client=client,
                plan_name=plan_str,
                price_monthly=499.00 if 'STARTER' in plan_str else (1499.00 if 'GROWTH' in plan_str else 2999.00),
                status='ACTIVE',
                current_period_start=now,
                current_period_end=now + timedelta(days=duration_days),
                auto_renew=True
            )

        period_end = sub.current_period_end
        if not period_end:
            period_end = now + timedelta(days=duration_days)
            sub.current_period_end = period_end
            sub.save(update_fields=['current_period_end'])

        if now > period_end:
            is_expired = True
            days_remaining = 0
            status_text = 'EXPIRED'
            if sub.status not in ['PAST_DUE', 'CANCELLED']:
                sub.status = 'PAST_DUE'
                sub.save(update_fields=['status'])
        else:
            is_expired = False
            days_remaining = max(0, (period_end - now).days)
            status_text = 'ACTIVE'
            if sub.status != 'ACTIVE':
                sub.status = 'ACTIVE'
                sub.save(update_fields=['status'])

        return {
            'plan_name': sub.plan_name,
            'status': status_text,
            'is_expired': is_expired,
            'days_remaining': days_remaining,
            'current_period_start': sub.current_period_start.isoformat() if sub.current_period_start else None,
            'current_period_end': period_end.isoformat(),
            'expires_at': period_end.isoformat(),
            'can_renew': is_expired or (days_remaining is not None and days_remaining <= 7),
            'billing_period': getattr(client, 'billing_period', 'MONTHLY')
        }


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

        customer_name = user.get_full_name() or user.username or (client.business_name if client else 'UWO Customer')
        customer_email = user.email or 'admin@uwo24.com'
        customer_phone = client.phone_number if client else getattr(user, 'phone_number', '') or '+918358990909'

        plink_res = rzp_service.create_payment_link(
            amount_in_inr=amount_inr,
            receipt_id=receipt_id,
            description=f"UWO Connect Wallet Recharge ₹{amount_inr:,.2f}",
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            callback_url="https://uwoconnect.aisa24.com/api/payments/checkout/callback"
        )

        return {
            'order_id': receipt_id,
            'razorpay_order_id': razorpay_order_id,
            'razorpay_key_id': rzp_res.get('razorpay_key_id'),
            'payment_link_url': plink_res.get('short_url'),
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
