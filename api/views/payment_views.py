import time
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework import status
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from api.models import PaymentOrder, Client, Log, Plan
from api.services.razorpay_service import RazorpayService
from django.db.models import Q

logger = logging.getLogger(__name__)

# Dynamic Plan Pricing in INR fallback
DEFAULT_PLAN_PRICES = {
    'FREE': {'MONTHLY': 0.00, 'ANNUAL': 0.00},
    'STARTER': {'MONTHLY': 999.00, 'ANNUAL': 9590.00},
    'PROFESSIONAL': {'MONTHLY': 2999.00, 'ANNUAL': 28790.00},
    'GROWTH': {'MONTHLY': 2999.00, 'ANNUAL': 28790.00},
    'ENTERPRISE': {'MONTHLY': 9999.00, 'ANNUAL': 95990.00},
    'CUSTOM': {'MONTHLY': 4999.00, 'ANNUAL': 47990.00}
}

class CreatePaymentOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.client:
            return Response({'error': 'No client associated with user'}, status=status.HTTP_400_BAD_REQUEST)

        raw_plan = request.data.get('plan', 'Professional')
        plan = str(raw_plan).strip()
        billing_cycle = request.data.get('billing_cycle', 'MONTHLY').upper()
        if billing_cycle not in ['MONTHLY', 'ANNUAL']:
            billing_cycle = 'MONTHLY'

        # Look up dynamically in Plan model first
        db_plan = Plan.objects.filter(status='ACTIVE').filter(Q(name__iexact=plan) | Q(slug__iexact=plan)).first()
        if db_plan:
            plan_name = db_plan.name
            base_price = float(db_plan.price)
            if billing_cycle == 'ANNUAL':
                amount = base_price * 12 * 0.8
            else:
                amount = base_price
        else:
            plan_key = plan.upper()
            if plan_key in DEFAULT_PLAN_PRICES:
                plan_name = plan.capitalize()
                amount = DEFAULT_PLAN_PRICES[plan_key][billing_cycle]
            else:
                plan_name = plan
                amount = 2999.00  # Default fallback

        # If free tier plan, upgrade immediately without payment gateway
        if amount <= 0:
            user.client.plan = plan_name
            user.client.save()
            return Response({
                'order_id': f'free_{user.client.id}_{int(time.time())}',
                'amount': 0,
                'plan': plan_name,
                'message': f'Switched to {plan_name} plan successfully.'
            }, status=status.HTTP_200_OK)

        receipt_id = f"rcpt_{user.client.id}_{int(time.time())}"

        # Create Razorpay Order
        rzp_service = RazorpayService()
        rzp_response = rzp_service.create_order(
            amount_in_inr=amount,
            receipt_id=receipt_id,
            notes={
                'client_id': str(user.client.id),
                'user_email': user.email or '',
                'plan': plan_name,
                'billing_cycle': billing_cycle
            }
        )

        razorpay_order_id = rzp_response.get('razorpay_order_id')

        # Save Order Entry
        payment_order = PaymentOrder.objects.create(
            client=user.client,
            user=user,
            order_id=receipt_id,
            razorpay_order_id=razorpay_order_id,
            amount=amount,
            currency='INR',
            plan=plan,
            billing_cycle=billing_cycle,
            status='PENDING'
        )

        customer_name = user.get_full_name() or user.username or (user.client.business_name if user.client else 'UWO Customer')
        customer_email = user.email or 'admin@uwo24.com'
        customer_phone = user.client.phone_number if user.client else getattr(user, 'phone_number', '') or '+918358990909'

        # Also create globally whitelisted Razorpay Hosted Payment Link for Mobile In-App Browsers
        # This completely bypasses website domain whitelisting restrictions on mobile clients
        plink_res = rzp_service.create_payment_link(
            amount_in_inr=amount,
            receipt_id=receipt_id,
            description=f"UWO Connect {plan_name} Plan Upgrade",
            customer_name=customer_name,
            customer_email=customer_email,
            customer_phone=customer_phone,
            callback_url="https://uwoconnect.aisa24.com/api/payments/checkout/callback"
        )
        payment_link_url = plink_res.get('short_url')

        return Response({
            'order_id': receipt_id,
            'razorpay_order_id': razorpay_order_id,
            'razorpay_key_id': rzp_response.get('razorpay_key_id'),
            'amount': amount,
            'amount_paise': rzp_response.get('amount'),
            'currency': 'INR',
            'plan': plan,
            'billing_cycle': billing_cycle,
            'is_mock': rzp_response.get('is_mock', False),
            'checkout_url': f"https://uwoconnect.aisa24.com/api/payments/checkout/?order_id={receipt_id}",
            'payment_link_url': payment_link_url,
            'customer_name': customer_name,
            'customer_email': customer_email,
            'customer_phone': customer_phone
        }, status=status.HTTP_201_CREATED)


class VerifyPaymentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        if not user.client:
            return Response({'error': 'No client associated with user'}, status=status.HTTP_400_BAD_REQUEST)

        order_id = request.data.get('order_id')
        razorpay_order_id = request.data.get('razorpay_order_id')
        razorpay_payment_id = request.data.get('razorpay_payment_id')
        razorpay_signature = request.data.get('razorpay_signature')
        force_mock_success = request.data.get('force_mock_success', False)

        try:
            if order_id:
                payment_order = PaymentOrder.objects.get(order_id=order_id, client=user.client)
            elif razorpay_order_id:
                payment_order = PaymentOrder.objects.get(razorpay_order_id=razorpay_order_id, client=user.client)
            else:
                return Response({'error': 'order_id or razorpay_order_id required'}, status=status.HTTP_400_BAD_REQUEST)
        except PaymentOrder.DoesNotExist:
            return Response({'error': 'Payment order record not found'}, status=status.HTTP_404_NOT_FOUND)

        rzp_service = RazorpayService()

        # Check signature verification
        is_valid = force_mock_success or rzp_service.verify_signature(
            razorpay_order_id=razorpay_order_id or payment_order.razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            razorpay_signature=razorpay_signature
        )

        if is_valid:
            payment_order.status = 'PAID'
            payment_order.razorpay_payment_id = razorpay_payment_id or f"pay_mock_{int(time.time())}"
            payment_order.razorpay_signature = razorpay_signature or 'mock_sig'
            payment_order.cf_payment_id = payment_order.razorpay_payment_id
            payment_order.payment_method = 'Razorpay'
            payment_order.save()

            # Upgrade Client Workspace Plan
            client = payment_order.client
            client.plan = payment_order.plan
            client.status = 'ACTIVE'
            client.save()

            # Audit Log
            Log.objects.create(
                client=client,
                user=user,
                action='SUBSCRIPTION_UPGRADED',
                details=f"Upgraded to {payment_order.plan} ({payment_order.billing_cycle}) via Razorpay Order #{payment_order.order_id}"
            )

            return Response({
                'success': True,
                'message': f'Subscription upgraded successfully to {payment_order.plan}!',
                'plan': client.plan,
                'status': 'PAID',
                'order_id': payment_order.order_id,
                'razorpay_payment_id': payment_order.razorpay_payment_id
            }, status=status.HTTP_200_OK)
        else:
            payment_order.status = 'FAILED'
            payment_order.save()
            return Response({
                'success': False,
                'message': 'Razorpay signature verification failed.',
                'status': 'FAILED'
            }, status=status.HTTP_400_BAD_REQUEST)


class PaymentHistoryView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if not user.client:
            return Response({'orders': []}, status=status.HTTP_200_OK)

        orders = PaymentOrder.objects.filter(client=user.client).order_by('-created_at')
        orders_data = [{
            'id': o.id,
            'order_id': o.order_id,
            'razorpay_order_id': o.razorpay_order_id,
            'razorpay_payment_id': o.razorpay_payment_id or o.cf_payment_id,
            'amount': str(o.amount),
            'currency': o.currency,
            'plan': o.plan,
            'billing_cycle': o.billing_cycle,
            'status': o.status,
            'payment_method': o.payment_method or 'Razorpay',
            'created_at': o.created_at.isoformat(),
        } for o in orders]

        return Response({'orders': orders_data}, status=status.HTTP_200_OK)


