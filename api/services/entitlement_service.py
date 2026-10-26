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

FEATURE_ALIASES = {
    'feature_autoreply': ['auto_replies', 'autoreply', 'automations', 'feature_autoreply'],
    'auto_replies': ['auto_replies', 'autoreply', 'automations', 'feature_autoreply'],
    'autoreply': ['auto_replies', 'autoreply', 'automations', 'feature_autoreply'],
    'automations': ['auto_replies', 'autoreply', 'automations', 'feature_autoreply'],
    'feature_workflow': ['workflows', 'workflow', 'branching_flows', 'feature_workflow'],
    'workflow': ['workflows', 'workflow', 'branching_flows', 'feature_workflow'],
    'workflows': ['workflows', 'workflow', 'branching_flows', 'feature_workflow'],
    'feature_quotation': ['quotations', 'quotation', 'sales_quotations', 'feature_quotation'],
    'quotation': ['quotations', 'quotation', 'sales_quotations', 'feature_quotation'],
    'quotations': ['quotations', 'quotation', 'sales_quotations', 'feature_quotation'],
    'sales_quotations': ['quotations', 'quotation', 'sales_quotations', 'feature_quotation'],
    'feature_proposal': ['proposals', 'proposal', 'sales_proposals', 'feature_proposal'],
    'proposal': ['proposals', 'proposal', 'sales_proposals', 'feature_proposal'],
    'proposals': ['proposals', 'proposal', 'sales_proposals', 'feature_proposal'],
    'sales_proposals': ['proposals', 'proposal', 'sales_proposals', 'feature_proposal'],
    'feature_invoice': ['invoices', 'invoice', 'sales_invoices', 'feature_invoice'],
    'invoice': ['invoices', 'invoice', 'sales_invoices', 'feature_invoice'],
    'invoices': ['invoices', 'invoice', 'sales_invoices', 'feature_invoice'],
    'sales_invoices': ['invoices', 'invoice', 'sales_invoices', 'feature_invoice'],
    'feature_voice_video_call': ['voice_video_call', 'voice_call', 'video_call', 'calls', 'feature_voice_video_call', 'conn_gmeet'],
    'voice_video_call': ['voice_video_call', 'voice_call', 'video_call', 'calls', 'feature_voice_video_call', 'conn_gmeet'],
    'calls': ['voice_video_call', 'voice_call', 'video_call', 'calls', 'feature_voice_video_call', 'conn_gmeet'],
    'feature_knowledge_base': ['knowledge_base', 'knowledge', 'feature_knowledge_base', 'f-kb'],
    'knowledge_base': ['knowledge_base', 'knowledge', 'feature_knowledge_base', 'f-kb'],
    'knowledge': ['knowledge_base', 'knowledge', 'feature_knowledge_base', 'f-kb'],
    'feature_team_dashboard': ['team_dashboard', 'team_management', 'team', 'feature_team_dashboard', 'f-team'],
    'team_dashboard': ['team_dashboard', 'team_management', 'team', 'feature_team_dashboard', 'f-team'],
    'team': ['team_dashboard', 'team_management', 'team', 'feature_team_dashboard', 'f-team'],
    'team_management': ['team_dashboard', 'team_management', 'team', 'feature_team_dashboard', 'f-team'],
    'feature_reports': ['reports', 'team_work_reports', 'work_reports', 'feature_reports', 'f-reports'],
    'reports': ['reports', 'team_work_reports', 'work_reports', 'feature_reports', 'f-reports'],
    'team_work_reports': ['reports', 'team_work_reports', 'work_reports', 'feature_reports', 'f-reports'],
    'feature_broadcast': ['broadcast', 'broadcasts', 'campaigns', 'advanced_campaigns', 'feature_broadcast'],
    'broadcast': ['broadcast', 'broadcasts', 'campaigns', 'advanced_campaigns', 'feature_broadcast'],
    'broadcasts': ['broadcast', 'broadcasts', 'campaigns', 'advanced_campaigns', 'feature_broadcast'],
    'campaigns': ['broadcast', 'broadcasts', 'campaigns', 'advanced_campaigns', 'feature_broadcast'],
    'feature_catalog': ['catalog', 'catalogs', 'sales_catalog', 'feature_catalog'],
    'catalog': ['catalog', 'catalogs', 'sales_catalog', 'feature_catalog'],
    'catalogs': ['catalog', 'catalogs', 'sales_catalog', 'feature_catalog'],
    'sales_catalog': ['catalog', 'catalogs', 'sales_catalog', 'feature_catalog'],
    'feature_payment': ['payment', 'payments', 'native_payments', 'feature_payment'],
    'payment': ['payment', 'payments', 'native_payments', 'feature_payment'],
    'payments': ['payment', 'payments', 'native_payments', 'feature_payment'],
    'native_payments': ['payment', 'payments', 'native_payments', 'feature_payment'],
    'feature_order': ['order', 'orders', 'sales_orders', 'feature_order'],
    'order': ['order', 'orders', 'sales_orders', 'feature_order'],
    'orders': ['order', 'orders', 'sales_orders', 'feature_order'],
    'sales_orders': ['order', 'orders', 'sales_orders', 'feature_order'],
    'feature_crm': ['crm', 'crm_leads', 'contact_management', 'crm_clients', 'feature_crm'],
    'crm': ['crm', 'crm_leads', 'contact_management', 'crm_clients', 'feature_crm'],
    'crm_leads': ['crm', 'crm_leads', 'contact_management', 'crm_clients', 'feature_crm'],
    'feature_shared_inbox': ['shared_inbox', 'live_messages_inbox', 'inbox', 'messages', 'feature_shared_inbox'],
    'shared_inbox': ['shared_inbox', 'live_messages_inbox', 'inbox', 'messages', 'feature_shared_inbox'],
    'inbox': ['shared_inbox', 'live_messages_inbox', 'inbox', 'messages', 'feature_shared_inbox'],
    'live_messages_inbox': ['shared_inbox', 'live_messages_inbox', 'inbox', 'messages', 'feature_shared_inbox'],
}

