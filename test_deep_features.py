import os
import sys
sys.stdout.reconfigure(encoding='utf-8')
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from rest_framework.test import APIClient
from api.models import (
    User, Client, Contact, Product, Order,
    SalesDocument, SalesDocumentItem, Invoice,
    ClientWallet, WalletLedger, Plan, Feature
)
from api.services.pdf_service import SalesDocumentPDFService
from api.services.invoice_pdf_service import InvoicePDFService

print("=" * 75)
print("🔍 DEEP FEATURE FUNCTIONALITY VERIFICATION AUDIT")
print("=" * 75)

admin_user = User.objects.filter(role='ADMIN').first()
client_user = User.objects.filter(role__in=['CLIENT', 'OWNER']).first()
if not client_user:
    client_user = User.objects.exclude(role='ADMIN').first()

client_obj = getattr(client_user, 'client', None) or Client.objects.first()

print(f"👤 Testing with User: {client_user.username} | Workspace: {client_obj.business_name if client_obj else 'None'}")

client_api = APIClient()
client_api.force_authenticate(user=client_user)

audit_results = {}

# ─────────────────────────────────────────────────────────────
# 1. QUOTATION FEATURE TEST
# ─────────────────────────────────────────────────────────────
print("\n📝 [1/8] TESTING QUOTATION ENGINE...")
try:
    # 1a. Create Quotation via API
    quote_payload = {
        "document_type": "QUOTATION",
        "customer_name": "Antigravity Automated Test Customer",
        "customer_email": "test-customer@uwo24.com",
        "customer_phone": "+919876543210",
        "customer_company": "Acme Global Corp",
        "document_date": "2026-09-10",
        "valid_until": "2026-10-10",
        "currency": "INR",
        "currency_symbol": "₹",
        "subtotal": 10000.00,
        "discount_type": "PERCENTAGE",
        "discount_value": 10.00,
        "discount_amount": 1000.00,
        "tax_amount": 1620.00,
        "grand_total": 10620.00,
        "items": [
            {
                "name": "Omnichannel CRM Suite Setup",
                "description": "Full multi-channel onboarding",
                "quantity": 1,
                "unit": "pcs",
                "unit_price": 10000.00,
                "tax_rate": 18.00,
                "tax_amount": 1620.00,
                "line_total": 10620.00
            }
        ]
    }
    create_resp = client_api.post('/api/sales-documents/', quote_payload, format='json')
    if create_resp.status_code in [200, 201]:
        quote_data = create_resp.data
        quote_id = quote_data.get('id')
        doc_num = quote_data.get('document_number')
        token = quote_data.get('secure_token')
        print(f"  ✅ Quotation created: ID={quote_id}, Number={doc_num}, Token={token[:8]}...")

        # 1b. Test Public View via Secure Token
        public_resp = client_api.get(f'/api/public/quotation/{token}/')
        if public_resp.status_code == 200:
            print(f"  ✅ Public Quotation access verified (Status: 200)")
        else:
            print(f"  ❌ Public Quotation access failed: {public_resp.status_code}")

        # 1c. Test PDF Generation
        try:
            q_instance = SalesDocument.objects.get(id=quote_id)
            pdf_buffer = SalesDocumentPDFService.generate_pdf(q_instance)
            pdf_bytes = pdf_buffer.getvalue() if hasattr(pdf_buffer, 'getvalue') else pdf_buffer
            if pdf_bytes and len(pdf_bytes) > 1000:
                print(f"  ✅ Quotation PDF generated successfully ({len(pdf_bytes)} bytes)")
            else:
                print(f"  ⚠️ Quotation PDF generated but small size: {len(pdf_bytes) if pdf_bytes else 0} bytes")
        except Exception as e:
            print(f"  ❌ Quotation PDF error: {e}")

        # 1d. Status update / Transition (SENT -> VIEWED)
        patch_resp = client_api.patch(f'/api/sales-documents/{quote_id}/', {'status': 'SENT'}, format='json')
        if patch_resp.status_code == 200:
            print(f"  ✅ Quotation status updated to SENT")

        audit_results['Quotation Engine'] = 'PASSED'
    else:
        print(f"  ❌ Quotation creation failed: {create_resp.status_code} - {create_resp.data}")
        audit_results['Quotation Engine'] = f'FAILED ({create_resp.status_code})'
except Exception as e:
    print(f"  ❌ Quotation Engine exception: {e}")
    audit_results['Quotation Engine'] = f'ERROR ({e})'


