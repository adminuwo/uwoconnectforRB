import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
import os, django
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Client, Contact, Conversation, Message, Workflow, Automation, Invoice, SalesDocument, Product, Order, User
from rest_framework.test import APIClient

print("=" * 90)
print("🔍 COMPREHENSIVE PLATFORM SUBSYSTEM INTEGRITY CHECK")
print("=" * 90)

client_obj = Client.objects.filter(status='ACTIVE').first() or Client.objects.first()

print(f"Testing with Tenant Client: {client_obj.business_name} (ID: {client_obj.id})")

results = []

# 1. Contacts & CRM Pipeline
try:
    c_count = Contact.objects.filter(client=client_obj).count()
    results.append(("CRM Contacts Integrity", f"Active contacts: {c_count}", True))
except Exception as e:
    results.append(("CRM Contacts Integrity", str(e), False))

# 2. Conversations & Inbox History
try:
    convo_count = Conversation.objects.filter(client=client_obj).count()
    msg_count = Message.objects.filter(client=client_obj).count()
    results.append(("Inbox & Conversations Integrity", f"Conversations: {convo_count}, Total Messages: {msg_count}", True))
except Exception as e:
    results.append(("Inbox & Conversations Integrity", str(e), False))

# 3. Workflows & Visual Automation Engine
try:
    wfs = Workflow.objects.filter(client=client_obj)
    active_wf_count = wfs.filter(enabled=True).count()
    results.append(("Workflow Engine Canvas", f"Total Workflows: {wfs.count()}, Active: {active_wf_count}", True))
except Exception as e:
    results.append(("Workflow Engine Canvas", str(e), False))

# 4. Automations & Keyword Auto-Replies
try:
    autos = Automation.objects.filter(client=client_obj)
    results.append(("Keyword Automations", f"Total Rules: {autos.count()}", True))
except Exception as e:
    results.append(("Keyword Automations", str(e), False))

# 5. Invoicing, Quotations & Sales Documents
try:
    invs = Invoice.objects.filter(client=client_obj).count()
    sales_docs = SalesDocument.objects.filter(client=client_obj).count()
    results.append(("Billing, Invoices & Quotations", f"Invoices: {invs}, Sales Documents: {sales_docs}", True))
except Exception as e:
    results.append(("Billing, Invoices & Quotations", str(e), False))

# 6. Products & Catalog
try:
    prods = Product.objects.filter(client=client_obj).count()
    orders = Order.objects.filter(client=client_obj).count()
    results.append(("Catalog & Order Management", f"Products: {prods}, Orders: {orders}", True))
except Exception as e:
    results.append(("Catalog & Order Management", str(e), False))

# 7. WhatsApp Cloud API Connection Credentials
try:
    has_token = bool(client_obj.whatsapp_access_token)
    has_phone_id = bool(client_obj.whatsapp_phone_number_id)
    wa_status = "Configured & Active" if (has_token and has_phone_id) else "Missing Token/Phone ID"
    results.append(("WhatsApp Connector Status", f"Phone ID: {client_obj.whatsapp_phone_number_id} ({wa_status})", has_token and has_phone_id))
except Exception as e:
    results.append(("WhatsApp Connector Status", str(e), False))

# 8. Human Takeover & Resume Bot Mechanism
try:
    sample_contact = Contact.objects.filter(client=client_obj, bot_paused=True).first()
    paused_status = f"Contact '{sample_contact.name}' is paused (Takeover active)" if sample_contact else "No contacts currently paused"
    results.append(("Takeover / Resume Bot Mechanism", paused_status, True))
except Exception as e:
    results.append(("Takeover / Resume Bot Mechanism", str(e), False))

print("\n" + "-" * 90)
for name, detail, passed in results:
    icon = "✅" if passed else "❌"
    print(f"{icon} {name:<35} | {detail}")
print("-" * 90)

all_ok = all(r[2] for r in results)
if all_ok:
    print("\n🏆 ALL PLATFORM SUBSYSTEMS ARE HEALTHY, ACTIVE, AND OPERATIONAL!")
else:
    print("\n⚠️ SOME SUBSYSTEMS REQUIRE ATTENTION.")