# Default Master Plan configurations for fallback
DEFAULT_PLANS_CONFIG = {
    'free': {
        'name': 'No Active Plan',
        'slug': 'free',
        'description': 'No active subscription plan found. Please select a plan to unlock workspace features.',
        'monthly_price': 0,
        'yearly_price': 0,
        'yearly_discount_percent': 0.0,
        'currency': '₹',
        'tax_info': '',
        'max_channels': 0,
        'allowed_channels': [],
        'allowed_connectors': [],
        'allowed_features': [],
        'channel_details': {}
    },
    'starter': {
        'name': 'Starter',
        'slug': 'starter',
        'description': 'Perfect for small teams starting automation on 1 chosen channel',
        'monthly_price': 499,
        'yearly_price': 4999,
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
        'yearly_price': 15999,
        'yearly_discount_percent': 85.0,
        'currency': '₹',
        'tax_info': '(+taxes)',
        'max_channels': 2,
        'allowed_channels': ['whatsapp', 'facebook', 'instagram'],
        'allowed_connectors': [
            'whatsapp', 'facebook', 'instagram', 'gmail', 'outlook',
            'google_sheets', 'onedrive', 'google_calendar', 'google_docs',
            'connector_outlook', 'connector_gmail', 'channel_youtube',
            'google_news', 'connector_google_news', 'conn_gnews'
        ],
        'allowed_features': [
            'auto_replies', 'shared_inbox', 'basic_automation', 'crm',
            'quick_flows', 'contact_management', 'faq_automations',
            'linear_chatbot', 'advanced_campaigns', 'catalogs',
            'native_payments', 'public_apis', 'feature_workflow',
            'feature_proposal', 'feature_invoice', 'feature_broadcast',
            'feature_catalog', 'feature_payment', 'feature_order',
            'feature_autoreply', 'feature_crm', 'feature_quotation',
            'feature_voice_video_call', 'voice_video_call', 'conn_gmeet', 'calls',
            'feature_knowledge_base', 'knowledge_base', 'f-kb',
            'feature_team_dashboard', 'team_dashboard', 'team_management', 'f-team',
            'feature_reports', 'team_work_reports', 'reports', 'f-reports'
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
        'yearly_price': 24999,
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
            return DEFAULT_PLANS_CONFIG['free']

        # Google Reviewer / Verification account bypass (Phase 6):
        # Grants test accounts full access to all Google integrations without requiring paid subscriptions.
        try:
            from .google_oauth_service import is_google_verification_account
            if is_google_verification_account(client):
                verification_cfg = dict(DEFAULT_PLANS_CONFIG.get('advanced', {}))
                verification_cfg.update({
                    'name': 'Google Verification Reviewer Plan',
                    'slug': 'verification_partner',
                    'description': 'Designated reviewer sandbox environment for Google OAuth verification review.',
                    'allowed_connectors': list(set(
                        verification_cfg.get('allowed_connectors', []) + [
                            'gmail', 'google_calendar', 'google_sheets', 'google_docs',
                            'google_slides', 'youtube', 'connector_gmail', 'channel_youtube',
                            'connector_google_news', 'conn_gnews'
                        ]
                    ))
                })
                return verification_cfg
        except Exception:
            pass

        plan_str = (client.plan or '').strip().lower()
        
        # 1. Check assigned_plan ForeignKey or active database Plan first
        plan_obj = None
        if client.assigned_plan and getattr(client.assigned_plan, 'status', 'ACTIVE') == 'ACTIVE':
            plan_obj = client.assigned_plan
        elif plan_str:
            try:
                from api.models import Plan
                plan_obj = Plan.objects.filter(name__iexact=plan_str, status='ACTIVE').first() or Plan.objects.filter(slug__iexact=plan_str, status='ACTIVE').first()
            except Exception:
                plan_obj = None

        if plan_obj:
            plan = plan_obj
            meta = plan.metadata or {}
            slug = plan.slug.lower() if plan.slug else plan.name.lower()
            
            monthly_cfg = meta.get('monthlyConfig') or meta.get('monthly_config') or {}
            yearly_cfg = meta.get('yearlyConfig') or meta.get('yearly_config') or {}

            monthly_price = monthly_cfg.get('price') or meta.get('monthly_price', float(plan.price))
            yearly_price = yearly_cfg.get('price') or meta.get('yearly_price', round(float(monthly_price) * 12 * 0.8, 2))

            # Determine plan tier
            tier = 'free'
            if 'advanced' in slug or 'enterprise' in slug or 'power' in slug:
                tier = 'advanced'
            elif 'growth' in slug or 'pro' in slug:
                tier = 'growth'
            elif 'starter' in slug or 'basic' in slug:
                tier = 'starter'

            tier_cfg = DEFAULT_PLANS_CONFIG.get(tier, {})
            tier_baseline_features = list(tier_cfg.get('allowed_features', []))
            tier_baseline_connectors = list(tier_cfg.get('allowed_connectors', []))
            tier_baseline_channels = list(tier_cfg.get('allowed_channels', []))

            # For Advanced plan, include all active features and connectors by default
            if tier == 'advanced':
                try:
                    all_feat_keys = list(Feature.objects.values_list('key', flat=True))
                    tier_baseline_features = list(set(tier_baseline_features + all_feat_keys))
                except Exception:
                    pass
                try:
                    all_conn_keys = list(GlobalConnector.objects.values_list('connector_key', flat=True))
                    tier_baseline_connectors = list(set(tier_baseline_connectors + all_conn_keys))
                except Exception:
                    pass

            meta_features = meta.get('allowed_features') or meta.get('feature_keys') or []
            meta_connectors = meta.get('allowed_connectors') or []
            meta_channels = meta.get('allowed_channels') or []

            feat_keys = list(set(tier_baseline_features + [str(x) for x in meta_features]))
            conn_keys = list(set(tier_baseline_connectors + [str(x) for x in meta_connectors]))
            chan_keys = list(set(tier_baseline_channels + [str(x) for x in meta_channels]))

            return {
                'id': str(plan.id),
                'name': plan.name,
                'slug': slug,
                'monthly_price': monthly_price,
                'yearly_price': yearly_price,
                'monthlyConfig': monthly_cfg,
                'yearlyConfig': yearly_cfg,
                'yearly_discount_percent': meta.get('yearly_discount_percent', 20.0),
                'max_channels': 1 if ('starter' in slug or slug == 'starter') else meta.get('max_channels', 3 if ('advanced' in slug or 'enterprise' in slug) else 2 if 'growth' in slug else 1),
                'allowed_channels': chan_keys,
                'allowed_connectors': conn_keys,
                'allowed_features': feat_keys,
                'limits': meta.get('limits', {}),
                'message_costs': meta.get('message_costs', []),
                'additional_benefits': meta.get('additional_benefits', []),
                'channel_details': meta.get('channel_details', {})
            }

        # 2. Fall back to DEFAULT_PLANS_CONFIG if no database plan exists
        if plan_str in DEFAULT_PLANS_CONFIG:
            return DEFAULT_PLANS_CONFIG[plan_str]
        
        # Check partial slug matches ('advanced', 'growth', 'starter', 'free')
        if 'advanced' in plan_str or 'enterprise' in plan_str:
            return DEFAULT_PLANS_CONFIG['advanced']
        elif 'growth' in plan_str or 'pro' in plan_str:
            return DEFAULT_PLANS_CONFIG['growth']
        elif 'starter' in plan_str:
            return DEFAULT_PLANS_CONFIG['starter']
        elif 'free' in plan_str or 'none' in plan_str or plan_str == '' or plan_str == 'no_plan':
            return DEFAULT_PLANS_CONFIG['free']

        return DEFAULT_PLANS_CONFIG['free']

    @staticmethod
    def get_effective_entitlements(client: Client) -> Dict[str, Any]:
        """Returns consolidated plan dictionary and allowed scopes/features for a client."""
        cfg = EntitlementService.get_client_plan_config(client)
        return {
            'plan_name': cfg.get('name', 'No Active Plan'),
            'plan_slug': cfg.get('slug', 'free'),
            'is_active': bool(client and getattr(client, 'status', 'ACTIVE') == 'ACTIVE'),
            'allowed_connectors': cfg.get('allowed_connectors', []),
            'allowed_features': cfg.get('allowed_features', []),
        }

    @staticmethod
    def can_access_channel(client: Client, channel_name: str):
        """Returns (can_access: bool, status: str) for a given channel/connector."""
        status = EntitlementService.evaluate_item_access(channel_name, 'connector', client)
        if status == 'AVAILABLE':
            return True, 'AVAILABLE'
        return False, status

    @staticmethod
    def evaluate_item_access(item_key: str, item_type: str, client: Client, context: dict = None) -> str:
        """
        Evaluates item access state:
        Returns COMING_SOON | AVAILABLE | UPGRADE_REQUIRED
        Supports optional pre-fetched context to eliminate N+1 queries.
        """
        # Google Reviewer / Verification account bypass (Phase 6):
        try:
            if context and 'is_verification_account' in context:
                if context['is_verification_account']:
                    return 'AVAILABLE'
            else:
                from .google_oauth_service import is_google_verification_account
                if is_google_verification_account(client):
                    return 'AVAILABLE'
        except Exception:
            pass

        # 1. Check if item is marked COMING SOON or INACTIVE by Admin in DB
        clean_k = item_key.lower().replace('feature_', '').replace('connector_', '').replace('channel_', '')

        # Check GlobalConnector
        if context and 'connectors_map' in context:
            cmap = context['connectors_map']
            gc = cmap.get(item_key.lower()) or cmap.get(clean_k)
        else:
            gc = (
                GlobalConnector.objects.filter(connector_key__iexact=item_key).first() or
                GlobalConnector.objects.filter(connector_key__iexact=clean_k).first()
            )
        if gc:
            if getattr(gc, 'is_coming_soon', False) or not getattr(gc, 'is_active', True):
                return 'COMING_SOON'

        # Check Feature
        if context and 'features_map' in context:
            fmap = context['features_map']
            feat = (
                fmap.get(item_key.lower()) or
                fmap.get(clean_k) or
                fmap.get(f"feature_{clean_k}") or
                fmap.get(f"channel_{clean_k}") or
                fmap.get(f"connector_{clean_k}")
            )
        else:
            feat = (
                Feature.objects.filter(key__iexact=item_key).first() or
                Feature.objects.filter(key__iexact=clean_k).first() or
                Feature.objects.filter(key__iexact=f"feature_{clean_k}").first() or
                Feature.objects.filter(key__iexact=f"channel_{clean_k}").first() or
                Feature.objects.filter(key__iexact=f"connector_{clean_k}").first()
            )
        if feat:
            if getattr(feat, 'is_coming_soon', False) or getattr(feat, 'status', 'ACTIVE') != 'ACTIVE' or not getattr(feat, 'is_active', True):
                return 'COMING_SOON'

        # 2. Check if item is override-added or override-removed by Admin for this client
        if context and 'overrides_map' in context:
            omap = context['overrides_map']
            clean_k = item_key.lower().replace('feature_', '').replace('connector_', '')
            ov_type = omap.get(item_key.lower()) or omap.get(clean_k) or omap.get(f"feature_{clean_k}")
            if ov_type == 'ADD':
                return 'AVAILABLE'
            elif ov_type == 'REMOVE':
                return 'UPGRADE_REQUIRED'
        elif client:
            try:
                from api.models import ClientFeatureOverride
                from django.db.models import Q
                clean_k = item_key.lower().replace('feature_', '').replace('connector_', '')
                db_override = ClientFeatureOverride.objects.filter(
                    client=client
                ).filter(
                    Q(feature__key__iexact=item_key) | 
                    Q(feature__key__iexact=clean_k) | 
                    Q(feature__key__iexact=f"feature_{clean_k}")
                ).first()
                if db_override:
                    if db_override.override_type == 'ADD':
                        return 'AVAILABLE'
                    elif db_override.override_type == 'REMOVE':
                        return 'UPGRADE_REQUIRED'
            except Exception:
                pass

        # 3. Check if included in client's plan configuration
        plan_config = context['plan_config'] if (context and 'plan_config' in context) else EntitlementService.get_client_plan_config(client)
        slug = (plan_config.get('slug') or plan_config.get('name') or '').lower()

        # Advanced tier has access to all active features and connectors
        if 'advanced' in slug or 'enterprise' in slug or 'power' in slug:
            return 'AVAILABLE'

        allowed_connectors = [str(c).lower() for c in plan_config.get('allowed_connectors', [])]
        allowed_features = [str(f).lower() for f in plan_config.get('allowed_features', [])]
        allowed_channels = [str(ch).lower() for ch in plan_config.get('allowed_channels', [])]

        k_low = item_key.lower()
        clean_key = k_low.replace('connector_', '').replace('channel_', '').replace('feature_', '')

        # Check direct keys and all canonical aliases
        candidate_keys = set(FEATURE_ALIASES.get(k_low, []) + FEATURE_ALIASES.get(clean_key, []) + [
            k_low, clean_key, f"feature_{clean_key}", f"connector_{clean_key}", f"channel_{clean_key}"
        ])

        for c_key in candidate_keys:
            if (c_key in allowed_features or 
                c_key in allowed_connectors or 
                c_key in allowed_channels):
                return 'AVAILABLE'

        return 'UPGRADE_REQUIRED'

    @staticmethod
    def get_full_client_entitlements(client: Client) -> Dict[str, Any]:
        """Builds a complete entitlement map for the client UI."""
        plan_config = EntitlementService.get_client_plan_config(client)

        selected_channels = (client.selected_channels if (client and client.selected_channels is not None) else []) or []
        if not selected_channels and client and client.whatsapp_enabled:
            selected_channels = ['whatsapp']
        
        max_channels = plan_config.get('max_channels', 1)
        billing_period = client.billing_period if client else 'MONTHLY'

        # Build in-memory lookup cache to eliminate N+1 queries during evaluation
        is_verification = False
        try:
            from .google_oauth_service import is_google_verification_account
            is_verification = is_google_verification_account(client)
        except Exception:
            pass

        all_connectors = list(GlobalConnector.objects.all())
        connectors_map = {}
        for gc in all_connectors:
            if gc.connector_key:
                k_norm = gc.connector_key.strip().lower()
                connectors_map[k_norm] = gc
                clean = k_norm.replace('connector_', '')
                connectors_map[clean] = gc
                connectors_map[f'connector_{clean}'] = gc

        all_features = list(Feature.objects.all())
        features_map = {}
        for ft in all_features:
            if ft.key:
                k_norm = ft.key.strip().lower()
                features_map[k_norm] = ft
                clean = k_norm.replace('feature_', '').replace('channel_', '').replace('connector_', '')
                features_map[clean] = ft
                features_map[f'feature_{clean}'] = ft
                features_map[f'channel_{clean}'] = ft
                features_map[f'connector_{clean}'] = ft

        overrides_map = {}
        raw_added = []
        raw_removed = []
        if client:
            try:
                from api.models import ClientFeatureOverride
                overrides = list(ClientFeatureOverride.objects.filter(client=client).select_related('feature'))
                for ov in overrides:
                    fkey = getattr(ov.feature, 'key', '') if ov.feature else ''
                    if fkey:
                        fk_norm = fkey.strip().lower()
                        overrides_map[fk_norm] = ov.override_type
                        clean = fk_norm.replace('feature_', '').replace('connector_', '')
                        overrides_map[clean] = ov.override_type
                        overrides_map[f'feature_{clean}'] = ov.override_type
                        if ov.override_type == 'ADD':
                            raw_added.append(fkey)
                        elif ov.override_type == 'REMOVE':
                            raw_removed.append(fkey)
            except Exception:
                pass

        eval_context = {
            'is_verification_account': is_verification,
            'connectors_map': connectors_map,
            'features_map': features_map,
            'overrides_map': overrides_map,
            'plan_config': plan_config
        }

        # Evaluate Channels
        all_channels = ['whatsapp', 'facebook', 'instagram']
        channels_eval = {}
        for ch in all_channels:
            access_state = EntitlementService.evaluate_item_access(ch, 'channel', client, context=eval_context)
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
        connectors_eval = {}
        for gc in all_connectors:
            k = gc.connector_key
            st = EntitlementService.evaluate_item_access(k, 'connector', client, context=eval_context)
            item_data = {
                'key': k,
                'name': gc.name,
                'category': gc.category,
                'status': st,
                'is_coming_soon': True if st == 'COMING_SOON' else getattr(gc, 'is_coming_soon', False)
            }
            connectors_eval[k] = item_data
            clean_k = k.lower().replace('connector_', '')
            connectors_eval[clean_k] = item_data
            connectors_eval[f'connector_{clean_k}'] = item_data

        # Evaluate Features
        features_eval = {}
        for ft in all_features:
            k = ft.key
            st = EntitlementService.evaluate_item_access(k, 'feature', client, context=eval_context)
            item_data = {
                'key': k,
                'name': ft.name,
                'category': ft.category,
                'status': st,
                'is_coming_soon': True if st == 'COMING_SOON' else getattr(ft, 'is_coming_soon', False)
            }
            features_eval[k] = item_data
            clean_k = k.lower().replace('feature_', '')
            features_eval[clean_k] = item_data
            features_eval[f'feature_{clean_k}'] = item_data

        # Get custom added and removed override keys for client
        custom_added = []
        custom_removed = []
        if client:
            try:
                custom_added_set = set()
                for k in raw_added:
                    custom_added_set.add(k)
                    clean_k = k.lower().replace('feature_', '')
                    custom_added_set.add(clean_k)
                    custom_added_set.add(f'feature_{clean_k}')
                custom_added = list(custom_added_set)

                custom_removed_set = set()
                for k in raw_removed:
                    custom_removed_set.add(k)
                    clean_k = k.lower().replace('feature_', '')
                    custom_removed_set.add(clean_k)
                    custom_removed_set.add(f'feature_{clean_k}')
                custom_removed = list(custom_removed_set)
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
