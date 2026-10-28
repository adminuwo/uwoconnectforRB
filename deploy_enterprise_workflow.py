import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Client, Workflow

def deploy_workflow():
    client = Client.objects.filter(users__email='connect@uwo24.com').first()
    if not client:
        print("[ERROR] Client connect@uwo24.com not found!")
        return

    print(f"[INFO] Deploying for client: {client.business_name} ({client.id})")

    # Disable old school workflow if present so catch-all triggers this new enterprise workflow
    old_wfs = Workflow.objects.filter(client=client, name='School')
    for ow in old_wfs:
        ow.enabled = False
        ow.save()
        print(f"[INFO] Disabled legacy workflow: '{ow.name}' (#{ow.id})")

    # Build the rich Enterprise SaaS DAG
    nodes = [
        # --- ROOT TRIGGER ---
        {
            "id": "start",
            "type": "trigger",
            "position": {"x": 600, "y": 40},
            "data": {
                "keyword": "*",
                "triggerMode": "ALL",
                "message": ""
            },
            "width": 256,
            "height": 125
        },

        # --- WELCOME SCREEN (INTERACTIVE BUTTONS) ---
        {
            "id": "welcome_buttons",
            "type": "buttons",
            "position": {"x": 600, "y": 220},
            "data": {
                "message": "👋 *Welcome to UWO Connect!* 🚀\n\nThe all-in-one AI & Omnichannel Customer Engagement Platform for fast-growing businesses.\n\nAutomate conversations on WhatsApp, Instagram & Facebook, streamline sales with CRM, and close deals faster.\n\nHow can we help you today?",
                "buttons": [
                    "🚀 Explore Features",
                    "📅 Book Live Demo",
                    "💰 Pricing & Plans"
                ]
            },
            "width": 256,
            "height": 240
        },

        # --- BRANCH 1: EXPLORE FEATURES (INTERACTIVE LIST) ---
        {
            "id": "features_list",
            "type": "list",
            "position": {"x": 100, "y": 520},
            "data": {
                "message": "⚡ *UWO Connect Core Modules*\n\nExplore our high-performance enterprise suite. Please choose an area to see details:",
                "buttonText": "Select Module",
                "rows": [
                    {
                        "id": "mod_omni",
                        "title": "Omnichannel Inbox",
                        "description": "WhatsApp, IG & FB unified with team notes & SLA"
                    },
                    {
                        "id": "mod_ai",
                        "title": "Autonomous AI Agents",
                        "description": "24/7 smart assistant trained on your docs & RAG"
                    },
                    {
                        "id": "mod_crm",
                        "title": "CRM & 1-Click Billing",
                        "description": "Lead pipelines, GST invoices & Razorpay links"
                    }
                ]
            },
            "width": 256,
            "height": 280
        },

        # Feature Sub-Branch 1.1: Omnichannel Details
        {
            "id": "omni_info",
            "type": "plain",
            "position": {"x": -220, "y": 860},
            "data": {
                "message": "📥 *Omnichannel Team Inbox*\n\n✅ *Unified Dashboard*: Manage WhatsApp, Instagram DMs, and Facebook Messenger from one unified screen.\n✅ *Private Team Notes*: Collaborate internally using private yellow notes and @mentions without the customer seeing.\n✅ *Multi-Agent Routing*: Assign chats dynamically to sales, support, or billing teams."
            },
            "width": 256,
            "height": 180
        },
        {
            "id": "ai_offer_buttons",
            "type": "buttons",
            "position": {"x": -220, "y": 1100},
            "data": {
                "message": "Would you like to test our Live AI Assistant or connect with an enterprise consultant?",
                "buttons": [
                    "🤖 Talk to AI Agent",
                    "👤 Talk to Human",
                    "🔙 Main Menu"
                ]
            },
            "width": 256,
            "height": 220
        },

        # Feature Sub-Branch 1.2: CRM & Billing Details
        {
            "id": "crm_info",
            "type": "plain",
            "position": {"x": 260, "y": 860},
            "data": {
                "message": "💼 *Unified CRM & Instant Invoicing*\n\n✅ *Visual Sales Funnel*: Auto-capture leads from every conversation into pipeline stages.\n✅ *Instant Invoicing*: Generate professional GST invoices in seconds with live Razorpay payment links.\n✅ *Automated Follow-ups*: Schedule WhatsApp payment reminders and invoice receipts automatically."
            },
            "width": 256,
            "height": 180
        },
        {
            "id": "crm_cta_buttons",
            "type": "buttons",
            "position": {"x": 260, "y": 1100},
            "data": {
                "message": "Transform your sales velocity with UWO Connect. What would you like to do next?",
                "buttons": [
                    "📅 Book Live Demo",
                    "💰 View Pricing",
                    "👤 Talk to Human"
                ]
            },
            "width": 256,
            "height": 220
        },

        # --- BRANCH 2: BOOK LIVE DEMO ---
        {
            "id": "demo_intro",
            "type": "plain",
            "position": {"x": 600, "y": 520},
            "data": {
                "message": "🎯 *Book an Exclusive 1-on-1 Product Demo*\n\nJoin our Enterprise Solutions Architect for a customized 30-minute walkthrough tailored to your business model.\n\nWe'll cover:\n• Meta API Setup (Free Meta Verification Guidance)\n• Custom Automated Workflow Building\n• WhatsApp Broadcast & Campaign ROI"
            },
            "width": 256,
            "height": 190
        },
        {
            "id": "meet_scheduler",
            "type": "google_meet",
            "position": {"x": 600, "y": 760},
            "data": {
                "title": "UWO Connect - Enterprise Product Walkthrough & Demo",
                "duration": "30"
            },
            "width": 256,
            "height": 150
        },
        {
            "id": "demo_success",
            "type": "plain",
            "position": {"x": 600, "y": 960},
            "data": {
                "message": "✅ *Your Product Demo Session is Reserved!*\n\nOur team has received your request. A calendar invitation and Google Meet link are ready.\n\nIf you have any urgent requirements or questions right now, feel free to reply below!"
            },
            "width": 256,
            "height": 160
        },

        # --- BRANCH 3: PRICING & PLANS ---
        {
            "id": "pricing_overview",
            "type": "plain",
            "position": {"x": 1020, "y": 520},
            "data": {
                "message": "💎 *UWO Connect Transparent Pricing*\n\n🔹 *Starter Plan*: ₹999/mo\n• Single Channel (WhatsApp/IG)\n• Standard Team Inbox & Contacts CRM\n\n🔹 *Growth Plan*: ₹2,499/mo (Most Popular!)\n• All 3 Channels (WhatsApp, IG & FB)\n• Visual Drag-and-Drop Workflow Builder\n• Razorpay Integrated Billing & Invoicing\n\n🔹 *Enterprise*: Custom\n• Dedicated Server, Unlimited AI RAG & 24/7 SLA"
            },
            "width": 256,
            "height": 240
        },
        {
            "id": "pricing_actions",
            "type": "buttons",
            "position": {"x": 1020, "y": 810},
            "data": {
                "message": "Ready to scale your business with UWO Connect? Select your next step:",
                "buttons": [
                    "📅 Book Live Demo",
                    "👤 Speak to Sales",
                    "🤖 Ask AI Agent"
                ]
            },
            "width": 256,
            "height": 220
        },

        # --- DESTINATION: AUTONOMOUS AI AGENT ---
        {
            "id": "ai_chat_node",
            "type": "ai_chat",
            "position": {"x": 100, "y": 1400},
            "data": {
                "message": "🤖 *UWO Connect Autonomous AI Assistant is Active!*\n\nI can answer any technical or business questions about UWO Connect (Meta APIs, pricing, data security, workflow logic).\n\nWhat would you like to know?"
            },
            "width": 256,
            "height": 170
        },

        # --- DESTINATION: HUMAN HANDOFF ---
        {
            "id": "handoff_node",
            "type": "handoff",
            "position": {"x": 800, "y": 1400},
            "data": {
                "message": "🔔 *Connecting You to Our Sales & Technical Team...*\n\nA representative has been alerted on their UWO Connect team inbox and will reply directly in this conversation shortly. Thank you for your patience! 🤝"
            },
            "width": 256,
            "height": 150
        }
    ]

    edges = [
        # Root trigger to Welcome
        {
            "id": "e_start_welcome",
            "source": "start",
            "target": "welcome_buttons",
            "animated": True,
            "style": {"stroke": "#10b981", "strokeWidth": 2}
        },

        # Welcome Buttons:
        # btn-0 -> Features List
        {
            "id": "e_welcome_btn0",
            "source": "welcome_buttons",
            "target": "features_list",
            "sourceHandle": "btn-0",
            "animated": True,
            "style": {"stroke": "#6366f1", "strokeWidth": 2}
        },
        # btn-1 -> Book Live Demo
        {
            "id": "e_welcome_btn1",
            "source": "welcome_buttons",
            "target": "demo_intro",
            "sourceHandle": "btn-1",
            "animated": True,
            "style": {"stroke": "#6366f1", "strokeWidth": 2}
        },
        # btn-2 -> Pricing Overview
        {
            "id": "e_welcome_btn2",
            "source": "welcome_buttons",
            "target": "pricing_overview",
            "sourceHandle": "btn-2",
            "animated": True,
            "style": {"stroke": "#6366f1", "strokeWidth": 2}
        },

        # Features List:
        # list-0 (Omnichannel) -> omni_info
        {
            "id": "e_list_omni",
            "source": "features_list",
            "target": "omni_info",
            "sourceHandle": "list-0",
            "animated": True,
            "style": {"stroke": "#8b5cf6", "strokeWidth": 2}
        },
        # list-1 (AI Agents) -> ai_chat_node
        {
            "id": "e_list_ai",
            "source": "features_list",
            "target": "ai_chat_node",
            "sourceHandle": "list-1",
            "animated": True,
            "style": {"stroke": "#8b5cf6", "strokeWidth": 2}
        },
        # list-2 (CRM & Billing) -> crm_info
        {
            "id": "e_list_crm",
            "source": "features_list",
            "target": "crm_info",
            "sourceHandle": "list-2",
            "animated": True,
            "style": {"stroke": "#8b5cf6", "strokeWidth": 2}
        },

        # Omni Info -> AI Offer Buttons
        {
            "id": "e_omni_to_buttons",
            "source": "omni_info",
            "target": "ai_offer_buttons",
            "animated": True,
            "style": {"stroke": "#94a3b8", "strokeWidth": 2}
        },
        # AI Offer Buttons:
        # btn-0 (Talk to AI) -> ai_chat_node
        {
            "id": "e_ai_offer_ai",
            "source": "ai_offer_buttons",
            "target": "ai_chat_node",
            "sourceHandle": "btn-0",
            "animated": True,
            "style": {"stroke": "#6366f1", "strokeWidth": 2}
        },
        # btn-1 (Talk to Human) -> handoff_node
        {
            "id": "e_ai_offer_human",
            "source": "ai_offer_buttons",
            "target": "handoff_node",
            "sourceHandle": "btn-1",
            "animated": True,
            "style": {"stroke": "#f43f5e", "strokeWidth": 2}
        },
        # btn-2 (Main Menu) -> welcome_buttons
        {
            "id": "e_ai_offer_menu",
            "source": "ai_offer_buttons",
            "target": "welcome_buttons",
            "sourceHandle": "btn-2",
            "animated": True,
            "style": {"stroke": "#94a3b8", "strokeWidth": 2}
        },

        # CRM Info -> CRM CTA Buttons
        {
            "id": "e_crm_to_buttons",
            "source": "crm_info",
            "target": "crm_cta_buttons",
            "animated": True,
            "style": {"stroke": "#94a3b8", "strokeWidth": 2}
        },
        # CRM CTA Buttons:
        # btn-0 (Book Demo) -> demo_intro
        {
            "id": "e_crm_cta_demo",
            "source": "crm_cta_buttons",
            "target": "demo_intro",
            "sourceHandle": "btn-0",
            "animated": True,
            "style": {"stroke": "#6366f1", "strokeWidth": 2}
        },
        # btn-1 (View Pricing) -> pricing_overview
        {
            "id": "e_crm_cta_price",
            "source": "crm_cta_buttons",
            "target": "pricing_overview",
            "sourceHandle": "btn-1",
            "animated": True,
            "style": {"stroke": "#6366f1", "strokeWidth": 2}
        },
        # btn-2 (Talk to Human) -> handoff_node
        {
            "id": "e_crm_cta_human",
            "source": "crm_cta_buttons",
            "target": "handoff_node",
            "sourceHandle": "btn-2",
            "animated": True,
            "style": {"stroke": "#f43f5e", "strokeWidth": 2}
        },

        # Demo Intro -> Google Meet Scheduler -> Demo Success
        {
            "id": "e_demo_scheduler",
            "source": "demo_intro",
            "target": "meet_scheduler",
            "animated": True,
            "style": {"stroke": "#2563eb", "strokeWidth": 2}
        },
        {
            "id": "e_scheduler_success",
            "source": "meet_scheduler",
            "target": "demo_success",
            "animated": True,
            "style": {"stroke": "#10b981", "strokeWidth": 2}
        },

        # Pricing Overview -> Pricing Actions
        {
            "id": "e_pricing_actions",
            "source": "pricing_overview",
            "target": "pricing_actions",
            "animated": True,
            "style": {"stroke": "#94a3b8", "strokeWidth": 2}
        },
        # Pricing Actions:
        # btn-0 (Book Demo) -> demo_intro
        {
            "id": "e_price_demo",
            "source": "pricing_actions",
            "target": "demo_intro",
            "sourceHandle": "btn-0",
            "animated": True,
            "style": {"stroke": "#6366f1", "strokeWidth": 2}
        },
        # btn-1 (Speak to Sales) -> handoff_node
        {
            "id": "e_price_sales",
            "source": "pricing_actions",
            "target": "handoff_node",
            "sourceHandle": "btn-1",
            "animated": True,
            "style": {"stroke": "#f43f5e", "strokeWidth": 2}
        },
        # btn-2 (Ask AI) -> ai_chat_node
        {
            "id": "e_price_ai",
            "source": "pricing_actions",
            "target": "ai_chat_node",
            "sourceHandle": "btn-2",
            "animated": True,
            "style": {"stroke": "#8b5cf6", "strokeWidth": 2}
        }
    ]

    workflow_name = "UWO Connect - Enterprise Growth & Sales Automation"
    
    # Check if this workflow already exists or create new
    wf = Workflow.objects.filter(client=client, name=workflow_name).first()
    if not wf:
        wf = Workflow(
            client=client,
            name=workflow_name,
            channels=['WHATSAPP', 'INSTAGRAM', 'FACEBOOK'],
            trigger_type='ALL',
            trigger_value=['*'],
            category='SaaS / Customer Experience',
            industry='Technology & Software',
            version=1,
            enabled=True,
            steps={
                "nodes": nodes,
                "edges": edges
            }
        )
    else:
        wf.channels = ['WHATSAPP', 'INSTAGRAM', 'FACEBOOK']
        wf.trigger_type = 'ALL'
        wf.trigger_value = ['*']
        wf.enabled = True
        wf.steps = {
            "nodes": nodes,
            "edges": edges
        }

    wf.save()
    print(f"\n[SUCCESS] Enterprise Workflow '{wf.name}' successfully deployed!")
    print(f"Workflow ID: {wf.id}")
    print(f"Nodes count: {len(nodes)}")
    print(f"Edges count: {len(edges)}")
    print(f"Enabled: {wf.enabled}")
    print(f"Channels: {wf.channels}")
    print(f"Trigger: {wf.trigger_value}")

if __name__ == '__main__':
    deploy_workflow()
