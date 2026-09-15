from django.core.management.base import BaseCommand
from django.utils import timezone
from api.models import (
    DynamicContentItem,
    DynamicBanner,
    AppMaintenanceConfig,
    AppFeatureFlag,
    DynamicContentVersionSnapshot,
    User
)

class Command(BaseCommand):
    help = "Seed initial CMS dynamic content, banners, feature flags, and version snapshot."

    def handle(self, *args, **options):
        self.stdout.write("Seeding CMS dynamic content...")

        admin_user = User.objects.filter(is_superuser=True).first() or User.objects.filter(role='ADMIN').first()
        now = timezone.now()

        # 1. Content Items Definition
        items_data = [
            # General
            {
                "section": "GENERAL", "key": "app_name", "type": "text", "label": "Application Name",
                "en": "UWO Connect", "hi": "यूडब्लूओ कनेक्ट",
                "desc": "Platform display name shown throughout the application."
            },
            {
                "section": "GENERAL", "key": "app_tagline", "type": "text", "label": "App Tagline",
                "en": "Unified Business Communication Platform", "hi": "एकीकृत व्यावसायिक संचार मंच",
                "desc": "Short branding tagline beneath application titles."
            },
            {
                "section": "GENERAL", "key": "welcome_title", "type": "text", "label": "Welcome Screen Title",
                "en": "Welcome to UWO Connect", "hi": "यूडब्लूओ कनेक्ट में आपका स्वागत है",
                "desc": "Main headline greeted to users on app launch and home screen."
            },
            {
                "section": "GENERAL", "key": "welcome_subtitle", "type": "text", "label": "Welcome Screen Subtitle",
                "en": "Manage customer conversations across WhatsApp, Meta, Google, and CRM in one place.",
                "hi": "व्हाट्सएप, मेटा, गूगल और सीआरएम पर ग्राहक वार्तालाप एक ही स्थान पर प्रबंधित करें।",
                "desc": "Subtext explaining platform core value on the home screen."
            },

            # Announcements & Banners
            {
                "section": "ANNOUNCEMENT", "key": "announcement_active", "type": "boolean", "label": "Announcement Banner Active",
                "en": "true", "hi": "true",
                "desc": "Controls whether the top announcement banner displays on the mobile home screen."
            },
            {
                "section": "ANNOUNCEMENT", "key": "announcement_title", "type": "text", "label": "Announcement Title",
                "en": "New AI Copilot is Live!", "hi": "नया एआई सहायक लाइव है!",
                "desc": "Headline for the global mobile announcement banner."
            },
            {
                "section": "ANNOUNCEMENT", "key": "announcement_message", "type": "text", "label": "Announcement Message",
                "en": "Connect your WhatsApp & Instagram channels to automate client responses with AI 24/7.",
                "hi": "24/7 एआई के साथ ग्राहक उत्तरों को स्वचालित करने के लिए व्हाट्सएप और इंस्टाग्राम कनेक्ट करें।",
                "desc": "Detailed announcement message displayed inside the banner."
            },

            # Support & Contact Information
            {
                "section": "SUPPORT", "key": "support_email", "type": "text", "label": "Support Email",
                "en": "support@uwo24.com", "hi": "support@uwo24.com",
                "desc": "Official customer support and escalation email address."
            },
            {
                "section": "SUPPORT", "key": "support_phone", "type": "text", "label": "Support Phone Number",
                "en": "+91 83589 90909", "hi": "+91 83589 90909",
                "desc": "Direct customer support and billing helpline number."
            },
            {
                "section": "SUPPORT", "key": "support_hours", "type": "text", "label": "Support Working Hours",
                "en": "Monday - Saturday, 9:00 AM - 7:00 PM IST", "hi": "सोमवार - शनिवार, सुबह 9:00 से शाम 7:00 IST",
                "desc": "Operational hours for real-time customer assistance."
            },
            {
                "section": "SUPPORT", "key": "support_address", "type": "text", "label": "Official Head Office Address",
                "en": "3rd Floor, SQ Square Building, Rampur Chowk, Jabalpur, Madhya Pradesh 482008, India",
                "hi": "तीसरी मंजिल, एसक्यू स्क्वायर बिल्डिंग, रामपुर चौक, जबलपुर, मध्य प्रदेश 482008, भारत",
                "desc": "Registered corporate headquarters address."
            },

            # Empty States
            {
                "section": "EMPTY_STATES", "key": "empty_inbox_title", "type": "text", "label": "Empty Inbox Title",
                "en": "No conversations yet", "hi": "अभी कोई बातचीत नहीं है",
                "desc": "Displayed when a user has zero active chat threads."
            },
            {
                "section": "EMPTY_STATES", "key": "empty_inbox_desc", "type": "text", "label": "Empty Inbox Description",
                "en": "When clients message your connected channels, chats will appear here automatically.",
                "hi": "जब ग्राहक आपके कनेक्टेड चैनलों पर संदेश भेजेंगे, तो चैट अपने आप यहां दिखाई देंगी।",
                "desc": "Help text explaining where incoming messages appear."
            },
            {
                "section": "EMPTY_STATES", "key": "empty_leads_title", "type": "text", "label": "Empty CRM Leads Title",
                "en": "No leads in pipeline", "hi": "पाइपलाइन में कोई लीड नहीं",
                "desc": "Displayed when no CRM contact leads are found."
            },
            {
                "section": "EMPTY_STATES", "key": "empty_leads_desc", "type": "text", "label": "Empty CRM Leads Description",
                "en": "Add new prospects or automatically capture leads from incoming WhatsApp inquiries.",
                "hi": "नए संभावित ग्राहक जोड़ें या आने वाली व्हाट्सएप पूछताछ से स्वचालित रूप से लीड कैप्चर करें।",
                "desc": "Guidance on capturing sales leads."
            },

            # Onboarding
            {
                "section": "ONBOARDING", "key": "onboarding_step1_title", "type": "text", "label": "Onboarding Step 1 Title",
                "en": "Connect Omnichannel Accounts", "hi": "ओमनीचैनल खाते कनेक्ट करें",
                "desc": "First onboarding card headline."
            },
            {
                "section": "ONBOARDING", "key": "onboarding_step1_desc", "type": "text", "label": "Onboarding Step 1 Description",
                "en": "Link WhatsApp Cloud API, Instagram DM, Facebook, Gmail, and Outlook with one tap.",
                "hi": "एक टैप से व्हाट्सएप क्लाउड एपीआई, इंस्टाग्राम, फेसबुक, जीमेल और आउटलुक लिंक करें।",
                "desc": "First onboarding card body text."
            },
            {
                "section": "ONBOARDING", "key": "onboarding_step2_title", "type": "text", "label": "Onboarding Step 2 Title",
                "en": "Automate Everyday Workflows", "hi": "रोजमर्रा के वर्कफ़्लो स्वचालित करें",
                "desc": "Second onboarding card headline."
            },
            {
                "section": "ONBOARDING", "key": "onboarding_step2_desc", "type": "text", "label": "Onboarding Step 2 Description",
                "en": "Set up instant AI replies, lead assignment rules, and automated scheduled follow-ups.",
                "hi": "त्वरित एआई उत्तर, लीड असाइनमेंट नियम और स्वचालित फ़ॉलो-अप सेट करें।",
                "desc": "Second onboarding card body text."
            },

            # Help & FAQ
            {
                "section": "HELP_FAQ", "key": "help_headline", "type": "text", "label": "Help Center Headline",
                "en": "Frequently Asked Questions", "hi": "अक्सर पूछे जाने वाले प्रश्न",
                "desc": "Headline for Help & Knowledge section."
            },
            {
                "section": "HELP_FAQ", "key": "faq_content", "type": "rich_text", "label": "FAQ Document Content",
                "en": "### 1. How do I connect WhatsApp?\nGo to Connectors -> WhatsApp -> Scan QR or input your Meta Cloud API credentials.\n\n### 2. Can multiple team members handle chats?\nYes! Assign roles, team channels, and conversations seamlessly.\n\n### 3. Is my client data secure?\nAll communications are encrypted and comply with enterprise data protection standards.",
                "hi": "### 1. मैं व्हाट्सएप कैसे कनेक्ट करूं?\nकनेक्टर्स -> व्हाट्सएप पर जाएं -> क्यूआर स्कैन करें या अपना मेटा क्रेडेंशियल दर्ज करें।\n\n### 2. क्या कई टीम सदस्य चैट संभाल सकते हैं?\nहाँ! भूमिकाएँ और वार्तालाप आसानी से असाइन करें।\n\n### 3. क्या मेरा डेटा सुरक्षित है?\nसभी संचार एन्क्रिप्टेड हैं और डेटा सुरक्षा मानकों का पालन करते हैं।",
                "desc": "Formatted FAQ document with common customer questions."
            }
        ]

        created_count = 0
        for data in items_data:
            # English item
            item_en, created_en = DynamicContentItem.objects.get_or_create(
                key=data["key"],
                language="en",
                defaults={
                    "section": data["section"],
                    "content_type": data["type"],
                    "label": data["label"],
                    "description": data["desc"],
                    "draft_value": data["en"],
                    "published_value": data["en"],
                    "is_active": True,
                    "version": 1,
                    "published_at": now,
                    "updated_by": admin_user
                }
            )
            if created_en:
                created_count += 1

            # Hindi item
            item_hi, created_hi = DynamicContentItem.objects.get_or_create(
                key=data["key"],
                language="hi",
                defaults={
                    "section": data["section"],
                    "content_type": data["type"],
                    "label": data["label"] + " (Hindi)",
                    "description": data["desc"],
                    "draft_value": data["hi"],
                    "published_value": data["hi"],
                    "is_active": True,
                    "version": 1,
                    "published_at": now,
                    "updated_by": admin_user
                }
            )
            if created_hi:
                created_count += 1

        self.stdout.write(f"Created / Verified {created_count} dynamic content items.")

        # 2. Dynamic Promotional Banners
        banners_data = [
            {
                "title": "Supercharge Omnichannel Sales",
                "description": "Connect WhatsApp Business API & Instagram with one click.",
                "image_url": "https://images.unsplash.com/photo-1557804506-669a67965ba0?auto=format&fit=crop&w=1200&q=80",
                "action_type": "route",
                "action_url": "connectors",
                "placement": "home_hero",
                "display_order": 1,
                "is_active": True
            },
            {
                "title": "Automate Client Follow-ups",
                "description": "Never miss a prospective customer with scheduled reminders.",
                "image_url": "https://images.unsplash.com/photo-1460925895917-afdab827c52f?auto=format&fit=crop&w=1200&q=80",
                "action_type": "route",
                "action_url": "crm",
                "placement": "home_hero",
                "display_order": 2,
                "is_active": True
            },
            {
                "title": "AI Knowledge Copilot",
                "description": "Upload business PDFs and let AI handle client inquiries 24/7.",
                "image_url": "https://images.unsplash.com/photo-1551288049-bebda4e38f71?auto=format&fit=crop&w=1200&q=80",
                "action_type": "route",
                "action_url": "copilot",
                "placement": "home_hero",
                "display_order": 3,
                "is_active": True
            },
        ]

        for b in banners_data:
            DynamicBanner.objects.get_or_create(
                title=b["title"],
                defaults=b
            )

        self.stdout.write("Created / Verified dynamic banners.")

        # 3. Feature Flags
        flags_data = [
            ("crm_module", "CRM Leads & Pipelines", "Manage customer leads, stages, and follow-ups."),
            ("workflows_module", "Workflows & Automations", "Visual automation triggers and campaign actions."),
            ("connectors_module", "Omnichannel Connectors", "WhatsApp, Facebook, Instagram, Gmail, and Outlook sync."),
            ("ai_copilot", "AI Assistant & Copilot", "AI automated replies and team chat assistants."),
            ("news_feed", "Industry News Feed", "Live curated technology and market news feed."),
        ]

        for key, name, desc in flags_data:
            AppFeatureFlag.objects.get_or_create(
                feature_key=key,
                defaults={
                    "name": name,
                    "description": desc,
                    "is_enabled": True
                }
            )

        self.stdout.write("Created / Verified feature flags.")

        # 4. Maintenance Config
        maint_config = AppMaintenanceConfig.objects.first()
        if not maint_config:
            AppMaintenanceConfig.objects.create(
                is_enabled=False,
                title="Under Maintenance",
                message="We are upgrading UWO Connect to deliver better speed and reliability. We will be back shortly.",
                estimated_completion="Within 30 minutes",
                allowed_roles=["ADMIN", "SUPER_ADMIN"],
                updated_by=admin_user
            )

        # 5. Version 1 Snapshot
        if not DynamicContentVersionSnapshot.objects.exists():
            snapshot_dict = {}
            for item in DynamicContentItem.objects.filter(is_active=True):
                lang_dict = snapshot_dict.setdefault(item.language, {})
                lang_dict[item.key] = item.published_value

            DynamicContentVersionSnapshot.objects.create(
                version_number=1,
                snapshot_data={
                    "content": snapshot_dict,
                    "features": {f.feature_key: f.is_enabled for f in AppFeatureFlag.objects.all()},
                    "banners": [b.title for b in DynamicBanner.objects.filter(is_active=True)]
                },
                changelog="Initial baseline CMS dynamic content published.",
                published_by=admin_user,
                published_at=now
            )
            self.stdout.write("Created Version 1 Snapshot.")

        self.stdout.write(self.style.SUCCESS("CMS Dynamic Content Seeding Completed Successfully!"))
