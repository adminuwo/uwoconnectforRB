"""
Centralized Plan-Based Entitlement System & Access Control Service for UWO Connect

Access Evaluation Hierarchy:
1. COMING_SOON (Admin marked item as coming soon - overrides all plan entitlements)
2. AVAILABLE / CONNECTED (Item included in client's subscribed plan & activated)
3. UPGRADE_REQUIRED (Item requires higher plan tier)
"""

from typing import Dict, Any, List
from django.core.exceptions import PermissionDenied
from api.models import Client, Plan, GlobalConnector, Feature

# Default Master Plan configurations for fallback
DEFAULT_PLANS_CONFIG = {
    'starter': {
        'name': 'Starter',
        'slug': 'starter',
        'description': 'Perfect for small teams starting automation on 1 chosen channel',
        'monthly_price': 499,
        'yearly_price': 999,
        'yearly_discount_percent': 83.0,
        'currency': '₹',
        'tax_info': '(+taxes)',
        'max_channels': 1,
        'allowed_channels': ['whatsapp', 'facebook', 'instagram'],
        'allowed_connectors': ['whatsapp', 'facebook', 'instagram'],
        'allowed_features': [
            'auto_replies', 'shared_inbox', 'basic_automation', 'crm',
            'quick_flows', 'contact_management', 'feature_autoreply',
            'feature_crm', 'feature_quotation'
        ],
        'channel_details': {
            'whatsapp': {
                'name': 'WhatsApp',
                'what_you_get': [
                    'WhatsApp Business API Automation',
                    'Shared Team Inbox for WhatsApp',
                    'Automated Keyword Replies',
                    'Contact & Lead Sync'
                ],
                'features': [
                    'WhatsApp Auto Replies',
                    'Shared Inbox',
                    'Keyword Triggers',
                    'Contact Management'
                ],
                'limits': {
                    'messages': {'value': 'unlimited', 'label': 'Messages', 'description': 'Based on your WhatsApp Number'},
                    'contacts': {'value': 'unlimited', 'label': 'Contacts'},
                    'custom_fields': {'value': 15, 'label': 'Custom Fields'},
                    'custom_tags': {'value': 15, 'label': 'Custom Tags'},
                    'events': {'value': '—', 'label': 'Custom Events'}
                },
                'message_costs': [
                    {'type': 'Marketing', 'price': '₹0.970'},
                    {'type': 'Authentication', 'price': '₹0.129'},
                    {'type': 'Utility', 'price': '₹0.160'},
                    {'type': 'Service', 'price': 'FREE'}
                ],
                'additional_benefits': ['No Markup Charges', 'Standard Support']
            },
            'facebook': {
                'name': 'Facebook',
                'what_you_get': [
                    'Facebook Messenger Automation',
                    'Facebook Page Inbox Sync',
                    'Automated Page Quick-Replies',
                    'Lead Form Acquisition'
                ],
                'features': [
                    'Facebook Auto Replies',
                    'Shared Page Inbox',
                    'Ad Lead Capture',
                    'Contact Management'
                ],
                'limits': {
                    'messages': {'value': 'unlimited', 'label': 'Conversations', 'description': 'Facebook Page Messaging'},
                    'contacts': {'value': 'unlimited', 'label': 'Contacts'},
                    'custom_fields': {'value': 15, 'label': 'Custom Fields'},
                    'custom_tags': {'value': 15, 'label': 'Custom Tags'},
                    'events': {'value': '—', 'label': 'Custom Events'}
                },
                'message_costs': [
                    {'type': 'Standard Messaging', 'price': 'FREE'},
                    {'type': 'Lead Form Triggers', 'price': 'FREE'}
                ],
                'additional_benefits': ['Meta Graph API Sync', 'Standard Support']
            },
            'instagram': {
                'name': 'Instagram',
                'what_you_get': [
                    'Instagram Direct DM Automation',
                    'Story Mention Auto-Replies',
                    'Comment Automation & Quick-Flows',
                    'Shared Inbox for Insta DMs'
                ],
                'features': [
                    'Insta Quick-Flows & Price Query Bots',
                    'Comment & Story Mention Triggers',
                    'Shared Inbox for DMs & Comments',
                    'Giveaway & Promo Automation'
                ],
                'limits': {
                    'messages': {'value': 'unlimited', 'label': 'DMs & Comments', 'description': 'Instagram Professional Account'},
                    'contacts': {'value': 'unlimited', 'label': 'Contacts'},
                    'custom_fields': {'value': 15, 'label': 'Custom Fields'},
                    'custom_tags': {'value': 15, 'label': 'Custom Tags'},
                    'events': {'value': '—', 'label': 'Custom Events'}
                },
                'message_costs': [
                    {'type': 'Unlimited DMs & Comments', 'price': 'FREE'},
                    {'type': 'Price Automation', 'price': 'FREE'},
                    {'type': 'Giveaway Automation', 'price': 'FREE'}
                ],
                'additional_benefits': ['IG Conversations FREE', 'Standard Support']
            }
        }
    },
    'growth': {
        'name': 'Growth',
        'slug': 'growth',
        'description': 'Designed for growing businesses using 2 simultaneous channels',
        'monthly_price': 1599,
        'yearly_price': 2799,
        'yearly_discount_percent': 85.0,
        'currency': '₹',
        'tax_info': '(+taxes)',
        'max_channels': 2,
        'allowed_channels': ['whatsapp', 'facebook', 'instagram'],
        'allowed_connectors': [
            'whatsapp', 'facebook', 'instagram', 'gmail', 'outlook',
            'google_sheets', 'onedrive', 'google_calendar', 'google_docs',
            'connector_outlook', 'connector_gmail', 'channel_youtube'
        ],
        'allowed_features': [
            'auto_replies', 'shared_inbox', 'basic_automation', 'crm',
            'quick_flows', 'contact_management', 'faq_automations',
            'linear_chatbot', 'advanced_campaigns', 'catalogs',
            'native_payments', 'public_apis', 'feature_workflow',
            'feature_proposal', 'feature_invoice', 'feature_broadcast',
            'feature_catalog', 'feature_payment', 'feature_order',
            'feature_autoreply', 'feature_crm', 'feature_quotation'
        ],
        'channel_details': {
            'whatsapp': {
                'name': 'WhatsApp',
                'what_you_get': [
                    'WhatsApp Business Automation & Broadcasts',
                    'FAQ Automations & Decision-Tree Chatbots',
                    'Catalog Sync & Product Collections',
                    'Native Payments via UPI'
                ],
                'features': [
                    'FAQ Automations & Linear Bots',
                    'Broadcast Campaigns & Catalogs',
                    'Native UPI Payment Collection',
                    'Public REST APIs & Webhooks'
                ],
                'limits': {
                    'messages': {'value': 'unlimited', 'label': 'Messages', 'description': 'Based on your WhatsApp Number'},
                    'contacts': {'value': 'unlimited', 'label': 'Contacts'},
                    'custom_fields': {'value': 25, 'label': 'Custom Fields'},
                    'custom_tags': {'value': 30, 'label': 'Custom Tags'},
                    'events': {'value': 5, 'label': 'Custom Events'}
                },
                'message_costs': [
                    {'type': 'Marketing', 'price': '₹0.958'},
                    {'type': 'Authentication', 'price': '₹0.128'},
                    {'type': 'Utility', 'price': '₹0.150'},
                    {'type': 'Service', 'price': 'FREE'}
                ],
                'additional_benefits': ['No Markup Charges', 'Higher Rate Limits', 'Priority Support']
            },
            'facebook': {
                'name': 'Facebook',
                'what_you_get': [
                    'Facebook Multi-Page Messenger Sync',
                    'Advanced Page Broadcasts',
                    'Automated Lead Nurturing',
                    'Custom Webhook Integrations'
                ],
                'features': [
                    'Multi-Page Messenger Bots',
                    'Lead Form Auto-Followups',
                    'Broadcast Campaigns',
                    'Public APIs & CRM Sync'
                ],
                'limits': {
                    'messages': {'value': 'unlimited', 'label': 'Conversations', 'description': 'Facebook Page Messaging'},
                    'contacts': {'value': 'unlimited', 'label': 'Contacts'},
                    'custom_fields': {'value': 25, 'label': 'Custom Fields'},
                    'custom_tags': {'value': 30, 'label': 'Custom Tags'},
                    'events': {'value': 5, 'label': 'Custom Events'}
                },
                'message_costs': [
                    {'type': 'Standard Messaging', 'price': 'FREE'},
                    {'type': 'Lead Form Triggers', 'price': 'FREE'}
                ],
                'additional_benefits': ['No Markup Charges', 'Higher Rate Limits', 'Priority Support']
            },
            'instagram': {
                'name': 'Instagram',
                'what_you_get': [
                    'Instagram Advanced DM Flow Automation',
                    'Product Catalog Display in DMs',
                    'Story & Reels Mention Triggers',
                    'Native Payment Links in DMs'
                ],
                'features': [
                    'Instagram Decision Tree Bots',
                    'Comment & Mention Auto-Replies',
                    'Product Catalogs in DMs',
                    'Public APIs'
                ],
                'limits': {
                    'messages': {'value': 'unlimited', 'label': 'DMs & Comments', 'description': 'Instagram Professional Account'},
                    'contacts': {'value': 'unlimited', 'label': 'Contacts'},
                    'custom_fields': {'value': 25, 'label': 'Custom Fields'},
                    'custom_tags': {'value': 30, 'label': 'Custom Tags'},
                    'events': {'value': 5, 'label': 'Custom Events'}
                },
                'message_costs': [
                    {'type': 'Unlimited DMs & Comments', 'price': 'FREE'},
                    {'type': 'Price Automation', 'price': 'FREE'},
                    {'type': 'Giveaway Automation', 'price': 'FREE'}
                ],
                'additional_benefits': ['IG Conversations FREE', 'Higher Rate Limits', 'Priority Support']
            }
        }
    },
    'advanced': {
        'name': 'Advanced',
        'slug': 'advanced',
        'description': 'Full power automation, custom integrations, AI agents & all 3 channels',
        'monthly_price': 2499,
        'yearly_price': 25489,
        'yearly_discount_percent': 15.0,
        'currency': '₹',
        'tax_info': '(+taxes)',
        'max_channels': 3,
        'allowed_channels': ['whatsapp', 'facebook', 'instagram'],
        'allowed_connectors': [
            'whatsapp', 'facebook', 'instagram', 'gmail', 'outlook',
            'onedrive', 'google_calendar', 'google_sheets', 'google_docs',
            'google_slides', 'zoho', 'youtube', 'google_news', 'telegram',
            'connector_outlook', 'connector_gmail', 'connector_google_news',
            'channel_youtube'
        ],
        'allowed_features': [
            'auto_replies', 'shared_inbox', 'basic_automation', 'crm',
            'quick_flows', 'contact_management', 'faq_automations',
            'linear_chatbot', 'advanced_campaigns', 'catalogs',
            'native_payments', 'public_apis', 'advanced_chatbot',
            'branching_flows', 'api_calls_conditions', 'auto_assignment',
            'advanced_webhooks', 'ai_agents', 'team_management',
            'feature_workflow', 'feature_proposal', 'feature_invoice',
            'feature_broadcast', 'feature_catalog', 'feature_payment',
            'feature_order', 'feature_voice_video_call', 'feature_knowledge_base',
            'feature_team_dashboard', 'feature_reports', 'feature_autoreply',
            'feature_crm', 'feature_quotation'
        ],
        'channel_details': {
            'whatsapp': {
                'name': 'WhatsApp',
                'what_you_get': [
                    'Enterprise Branching Chatbots & Dynamic Logic',
                    'Autonomous AI Copilot & Sales Agents',
                    'Chat Auto-Assignment & Round-Robin Routing',
                    'Real-Time Webhooks & Dedicated Manager'
                ],
                'features': [
                    'Branching Chatbot & Conditions',
                    'Chat Auto-Assignment & Webhooks',
                    'Autonomous AI Agents & Copilot',
                    'Multi-Team & Org Management'
                ],
                'limits': {
                    'messages': {'value': 'unlimited', 'label': 'Messages', 'description': 'Based on your WhatsApp Number'},
                    'contacts': {'value': 'unlimited', 'label': 'Contacts'},
                    'custom_fields': {'value': 30, 'label': 'Custom Fields'},
                    'custom_tags': {'value': 45, 'label': 'Custom Tags'},
                    'events': {'value': 7, 'label': 'Custom Events'}
                },
                'message_costs': [
                    {'type': 'Marketing', 'price': '₹0.949'},
                    {'type': 'Authentication', 'price': '₹0.127'},
                    {'type': 'Utility', 'price': '₹0.140'},
                    {'type': 'Service', 'price': 'FREE'}
                ],
                'additional_benefits': [
                    'No Markup Charges',
                    'Dedicated Account Manager',
                    'Higher Rate Limits',
                    'Better Campaign Speeds',
                    'Personalized Support'
                ]
            },
            'facebook': {
                'name': 'Facebook',
                'what_you_get': [
                    'AI-Powered Facebook Messenger Copilot',
                    'Branching Conversational Flow Builder',
                    'Round-Robin Agent Routing',
                    'Real-Time Webhook Event Streaming'
                ],
                'features': [
                    'Branching Messenger Flows',
                    'AI Copilot & Lead Scoring',
                    'Chat Auto-Assignment',
                    'Real-Time Webhooks'
                ],
                'limits': {
                    'messages': {'value': 'unlimited', 'label': 'Conversations', 'description': 'Facebook Page Messaging'},
                    'contacts': {'value': 'unlimited', 'label': 'Contacts'},
                    'custom_fields': {'value': 30, 'label': 'Custom Fields'},
                    'custom_tags': {'value': 45, 'label': 'Custom Tags'},
                    'events': {'value': 7, 'label': 'Custom Events'}
                },
                'message_costs': [
                    {'type': 'Standard Messaging', 'price': 'FREE'},
                    {'type': 'Lead Form Triggers', 'price': 'FREE'}
                ],
                'additional_benefits': [
                    'No Markup Charges',
                    'Dedicated Account Manager',
                    'Higher Rate Limits',
                    'Personalized Support'
                ]
            },
            'instagram': {
                'name': 'Instagram',
                'what_you_get': [
                    'Autonomous AI Copilot for Insta DMs',
                    'Branching DM Sales Funnels',
                    'Live API Call Triggers in DMs',
                    'Real-Time Webhook Event Sync'
                ],
                'features': [
                    'Branching Insta DM Chatbots',
                    'AI Copilot & Auto-Assignment',
                    'Real-Time Webhooks & APIs',
                    'Org & Multi-Agent Routing'
                ],
                'limits': {
                    'messages': {'value': 'unlimited', 'label': 'DMs & Comments', 'description': 'Instagram Professional Account'},
                    'contacts': {'value': 'unlimited', 'label': 'Contacts'},
                    'custom_fields': {'value': 30, 'label': 'Custom Fields'},
                    'custom_tags': {'value': 45, 'label': 'Custom Tags'},
                    'events': {'value': 7, 'label': 'Custom Events'}
                },
                'message_costs': [
                    {'type': 'Unlimited DMs & Comments', 'price': 'FREE'},
                    {'type': 'Price Automation', 'price': 'FREE'},
                    {'type': 'Giveaway Automation', 'price': 'FREE'}
                ],
                'additional_benefits': [
                    'IG Conversations FREE',
                    'Dedicated Account Manager',
                    'Higher Rate Limits',
                    'Personalized Support'
                ]
            }
        }
    }
}


