import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Guide, GuideSection, GuideStep

GUIDES_DATA = [
    {
        "title": "WhatsApp Cloud API & Meta Webhook Quickstart",
        "slug": "whatsapp-cloud-api-quickstart",
        "icon": "Link2",
        "category": "Integrations",
        "description": "Step-by-step blueprint to connect your Meta Business Portfolio, configure Webhooks, and verify your phone number.",
        "estimated_time": "7 mins",
        "order": 1,
        "sections": [
            {
                "title": "Meta Developer & Business Setup",
                "icon": "Settings",
                "order": 1,
                "steps": [
                    {
                        "title": "Prerequisites Checklist",
                        "step_type": "checklist",
                        "content": "Make sure you have completed the following prerequisites before connecting:",
                        "checklist_items": [
                            {"label": "Meta Business Manager Account with Admin privileges", "checked": True},
                            {"label": "A dedicated phone number not currently registered on personal WhatsApp", "checked": False},
                            {"label": "A verified Facebook Page or Business Portfolio", "checked": False},
                            {"label": "Valid credit card or payment method attached to Meta Business Manager", "checked": False}
                        ],
                        "order": 1
                    },
                    {
                        "title": "Generating Permanent Access Token",
                        "step_type": "tip",
                        "content": "⚠️ Never use temporary 24-hour tokens in production! Go to Meta Business Settings > System Users, create a System User with 'Admin' role, generate a token with 'whatsapp_business_messaging' and 'whatsapp_business_management' permissions, and set expiration to 'Never'.",
                        "order": 2
                    }
                ]
            },
            {
                "title": "Connecting to UWO Connect",
                "icon": "CheckCircle2",
                "order": 2,
                "steps": [
                    {
                        "title": "Enter Credentials in Channels",
                        "step_type": "text",
                        "content": "Navigate to **Channels > WhatsApp** in UWO Connect. Paste your **Phone Number ID**, **WABA ID**, and **Permanent Access Token**. Click Save and Verify.",
                        "order": 1
                    },
                    {
                        "title": "Webhook Callback URL & Verify Token",
                        "step_type": "code",
                        "code_language": "bash",
                        "code_snippet": "# Webhook Callback URL:\nhttps://uwoconnect.aisa24.com/api/meta/webhook/\n\n# Verify Token:\n(Enter the custom verification token from your Channels page)",
                        "content": "In your Meta App Dashboard under WhatsApp > Configuration > Webhook, paste the callback URL and verify token. Subscribe to 'messages' field.",
                        "order": 2
                    }
                ]
            }
        ]
    },
    {
        "title": "Visual Drag-and-Drop Workflow Builder",
        "slug": "visual-workflow-builder-guide",
        "icon": "GitBranch",
        "category": "Automation",
        "description": "Master interactive buttons, list menus, conditional routing, and automated branching bots.",
        "estimated_time": "10 mins",
        "order": 2,
        "sections": [
            {
                "title": "Building Your First Workflow",
                "icon": "Rocket",
                "order": 1,
                "steps": [
                    {
                        "title": "Creating the Trigger Node",
                        "step_type": "text",
                        "content": "Go to **Workflows > Create New**. Click on the Start/Trigger node. You can set specific trigger keywords (e.g. `admission`, `support`, `demo`) or use `*` as a catch-all universal trigger for all incoming chats.",
                        "order": 1
                    },
                    {
                        "title": "Adding Interactive Quick-Reply Buttons",
                        "step_type": "text",
                        "content": "Drag a **Buttons** node from the sidebar onto the canvas. Type your welcome message and add up to 3 button options (e.g. `1. Pricing`, `2. Book Demo`, `3. Contact Support`). Connect the trigger node to this buttons node.",
                        "order": 2
                    }
                ]
            },
            {
                "title": "Branching & Lead Collection",
                "icon": "GitBranch",
                "order": 2,
                "steps": [
                    {
                        "title": "Connecting Branches",
                        "step_type": "tip",
                        "content": "Each button has its own output handle on the node. Drag a connector line from 'Button 1' to a follow-up plain text node or form node. When customers tap a button, the workflow will automatically route down that specific path.",
                        "order": 1
                    },
                    {
                        "title": "Workflow Best Practices",
                        "step_type": "checklist",
                        "content": "Key rules for designing high-converting customer workflows:",
                        "checklist_items": [
                            {"label": "Keep button labels under 20 characters for clean mobile display", "checked": True},
                            {"label": "Always provide a way to talk to a human or reach support", "checked": True},
                            {"label": "Test workflow triggers from a fresh WhatsApp number before launching", "checked": False}
                        ],
                        "order": 2
                    }
                ]
            }
        ]
    },
    {
        "title": "AI Smart Assistant & Knowledge Base (RAG)",
        "slug": "ai-assistant-rag-setup",
        "icon": "Brain",
        "category": "AI & Training",
        "description": "Train Gemini AI on your business documents, PDFs, and FAQs to answer customer inquiries 24/7.",
        "estimated_time": "8 mins",
        "order": 3,
        "sections": [
            {
                "title": "Uploading Knowledge Documents",
                "icon": "Database",
                "order": 1,
                "steps": [
                    {
                        "title": "Document Formats & Ingestion",
                        "step_type": "text",
                        "content": "Navigate to **Knowledge Base** from your sidebar. Upload your company's product catalogs, pricing sheets, FAQs, or policy documents in PDF or TXT format. UWO Connect will automatically chunk and generate vector embeddings.",
                        "order": 1
                    },
                    {
                        "title": "Setting AI Context & Boundaries",
                        "step_type": "tip",
                        "content": "Go to **Channels > AI Assistant**. Provide a clear business description: who your company is, what services you offer, business hours, and instructions on how to handle unknown questions (e.g. 'Politely ask for the customer's phone number so our team can follow up').",
                        "order": 2
                    }
                ]
            },
            {
                "title": "Hybrid AI & Human Agent Handoff",
                "icon": "MessageSquare",
                "order": 2,
                "steps": [
                    {
                        "title": "How Agent Handoff Works",
                        "step_type": "text",
                        "content": "When a customer asks complex questions or types `talk to human`, the AI assistant gracefully flags the conversation in your Inbox. Human agents can click **'Take Over'** at any time to pause the bot and chat directly.",
                        "order": 1
                    }
                ]
            }
        ]
    },
    {
        "title": "Broadcast Campaigns & Template Approvals",
        "slug": "broadcast-campaigns-templates",
        "icon": "Megaphone",
        "category": "Marketing",
        "description": "Draft high-converting Meta message templates, get instant approvals, and schedule mass broadcasts.",
        "estimated_time": "12 mins",
        "order": 4,
        "sections": [
            {
                "title": "Meta Template Submission",
                "icon": "FileText",
                "order": 1,
                "steps": [
                    {
                        "title": "Template Categories",
                        "step_type": "text",
                        "content": "Meta classifies WhatsApp templates into three categories:\n1. **Marketing**: Promotional offers, product launches, newsletters.\n2. **Utility**: Order updates, receipts, appointment reminders.\n3. **Authentication**: OTPs and login codes.",
                        "order": 1
                    },
                    {
                        "title": "Template Variables Syntax",
                        "step_type": "code",
                        "code_language": "text",
                        "code_snippet": "Hi {{1}},\n\nYour appointment with {{2}} is confirmed for {{3}}.\n\nSee you soon!",
                        "content": "Use sequential number variables {{1}}, {{2}} for dynamic customer names, order IDs, or dates. Meta usually approves utility templates within 5-15 minutes.",
                        "order": 2
                    }
                ]
            },
            {
                "title": "Launching a Broadcast Campaign",
                "icon": "Rocket",
                "order": 2,
                "steps": [
                    {
                        "title": "Audience Upload & Wallet Balance",
                        "step_type": "checklist",
                        "content": "Pre-flight checklist before launching your broadcast:",
                        "checklist_items": [
                            {"label": "Approved template synced from Meta", "checked": True},
                            {"label": "CSV list with valid E.164 phone numbers (e.g. +919876543210)", "checked": False},
                            {"label": "Sufficient UWO Connect Wallet balance for Meta conversation fees", "checked": False}
                        ],
                        "order": 1
                    }
                ]
            }
        ]
    },
    {
        "title": "Multi-Channel Shared Inbox & Team Collaboration",
        "slug": "shared-inbox-team-collaboration",
        "icon": "MessageSquare",
        "category": "Communication",
        "description": "Unified customer communication across WhatsApp, Instagram, Messenger, and Gmail with bot pause controls.",
        "estimated_time": "6 mins",
        "order": 5,
        "sections": [
            {
                "title": "Inbox Navigation & Filters",
                "icon": "LayoutDashboard",
                "order": 1,
                "steps": [
                    {
                        "title": "Filtering Channels",
                        "step_type": "text",
                        "content": "In your **Inbox / Messages** page, use the top channel pills (`All`, `WhatsApp`, `Instagram`, `Facebook`) to view conversations from specific platforms or manage everything from one single unified stream.",
                        "order": 1
                    },
                    {
                        "title": "Bot Status & Live Takeover",
                        "step_type": "tip",
                        "content": "Each conversation displays a **'Bot ON'** badge. When you click **'Take Over'**, the badge turns orange, automations are safely paused for that specific contact, and you can chat live without bot interference.",
                        "order": 2
                    }
                ]
            }
        ]
    },
    {
        "title": "Sales CRM: Quotations, Invoices & Digital Proposals",
        "slug": "sales-crm-quotations-invoices",
        "icon": "LayoutDashboard",
        "category": "Sales",
        "description": "Generate GST-compliant invoices, track deal pipelines, and send instant PDF quotations on WhatsApp.",
        "estimated_time": "9 mins",
        "order": 6,
        "sections": [
            {
                "title": "Deal Pipeline & Quotation Builder",
                "icon": "FileText",
                "order": 1,
                "steps": [
                    {
                        "title": "Creating a Professional Quotation",
                        "step_type": "text",
                        "content": "Go to **Quotations > Create New**. Select the customer contact from your CRM, add line items with quantity, unit prices, and GST rates. Click **'Save & Generate PDF'**.",
                        "order": 1
                    },
                    {
                        "title": "Instant WhatsApp Delivery",
                        "step_type": "tip",
                        "content": "Once generated, you can click **'Send via WhatsApp'** to deliver the branded PDF quotation directly into the customer's chat with an interactive approval link.",
                        "order": 2
                    }
                ]
            }
        ]
    },
    {
        "title": "Google Workspace & CRM Cloud Connectors",
        "slug": "google-workspace-crm-sync",
        "icon": "Database",
        "category": "Integrations",
        "description": "Sync leads directly with Google Sheets, schedule meetings with Google Calendar, and backup to Drive.",
        "estimated_time": "8 mins",
        "order": 7,
        "sections": [
            {
                "title": "Connecting Google Services",
                "icon": "Link2",
                "order": 1,
                "steps": [
                    {
                        "title": "One-Click OAuth Activation",
                        "step_type": "text",
                        "content": "Navigate to **Channels**. Find Google Drive, Google Sheets, Google Calendar, or Gmail. Click **'Connect'** to authorize your Google Workspace account securely via OAuth 2.0.",
                        "order": 1
                    },
                    {
                        "title": "Automated Lead Logging in Google Sheets",
                        "step_type": "tip",
                        "content": "Whenever a customer fills out an interactive workflow or inquires about a product, their contact details, timestamps, and selected options can be automatically appended as a new row in your connected Google Sheet.",
                        "order": 2
                    }
                ]
            }
        ]
    }
]

def seed_guides():
    print("Seeding Interactive Learning Center Guides...")
    for g_data in GUIDES_DATA:
        sections_data = g_data.pop("sections", [])
        guide, created = Guide.objects.update_or_create(
            slug=g_data["slug"],
            defaults=g_data
        )
        print(f"[{'CREATED' if created else 'UPDATED'}] Guide: {guide.title}")

        for s_data in sections_data:
            steps_data = s_data.pop("steps", [])
            section, s_created = GuideSection.objects.update_or_create(
                guide=guide,
                title=s_data["title"],
                defaults={
                    "icon": s_data.get("icon", "ChevronRight"),
                    "order": s_data.get("order", 0)
                }
            )

            for st_data in steps_data:
                step, st_created = GuideStep.objects.update_or_create(
                    section=section,
                    title=st_data.get("title", ""),
                    defaults=st_data
                )

    print(f"\n[SUCCESS] Seeded {Guide.objects.count()} interactive learning guides with {GuideSection.objects.count()} chapters and {GuideStep.objects.count()} steps!")

if __name__ == '__main__':
    seed_guides()
