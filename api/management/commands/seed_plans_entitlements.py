"""
Management Command to seed and sync the 3 core plans (Starter, Growth, Advanced),
their default entitlements, channels, connectors, features, limits, message costs, and additional benefits.
"""

from django.core.management.base import BaseCommand
from api.models import Plan, Feature, GlobalConnector
from api.services.entitlement_service import DEFAULT_PLANS_CONFIG

class Command(BaseCommand):
    help = 'Seeds standard core plans (Starter, Growth, Advanced) and entitlements'

    def handle(self, *args, **options):
        self.stdout.write("Seeding UWO Connect Plan Entitlements...")

        # Ensure default global connectors exist
        connectors_data = [
            ('whatsapp', 'WhatsApp Business', 'WhatsApp', 'CORE', True),
            ('facebook', 'Facebook Messenger', 'Facebook', 'CORE', True),
            ('instagram', 'Instagram Direct', 'Instagram', 'CORE', True),
            ('gmail', 'Gmail / Google Workspace', 'Gmail', 'EMAIL', False),
            ('outlook', 'Microsoft Outlook', 'Outlook', 'EMAIL', False),
            ('onedrive', 'Microsoft OneDrive', 'OneDrive', 'STORAGE', False),
            ('google_calendar', 'Google Calendar', 'G-Calendar', 'EMAIL', False),
            ('google_sheets', 'Google Sheets', 'G-Sheets', 'STORAGE', False),
            ('google_docs', 'Google Docs', 'G-Docs', 'STORAGE', False),
            ('google_slides', 'Google Slides', 'G-Slides', 'MEDIA', False),
            ('zoho', 'Zoho CRM', 'Zoho', 'CRM', False),
            ('youtube', 'YouTube Automation', 'YouTube', 'MEDIA', False),
            ('google_news', 'Google News Alerts', 'G-News', 'MEDIA', False),
            ('telegram', 'Telegram Bot API', 'Telegram', 'MESSAGING', False),
        ]
        for key, name, short_name, cat, is_core in connectors_data:
            GlobalConnector.objects.get_or_create(
                connector_key=key,
                defaults={
                    'name': name,
                    'short_name': short_name,
                    'category': cat,
                    'is_core': is_core,
                    'is_active': True,
                    'is_coming_soon': False
                }
            )

        # Seed 3 Core Plans
        for slug, config in DEFAULT_PLANS_CONFIG.items():
            plan, created = Plan.objects.get_or_create(
                slug=slug,
                defaults={
                    'name': config['name'],
                    'description': config['description'],
                    'price': config['monthly_price'],
                    'currency': 'INR',
                    'billing_cycle': 'MONTHLY',
                    'status': 'ACTIVE',
                    'display_order': 1 if slug == 'starter' else (2 if slug == 'growth' else 3),
                    'is_default': (slug == 'starter'),
                    'badge_text': 'Most Popular' if slug == 'growth' else ('Power House' if slug == 'advanced' else ''),
                    'metadata': config
                }
            )
            if not created:
                # Update existing plan metadata with seeded values if missing
                meta = plan.metadata or {}
                meta['channel_details'] = config['channel_details']
                for field in [
                    'monthly_price', 'yearly_price', 'yearly_discount_percent',
                    'max_channels', 'allowed_channels', 'allowed_connectors',
                    'allowed_features', 'limits', 'message_costs', 'additional_benefits'
                ]:
                    if field not in meta:
                        meta[field] = config[field]
                plan.metadata = meta
                plan.save()
            
            self.stdout.write(self.style.SUCCESS(f"Plan '{plan.name}' successfully seeded/verified."))

        self.stdout.write(self.style.SUCCESS("All core plans & entitlements seeded successfully!"))
