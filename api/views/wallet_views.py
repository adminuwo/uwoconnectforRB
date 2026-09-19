import logging
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
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
        is_admin = getattr(user, 'role', '') == 'ADMIN' or getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)
        client = getattr(user, 'client', None)

        # Allow Admin to inspect a specific client workspace via query parameter
        if is_admin and not client:
            client_id = request.query_params.get('client_id')
            if client_id:
                try:
                    client = Client.objects.filter(id=client_id).first()
                except Exception:
                    pass

        # If still no specific client and user is Admin, return global overview
        if not client:
            if is_admin:
                try:
                    from django.db.models import Sum
                    total_wallets = ClientWallet.objects.aggregate(total=Sum('balance_paise'))['total'] or 0
                except Exception:
                    total_wallets = sum(getattr(w, 'balance_paise', 0) or 0 for w in ClientWallet.objects.all())

                # Return recent system-wide ledger transactions for admin
                global_entries = WalletLedger.objects.all().order_by('-created_at')[:50]
                transactions_data = [{
                    'id': str(entry.id),
                    'transaction_id': entry.transaction_id,
                    'client_name': entry.client.business_name if entry.client else 'System',
                    'type': entry.type,
                    'amount_inr': entry.amount_inr,
                    'amount_paise': entry.amount_paise,
                    'balance_after_inr': entry.balance_after_inr,
                    'description': entry.description,
                    'service_category': entry.service_category,
                    'reference_id': entry.reference_id,
                    'status': entry.status,
                    'created_at': entry.created_at.isoformat()
                } for entry in global_entries]

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
                    'transactions': transactions_data
                }, status=status.HTTP_200_OK)

            return Response({'error': 'No workspace client associated with user.'}, status=status.HTTP_400_BAD_REQUEST)

        summary = WalletService.get_wallet_summary(client)

        # Retrieve recent ledger transactions for client
        ledger_entries = WalletLedger.objects.filter(client=client).order_by('-created_at')[:50]
        transactions_data = [{
            'id': str(entry.id),
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
        is_admin = getattr(user, 'role', '') == 'ADMIN' or getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)
        client = getattr(user, 'client', None)

        if is_admin and not client:
            client_id = request.data.get('client_id')
            if client_id:
                try:
                    client = Client.objects.filter(id=client_id).first()
                except Exception:
                    pass

        if not client:
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
                client=client,
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
        is_admin = getattr(user, 'role', '') == 'ADMIN' or getattr(user, 'is_staff', False) or getattr(user, 'is_superuser', False)

        if not getattr(user, 'client', None) and not is_admin:
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
        payment_entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
        order_entity = payload.get('payload', {}).get('order', {}).get('entity', {})

        razorpay_order_id = payment_entity.get('order_id') or order_entity.get('id')
        razorpay_payment_id = payment_entity.get('id')

        if razorpay_order_id and event in ['payment.captured', 'order.paid']:
            try:
                recharge_order = WalletRechargeOrder.objects.filter(razorpay_order_id=razorpay_order_id).first()
                if not recharge_order:
                    recharge_order = WalletRechargeOrder.objects.filter(order_id=razorpay_order_id).first()

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


@method_decorator(csrf_exempt, name='dispatch')
class WalletRechargeCheckoutView(APIView):
    """
    GET /api/wallet/recharge/checkout/?order_id=<order_id>&redirect_url=<redirect_url>
    POST /api/wallet/recharge/checkout/

    Mobile In-App Browser checkout page for Android and iOS.
    Renders a responsive checkout window with the official Razorpay Checkout SDK.
    Verifies payment signature and redirects back to the app deep link (uwoconnect://payment-result).
    """
    permission_classes = [AllowAny]

    def get(self, request):
        order_id = request.query_params.get('order_id') or request.GET.get('order_id')
        redirect_url = request.query_params.get('redirect_url') or request.GET.get('redirect_url') or 'uwoconnect://payment-result'

        if not order_id:
            html = f"""<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #fff; margin: 0; padding: 24px; display: flex; align-items: center; justify-content: center; min-height: 100vh; text-align: center; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 24px; padding: 32px 24px; max-width: 380px; width: 100%; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
  .btn {{ display: block; width: 100%; padding: 14px; background: #ef4444; color: #fff; text-decoration: none; border-radius: 14px; font-weight: 700; margin-top: 24px; box-sizing: border-box; }}
</style>
</head><body>
<div class="card">
  <h2 style="margin:0 0 12px 0;">Order ID Missing</h2>
  <p style="color:#94a3b8; font-size:14px; line-height:1.5;">No valid order identifier was provided.</p>
  <a href="{redirect_url}?status=error&message=No+order_id+provided" class="btn">Return to App</a>
</div>
</body></html>"""
            return HttpResponse(html, content_type="text/html", status=400)

        recharge_order = WalletRechargeOrder.objects.filter(order_id=order_id).first()
        if not recharge_order:
            recharge_order = WalletRechargeOrder.objects.filter(razorpay_order_id=order_id).first()

        if not recharge_order:
            html = f"""<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #fff; margin: 0; padding: 24px; display: flex; align-items: center; justify-content: center; min-height: 100vh; text-align: center; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 24px; padding: 32px 24px; max-width: 380px; width: 100%; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
  .btn {{ display: block; width: 100%; padding: 14px; background: #ef4444; color: #fff; text-decoration: none; border-radius: 14px; font-weight: 700; margin-top: 24px; box-sizing: border-box; }}
</style>
</head><body>
<div class="card">
  <h2 style="margin:0 0 12px 0;">Order Not Found</h2>
  <p style="color:#94a3b8; font-size:14px; line-height:1.5;">Recharge order {order_id} could not be located.</p>
  <a href="{redirect_url}?status=error&message=Order+not+found" class="btn">Return to App</a>
</div>
</body></html>"""
            return HttpResponse(html, content_type="text/html", status=404)

        if recharge_order.status == 'PAID':
            html = f"""<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="2;url={redirect_url}?status=success&order_id={recharge_order.order_id}&amount={recharge_order.amount_inr}">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #fff; margin: 0; padding: 24px; display: flex; align-items: center; justify-content: center; min-height: 100vh; text-align: center; }}
  .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 24px; padding: 32px 24px; max-width: 380px; width: 100%; }}
  .check {{ width: 56px; height: 56px; border-radius: 50%; background: rgba(16,185,129,0.2); color: #10b981; font-size: 28px; display: flex; align-items: center; justify-content: center; margin: 0 auto 16px auto; }}
  .btn {{ display: block; width: 100%; padding: 14px; background: #10b981; color: #fff; text-decoration: none; border-radius: 14px; font-weight: 700; margin-top: 24px; box-sizing: border-box; }}
</style>
</head><body>
<div class="card">
  <div class="check">&#10004;</div>
  <h2 style="margin:0 0 8px 0;">Already Recharged!</h2>
  <p style="color:#94a3b8; font-size:14px; line-height:1.5;">₹{recharge_order.amount_inr} has already been credited to your wallet balance.</p>
  <a href="{redirect_url}?status=success&order_id={recharge_order.order_id}&amount={recharge_order.amount_inr}" class="btn">Back to App</a>
</div>
</body></html>"""
            return HttpResponse(html, content_type="text/html", status=200)

        from api.services.razorpay_service import RazorpayService
        rzp_service = RazorpayService()
        key_id = rzp_service.key_id or 'rzp_test_1DP5mmOlF5G5ag'
        user = recharge_order.user
        client = recharge_order.client
        user_email = getattr(user, 'email', '') or ''
        client_name = getattr(client, 'business_name', '') or 'UwoConnect Workspace'
        amount_inr = float(recharge_order.amount_inr)
        amount_paise = int(recharge_order.amount_paise)
        razorpay_order_id = recharge_order.razorpay_order_id or recharge_order.order_id
        is_mock = 'mock' in razorpay_order_id or not rzp_service.key_id

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>UwoConnect Secure Checkout</title>
  <script src="https://checkout.razorpay.com/v1/checkout.js"></script>
  <style>
    * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background: #090d16;
      color: #f8fafc;
      margin: 0;
      padding: 20px 16px;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
    }}
    .checkout-card {{
      background: #131b2e;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 28px;
      padding: 32px 24px;
      max-width: 420px;
      width: 100%;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.7);
      text-align: center;
      position: relative;
      overflow: hidden;
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 6px 14px;
      background: rgba(16, 185, 129, 0.15);
      border: 1px solid rgba(16, 185, 129, 0.3);
      border-radius: 9999px;
      color: #34d399;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      margin-bottom: 20px;
    }}
    .title {{ font-size: 20px; font-weight: 800; margin: 0 0 6px 0; color: #ffffff; }}
    .subtitle {{ font-size: 13px; color: #94a3b8; margin: 0 0 24px 0; }}
    .amount-box {{
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 20px;
      padding: 20px 16px;
      margin-bottom: 24px;
    }}
    .amount-label {{ font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700; letter-spacing: 0.05em; }}
    .amount-val {{ font-size: 36px; font-weight: 900; color: #10b981; margin: 6px 0; }}
    .details-row {{ display: flex; justify-content: space-between; font-size: 13px; color: #94a3b8; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255, 255, 255, 0.05); }}
    .details-row span:last-child {{ color: #e2e8f0; font-weight: 600; }}
    .btn-pay {{
      display: block;
      width: 100%;
      padding: 16px;
      background: #10b981;
      color: #ffffff;
      border: none;
      border-radius: 16px;
      font-size: 16px;
      font-weight: 800;
      cursor: pointer;
      box-shadow: 0 10px 15px -3px rgba(16, 185, 129, 0.4);
      transition: all 0.2s ease;
    }}
    .btn-pay:hover {{ background: #059669; }}
    .btn-cancel {{
      display: block;
      width: 100%;
      padding: 14px;
      background: transparent;
      color: #94a3b8;
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 16px;
      font-size: 14px;
      font-weight: 600;
      text-decoration: none;
      margin-top: 12px;
      cursor: pointer;
    }}
    .status-msg {{
      margin-top: 16px;
      font-size: 13px;
      color: #38bdf8;
      display: none;
    }}
    .security-note {{
      margin-top: 24px;
      font-size: 11px;
      color: #64748b;
      display: flex;
      align-items: center;
      justify-content: center;
      gap: 6px;
    }}
  </style>
</head>
<body>
  <div class="checkout-card">
    <div class="badge">🔒 256-Bit Razorpay Secure</div>
    <h1 class="title">Wallet Balance Recharge</h1>
    <p class="subtitle">Complete payment to instantly add credits</p>

    <div class="amount-box">
      <div class="amount-label">Recharge Amount</div>
      <div class="amount-val">₹{amount_inr:,.2f}</div>
      <div class="details-row">
        <span>Order Reference</span>
        <span>{recharge_order.order_id}</span>
      </div>
      <div class="details-row">
        <span>Workspace</span>
        <span>{client_name}</span>
      </div>
    </div>

    <button id="pay-btn" class="btn-pay" onclick="launchCheckout()">
      Pay ₹{amount_inr:,.2f} with Razorpay
    </button>
    <button class="btn-cancel" onclick="cancelPayment()">Cancel & Return to App</button>

    <div id="status-box" class="status-msg">Opening secure payment gateway...</div>

    <div class="security-note">
      UPI • Cards • NetBanking • Wallets
    </div>
  </div>

  <script>
    const ORDER_ID = "{recharge_order.order_id}";
    const RZP_ORDER_ID = "{razorpay_order_id}";
    const KEY_ID = "{key_id}";
    const AMOUNT_PAISE = {amount_paise};
    const AMOUNT_INR = {amount_inr};
    const USER_EMAIL = "{user_email}";
    const CLIENT_NAME = "{client_name}";
    const REDIRECT_URL = "{redirect_url}";
    const IS_MOCK = {str(is_mock).lower()};

    function setStatus(msg, isError = false) {{
      const box = document.getElementById('status-box');
      box.style.display = 'block';
      box.textContent = msg;
      box.style.color = isError ? '#f87171' : '#38bdf8';
    }}

    function cancelPayment() {{
      window.location.href = REDIRECT_URL + '?status=cancelled&order_id=' + encodeURIComponent(ORDER_ID);
    }}

    function verifyAndComplete(paymentId, signature) {{
      setStatus('Verifying payment signature...');
      document.getElementById('pay-btn').disabled = true;

      fetch('/api/wallet/recharge/checkout/', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          order_id: ORDER_ID,
          razorpay_order_id: RZP_ORDER_ID,
          razorpay_payment_id: paymentId,
          razorpay_signature: signature,
          force_mock_success: IS_MOCK
        }})
      }})
      .then(res => res.json())
      .then(data => {{
        if (data.success) {{
          setStatus('Payment Successful! Returning to UwoConnect...');
          setTimeout(() => {{
            window.location.href = REDIRECT_URL + '?status=success&order_id=' + encodeURIComponent(ORDER_ID) + '&amount=' + AMOUNT_INR;
          }}, 500);
        }} else {{
          setStatus(data.error || 'Payment verification failed.', true);
          document.getElementById('pay-btn').disabled = false;
        }}
      }})
      .catch(err => {{
        setStatus('Network verification error: ' + err.message, true);
        document.getElementById('pay-btn').disabled = false;
      }});
    }}

    function launchCheckout() {{
      setStatus('Launching Razorpay Checkout...');

      if (IS_MOCK || !window.Razorpay) {{
        // Sandbox Mock Mode
        if (confirm('Simulate successful payment of ₹' + AMOUNT_INR + ' in Test Sandbox mode?')) {{
          verifyAndComplete('pay_mock_' + Date.now(), 'mock_sig_pass');
        }} else {{
          setStatus('Payment cancelled by user.', true);
        }}
        return;
      }}

      try {{
        const options = {{
          key: KEY_ID,
          amount: AMOUNT_PAISE,
          currency: 'INR',
          name: 'UwoConnect',
          description: 'Prepaid Usage Wallet Recharge (₹' + AMOUNT_INR + ')',
          order_id: RZP_ORDER_ID.startsWith('order_') ? RZP_ORDER_ID : undefined,
          prefill: {{
            name: CLIENT_NAME,
            email: USER_EMAIL
          }},
          theme: {{
            color: '#10b981'
          }},
          handler: function (response) {{
            verifyAndComplete(response.razorpay_payment_id, response.razorpay_signature);
          }},
          modal: {{
            ondismiss: function () {{
              setStatus('Payment was dismissed or cancelled.', true);
            }}
          }}
        }};

        const rzp = new window.Razorpay(options);
        rzp.on('payment.failed', function (resp) {{
          setStatus('Payment Failed: ' + (resp.error?.description || 'Unknown error'), true);
        }});
        rzp.open();
      }} catch (e) {{
        setStatus('Failed to launch Razorpay: ' + e.message, true);
      }}
    }}

    window.addEventListener('DOMContentLoaded', () => {{
      setTimeout(launchCheckout, 600);
    }});
  </script>
</body>
</html>"""
        return HttpResponse(html, content_type="text/html", status=200)

    def post(self, request):
        """
        POST /api/wallet/recharge/checkout/
        Public endpoint for the in-app checkout page to verify Razorpay signature and credit the wallet.
        Body: { order_id, razorpay_order_id, razorpay_payment_id, razorpay_signature, force_mock_success }
        """
        order_id = request.data.get('order_id') or request.data.get('razorpay_order_id')
        payment_id = request.data.get('razorpay_payment_id')
        signature = request.data.get('razorpay_signature')
        force_mock_success = request.data.get('force_mock_success', False)

        if not order_id:
            return Response({'error': 'order_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

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
            logger.error(f"[WalletRechargeCheckoutView.post] Error: {err}")
            return Response({'error': 'Payment verification failed.'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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
                'client_id': str(client.id),
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
        adjustment_type = request.data.get('type', 'ADJUSTMENT') # ADJUSTMENT, REFUND, BONUS, DEBIT
        amount_inr = request.data.get('amount')
        reason = request.data.get('reason')
        is_deduction = request.data.get('is_deduction', False)

        if not client_id or amount_inr is None or not reason:
            return Response({'error': 'client_id, amount, and reason are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = Client.objects.get(id=client_id)
            amount_float = float(amount_inr)
            
            # If specified as deduction or negative amount
            if is_deduction or adjustment_type == 'DEBIT':
                amount_float = -abs(amount_float)
            
            if adjustment_type == 'DEBIT':
                adjustment_type = 'ADJUSTMENT'

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
                'message': f"Successfully applied {adjustment_type} of ₹{abs(amount_float)} to {client.business_name}.",
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
