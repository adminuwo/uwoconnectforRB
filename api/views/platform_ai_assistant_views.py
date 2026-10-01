"""
platform_ai_assistant_views.py
──────────────────────────────
Dedicated In-App Platform AI Assistant for UWOConnect Clients.
Completely isolated from the client's custom RAG customer-facing bots.

This assistant answers questions about how to use UWOConnect:
  - How to connect Razorpay payment gateway
  - How to share product checkout links
  - How to create & send GST invoices via WhatsApp
  - How to connect WhatsApp Cloud API, Instagram, FB
  - How to configure 24/7 AI auto replies & workflows
  - How to manage CRM leads and broadcast campaigns

Endpoint:
  POST /api/platform/ai-assistant/chat
  Payload: { "message": "...", "history": [...] }
"""

import os
import re
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status

logger = logging.getLogger(__name__)

PLATFORM_SYSTEM_PROMPT = """You are BOT, the official in-app AI assistant for the UWOConnect platform.
Your job is to help business owners, clients, and team members use and navigate the UWOConnect software platform.

Tone & Style:
- Warm, helpful, professional, and clear.
- Understand and respond naturally in the user's language (Hinglish, Hindi, or English).
- Use bullet points, bold key terms, and step-by-step instructions.
- Official Support Email: `support@uwo24.com`
- Whenever relevant, provide direct links to the internal dashboard pages:
  - Payment Gateway & Sales: `/client/payments` and `/client/payments/dashboard`
  - E-Commerce Catalog: `/client/catalog`
  - GST Invoices: `/client/invoices`
  - Channel Connectors: `/client/channels`
  - 24/7 Auto Replies: `/client/automations`
  - Visual Workflows: `/client/workflows`
  - Leads & CRM: `/client/crm`
  - WhatsApp Broadcasts: `/client/broadcasts`
  - Learning Center & Help Desk: `/client/guides`

Core Knowledge of UWOConnect Features:
1. Razorpay Gateway & Payments:
   - Clients can connect their own personal/business Razorpay account to receive payments directly to their bank.
   - Two connection methods:
     a) Fastest: Enter Razorpay Key ID (`rzp_test_...` or `rzp_live_...`) and Key Secret directly.
     b) 1-Click OAuth: Connect via Razorpay login button.
   - Modes: Supports TEST mode for sandbox testing and LIVE mode for real customer payments.
   - 100% Direct Payouts: UWOConnect does not hold client funds; money settles directly into the client's bank account.
   - Tracking: View all customer payments, transaction IDs, and revenue in the Sales Dashboard at `/client/payments/dashboard`.

2. E-Commerce Catalog & Product Checkout Links:
   - Location: `/client/catalog`.
   - Clients can add physical or digital products with price, images, and inventory.
   - Each product card has a 💳 Credit Card icon: clicking it copies a public checkout link (`http://<domain>/checkout/<productId>`).
   - Clients share this link via WhatsApp, Instagram DM, or automated chat flows.
   - When a customer opens the link, they enter Name, Email, Phone and click 'Pay Now' to pay via Razorpay (UPI, Card, NetBanking).
   - Once paid, the sale automatically logs in `/client/payments/dashboard` and the customer gets an instant confirmation.

3. GST Invoices & Digital Payment Links:
   - Location: `/client/invoices`.
   - Click '+ Create Manual Invoice' to generate branded GST invoices with CGST, SGST, IGST calculations.
   - To collect online payments, set Payment Status to 'PENDING' and select 'INR (₹)'.
   - Once generated, click the green 'Send' button to send the invoice link directly to the customer via WhatsApp or Email.
   - Customer opens the public link (`/public/invoice/<token>`) to view invoice details and download official PDF.

4. Channels & Social Integrations:
   - Location: `/client/channels`.
   - Connect official WhatsApp Cloud API (Meta), Instagram Direct, Facebook Messenger, Telegram, and Gmail.
   - All customer messages flow into the Unified Team Inbox at `/client/inbox`.

5. 24/7 AI Auto Replies & Workflows:
   - Location: `/client/automations` and `/client/workflows`.
   - AI Auto Replies: Set up AI keyword triggers (e.g. pricing, address, working hours) for instant 24/7 customer responses.
   - Visual Workflows: Drag-and-drop flow builder to qualify leads, ask questions, and book appointments automatically.

6. Leads & Smart CRM:
   - Location: `/client/crm`.
   - Automatically stores every customer who messages or buys, along with contact details, tags, and complete conversation history.

Keep answers concise, direct, friendly, and practical!
"""

