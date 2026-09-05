import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from django.utils import timezone

from api.models import (
    Client, User, ClientWallet, WalletLedger, UsageRate, WalletRechargeOrder, ClientSubscription
)
from api.services.wallet_services import (
    WalletService, SubscriptionService, WalletLedgerService, PaymentService, PricingService, UsageBillingService
)

logger = logging.getLogger(__name__)

class ClientWalletDashboardView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not getattr(user, 'client', None):
            if getattr(user, 'role', '') == 'ADMIN' or getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False):
                try:
                    from django.db.models import Sum
                    total_wallets = ClientWallet.objects.aggregate(total=Sum('balance_paise'))['total'] or 0
                except Exception:
                    total_wallets = sum(getattr(w, 'balance_paise', 0) or 0 for w in ClientWallet.objects.all())
                return Response({
                    'wallet_balance_inr': round(total_wallets / 100.0, 2),
                    'wallet_balance_paise': total_wallets,
                    'is_low_balance': False,
                    'is_zero_balance': False,
                    'subscription': {
                        'status': 'ACTIVE',
                        'plan_name': 'SUPER_ADMIN',
                        'price_monthly': 0
                    },
                    'transactions': []
                }, status=status.HTTP_200_OK)
            return Response({'error': 'No workspace client associated with user.'}, status=status.HTTP_400_BAD_REQUEST)

        client = user.client
        summary = WalletService.get_wallet_summary(client)

        # Retrieve recent ledger transactions
        ledger_entries = WalletLedger.objects.filter(client=client).order_by('-created_at')[:50]
        transactions_data = [{
            'id': entry.id,
            'transaction_id': entry.transaction_id,
            'type': entry.type,
            'amount_inr': entry.amount_inr,
            'amount_paise': entry.amount_paise,
            'balance_after_inr': entry.balance_after_inr,
            'description': entry.description,
            'service_category': entry.service_category,
            'reference_id': entry.reference_id,
            'status': entry.status,
            'created_at': entry.created_at.isoformat()
        } for entry in ledger_entries]

        summary['transactions'] = transactions_data
        return Response(summary, status=status.HTTP_200_OK)


class WalletRechargeCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.client:
            return Response({'error': 'No workspace client associated with user.'}, status=status.HTTP_400_BAD_REQUEST)

        raw_amount = request.data.get('amount')
        try:
            amount_inr = float(raw_amount)
            if amount_inr < 1:
                return Response({'error': 'Minimum recharge amount is ₹1.00'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'error': 'Invalid monetary amount specified.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order_data = PaymentService.create_wallet_recharge_order(
                client=user.client,
                user=user,
                amount_inr=amount_inr
            )
            return Response(order_data, status=status.HTTP_201_CREATED)
        except Exception as err:
            logger.error(f"[WalletRechargeCreateView] Error: {err}")
            return Response({'error': str(err)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WalletRechargeVerifyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.client:
            return Response({'error': 'No workspace client associated with user.'}, status=status.HTTP_400_BAD_REQUEST)

        order_id = request.data.get('order_id') or request.data.get('razorpay_order_id')
        payment_id = request.data.get('razorpay_payment_id')
        signature = request.data.get('razorpay_signature')
        force_mock_success = request.data.get('force_mock_success', False)

        if not order_id:
            return Response({'error': 'order_id or razorpay_order_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            res = PaymentService.verify_and_credit_recharge(
                order_id=order_id,
                razorpay_payment_id=payment_id,
                razorpay_signature=signature,
                force_mock_success=force_mock_success
            )
            return Response(res, status=status.HTTP_200_OK)
        except ValueError as err:
            return Response({'error': str(err)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as err:
            logger.error(f"[WalletRechargeVerifyView] Error: {err}")
            return Response({'error': 'Payment verification failed.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class WalletWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.data
        logger.info(f"[WalletWebhookView] Payload: {payload}")

        event = payload.get('event')
        entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
        razorpay_order_id = entity.get('order_id')
        razorpay_payment_id = entity.get('id')

        if razorpay_order_id and event in ['payment.captured', 'order.paid']:
            try:
                recharge_order = WalletRechargeOrder.objects.filter(razorpay_order_id=razorpay_order_id).first()
                if recharge_order and recharge_order.status != 'PAID':
                    PaymentService.verify_and_credit_recharge(
                        order_id=recharge_order.order_id,
                        razorpay_payment_id=razorpay_payment_id,
                        razorpay_signature='',
                        force_mock_success=True
                    )
            except Exception as err:
                logger.error(f"[WalletWebhookView] Error handling webhook: {err}")

        return Response({'status': 'OK'}, status=status.HTTP_200_OK)


class AdminWalletOverviewView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'ADMIN' and not request.user.is_staff:
            return Response({'error': 'Unauthorized admin access required.'}, status=status.HTTP_403_FORBIDDEN)

        clients = Client.objects.all().order_by('-created_at')
        result = []

        for client in clients:
            summary = WalletService.get_wallet_summary(client)
            last_tx = WalletLedger.objects.filter(client=client).order_by('-created_at').first()

            result.append({
                'client_id': client.id,
                'business_name': client.business_name,
                'subscription_status': summary['subscription']['status'],
                'subscription_amount': summary['subscription']['price_monthly'],
                'wallet_balance_inr': summary['wallet_balance_inr'],
                'is_low_balance': summary['is_low_balance'],
                'is_zero_balance': summary['is_zero_balance'],
                'usage_this_month_inr': summary['usage_this_month_inr'],
                'last_transaction': {
                    'type': last_tx.type,
                    'amount_inr': last_tx.amount_inr,
                    'timestamp': last_tx.created_at.isoformat()
                } if last_tx else None
            })

        return Response({'clients': result}, status=status.HTTP_200_OK)


class AdminWalletAdjustmentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'ADMIN' and not request.user.is_staff:
            return Response({'error': 'Unauthorized admin access required.'}, status=status.HTTP_403_FORBIDDEN)

        client_id = request.data.get('client_id')
        adjustment_type = request.data.get('type', 'ADJUSTMENT') # ADJUSTMENT or REFUND
        amount_inr = request.data.get('amount')
        reason = request.data.get('reason')

        if not client_id or not amount_inr or not reason:
            return Response({'error': 'client_id, amount, and reason are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = Client.objects.get(id=client_id)
            amount_float = float(amount_inr)
            amount_paise = int(round(amount_float * 100))

            if adjustment_type not in ['ADJUSTMENT', 'REFUND', 'BONUS']:
                adjustment_type = 'ADJUSTMENT'

            ledger_entry = WalletLedgerService.record_transaction(
                client=client,
                tx_type=adjustment_type,
                amount_paise=amount_paise,
                description=f"Admin {adjustment_type.capitalize()}: {reason}",
                service_category='SYSTEM',
                user=request.user
            )

            return Response({
                'success': True,
                'message': f"Successfully applied {adjustment_type} of ₹{amount_float} to {client.business_name}.",
                'new_balance_inr': ledger_entry.balance_after_inr
            }, status=status.HTTP_200_OK)
        except Client.DoesNotExist:
            return Response({'error': 'Client workspace not found.'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as err:
            return Response({'error': str(err)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AdminRateConfigView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'ADMIN' and not request.user.is_staff:
            return Response({'error': 'Unauthorized admin access required.'}, status=status.HTTP_403_FORBIDDEN)

        rates = UsageRate.objects.all().order_by('country_code', 'service_category')
        rates_data = [{
            'id': r.id,
            'country_code': r.country_code,
            'service_category': r.service_category,
            'unit_price_paise': r.unit_price_paise,
            'unit_price_inr': r.unit_price_inr,
            'status': r.status,
            'effective_from': r.effective_from.isoformat()
        } for r in rates]

        return Response({'rates': rates_data}, status=status.HTTP_200_OK)

    def post(self, request):
        if request.user.role != 'ADMIN' and not request.user.is_staff:
            return Response({'error': 'Unauthorized admin access required.'}, status=status.HTTP_403_FORBIDDEN)

        country_code = request.data.get('country_code', 'IN').upper()
        service_category = request.data.get('service_category')
        unit_price_paise = request.data.get('unit_price_paise')

        if not service_category or unit_price_paise is None:
            return Response({'error': 'service_category and unit_price_paise are required.'}, status=status.HTTP_400_BAD_REQUEST)

        rate, created = UsageRate.objects.update_or_create(
            country_code=country_code,
            service_category=service_category,
            status='ACTIVE',
            defaults={
                'unit_price_paise': int(unit_price_paise),
                'effective_from': timezone.now()
            }
        )

        return Response({
            'success': True,
            'message': f"Usage rate for {country_code} {service_category} updated to ₹{rate.unit_price_inr}.",
            'rate': {
                'id': rate.id,
                'country_code': rate.country_code,
                'service_category': rate.service_category,
                'unit_price_paise': rate.unit_price_paise,
                'unit_price_inr': rate.unit_price_inr
            }
        }, status=status.HTTP_200_OK)