class EntitlementService:
    """Centralized service for checking plan entitlements and channel limits."""

    @staticmethod
    def get_client_plan_config(client: Client) -> Dict[str, Any]:
        """Resolves plan metadata for a client (using client.plan string or assigned_plan)."""
        if not client:
            return DEFAULT_PLANS_CONFIG['starter']

        plan_str = (client.plan or '').strip().lower()
        
        # 1. Match client.plan string directly against DEFAULT_PLANS_CONFIG
        if plan_str in DEFAULT_PLANS_CONFIG:
            return DEFAULT_PLANS_CONFIG[plan_str]
        
        # Check partial slug matches ('advanced', 'growth', 'starter')
        if 'advanced' in plan_str or 'enterprise' in plan_str:
            return DEFAULT_PLANS_CONFIG['advanced']
        elif 'growth' in plan_str or 'pro' in plan_str:
            return DEFAULT_PLANS_CONFIG['growth']
        elif 'starter' in plan_str or 'free' in plan_str:
            return DEFAULT_PLANS_CONFIG['starter']

        # 2. Check assigned_plan ForeignKey if active
        if client.assigned_plan and client.assigned_plan.status == 'ACTIVE':
            plan = client.assigned_plan
            meta = plan.metadata or {}
            slug = plan.slug.lower() if plan.slug else plan.name.lower()
            
            if slug in DEFAULT_PLANS_CONFIG:
                return DEFAULT_PLANS_CONFIG[slug]

            monthly_price = meta.get('monthly_price', float(plan.price))
            yearly_price = meta.get('yearly_price', round(monthly_price * 12 * 0.8, 2))

            return {
                'id': str(plan.id),
                'name': plan.name,
                'slug': slug,
                'monthly_price': monthly_price,
                'yearly_price': yearly_price,
                'yearly_discount_percent': meta.get('yearly_discount_percent', 20.0),
                'max_channels': meta.get('max_channels', 3 if 'advanced' in slug else 2 if 'growth' in slug else 1),
                'allowed_channels': meta.get('allowed_channels', ['whatsapp', 'facebook', 'instagram']),
                'allowed_connectors': meta.get('allowed_connectors', ['whatsapp', 'facebook', 'instagram', 'gmail', 'outlook']),
                'allowed_features': meta.get('allowed_features', ['auto_replies', 'crm', 'feature_workflow', 'feature_proposal', 'feature_invoice']),
                'limits': meta.get('limits', {}),
                'message_costs': meta.get('message_costs', []),
                'additional_benefits': meta.get('additional_benefits', []),
                'channel_details': meta.get('channel_details', {})
            }

        return DEFAULT_PLANS_CONFIG['starter']

    @staticmethod
    def evaluate_item_access(item_key: str, item_type: str, client: Client) -> str:
        """
        Evaluates item access state:
        Returns COMING_SOON | AVAILABLE | UPGRADE_REQUIRED
        """
        # 1. Check if item is marked COMING SOON in DB
        if item_type == 'connector':
            gc = GlobalConnector.objects.filter(connector_key=item_key).first()
            if gc and getattr(gc, 'is_coming_soon', False):
                return 'COMING_SOON'
        elif item_type == 'feature':
            feat = Feature.objects.filter(key=item_key).first()
            if feat and getattr(feat, 'is_coming_soon', False):
                return 'COMING_SOON'

        # 2. Check if item is override-added or override-removed by Admin for this client
        if client:
            try:
                from api.models import ClientFeatureOverride
                db_override = ClientFeatureOverride.objects.filter(client=client, feature__key__iexact=item_key).first()
                if db_override:
                    if db_override.override_type == 'ADD':
                        return 'AVAILABLE'
                    elif db_override.override_type == 'REMOVE':
                        return 'UPGRADE_REQUIRED'
            except Exception:
                pass

        # 3. Check if included in client's plan configuration
        plan_config = EntitlementService.get_client_plan_config(client)
        allowed_connectors = [c.lower() for c in plan_config.get('allowed_connectors', [])]
        allowed_features = [f.lower() for f in plan_config.get('allowed_features', [])]
        allowed_channels = [ch.lower() for ch in plan_config.get('allowed_channels', [])]

        k_low = item_key.lower()
        clean_key = k_low.replace('connector_', '').replace('channel_', '').replace('feature_', '')

        if (k_low in allowed_features or 
            k_low in allowed_connectors or 
            k_low in allowed_channels or 
            clean_key in allowed_connectors or
            clean_key in allowed_channels or
            clean_key in allowed_features):
            return 'AVAILABLE'

        return 'UPGRADE_REQUIRED'

    @staticmethod
    def get_full_client_entitlements(client: Client) -> Dict[str, Any]:
        """Builds a complete entitlement map for the client UI."""
        plan_config = EntitlementService.get_client_plan_config(client)

        selected_channels = client.selected_channels if client else []
        if not selected_channels and client and client.whatsapp_enabled:
            selected_channels = ['whatsapp']
        
        max_channels = plan_config.get('max_channels', 1)
        billing_period = client.billing_period if client else 'MONTHLY'

        # Evaluate Channels
        all_channels = ['whatsapp', 'facebook', 'instagram']
        channels_eval = {}
        for ch in all_channels:
            access_state = EntitlementService.evaluate_item_access(ch, 'channel', client)
            is_selected = ch.lower() in [s.lower() for s in selected_channels]
            
            if access_state == 'COMING_SOON':
                status = 'COMING_SOON'
            elif access_state == 'AVAILABLE':
                if is_selected:
                    status = 'CONNECTED'
                elif len(selected_channels) < max_channels:
                    status = 'AVAILABLE'
                else:
                    status = 'LIMIT_REACHED'
            else:
                status = 'UPGRADE_REQUIRED'
            
            channels_eval[ch] = {
                'key': ch,
                'status': status,
                'is_selected': is_selected,
                'can_select': (status == 'AVAILABLE' or is_selected)
            }

        # Evaluate Connectors
        all_connectors = list(GlobalConnector.objects.all())
        connectors_eval = {}
        for gc in all_connectors:
            k = gc.connector_key
            st = EntitlementService.evaluate_item_access(k, 'connector', client)
            connectors_eval[k] = {
                'key': k,
                'name': gc.name,
                'category': gc.category,
                'status': st,
                'is_coming_soon': getattr(gc, 'is_coming_soon', False)
            }

        # Evaluate Features
        all_features = list(Feature.objects.all())
        features_eval = {}
        for ft in all_features:
            k = ft.key
            st = EntitlementService.evaluate_item_access(k, 'feature', client)
            features_eval[k] = {
                'key': k,
                'name': ft.name,
                'category': ft.category,
                'status': st,
                'is_coming_soon': getattr(ft, 'is_coming_soon', False)
            }

        # Get custom added and removed override keys for client
        custom_added = []
        custom_removed = []
        if client:
            try:
                from api.models import ClientFeatureOverride
                overrides = ClientFeatureOverride.objects.filter(client=client)
                custom_added = list(overrides.filter(override_type='ADD').values_list('feature__key', flat=True))
                custom_removed = list(overrides.filter(override_type='REMOVE').values_list('feature__key', flat=True))
            except Exception:
                pass

        return {
            'client_id': str(client.id) if client else None,
            'business_name': client.business_name if client else '',
            'billing_period': billing_period,
            'plan': plan_config,
            'selected_channels': selected_channels,
            'channel_limit': max_channels,
            'channels': channels_eval,
            'connectors': connectors_eval,
            'features': features_eval,
            'custom_added': custom_added,
            'custom_removed': custom_removed,
        }

    @staticmethod
    def select_channel_for_client(client: Client, channel_key: str) -> Dict[str, Any]:
        """
        Activates or toggles channel selection for a client.
        Enforces plan max_channels allowance.
        """
        plan_config = EntitlementService.get_client_plan_config(client)
        max_channels = plan_config.get('max_channels', 1)
        allowed_channels = [c.lower() for c in plan_config.get('allowed_channels', [])]

        norm_key = channel_key.lower()

        # Check if channel is allowed in plan
        if norm_key not in allowed_channels:
            raise PermissionDenied(f"Your {plan_config['name']} plan does not support the {channel_key} channel. Upgrade to access.")

        # Check if channel is Coming Soon
        access_state = EntitlementService.evaluate_item_access(norm_key, 'channel', client)
        if access_state == 'COMING_SOON':
            raise PermissionDenied(f"The {channel_key} channel is currently Under Development (Coming Soon).")

        current_selected = [c.lower() for c in (client.selected_channels or [])]

        if norm_key in current_selected:
            # Already selected - allow toggle / keep
            return {
                'message': f"{channel_key} is already selected.",
                'selected_channels': client.selected_channels,
                'channel_limit': max_channels
            }

        # Selecting new channel - check limit
        if len(current_selected) >= max_channels:
            # Cannot select additional channel
            required_plan = 'Growth' if max_channels == 1 else 'Advanced'
            raise PermissionDenied(
                f"Your {plan_config['name']} plan allows a maximum of {max_channels} active channel(s). "
                f"Upgrade your plan to {required_plan} to automate more channels."
            )

        # Add to selected channels
        new_selected = list(set(current_selected + [norm_key]))
        client.selected_channels = new_selected
        client.save(update_fields=['selected_channels'])

        return {
            'message': f"{channel_key} successfully selected.",
            'selected_channels': client.selected_channels,
            'channel_limit': max_channels
        }

    @staticmethod
    def check_connector_permission(client: Client, connector_key: str):
        """Raises PermissionDenied if client is not authorized for connector."""
        status = EntitlementService.evaluate_item_access(connector_key, 'connector', client)
        if status == 'COMING_SOON':
            raise PermissionDenied(f"Connector '{connector_key}' is currently Coming Soon.")
        elif status == 'UPGRADE_REQUIRED':
            plan_config = EntitlementService.get_client_plan_config(client)
            raise PermissionDenied(
                f"Connector '{connector_key}' is not included in your current '{plan_config['name']}' plan. "
                "Upgrade your plan to connect."
            )