# Fallback smart keyword answers if OpenAI is unreachable or offline
FALLBACK_KNOWLEDGE = [
    {
        'keywords': ['razorpay', 'payment', 'gateway', 'bank', 'key', 'paisa'],
        'title': '💳 Razorpay Payment Gateway Setup',
        'reply': (
            "**Razorpay Payment Gateway connect karne ka aasan tareeqa:**\n\n"
            "1. Left menu se **[Channels](/client/channels)** ya **[Payments](/client/payments)** par jaayein.\n"
            "2. **Razorpay Gateway** card par **'Configure'** ya **'+ Connect'** button dabayein.\n"
            "3. Apne Razorpay dashboard se **Key ID** (`rzp_test_...` ya `rzp_live_...`) aur **Key Secret** copy karke paste karein.\n"
            "4. **Save & Connect** par click karein — aapka gateway turant active ho jayega!\n\n"
            "💡 **Fayda:** Customer UPI ya Card se jo bhi pay karega, wo paisa 100% seedha **aapke bank account** mein jayega. UWOConnect beech mein koi commission nahi leta!"
        )
    },
    {
        'keywords': ['catalog', 'product', 'checkout', 'link', 'share', 'sell'],
        'title': '🛍️ Catalog se Product Sell karne ka Flow',
        'reply': (
            "**Catalog se product ka checkout link share karne ka tareeqa:**\n\n"
            "1. Left menu se **[Catalog](/client/catalog)** par jaayein.\n"
            "2. Apne product ke card ke bottom mein bane **💳 Credit Card icon** par click karein.\n"
            "3. Aapka direct checkout link copy ho jayega (`/checkout/<productId>`).\n"
            "4. Ye link aap WhatsApp, Instagram ya chat mein customer ko bhej sakte hain.\n\n"
            "👉 **Customer Flow:** Customer link kholega ➔ Name, Phone bharega ➔ Razorpay se UPI/Card pay karega ➔ Sale turant aapke **[Sales Dashboard](/client/payments/dashboard)** mein dikhegi!"
        )
    },
    {
        'keywords': ['invoice', 'gst', 'bill', 'pdf', 'send'],
        'title': '🧾 GST Invoice Generate & Send karna',
        'reply': (
            "**Branded GST Tax Invoice banane aur bhejne ka flow:**\n\n"
            "1. Left menu se **[Invoices](/client/invoices)** par jaayein.\n"
            "2. **'+ Create Manual Invoice'** button par click karein.\n"
            "3. Customer ka Name, Phone aur Product/Item daalein.\n"
            "4. Online payment lene ke liye **Payment Status = PENDING** aur **Currency = INR (₹)** rakhein.\n"
            "5. Save karein, phir table mein invoice ke aage bane green **'Send'** button se WhatsApp ya Email par direct link bhej dein!"
        )
    },
    {
        'keywords': ['whatsapp', 'channel', 'instagram', 'facebook', 'connect'],
        'title': '🔗 WhatsApp & Social Channels Connection',
        'reply': (
            "**WhatsApp & Social Channels connect karne ke steps:**\n\n"
            "1. Left menu se **[Channels](/client/channels)** par jaayein.\n"
            "2. **WhatsApp Cloud API** ya **Instagram** card par **'+ Connect'** par click karein.\n"
            "3. Meta Business credentials daal kar authenticate karein.\n"
            "4. Connect hote hi aapke customers ke saare messages **[Messages Inbox](/client/inbox)** mein ek sath aane lagenge!"
        )
    },
    {
        'keywords': ['auto reply', 'bot', 'workflow', 'automation', '24/7'],
        'title': '⚡ 24/7 AI Auto Replies & Workflows',
        'reply': (
            "**AI Automation Setup:**\n\n"
            "1. **[Auto Replies](/client/automations):** Common sawalon (jaise price, location, timings) ke keyword triggers set karein taki AI bot 24/7 instant reply de sake.\n"
            "2. **[Workflows](/client/workflows):** Visual drag-and-drop builder se multi-step chatbot flows banayein jo customer se details le kar appointment book karein ya lead qualify karein."
        )
    },
    {
        'keywords': ['crm', 'lead', 'contact', 'customer', 'data'],
        'title': '👥 Leads & CRM Database',
        'reply': (
            "**Leads & CRM ka use:**\n\n"
            "Jab bhi koi customer aapke WhatsApp ya chat link par message karta hai, uska phone number, naam aur poori chat history **[Leads (CRM)](/client/crm)** mein auto-save ho jati hai. Wahan se aap tags laga sakte hain aur direct follow-up kar sakte hain!"
        )
    },
    {
        'keywords': ['email', 'support', 'contact', 'help', 'baat', 'phone', 'call', 'ticket', 'reach'],
        'title': '📞 Support & Contact Info',
        'reply': (
            "**UWOConnect Support & Contact Details:**\n\n"
            "- 📧 **Official Support Email:** `support@uwo24.com`\n"
            "- 💬 **Learning Center & Help Desk:** Dashboard par **[Learning Center](/client/guides)** visit karein tutorials aur guides ke liye.\n"
            "- ⚡ **24/7 Platform Bot:** Aap mujhse yahan kisi bhi feature (Razorpay, Invoices, Workflows, WhatsApp API) ke steps seedha pooch sakte hain!"
        )
    }
]