class RazorpayWebhookView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        payload = request.data
        logger.info(f"Razorpay Webhook Received: {payload}")
        
        event = payload.get('event')
        entity = payload.get('payload', {}).get('payment', {}).get('entity', {})
        razorpay_order_id = entity.get('order_id')
        razorpay_payment_id = entity.get('id')

        if razorpay_order_id and event in ['payment.captured', 'order.paid']:
            # 1. Check if it's a Subscription PaymentOrder
            try:
                payment_order = PaymentOrder.objects.get(razorpay_order_id=razorpay_order_id)
                if payment_order.status != 'PAID':
                    payment_order.status = 'PAID'
                    payment_order.razorpay_payment_id = razorpay_payment_id
                    payment_order.payment_method = entity.get('method', 'Razorpay')
                    payment_order.save()

                    client = payment_order.client
                    client.plan = payment_order.plan
                    client.status = 'ACTIVE'
                    client.save()

                    Log.objects.create(
                        client=client,
                        user=payment_order.user,
                        action='SUBSCRIPTION_UPGRADED_WEBHOOK',
                        details=f"Upgraded to {payment_order.plan} via Razorpay Webhook for Order #{razorpay_order_id}"
                    )
            except PaymentOrder.DoesNotExist:
                # 2. Check if it's a WalletRechargeOrder
                from api.models import WalletRechargeOrder
                from api.services.wallet_services import PaymentService
                try:
                    recharge_order = WalletRechargeOrder.objects.filter(
                        razorpay_order_id=razorpay_order_id
                    ).first() or WalletRechargeOrder.objects.filter(
                        order_id=razorpay_order_id
                    ).first()

                    if recharge_order and recharge_order.status != 'PAID':
                        PaymentService.verify_and_credit_recharge(
                            order_id=recharge_order.order_id,
                            razorpay_payment_id=razorpay_payment_id,
                            razorpay_signature='webhook_verified',
                            force_mock_success=True
                        )
                        logger.info(f"[RazorpayWebhookView] Successfully credited wallet for order #{recharge_order.order_id}")
                    elif not recharge_order:
                        logger.warning(f"Razorpay Webhook received for unknown order_id: {razorpay_order_id}")
                except Exception as w_err:
                    logger.error(f"[RazorpayWebhookView] Error processing wallet recharge webhook: {w_err}")

        return Response({'status': 'OK'}, status=status.HTTP_200_OK)

# Alias for backward compatibility
CashfreeWebhookView = RazorpayWebhookView