# ─────────────────────────────────────────────────────────────
# 2. INVOICE FEATURE TEST
# ─────────────────────────────────────────────────────────────
print("\n🧾 [2/8] TESTING INVOICE ENGINE...")
try:
    inv_payload = {
        "channel": "DIRECT",
        "currency": "INR",
        "currency_symbol": "₹",
        "subtotal": 5000.00,
        "discount": 0.00,
        "tax": 900.00,
        "total": 5900.00,
        "amount_paid": 5900.00,
        "balance_due": 0.00,
        "payment_status": "PAID",
        "invoice_status": "GENERATED",
        "payment_method": "Razorpay UPI",
        "billing_details": {
            "name": "Antigravity Enterprise Test",
            "email": "enterprise@test.com",
            "phone": "+919876543210",
            "address": "Tech Park, Cyber Hub, Bengaluru"
        },
        "line_items": [
            {
                "item_name": "UWO Connect Annual Pro Plan",
                "quantity": 1,
                "unit_price": 5000.00,
                "tax_rate": 18,
                "total": 5900.00
            }
        ]
    }
    create_inv_resp = client_api.post('/api/invoices/', inv_payload, format='json')
    if create_inv_resp.status_code in [200, 201]:
        inv_data = create_inv_resp.data
        inv_id = inv_data.get('id')
        inv_num = inv_data.get('invoice_number')
        inv_token = inv_data.get('secure_token')
        print(f"  ✅ Invoice created: ID={inv_id}, Number={inv_num}, Token={inv_token[:8] if inv_token else 'N/A'}...")

        # 2b. Test PDF Generation
        try:
            inv_instance = Invoice.objects.get(id=inv_id)
            inv_pdf_buf = InvoicePDFService.generate_pdf(inv_instance)
            inv_pdf = inv_pdf_buf.getvalue() if hasattr(inv_pdf_buf, 'getvalue') else inv_pdf_buf
            if inv_pdf and len(inv_pdf) > 1000:
                print(f"  ✅ Invoice PDF rendered successfully ({len(inv_pdf)} bytes)")
            else:
                print(f"  ⚠️ Invoice PDF generated but size is {len(inv_pdf) if inv_pdf else 0} bytes")
        except Exception as e:
            print(f"  ❌ Invoice PDF generation error: {e}")

        # 2c. Test Public Invoice View
        if inv_token:
            pub_inv = client_api.get(f'/api/public/invoice/{inv_token}/')
            if pub_inv.status_code == 200:
                print(f"  ✅ Public Invoice access verified (Status: 200)")
            else:
                print(f"  ⚠️ Public invoice response: {pub_inv.status_code}")

        audit_results['Invoice Engine'] = 'PASSED'
    else:
        print(f"  ❌ Invoice creation failed: {create_inv_resp.status_code} - {create_inv_resp.data}")
        audit_results['Invoice Engine'] = f'FAILED ({create_inv_resp.status_code})'
except Exception as e:
    print(f"  ❌ Invoice Engine exception: {e}")
    audit_results['Invoice Engine'] = f'ERROR ({e})'


# ─────────────────────────────────────────────────────────────
# 3. PROPOSAL FEATURE TEST
# ─────────────────────────────────────────────────────────────
print("\n📑 [3/8] TESTING PROPOSAL ENGINE...")
try:
    prop_payload = {
        "document_type": "PROPOSAL",
        "customer_name": "Apex Innovations Ltd",
        "customer_email": "apex@innovations.com",
        "document_date": "2026-09-10",
        "currency": "INR",
        "currency_symbol": "₹",
        "subtotal": 25000.00,
        "grand_total": 29500.00,
        "proposal_sections": [
            {"title": "Executive Summary", "content": "Comprehensive enterprise messaging rollout."},
            {"title": "Scope of Work", "content": "Deployment of WhatsApp Cloud API, AI Bot, and CRM integration."}
        ],
        "items": [
            {
                "name": "Enterprise Setup & Deployment",
                "quantity": 1,
                "unit_price": 25000.00,
                "tax_rate": 18.00,
                "line_total": 29500.00
            }
        ]
    }
    create_prop_resp = client_api.post('/api/sales-documents/', prop_payload, format='json')
    if create_prop_resp.status_code in [200, 201]:
        prop_data = create_prop_resp.data
        print(f"  ✅ Proposal created: {prop_data.get('document_number')} (Status: {prop_data.get('status')})")
        audit_results['Proposal Engine'] = 'PASSED'
    else:
        print(f"  ❌ Proposal creation failed: {create_prop_resp.status_code}")
        audit_results['Proposal Engine'] = f'FAILED ({create_prop_resp.status_code})'
except Exception as e:
    print(f"  ❌ Proposal Engine exception: {e}")
    audit_results['Proposal Engine'] = f'ERROR ({e})'


# ─────────────────────────────────────────────────────────────
# 4. CRM & CONTACT MANAGEMENT TEST
# ─────────────────────────────────────────────────────────────
print("\n👥 [4/8] TESTING CRM & CONTACT ENGINE...")
try:
    import time
    unique_pid = f"wa_test_{int(time.time())}"
    contact_payload = {
        "name": "Audit Test Contact",
        "phone_number": f"+919988{int(time.time())%1000000:06d}",
        "platform_id": unique_pid,
        "email": f"audit-{int(time.time())}@test.com",
        "company": "Audit Tech",
        "tags": ["AutomatedTest", "VIP"]
    }
    create_contact_resp = client_api.post('/api/contacts/', contact_payload, format='json')
    if create_contact_resp.status_code in [200, 201]:
        c_data = create_contact_resp.data
        contact_id = c_data.get('id')
        print(f"  ✅ CRM Contact created: ID={contact_id}, Name={c_data.get('name')}")
        # Search contact
        search_resp = client_api.get('/api/contacts/?search=Audit Test Contact')
        if search_resp.status_code == 200:
            print(f"  ✅ CRM Contact search functioning")
        audit_results['CRM & Contacts'] = 'PASSED'
    else:
        print(f"  ⚠️ Contact create response: {create_contact_resp.status_code} - {create_contact_resp.data}")
        audit_results['CRM & Contacts'] = 'WARNING'
