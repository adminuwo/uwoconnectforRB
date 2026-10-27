import os
import hmac
import hashlib
import requests
from django.conf import settings
import logging

logger = logging.getLogger(__name__)

def payments_mock_allowed():
    """
    Mock/sandbox payment success is ONLY allowed for local development when BOTH
    DEBUG=True and ALLOW_MOCK_PAYMENTS=true are set. Never in production.
    """
    return bool(getattr(settings, 'DEBUG', False)) and os.getenv('ALLOW_MOCK_PAYMENTS', 'false').strip().lower() in ('1', 'true', 'yes')


class RazorpayService:
    def __init__(self):
        self.key_id = getattr(settings, 'RAZORPAY_KEY_ID', None) or os.getenv('RAZORPAY_KEY_ID', '')
        self.key_secret = getattr(settings, 'RAZORPAY_KEY_SECRET', None) or os.getenv('RAZORPAY_KEY_SECRET', '')
        if payments_mock_allowed():
            self.key_id = self.key_id or 'rzp_test_TGv2xByWyhTGoM'
        self.base_url = 'https://api.razorpay.com/v1'

    def _mock_or_error_order(self, receipt_id, amount_paise, error_message):
        """Returns a mock order only in local mock mode; otherwise an explicit failure."""
        if payments_mock_allowed():
            return {
                'razorpay_order_id': f"order_rzp_mock_{receipt_id}",
                'razorpay_key_id': self.key_id or 'rzp_test_1DP5mmOlF5G5ag',
                'amount': amount_paise,
                'currency': 'INR',
                'is_mock': True,
                'error_message': error_message,
            }
        raise RuntimeError(f"Payment gateway unavailable: {error_message}")

    def create_order(self, amount_in_inr, receipt_id, notes=None):
        """
        Creates a Razorpay Order.
        Amount is converted to paise (1 INR = 100 paise).
        """
        amount_paise = int(float(amount_in_inr) * 100)

        # Credentials missing: mock only in local mock mode, otherwise fail loudly
        if not self.key_id or not self.key_secret:
            logger.warning("RAZORPAY_KEY_ID or RAZORPAY_KEY_SECRET not set.")
            return self._mock_or_error_order(receipt_id, amount_paise, 'Razorpay credentials are not configured')

        safe_notes = {str(k): str(v) for k, v in (notes or {'platform': 'UWO Connect'}).items()}
        payload = {
            'amount': amount_paise,
            'currency': 'INR',
            'receipt': str(receipt_id),
            'notes': safe_notes
        }

        try:
            url = f"{self.base_url}/orders"
            res = requests.post(
                url, 
                json=payload, 
                auth=(self.key_id, self.key_secret), 
                timeout=10
            )
            data = res.json()

            if res.status_code in [200, 201] and 'id' in data:
                return {
                    'razorpay_order_id': data['id'],
                    'razorpay_key_id': self.key_id,
                    'amount': data['amount'],
                    'currency': data['currency'],
                    'is_mock': False,
                    'raw_data': data
                }
            else:
                logger.error(f"Razorpay Order Error: {res.status_code} - {data}")
                return self._mock_or_error_order(
                    receipt_id, amount_paise,
                    data.get('error', {}).get('description', 'Failed to create Razorpay order')
                )
        except RuntimeError:
            raise
        except Exception as e:
            logger.error(f"Razorpay Connection Exception: {str(e)}")
            return self._mock_or_error_order(receipt_id, amount_paise, str(e))

    def verify_signature(self, razorpay_order_id, razorpay_payment_id, razorpay_signature):
        """
        Verifies Razorpay HMAC SHA256 signature for standard orders.
        SECURITY: No magic-word bypass ('test', 'mock', 'valid' ...). Always HMAC-verified,
        except in explicit local mock mode for mock orders.
        """
        if payments_mock_allowed() and 'mock' in str(razorpay_order_id):
            return True

        if not self.key_secret or not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            return False

        try:
            msg = f"{razorpay_order_id}|{razorpay_payment_id}".encode('utf-8')
            secret_bytes = self.key_secret.encode('utf-8')
            generated_signature = hmac.new(secret_bytes, msg, hashlib.sha256).hexdigest()
            return hmac.compare_digest(generated_signature, razorpay_signature)
        except Exception as e:
            logger.error(f"Razorpay Signature Verification Error: {str(e)}")
            return False

    def create_payment_link(self, amount_in_inr, receipt_id, description, customer_name='', customer_email='', customer_phone='', callback_url=None):
        """
        Creates an official Razorpay Hosted Payment Link (rzp.io).
        Bypasses merchant website domain whitelisting restrictions on mobile in-app browsers
        because it is hosted directly on Razorpay's trusted global infrastructure.
        """
        amount_paise = int(float(amount_in_inr) * 100)

        if not self.key_id or not self.key_secret:
            if not payments_mock_allowed():
                return {'id': None, 'short_url': None, 'error': 'Razorpay credentials are not configured'}
            return {
                'id': f"plink_mock_{receipt_id}",
                'short_url': None,
                'is_mock': True
            }

        target_callback = callback_url or "https://uwoconnect.aisa24.com/api/payments/checkout/callback"

        payload = {
            'amount': amount_paise,
            'currency': 'INR',
            'accept_partial': False,
            'reference_id': str(receipt_id),
            'description': str(description),
            'customer': {
                'name': customer_name or 'UWO Connect Customer',
                'email': customer_email or 'admin@uwo24.com',
                'contact': customer_phone or '+918358990909'
            },
            'notify': {'sms': False, 'email': False, 'whatsapp': False},
            'callback_url': target_callback,
            'callback_method': 'get'
        }

        try:
            url = f"{self.base_url}/payment_links"
            res = requests.post(url, json=payload, auth=(self.key_id, self.key_secret), timeout=10)
            data = res.json()
            if res.status_code in [200, 201] and 'short_url' in data:
                return {
                    'id': data.get('id'),
                    'short_url': data.get('short_url'),
                    'is_mock': False,
                    'raw_data': data
                }
            else:
                logger.warning(f"Razorpay Payment Link Warning ({res.status_code}): {data}")
                return {'id': None, 'short_url': None, 'error': data}
        except Exception as e:
            logger.error(f"Razorpay Payment Link Exception: {str(e)}")
            return {'id': None, 'short_url': None, 'error': str(e)}

    def verify_payment_link_signature(self, payment_link_id, payment_link_ref_id, payment_link_status, payment_id, signature):
        """
        Verifies HMAC SHA256 signature for Razorpay Payment Links callback.
        """
        if payments_mock_allowed() and 'mock' in str(payment_link_id):
            return True

        if not self.key_secret or not all([payment_link_id, payment_link_ref_id, payment_link_status, payment_id, signature]):
            return False

        try:
            msg = f"{payment_link_id}|{payment_link_ref_id}|{payment_link_status}|{payment_id}".encode('utf-8')
            secret_bytes = self.key_secret.encode('utf-8')
            generated_signature = hmac.new(secret_bytes, msg, hashlib.sha256).hexdigest()
            return hmac.compare_digest(generated_signature, signature)
        except Exception as e:
            logger.error(f"Razorpay Payment Link Signature Error: {str(e)}")
            return False