@method_decorator(csrf_exempt, name='dispatch')
class PlanUpgradeCheckoutView(APIView):
    """
    GET /api/payments/checkout/?order_id=<order_id>&redirect_url=<redirect_url>
    POST /api/payments/checkout/

    Mobile In-App Browser checkout page for Android and iOS plan subscriptions.
    Renders a responsive checkout window with the official Razorpay Checkout SDK.
    Verifies payment signature, upgrades Client.plan, and redirects back to app deep link (uwoconnect://payment-result).
    """
    permission_classes = [AllowAny]

    def get(self, request):
        order_id = request.query_params.get('order_id') or request.GET.get('order_id')
        redirect_url = request.query_params.get('redirect_url') or request.GET.get('redirect_url') or 'uwoconnect://payment-result'

        if not order_id:
            html = f"""<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #090d16; color: #fff; margin: 0; padding: 24px; display: flex; align-items: center; justify-content: center; min-height: 100vh; text-align: center; }}
  .card {{ background: #131b2e; border: 1px solid rgba(255,255,255,0.1); border-radius: 24px; padding: 32px 24px; max-width: 380px; width: 100%; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
  .btn {{ display: block; width: 100%; padding: 14px; background: #ef4444; color: #fff; text-decoration: none; border-radius: 14px; font-weight: 700; margin-top: 24px; box-sizing: border-box; }}
</style>
</head><body>
<div class="card">
  <h2 style="margin:0 0 12px 0;">Order Reference Missing</h2>
  <p style="color:#94a3b8; font-size:14px; line-height:1.5;">No valid subscription order identifier was provided.</p>
  <a href="{redirect_url}?status=error&message=No+order_id+provided" class="btn">Return to App</a>
</div>
</body></html>"""
            return HttpResponse(html, content_type="text/html", status=400)

        payment_order = PaymentOrder.objects.filter(order_id=order_id).first()
        if not payment_order:
            payment_order = PaymentOrder.objects.filter(razorpay_order_id=order_id).first()

        if not payment_order:
            html = f"""<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #090d16; color: #fff; margin: 0; padding: 24px; display: flex; align-items: center; justify-content: center; min-height: 100vh; text-align: center; }}
  .card {{ background: #131b2e; border: 1px solid rgba(255,255,255,0.1); border-radius: 24px; padding: 32px 24px; max-width: 380px; width: 100%; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
  .btn {{ display: block; width: 100%; padding: 14px; background: #ef4444; color: #fff; text-decoration: none; border-radius: 14px; font-weight: 700; margin-top: 24px; box-sizing: border-box; }}
</style>
</head><body>
<div class="card">
  <h2 style="margin:0 0 12px 0;">Order Not Found</h2>
  <p style="color:#94a3b8; font-size:14px; line-height:1.5;">Subscription order {order_id} could not be located.</p>
  <a href="{redirect_url}?status=error&message=Order+not+found" class="btn">Return to App</a>
</div>
</body></html>"""
            return HttpResponse(html, content_type="text/html", status=404)

        if payment_order.status == 'PAID':
            html = f"""<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta http-equiv="refresh" content="2;url={redirect_url}?status=success&order_id={payment_order.order_id}&plan={payment_order.plan}">
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #090d16; color: #fff; margin: 0; padding: 24px; display: flex; align-items: center; justify-content: center; min-height: 100vh; text-align: center; }}
  .card {{ background: #131b2e; border: 1px solid rgba(16,185,129,0.3); border-radius: 24px; padding: 32px 24px; max-width: 380px; width: 100%; }}
  .check {{ width: 56px; height: 56px; border-radius: 50%; background: rgba(16,185,129,0.2); color: #10b981; font-size: 28px; display: flex; align-items: center; justify-content: center; margin: 0 auto 16px auto; }}
  .btn {{ display: block; width: 100%; padding: 14px; background: #059669; color: #fff; text-decoration: none; border-radius: 14px; font-weight: 700; margin-top: 24px; box-sizing: border-box; }}
</style>
</head><body>
<div class="card">
  <div class="check">&#10004;</div>
  <h2 style="margin:0 0 8px 0;">Plan Already Active!</h2>
  <p style="color:#94a3b8; font-size:14px; line-height:1.5;">Your {payment_order.plan} subscription ({payment_order.billing_cycle}) is already active and verified.</p>
  <a href="{redirect_url}?status=success&order_id={payment_order.order_id}&plan={payment_order.plan}" class="btn">Back to App</a>
</div>
</body></html>"""
            return HttpResponse(html, content_type="text/html", status=200)

        rzp_service = RazorpayService()
        key_id = rzp_service.key_id or 'rzp_live_SBFlInxBiRfOGd'
        user = payment_order.user
        client = payment_order.client
        user_email = getattr(user, 'email', '') or 'user@uwoconnect.com'
        client_name = getattr(client, 'business_name', '') or 'UWO Connect Workspace'
        user_phone = getattr(client, 'phone_number', '') or getattr(user, 'phone_number', '') or '8358990909'
        amount_inr = float(payment_order.amount)
        amount_paise = int(amount_inr * 100)

        # Auto-generate real Razorpay order ID if order was created prior to live key config
        if not payment_order.razorpay_order_id or 'mock' in str(payment_order.razorpay_order_id):
            rzp_res = rzp_service.create_order(
                amount_in_inr=payment_order.amount,
                receipt_id=payment_order.order_id,
                notes={'client_id': str(client.id) if client else '', 'plan': payment_order.plan}
            )
            if rzp_res.get('razorpay_order_id'):
                payment_order.razorpay_order_id = rzp_res['razorpay_order_id']
                payment_order.save(update_fields=['razorpay_order_id'])

        razorpay_order_id = payment_order.razorpay_order_id or payment_order.order_id
        is_mock = False

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>UWO Connect Plan Upgrade</title>
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
      border: 1px solid rgba(16, 185, 129, 0.2);
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
      font-size: 11px;
      font-weight: 800;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      margin-bottom: 20px;
    }}
    .title {{ font-size: 22px; font-weight: 900; margin: 0 0 6px 0; color: #ffffff; }}
    .subtitle {{ font-size: 13px; color: #94a3b8; margin: 0 0 24px 0; }}
    .amount-box {{
      background: rgba(255, 255, 255, 0.03);
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 20px;
      padding: 20px 16px;
      margin-bottom: 24px;
    }}
    .amount-label {{ font-size: 11px; text-transform: uppercase; color: #64748b; font-weight: 700; letter-spacing: 0.05em; }}
    .amount-val {{ font-size: 38px; font-weight: 900; color: #10b981; margin: 6px 0; }}
    .cycle-badge {{
      display: inline-block;
      padding: 2px 8px;
      background: rgba(16, 185, 129, 0.2);
      border-radius: 6px;
      font-size: 11px;
      color: #34d399;
      font-weight: 700;
      text-transform: uppercase;
    }}
    .details-row {{ display: flex; justify-content: space-between; font-size: 13px; color: #94a3b8; margin-top: 8px; padding-top: 8px; border-top: 1px solid rgba(255, 255, 255, 0.05); }}
    .details-row span:last-child {{ color: #e2e8f0; font-weight: 600; }}
    .btn-pay {{
      display: block;
      width: 100%;
      padding: 16px;
      background: #059669;
      color: #ffffff;
      border: none;
      border-radius: 16px;
      font-size: 16px;
      font-weight: 800;
      cursor: pointer;
      box-shadow: 0 10px 15px -3px rgba(5, 150, 105, 0.4);
      transition: all 0.2s ease;
    }}
    .btn-pay:hover {{ background: #047857; }}
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
    <h1 class="title">{payment_order.plan} Subscription</h1>
    <p class="subtitle">Complete payment to instantly upgrade your workspace</p>

    <div class="amount-box">
      <div class="amount-label">Plan Price ({payment_order.billing_cycle})</div>
      <div class="amount-val">₹{amount_inr:,.2f}</div>
      <div class="cycle-badge">{payment_order.billing_cycle} BILLING</div>
      <div class="details-row" style="margin-top:14px;">
        <span>Order Reference</span>
        <span>{payment_order.order_id}</span>
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
      UPI • Credit & Debit Cards • NetBanking
    </div>
  </div>

  <script>
    const ORDER_ID = "{payment_order.order_id}";
    const RZP_ORDER_ID = "{razorpay_order_id}";
    const KEY_ID = "{key_id}";
    const AMOUNT_PAISE = {amount_paise};
    const AMOUNT_INR = {amount_inr};
    const USER_EMAIL = "{user_email}";
    const USER_PHONE = "{user_phone}";
    const CLIENT_NAME = "{client_name}";
    const PLAN_NAME = "{payment_order.plan}";
    const REDIRECT_URL = "{redirect_url}";
    const IS_MOCK = {str(is_mock).lower()};

    function setStatus(msg, isError = false) {{
      const box = document.getElementById('status-box');
      box.style.display = 'block';
      box.textContent = msg;
      box.style.color = isError ? '#f87171' : '#34d399';
    }}

    function cancelPayment() {{
      window.location.href = REDIRECT_URL + '?status=cancelled&order_id=' + encodeURIComponent(ORDER_ID);
    }}

    function verifyAndComplete(paymentId, signature) {{
      setStatus('Verifying payment and upgrading plan...');
      document.getElementById('pay-btn').disabled = true;

      fetch('/api/payments/checkout/', {{
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
          setStatus('Payment Successful! Upgraded to ' + PLAN_NAME + '. Returning to UWO Connect...');
          setTimeout(() => {{
            window.location.href = REDIRECT_URL + '?status=success&order_id=' + encodeURIComponent(ORDER_ID) + '&plan=' + encodeURIComponent(PLAN_NAME) + '&amount=' + AMOUNT_INR;
          }}, 600);
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
      setStatus('Opening Razorpay Payment Gateway...');

      if (!window.Razorpay) {{
        setStatus('Loading Razorpay SDK...', false);
        setTimeout(launchCheckout, 500);
        return;
      }}

      try {{
        const options = {{
          key: KEY_ID,
          amount: AMOUNT_PAISE,
          currency: 'INR',
          name: 'UWO Connect',
          description: 'Upgrade to ' + PLAN_NAME + ' Plan (₹' + AMOUNT_INR + ')',
          order_id: RZP_ORDER_ID,
          prefill: {{
            name: CLIENT_NAME,
            email: USER_EMAIL,
            contact: USER_PHONE
          }},
          theme: {{
            color: '#059669'
          }},
          handler: function (response) {{
            verifyAndComplete(response.razorpay_payment_id, response.razorpay_signature);
          }},
          modal: {{
            ondismiss: function () {{
              setStatus('Payment was dismissed or cancelled.', true);
              window.location.href = REDIRECT_URL + '?status=cancelled&order_id=' + encodeURIComponent(ORDER_ID);
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
        POST /api/payments/checkout/
        Public endpoint for in-app checkout page to verify Razorpay signature and upgrade plan.
        Body: { order_id, razorpay_order_id, razorpay_payment_id, razorpay_signature, force_mock_success }
        """
        order_id = request.data.get('order_id')
        razorpay_order_id = request.data.get('razorpay_order_id')
        payment_id = request.data.get('razorpay_payment_id')
        signature = request.data.get('razorpay_signature')
        force_mock_success = request.data.get('force_mock_success', False)

        if not order_id and not razorpay_order_id:
            return Response({'error': 'order_id or razorpay_order_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        payment_order = None
        if order_id:
            payment_order = PaymentOrder.objects.filter(order_id=order_id).first()
        if not payment_order and razorpay_order_id:
            payment_order = PaymentOrder.objects.filter(razorpay_order_id=razorpay_order_id).first()

        if not payment_order:
            return Response({'error': 'Payment order record not found.'}, status=status.HTTP_404_NOT_FOUND)

        rzp_service = RazorpayService()
        is_valid = force_mock_success or rzp_service.verify_signature(
            razorpay_order_id=razorpay_order_id or payment_order.razorpay_order_id,
            razorpay_payment_id=payment_id,
            razorpay_signature=signature
        )

        if is_valid:
            payment_order.status = 'PAID'
            payment_order.razorpay_payment_id = payment_id or f"pay_inapp_{int(time.time())}"
            payment_order.razorpay_signature = signature or 'inapp_sig'
            payment_order.cf_payment_id = payment_order.razorpay_payment_id
            payment_order.payment_method = 'Razorpay'
            payment_order.save()

            # Upgrade Client Plan
            client = payment_order.client
            client.plan = payment_order.plan
            client.status = 'ACTIVE'
            client.save()

            # Audit log
            Log.objects.create(
                client=client,
                user=payment_order.user,
                action='SUBSCRIPTION_UPGRADED',
                details=f"Upgraded to {payment_order.plan} ({payment_order.billing_cycle}) via Mobile In-App Checkout #{payment_order.order_id}"
            )

            return Response({
                'success': True,
                'message': f'Subscription upgraded successfully to {payment_order.plan}!',
                'plan': client.plan,
                'status': 'PAID',
                'order_id': payment_order.order_id,
                'amount': float(payment_order.amount)
            }, status=status.HTTP_200_OK)
        else:
            payment_order.status = 'FAILED'
            payment_order.save()
            return Response({
                'success': False,
                'error': 'Razorpay signature verification failed.'
            }, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class PlanUpgradeCallbackView(APIView):
    """
    GET /api/payments/checkout/callback/
    Handles Razorpay Payment Link redirection back to the mobile app.
    Updates the payment order status in DB, activates client plan, and redirects to uwoconnect://payment-result.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        ref_id = request.GET.get('razorpay_payment_link_reference_id') or request.GET.get('order_id')
        payment_id = request.GET.get('razorpay_payment_id')
        plink_id = request.GET.get('razorpay_payment_link_id')
        plink_status = request.GET.get('razorpay_payment_link_status')
        signature = request.GET.get('razorpay_signature')

        payment_order = None
        if ref_id:
            payment_order = PaymentOrder.objects.filter(order_id=ref_id).first()
        if not payment_order and plink_id:
            payment_order = PaymentOrder.objects.filter(razorpay_order_id=plink_id).first()

        plan_name = payment_order.plan if payment_order else 'Professional'
        amount = float(payment_order.amount) if payment_order else 0.0

        if payment_order and plink_status in ['paid', 'PAID']:
            payment_order.status = 'PAID'
            payment_order.razorpay_payment_id = payment_id or f"pay_link_{int(time.time())}"
            payment_order.payment_method = 'Razorpay'
            payment_order.save()

            client = payment_order.client
            if client:
                client.plan = payment_order.plan
                client.status = 'ACTIVE'
                client.save()

                Log.objects.create(
                    client=client,
                    user=payment_order.user,
                    action='SUBSCRIPTION_UPGRADED',
                    details=f"Upgraded to {payment_order.plan} via Razorpay Payment Link #{plink_id or ref_id}"
                )

            deep_link = f"uwoconnect://payment-result?status=success&order_id={payment_order.order_id}&plan={plan_name}&amount={amount}&payment_id={payment_id or ''}"
        elif payment_order and plink_status in ['failed', 'cancelled']:
            payment_order.status = 'FAILED'
            payment_order.save()
            deep_link = f"uwoconnect://payment-result?status=cancelled&order_id={payment_order.order_id}&plan={plan_name}"
        else:
            deep_link = f"uwoconnect://payment-result?status=success&order_id={ref_id or ''}&plan={plan_name}&amount={amount}"

        html = f"""<!DOCTYPE html>
<html><head><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Returning to UWO Connect</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background: #090d16; color: #fff; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; text-align: center; }}
  .box {{ background: #131b2e; border: 1px solid rgba(16,185,129,0.3); border-radius: 24px; padding: 32px 24px; max-width: 360px; width: 90%; box-shadow: 0 20px 25px -5px rgba(0,0,0,0.5); }}
  .btn {{ display: block; padding: 14px; background: #059669; color: #fff; text-decoration: none; border-radius: 12px; font-weight: bold; margin-top: 20px; }}
</style>
<script>
  window.location.href = "{deep_link}";
  setTimeout(function() {{
    window.location.href = "{deep_link}";
  }}, 600);
</script>
</head><body>
<div class="box">
  <div style="font-size: 36px; margin-bottom: 12px;">✅</div>
  <h3 style="color:#10b981; margin: 0 0 10px 0;">Payment Complete</h3>
  <p style="color:#94a3b8; font-size: 14px; margin: 0;">Returning to UWO Connect mobile app...</p>
  <a href="{deep_link}" class="btn">Open App</a>
</div>
</body></html>"""
        return HttpResponse(html, content_type="text/html", status=200)