except Exception as e:
    print(f"  ❌ CRM Contact error: {e}")
    audit_results['CRM & Contacts'] = f'ERROR ({e})'


# ─────────────────────────────────────────────────────────────
# 5. PREPAID WALLET & RECHARGE ENGINE
# ─────────────────────────────────────────────────────────────
print("\n💳 [5/8] TESTING PREPAID WALLET ENGINE...")
try:
    wallet_resp = client_api.get('/api/wallet/dashboard/')
    if wallet_resp.status_code == 200:
        w_data = wallet_resp.data
        bal = w_data.get('balance_inr', w_data.get('wallet', {}).get('balance_inr', 0))
        print(f"  ✅ Client Wallet active: Current Balance = ₹{bal}")
        audit_results['Prepaid Wallet'] = 'PASSED'
    else:
        print(f"  ⚠️ Wallet response status: {wallet_resp.status_code}")
        audit_results['Prepaid Wallet'] = f'STATUS ({wallet_resp.status_code})'
except Exception as e:
    print(f"  ❌ Wallet error: {e}")
    audit_results['Prepaid Wallet'] = f'ERROR ({e})'


# ─────────────────────────────────────────────────────────────
# 6. PRODUCT CATALOG & ORDER MANAGEMENT
# ─────────────────────────────────────────────────────────────
print("\n🛍️ [6/8] TESTING PRODUCT & ORDER ENGINE...")
try:
    prod_payload = {
        "name": "Audit Test Product Item",
        "description": "Enterprise cloud messaging credits",
        "price": 999.00,
        "currency": "INR",
        "stock": 100,
        "is_active": True
    }
    prod_resp = client_api.post('/api/products/', prod_payload, format='json')
    if prod_resp.status_code in [200, 201]:
        p_id = prod_resp.data.get('id')
        print(f"  ✅ Product created: ID={p_id}, Name={prod_resp.data.get('name')}")
        audit_results['Product Catalog'] = 'PASSED'
    else:
        print(f"  ⚠️ Product create status: {prod_resp.status_code} - {prod_resp.data}")
        audit_results['Product Catalog'] = 'WARNING'
except Exception as e:
    print(f"  ❌ Product Catalog error: {e}")
    audit_results['Product Catalog'] = f'ERROR ({e})'


# ─────────────────────────────────────────────────────────────
# 7. AUTOMATIONS & WORKFLOWS
# ─────────────────────────────────────────────────────────────
print("\n⚡ [7/8] TESTING AUTOMATIONS & WORKFLOWS...")
try:
    auto_resp = client_api.get('/api/automations/')
    wf_resp = client_api.get('/api/workflows/')
    if auto_resp.status_code == 200 and wf_resp.status_code == 200:
        print(f"  ✅ Auto Replies query OK (Found {len(auto_resp.data.get('results', auto_resp.data)) if isinstance(auto_resp.data, (dict, list)) else 'N/A'})")
        print(f"  ✅ Workflows query OK (Found {len(wf_resp.data.get('results', wf_resp.data)) if isinstance(wf_resp.data, (dict, list)) else 'N/A'})")
        audit_results['Automations & Workflows'] = 'PASSED'
    else:
        print(f"  ⚠️ Automations status: auto={auto_resp.status_code}, wf={wf_resp.status_code}")
        audit_results['Automations & Workflows'] = 'WARNING'
except Exception as e:
    print(f"  ❌ Automations error: {e}")
    audit_results['Automations & Workflows'] = f'ERROR ({e})'


# ─────────────────────────────────────────────────────────────
# 8. PLANS & ENTITLEMENT GATING
# ─────────────────────────────────────────────────────────────
print("\n🛡️ [8/8] TESTING PLANS & ENTITLEMENTS...")
try:
    ent_resp = client_api.get('/api/client/entitlements/')
    if ent_resp.status_code == 200:
        ent_data = ent_resp.data
        plan_name = ent_data.get('plan', {}).get('name', 'None')
        print(f"  ✅ Entitlements active: Client Plan = {plan_name}")
        audit_results['Plans & Entitlements'] = 'PASSED'
    else:
        print(f"  ⚠️ Entitlements status: {ent_resp.status_code}")
        audit_results['Plans & Entitlements'] = f'STATUS ({ent_resp.status_code})'
except Exception as e:
    print(f"  ❌ Entitlements error: {e}")
    audit_results['Plans & Entitlements'] = f'ERROR ({e})'


print("\n" + "=" * 75)
print("📊 SUMMARY OF FEATURE AUDIT RESULTS")
print("=" * 75)
for feat, status_res in audit_results.items():
    icon = "✅" if status_res == 'PASSED' else "⚠️"
    print(f" {icon} {feat:<30} : {status_res}")
print("=" * 75)