def _get_fallback_reply(query: str) -> str:
    """Smart keyword matcher for offline or fallback mode."""
    q_lower = query.lower()
    for item in FALLBACK_KNOWLEDGE:
        matches = [kw for kw in item['keywords'] if kw in q_lower]
        if len(matches) >= 1:
            return item['reply']

    return (
        "Namaste! Main aapka **UWOConnect BOT** hoon. 😊\n\n"
        "Aap mujhse UWOConnect software ke kisi bhi feature ke baare mein pooch sakte hain, jaise:\n"
        "- 💳 **Razorpay Payment Gateway** kaise connect karein?\n"
        "- 🛍️ **Catalog** se customer checkout link kaise bhejte hain?\n"
        "- 🧾 **GST Invoices** create karke WhatsApp par kaise share karein?\n"
        "- 🔗 **WhatsApp Cloud API** kaise link karein?\n"
        "- ⚡ **24/7 AI Auto Replies** kaise activate karein?\n\n"
        "Aap apna sawal Hinglish, Hindi ya English mein pooch sakte hain!"
    )


class PlatformAIAssistantChatView(APIView):
    """
    POST /api/platform/ai-assistant/chat
    Allows logged-in clients to ask questions about UWOConnect platform features.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user_message = (request.data.get('message') or '').strip()
        history = request.data.get('history') or []

        if not user_message:
            return Response({'error': 'Message cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)

        # Attempt OpenAI generation
        openai_key = os.getenv("OPENAI_API_KEY")
        if openai_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=openai_key)

                messages = [{"role": "system", "content": PLATFORM_SYSTEM_PROMPT}]

                # Include past 6 conversational turns for context
                for h in history[-6:]:
                    role = 'assistant' if h.get('role') in ('assistant', 'bot') else 'user'
                    content = h.get('content') or ''
                    if content:
                        messages.append({"role": role, "content": content})

                messages.append({"role": "user", "content": user_message})

                response = client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=messages,
                    temperature=0.3,
                    max_tokens=600,
                )

                reply_text = response.choices[0].message.content.strip()
                return Response({
                    'success': True,
                    'reply': reply_text,
                    'source': 'openai'
                })
            except Exception as e:
                logger.warning(f"[Platform AI Assistant] OpenAI error: {e}. Using fallback knowledge.")

        # Fallback knowledge response
        fallback_reply = _get_fallback_reply(user_message)
        return Response({
            'success': True,
            'reply': fallback_reply,
            'source': 'local_knowledge'
        })
