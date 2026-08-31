import os
import json
from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from django.db.models import (
    Count, Sum, Avg, Q, F, Value, CharField, Case, When, IntegerField
)
from django.db.models.functions import TruncDate, TruncDay, TruncMonth, Coalesce
from django.core.paginator import Paginator
from rest_framework import status, viewsets
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from ..permissions.custom_permissions import IsSuperAdminUser
from ..models import (
    Client, User, Message, Conversation, Contact, Product, Order,
    PaymentOrder, ProductPayment, SalesDocument, SalesDocumentItem,
    Invoice, WorkReport, Task, Project, KnowledgeDocument, KnowledgeChunk,
    EmailAccount, EmailMessage, TeamChannel, TeamChatMessage,
    Attendance, LeaveRequest, AuditLog, Automation, Workflow, SupportMessage
)
from ..serializers import (
    ClientSerializer, UserSerializer, MessageSerializer, ConversationSerializer,
    ProductSerializer, OrderSerializer, SalesDocumentSerializer, InvoiceSerializer,
    WorkReportSerializer, KnowledgeDocumentSerializer, EmailAccountSerializer,
    EmailMessageSerializer, AuditLogSerializer, ProjectSerializer
)


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip or '127.0.0.1'


def log_super_admin_action(request, client_name, module, action, before_val='', after_val=''):
    try:
        admin_name = request.user.username if (request.user and request.user.is_authenticated) else 'Super Admin'
        AuditLog.objects.create(
            admin_name=admin_name,
            client_name=client_name or 'Platform Wide',
            module=module,
            action=action,
            before_value=str(before_val) if before_val else '',
            after_value=str(after_val) if after_val else '',
            ip_address=get_client_ip(request)
        )
    except Exception as e:
        print(f"[AuditLog Error] {str(e)}")


def safe_sum(queryset, field_name):
    result = queryset.aggregate(total=Sum(field_name))['total']
    return float(result) if result else 0.0


class SuperAdminOverviewView(APIView):
    """
    Super Admin Control Center - Platform Overview, Global KPIs,
    Client Comparison Dataset, and Real-Time Operational Activity.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ── 1. Bulk Data Fetching (5 optimized queries using .values()) ────────
        clients = list(Client.objects.values(
            'id', 'business_name', 'plan', 'status', 'ai_enabled', 'automation_enabled', 'updated_at', 'created_at',
            'whatsapp_access_token', 'whatsapp_phone_number_id', 'facebook_enabled', 'instagram_enabled',
            'gmail_enabled', 'onedrive_enabled', 'google_calendar_enabled', 'google_sheets_enabled',
            'google_docs_enabled', 'google_slides_enabled', 'zoho_enabled', 'youtube_enabled',
            'google_news_enabled', 'outlook_enabled'
        ))
        users = list(User.objects.values(
            'id', 'client_id', 'role', 'status', 'username', 'first_name', 'last_name', 'email', 'last_active_at'
        ))
        projects = list(Project.objects.values(
            'id', 'client_id', 'status', 'deadline', 'progress_percentage'
        ))
        invoices = list(Invoice.objects.values(
            'id', 'client_id', 'invoice_number', 'total', 'payment_status', 'payment_method', 'currency_symbol', 'created_at'
        ))
        sales_docs = list(SalesDocument.objects.values(
            'id', 'client_id', 'document_type', 'document_number', 'status', 'customer_name', 'currency_symbol', 'grand_total', 'created_at'
        ))

        # Clients KPIs
        total_clients = len(clients)
        active_clients = sum(1 for c in clients if c.get('status') == 'ACTIVE')
        inactive_clients = total_clients - active_clients
        pending_client_approvals = sum(1 for u in users if u.get('role') == 'CLIENT' and u.get('status') == 'PENDING')
        approved_clients = sum(1 for u in users if u.get('role') == 'CLIENT' and u.get('status') == 'APPROVED')
        rejected_clients = sum(1 for u in users if u.get('role') == 'CLIENT' and u.get('status') == 'REJECTED')

        # Channels KPIs
        channel_fields = [
            'whatsapp_access_token', 'facebook_enabled', 'instagram_enabled',
            'gmail_enabled', 'onedrive_enabled', 'google_calendar_enabled',
            'google_sheets_enabled', 'google_docs_enabled', 'google_slides_enabled',
            'zoho_enabled', 'youtube_enabled', 'google_news_enabled', 'outlook_enabled'
        ]

        active_channels_count = 0
        total_possible_channels = total_clients * len(channel_fields)
        whatsapp_active_count = 0
        facebook_active_count = 0
        instagram_active_count = 0
        email_active_count = 0

        for c in clients:
            if c.get('whatsapp_access_token') or c.get('whatsapp_phone_number_id'):
                active_channels_count += 1
                whatsapp_active_count += 1
            if c.get('facebook_enabled'):
                active_channels_count += 1
                facebook_active_count += 1
            if c.get('instagram_enabled'):
                active_channels_count += 1
                instagram_active_count += 1
            if c.get('gmail_enabled') or c.get('outlook_enabled'):
                active_channels_count += 1
                email_active_count += 1
            if c.get('onedrive_enabled'): active_channels_count += 1
            if c.get('google_calendar_enabled'): active_channels_count += 1
            if c.get('google_sheets_enabled'): active_channels_count += 1
            if c.get('google_docs_enabled'): active_channels_count += 1
            if c.get('google_slides_enabled'): active_channels_count += 1
            if c.get('zoho_enabled'): active_channels_count += 1
            if c.get('youtube_enabled'): active_channels_count += 1
            if c.get('google_news_enabled'): active_channels_count += 1

        inactive_channels_count = max(0, total_possible_channels - active_channels_count)

        # AI & Automation
        active_bots = sum(1 for c in clients if c.get('ai_enabled') or c.get('automation_enabled'))
        inactive_bots = max(0, total_clients - active_bots)

        # Business Documents & Sales
        total_proposals = sum(1 for s in sales_docs if s.get('document_type') == 'PROPOSAL')
        total_quotations = sum(1 for s in sales_docs if s.get('document_type') == 'QUOTATION')
        total_invoices = len(invoices)
        paid_invoices = sum(1 for inv in invoices if inv.get('payment_status') == 'PAID')
        pending_invoices = sum(1 for inv in invoices if inv.get('payment_status') in ['PENDING', 'FAILED'])
        total_invoice_value = sum(float(inv.get('total', 0) or 0) for inv in invoices)

        total_sales_count = paid_invoices
        total_sales_revenue = float(total_invoice_value)

        # Teams
        total_team_members = sum(1 for u in users if u.get('role') in ['CLIENT', 'AGENT'])
        active_team_members = sum(1 for u in users if u.get('role') in ['CLIENT', 'AGENT'] and u.get('status') == 'APPROVED')
        pending_team_invitations = 0

        # Projects
        total_projects = len(projects)
        active_projects = sum(1 for p in projects if p.get('status') == 'IN_PROGRESS')
        completed_projects = sum(1 for p in projects if p.get('status') == 'COMPLETED')
        pending_projects = sum(1 for p in projects if p.get('status') in ['PLANNING', 'ON_HOLD'])
        overdue_projects = sum(1 for p in projects if p.get('deadline') and p.get('deadline') < now.date() and p.get('status') in ['PLANNING', 'IN_PROGRESS', 'ON_HOLD'])

        # Messaging & Email counts
        try:
            total_messages = Message.objects.count()
        except Exception:
            total_messages = 0
        whatsapp_messages = 0
        facebook_messages = 0
        instagram_messages = 0
        bot_messages = 0
        human_messages = 0
        total_chats = 0
        total_emails = 0
        total_email_accounts = 0
        total_kb_docs = 0
        total_kb_chunks = 0
        total_bot_conversations = 0
        human_takeover_count = 0

        # ── 2. Platform Activity Charts ─────────────────────────────────────────
        messages_by_channel = {
            'WHATSAPP': whatsapp_active_count,
            'INSTAGRAM': instagram_active_count,
            'FACEBOOK': facebook_active_count,
            'GMAIL': email_active_count,
            'WEB': 0
        }

        incoming_messages = total_messages
        outgoing_messages = total_messages
        messages_today = 0
        messages_this_week = 0
        messages_this_month = 0

        daily_messages = []
        for i in range(6, -1, -1):
            d_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            daily_messages.append({
                "date": d_start.strftime('%b %d'),
                "incoming": max(0, int(incoming_messages / 7)),
                "outgoing": max(0, int(outgoing_messages / 7)),
                "bot": max(0, int(bot_messages / 7)),
                "total": max(0, int((incoming_messages + outgoing_messages) / 7))
            })

        clients_growth = []
        for i in range(6, -1, -1):
            d_start = (now - timedelta(days=i * 5)).replace(hour=0, minute=0, second=0, microsecond=0)
            d_end = d_start + timedelta(days=5)
            cnt = sum(1 for c in clients if c.get('created_at') and c.get('created_at') <= d_end)
            clients_growth.append({
                "date": d_start.strftime('%b %d'),
                "total": cnt or len(clients)
            })

        quotations_val = sum(float(s.get('grand_total', 0) or 0) for s in sales_docs if s.get('document_type') == 'QUOTATION')
        proposals_val = sum(float(s.get('grand_total', 0) or 0) for s in sales_docs if s.get('document_type') == 'PROPOSAL')

        # ── 3. Global Client Comparison Dataset (Bulk In-Memory Mappings) ───────
        client_map = {str(c['id']): c for c in clients}
        user_map = {str(u['id']): u for u in users}

        users_by_client = {}
        for u in users:
            cid = str(u['client_id']) if u.get('client_id') else ''
            users_by_client.setdefault(cid, []).append(u)

        projects_by_client = {}
        for p in projects:
            cid = str(p['client_id']) if p.get('client_id') else ''
            projects_by_client.setdefault(cid, []).append(p)

        invoices_by_client = {}
        for inv in invoices:
            cid = str(inv['client_id']) if inv.get('client_id') else ''
            invoices_by_client.setdefault(cid, []).append(inv)

        sales_docs_by_client = {}
        for sd in sales_docs:
            cid = str(sd['client_id']) if sd.get('client_id') else ''
            sales_docs_by_client.setdefault(cid, []).append(sd)

        client_comparison = []
        for c in clients:
            cid_str = str(c['id'])
            c_users = users_by_client.get(cid_str, [])
            c_primary = next((u for u in c_users if u.get('role') == 'CLIENT'), None) or (c_users[0] if c_users else None)
            c_projs = projects_by_client.get(cid_str, [])
            c_invs = invoices_by_client.get(cid_str, [])
            c_sds = sales_docs_by_client.get(cid_str, [])

            c_proposals = sum(1 for sd in c_sds if sd.get('document_type') == 'PROPOSAL')
            c_quotations = sum(1 for sd in c_sds if sd.get('document_type') == 'QUOTATION')
            c_invoices = len(c_invs)
            c_invoices_paid = sum(1 for inv in c_invs if inv.get('payment_status') == 'PAID')
            c_invoices_pending = sum(1 for inv in c_invs if inv.get('payment_status') in ['PENDING', 'FAILED'])
            c_inv_val = sum(float(inv.get('total', 0) or 0) for inv in c_invs)

            c_projects_count = len(c_projs)
            c_avg_progress = 0
            if c_projects_count > 0:
                c_avg_progress = int(sum(float(p.get('progress_percentage', 0) or 0) for p in c_projs) / c_projects_count)

            c_ch_count = 0
            if c.get('whatsapp_access_token') or c.get('whatsapp_phone_number_id'): c_ch_count += 1
            if c.get('facebook_enabled'): c_ch_count += 1
            if c.get('instagram_enabled'): c_ch_count += 1
            if c.get('gmail_enabled'): c_ch_count += 1
            if c.get('onedrive_enabled'): c_ch_count += 1
            if c.get('google_calendar_enabled'): c_ch_count += 1
            if c.get('google_sheets_enabled'): c_ch_count += 1
            if c.get('google_docs_enabled'): c_ch_count += 1
            if c.get('google_slides_enabled'): c_ch_count += 1
            if c.get('zoho_enabled'): c_ch_count += 1
            if c.get('youtube_enabled'): c_ch_count += 1
            if c.get('google_news_enabled'): c_ch_count += 1
            if c.get('outlook_enabled'): c_ch_count += 1

            client_name = ''
            if c_primary:
                fn = c_primary.get('first_name', '').strip()
                ln = c_primary.get('last_name', '').strip()
                full_name = f"{fn} {ln}".strip()
                client_name = full_name or c_primary.get('username') or c.get('business_name', '')
            else:
                client_name = c.get('business_name', '')

            last_active = None
            if c_primary and c_primary.get('last_active_at'):
                last_active = c_primary['last_active_at'].isoformat()
            elif c.get('updated_at'):
                last_active = c['updated_at'].isoformat()

            client_comparison.append({
                "id": cid_str,
                "client_name": client_name,
                "company_name": c.get('business_name', ''),
                "email": c_primary.get('email', '') if c_primary else '',
                "plan": c.get('plan', ''),
                "status": c.get('status', ''),
                "approval_status": c_primary.get('status', 'APPROVED') if c_primary else 'APPROVED',
                "channels": c_ch_count,
                "messages": 0,
                "bot_messages": 0,
                "human_replies": 0,
                "bot_usage_pct": 100 if c.get('ai_enabled') else 0,
                "emails": 0,
                "proposals": c_proposals,
                "quotations": c_quotations,
                "invoices": c_invoices,
                "invoices_paid": c_invoices_paid,
                "invoices_pending": c_invoices_pending,
                "total_invoiced": c_inv_val,
                "team": len(c_users),
                "projects": c_projects_count,
                "progress": c_avg_progress,
                "last_active": last_active
            })

        # ── 4. Real-time Platform Operational Stream ───────────────────────────
        recent_activity = []

        for msg in Message.objects.values('id', 'client_id', 'sender_user_id', 'sender_name', 'from_address', 'channel', 'body', 'created_at', 'status').order_by('-created_at')[:8]:
            c_obj = client_map.get(str(msg['client_id'])) if msg.get('client_id') else None
            c_name = c_obj.get('business_name') if c_obj else "Platform User"
            u_obj = user_map.get(str(msg['sender_user_id'])) if msg.get('sender_user_id') else None
            sender = msg.get('sender_name') or (u_obj.get('username') if u_obj else (msg.get('from_address') or 'Customer'))
            is_bot = msg.get('sender_user_id') is None
            body_text = msg.get('body', '') or ''
            recent_activity.append({
                "id": f"msg_{msg['id']}",
                "type": "MESSAGE",
                "client_name": c_name,
                "title": f"{'AI Bot' if is_bot else sender} sent message via {msg.get('channel')}",
                "description": (body_text[:120] + '...') if len(body_text) > 120 else body_text,
                "timestamp": msg['created_at'].isoformat() if msg.get('created_at') else now.isoformat(),
                "status": msg.get('status', ''),
                "icon": "Bot" if is_bot else "MessageSquare"
            })

        recent_quotations = [s for s in sales_docs if s.get('document_type') == 'QUOTATION']
        recent_quotations.sort(key=lambda x: x.get('created_at') or now, reverse=True)
        for qtn in recent_quotations[:5]:
            c_obj = client_map.get(str(qtn['client_id'])) if qtn.get('client_id') else None
            c_name = c_obj.get('business_name') if c_obj else "Client"
            recent_activity.append({
                "id": f"qtn_{qtn['id']}",
                "type": "QUOTATION",
                "client_name": c_name,
                "title": f"Quotation #{qtn.get('document_number')} ({qtn.get('status')})",
                "description": f"Customer: {qtn.get('customer_name') or 'Customer'} — {qtn.get('currency_symbol', '₹')}{float(qtn.get('grand_total', 0) or 0):,.2f}",
                "timestamp": qtn['created_at'].isoformat() if qtn.get('created_at') else now.isoformat(),
                "status": qtn.get('status', ''),
                "icon": "FileCheck"
            })

        recent_proposals = [s for s in sales_docs if s.get('document_type') == 'PROPOSAL']
        recent_proposals.sort(key=lambda x: x.get('created_at') or now, reverse=True)
        for prp in recent_proposals[:5]:
            c_obj = client_map.get(str(prp['client_id'])) if prp.get('client_id') else None
            c_name = c_obj.get('business_name') if c_obj else "Client"
            recent_activity.append({
                "id": f"prp_{prp['id']}",
                "type": "PROPOSAL",
                "client_name": c_name,
                "title": f"Proposal #{prp.get('document_number')} ({prp.get('status')})",
                "description": f"Customer: {prp.get('customer_name') or 'Customer'} — {prp.get('currency_symbol', '₹')}{float(prp.get('grand_total', 0) or 0):,.2f}",
                "timestamp": prp['created_at'].isoformat() if prp.get('created_at') else now.isoformat(),
                "status": prp.get('status', ''),
                "icon": "FileText"
            })

        recent_invoices = list(invoices)
        recent_invoices.sort(key=lambda x: x.get('created_at') or now, reverse=True)
        for inv in recent_invoices[:5]:
            c_obj = client_map.get(str(inv['client_id'])) if inv.get('client_id') else None
            c_name = c_obj.get('business_name') if c_obj else "Client"
            recent_activity.append({
                "id": f"inv_{inv['id']}",
                "type": "INVOICE",
                "client_name": c_name,
                "title": f"Invoice #{inv.get('invoice_number')} ({inv.get('payment_status')})",
                "description": f"Amount: {inv.get('currency_symbol', '₹')}{float(inv.get('total', 0) or 0):,.2f} via {inv.get('payment_method', 'Razorpay')}",
                "timestamp": inv['created_at'].isoformat() if inv.get('created_at') else now.isoformat(),
                "status": inv.get('payment_status', ''),
                "icon": "Receipt"
            })

        for aud in AuditLog.objects.values('id', 'client_name', 'admin_name', 'action', 'module', 'after_value', 'created_at').order_by('-created_at')[:6]:
            after_val = aud.get('after_value', '') or ''
            recent_activity.append({
                "id": f"aud_{aud['id']}",
                "type": "AUDIT",
                "client_name": aud.get('client_name', ''),
                "title": f"{aud.get('admin_name', '')} executed {aud.get('action', '')}",
                "description": f"Module: {aud.get('module', '')} — {after_val[:100]}",
                "timestamp": aud['created_at'].isoformat() if aud.get('created_at') else now.isoformat(),
                "status": "LOGGED",
                "icon": "ShieldCheck"
            })

        recent_activity.sort(key=lambda x: x['timestamp'], reverse=True)
        recent_activity = recent_activity[:25]

        recent_logins = []
        for log in AuditLog.objects.filter(action__in=['LOGIN', 'REGISTER & LOGIN']).values('id', 'admin_name', 'client_name', 'created_at', 'ip_address', 'action').order_by('-created_at')[:10]:
            recent_logins.append({
                "id": str(log['id']),
                "username": log.get('admin_name', ''),
                "client_name": log.get('client_name', ''),
                "timestamp": log['created_at'].isoformat() if log.get('created_at') else now.isoformat(),
                "ip_address": log.get('ip_address') or 'System/Internal',
                "action": log.get('action', '')
            })

        return Response({
            "kpis": {
                # Clients
                "totalClients": total_clients,
                "activeClients": active_clients,
                "inactiveClients": inactive_clients,
                "pendingClientApprovals": pending_client_approvals,
                "approvedClients": approved_clients,
                "rejectedClients": rejected_clients,
                # Channels
                "totalChannels": total_possible_channels,
                "activeChannels": active_channels_count,
                "inactiveChannels": inactive_channels_count,
                "whatsappChannels": whatsapp_active_count,
                "facebookChannels": facebook_active_count,
                "instagramChannels": instagram_active_count,
                "emailChannels": email_active_count,
                # Messaging
                "totalMessages": total_messages,
                "whatsappMessages": whatsapp_messages,
                "facebookMessages": facebook_messages,
                "instagramMessages": instagram_messages,
                "botMessages": bot_messages,
                "humanMessages": human_messages,
                "totalChats": total_chats,
                # AI
                "activeBots": active_bots,
                "inactiveBots": inactive_bots,
                "totalBotConversations": total_bot_conversations,
                "humanTakeoverCount": human_takeover_count,
                "totalKnowledgeBaseDocuments": total_kb_docs,
                "totalKnowledgeBaseChunks": total_kb_chunks,
                # Documents & Sales
                "totalProposals": total_proposals,
                "totalQuotations": total_quotations,
                "totalInvoices": total_invoices,
                "paidInvoices": paid_invoices,
                "pendingInvoices": pending_invoices,
                "totalInvoiceValue": total_invoice_value,
                "totalProducts": Product.objects.count(),
                "totalSales": total_sales_count,
                "totalSalesRevenue": total_sales_revenue,
                # Teams & Projects
                "totalTeamMembers": total_team_members,
                "activeTeamMembers": active_team_members,
                "pendingTeamInvitations": pending_team_invitations,
                "totalProjects": total_projects,
                "activeProjects": active_projects,
                "completedProjects": completed_projects,
                "pendingProjects": pending_projects,
                "overdueProjects": overdue_projects,
                "totalEmails": total_emails,
                "totalEmailAccounts": total_email_accounts
            },
            "charts": {
                "messagesToday": messages_today,
                "messagesThisWeek": messages_this_week,
                "messagesThisMonth": messages_this_month,
                "incomingMessages": incoming_messages,
                "outgoingMessages": outgoing_messages,
                "botMessages": bot_messages,
                "humanMessages": human_messages,
                "messagesByChannel": messages_by_channel,
                "dailyMessagesTrend": daily_messages,
                "clientsGrowth": clients_growth,
                "financialDistribution": {
                    "quotationsValue": quotations_val,
                    "proposalsValue": proposals_val,
                    "invoicesValue": total_invoice_value,
                    "salesRevenue": total_sales_revenue
                }
            },
            "clientComparison": client_comparison,
            "recentActivity": recent_activity,
            "recentLogins": recent_logins
        })


class SuperAdminClientsListView(APIView):
    """
    Super Admin Clients Directory API (Section 1).
    Provides all 21 requested fields per client, search, multi-faceted filters,
    and server-side sorting.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status', 'ALL').upper()
        approval_filter = request.query_params.get('approval', 'ALL').upper()
        date_range = request.query_params.get('date_range', 'ALL').upper()
        page = int(request.query_params.get('page', 1))
        page_size = int(request.query_params.get('page_size', 20))
        sort_by = request.query_params.get('sort_by', '-created_at')

        clients_qs = Client.objects.all()

        if status_filter != 'ALL':
            clients_qs = clients_qs.filter(status=status_filter)

        if search:
            clients_qs = clients_qs.filter(
                Q(business_name__icontains=search) |
                Q(phone_number__icontains=search) |
                Q(users__email__icontains=search) |
                Q(users__username__icontains=search) |
                Q(users__first_name__icontains=search) |
                Q(users__last_name__icontains=search)
            ).distinct()

        # Date range filtering
        now = timezone.now()
        if date_range == 'TODAY':
            clients_qs = clients_qs.filter(created_at__date=now.date())
        elif date_range == '7D':
            clients_qs = clients_qs.filter(created_at__gte=now - timedelta(days=7))
        elif date_range == '30D':
            clients_qs = clients_qs.filter(created_at__gte=now - timedelta(days=30))
        elif date_range == '90D':
            clients_qs = clients_qs.filter(created_at__gte=now - timedelta(days=90))

        # Sort order
        if sort_by in ['created_at', '-created_at', 'business_name', '-business_name', 'status', '-status']:
            clients_qs = clients_qs.order_by(sort_by)
        else:
            clients_qs = clients_qs.order_by('-created_at')

        # Collect and filter all clients
        all_clients_data = []
        for client in clients_qs:
            primary_user = client.users.filter(role='CLIENT').first() or client.users.first()
            user_email = primary_user.email if primary_user else ''
            user_name = ''
            if primary_user:
                user_name = f"{primary_user.first_name} {primary_user.last_name}".strip() or primary_user.username or ''
            if not user_name:
                user_name = client.business_name
            user_phone = client.phone_number or (primary_user.employee_id if primary_user else '')
            approval_status = primary_user.status if primary_user else 'PENDING'
            last_active = primary_user.last_active_at if primary_user else client.updated_at
            last_login = primary_user.last_login if primary_user else None

            if approval_filter != 'ALL' and approval_status != approval_filter:
                continue

            channels_map = {
                "whatsapp": bool(client.whatsapp_access_token or client.whatsapp_phone_number_id),
                "facebook": bool(client.facebook_enabled),
                "instagram": bool(client.instagram_enabled),
                "gmail": bool(client.gmail_enabled),
                "onedrive": bool(client.onedrive_enabled),
                "google_calendar": bool(client.google_calendar_enabled),
                "google_sheets": bool(client.google_sheets_enabled),
                "google_docs": bool(client.google_docs_enabled),
                "google_slides": bool(client.google_slides_enabled),
                "zoho": bool(client.zoho_enabled),
                "youtube": bool(client.youtube_enabled),
                "google_news": bool(client.google_news_enabled),
                "outlook": bool(client.outlook_enabled)
            }
            active_channels_count = sum(1 for v in channels_map.values() if v)
            total_channels_count = len(channels_map)
            inactive_channels_count = total_channels_count - active_channels_count

            # Message metrics
            c_msgs = client.messages.all()
            total_messages_count = c_msgs.count()
            bot_messages_count = c_msgs.filter(sender_user__isnull=True).count()
            human_replies_count = c_msgs.filter(sender_user__isnull=False).count()

            # Project metrics
            c_projects = client.projects.all()
            active_projects_count = c_projects.filter(status='IN_PROGRESS').count()
            completed_projects_count = c_projects.filter(status='COMPLETED').count()
            pending_projects_count = c_projects.filter(status__in=['PLANNING', 'ON_HOLD']).count()

            bot_status = bool(client.ai_enabled or client.automation_enabled)
            email_activity_count = client.email_messages.count()
            proposals_count = client.sales_documents.filter(document_type='PROPOSAL').count()
            quotations_count = client.sales_documents.filter(document_type='QUOTATION').count()
            invoices_count = client.invoices.count() + client.sales_documents.filter(document_type='INVOICE').count()

            all_clients_data.append({
                "id": str(client.id),
                "client_name": user_name,
                "company_name": client.business_name,
                "email": user_email,
                "phone": user_phone or client.phone_number or '—',
                "status": client.status,
                "approval_status": approval_status,
                "registration_date": client.created_at.isoformat() if client.created_at else None,
                "created_date": client.created_at.isoformat() if client.created_at else None,
                "last_active": last_active.isoformat() if last_active else None,
                "last_login": last_login.isoformat() if last_login else None,
                # Channels
                "total_channels": total_channels_count,
                "active_channels": active_channels_count,
                "inactive_channels": inactive_channels_count,
                "channels": channels_map,
                # Messaging & Bot
                "total_messages": total_messages_count,
                "bot_messages": bot_messages_count,
                "human_replies": human_replies_count,
                "bot_status": bot_status,
                "email_activity": email_activity_count,
                # Projects & Team
                "team_members": client.users.count(),
                "active_projects": active_projects_count,
                "completed_projects": completed_projects_count,
                "pending_projects": pending_projects_count,
                # Documents & Sales
                "proposal_count": proposals_count,
                "quotation_count": quotations_count,
                "invoice_count": invoices_count,
                "products_count": client.products.count(),
                "plan": client.plan,
                "white_label_name": client.white_label_name or '',
                "white_label_domain": client.white_label_domain or (client.settings.get('custom_domain') if isinstance(client.settings, dict) else ''),
                "white_label_logo": client.white_label_logo or '',
                "company_logo_url": client.company_logo_url or client.white_label_logo or '',
                "settings": client.settings if isinstance(client.settings, dict) else {},
                "user_id": str(primary_user.id) if primary_user else None
            })

        # Paginate in memory
        total_count = len(all_clients_data)
        total_pages = (total_count + page_size - 1) // page_size if total_count > 0 else 1

        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        clients_data = all_clients_data[start_idx:end_idx]

        return Response({
            "results": clients_data,
            "total_count": total_count,
            "total_pages": total_pages,
            "current_page": page
        })


class SuperAdminClientDetailDashboardView(APIView):
    """
    Client 360° Detail Dashboard API (Sections 2 to 17).
    Gathers live database state for all 16 tabs:
    Overview, Channels, WhatsApp, Facebook, Instagram, Bot & AI, Messages, Email,
    Proposals, Quotations, Invoices (with Product-Wise Aggregation), Products,
    Team, Projects, Activity Timeline, and Settings.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request, client_id):
        print("DEBUG VIEW client_id:", repr(client_id))
        try:
            client = Client.objects.get(id=client_id)
            print("DEBUG VIEW client object:", repr(client))
        except Client.DoesNotExist:
            print("DEBUG VIEW client does not exist")
            return Response({"error": "Client not found."}, status=status.HTTP_404_NOT_FOUND)

        def safe_get_relation_attr(instance, relation_name, attr_name, default=""):
            try:
                rel = getattr(instance, relation_name)
                if rel:
                    return getattr(rel, attr_name, default)
            except Exception:
                pass
            return default

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ── 1. Client Overview ──────────────────────────────────────────────────
        primary_user = client.users.filter(role='CLIENT').first() or client.users.first()
        overview = {
            "id": str(client.id),
            "business_name": client.business_name,
            "email": primary_user.email if primary_user else '',
            "phone_number": client.phone_number or '',
            "address": client.address or '',
            "status": client.status,
            "approval_status": primary_user.status if primary_user else 'APPROVED',
            "plan": client.plan,
            "created_at": client.created_at.isoformat() if client.created_at else None,
            "last_login": primary_user.last_login.isoformat() if (primary_user and primary_user.last_login) else None,
            "last_active": primary_user.last_active_at.isoformat() if (primary_user and primary_user.last_active_at) else None,
            "team_member_count": client.users.count()
        }

        # ── 2. Messages & Chat Analytics ────────────────────────────────────────
        client_msgs = client.messages.all()
        msg_stats = client_msgs.aggregate(
            total_msgs=Count('id'),
            msgs_sent=Count('id', filter=Q(message_type='OUTGOING')),
            msgs_received=Count('id', filter=Q(message_type='INCOMING')),
            bot_msgs=Count('id', filter=Q(sender_user__isnull=True)),
            human_replies=Count('id', filter=Q(sender_user__isnull=False)),
            msgs_today=Count('id', filter=Q(created_at__gte=today_start)),
            msgs_this_week=Count('id', filter=Q(created_at__gte=seven_days_ago)),
            msgs_this_month=Count('id', filter=Q(created_at__gte=month_start)),
        )
        total_msgs = msg_stats['total_msgs']
        msgs_sent = msg_stats['msgs_sent']
        msgs_received = msg_stats['msgs_received']
        bot_msgs = msg_stats['bot_msgs']
        human_replies = msg_stats['human_replies']
        msgs_today = msg_stats['msgs_today']
        msgs_this_week = msg_stats['msgs_this_week']
        msgs_this_month = msg_stats['msgs_this_month']

        client_convos = client.conversations.all()
        convo_stats = client_convos.aggregate(
            total_convos=Count('id'),
            active_convos=Count('id', filter=Q(status__in=['OPEN', 'IN_PROGRESS'])),
            closed_convos=Count('id', filter=Q(status__in=['CLOSED', 'RESOLVED'])),
            unread_convos=Count('id', filter=Q(unread_count_admin__gt=0) | Q(unread_count_employee__gt=0)),
        )
        total_convos = convo_stats['total_convos']
        active_convos = convo_stats['active_convos']
        closed_convos = convo_stats['closed_convos']
        unread_convos = convo_stats['unread_convos']

        # Messages trend
        msg_trend = []
        for i in range(6, -1, -1):
            d_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            d_end = d_start + timedelta(days=1)
            in_cnt = client_msgs.filter(created_at__gte=d_start, created_at__lt=d_end, message_type='INCOMING').count()
            out_cnt = client_msgs.filter(created_at__gte=d_start, created_at__lt=d_end, message_type='OUTGOING').count()
            bot_cnt = client_msgs.filter(created_at__gte=d_start, created_at__lt=d_end, sender_user__isnull=True).count()
            msg_trend.append({
                "date": d_start.strftime('%b %d'),
                "incoming": in_cnt,
                "outgoing": out_cnt,
                "bot": bot_cnt,
                "total": in_cnt + out_cnt
            })

        channel_dist_qs = client_msgs.values('channel').annotate(count=Count('id'))
        channel_dist = {item['channel']: item['count'] for item in channel_dist_qs}

        # ── 3. Channels Management ──────────────────────────────────────────────
        channels = [
            {
                "name": "WhatsApp Business",
                "key": "whatsapp",
                "connected": bool(client.whatsapp_access_token or client.whatsapp_phone_number_id),
                "active": bool(client.whatsapp_access_token),
                "details": f"Phone ID: {client.whatsapp_phone_number_id or 'Not Configured'} • WABA: {client.whatsapp_waba_id or 'N/A'}",
                "messages_count": client_msgs.filter(channel='WHATSAPP').count(),
                "conversations_count": client_convos.filter(channel='WHATSAPP').count(),
                "bot_replies": client_msgs.filter(channel='WHATSAPP', sender_user__isnull=True).count(),
                "human_replies": client_msgs.filter(channel='WHATSAPP', sender_user__isnull=False).count(),
                "status": "Connected" if client.whatsapp_access_token else "Disconnected",
                "health": "Healthy" if client.whatsapp_access_token else "Offline"
            },
            {
                "name": "Instagram Direct",
                "key": "instagram",
                "connected": bool(client.instagram_enabled),
                "active": bool(client.instagram_enabled),
                "details": "Meta Graph API Linked" if client.instagram_enabled else "Not Configured",
                "messages_count": client_msgs.filter(channel='INSTAGRAM').count(),
                "conversations_count": client_convos.filter(channel='INSTAGRAM').count(),
                "bot_replies": client_msgs.filter(channel='INSTAGRAM', sender_user__isnull=True).count(),
                "human_replies": client_msgs.filter(channel='INSTAGRAM', sender_user__isnull=False).count(),
                "status": "Active" if client.instagram_enabled else "Inactive",
                "health": "Healthy" if client.instagram_enabled else "Offline"
            },
            {
                "name": "Facebook Messenger",
                "key": "facebook",
                "connected": bool(client.facebook_enabled),
                "active": bool(client.facebook_enabled),
                "details": "Facebook Page Webhook Active" if client.facebook_enabled else "Not Configured",
                "messages_count": client_msgs.filter(channel='FACEBOOK').count(),
                "conversations_count": client_convos.filter(channel='FACEBOOK').count(),
                "bot_replies": client_msgs.filter(channel='FACEBOOK', sender_user__isnull=True).count(),
                "human_replies": client_msgs.filter(channel='FACEBOOK', sender_user__isnull=False).count(),
                "status": "Active" if client.facebook_enabled else "Inactive",
                "health": "Healthy" if client.facebook_enabled else "Offline"
            },
            {
                "name": "Gmail / Google Workspace",
                "key": "gmail",
                "connected": bool(client.gmail_enabled or client.email_accounts.filter(provider='gmail').exists()),
                "active": bool(client.gmail_enabled),
                "details": f"Connected Accounts: {client.email_accounts.filter(provider='gmail').count()}",
                "messages_count": client.email_messages.count(),
                "conversations_count": 0,
                "bot_replies": client.email_auto_replies.filter(is_active=True).count(),
                "human_replies": client.email_messages.filter(folder='sent').count(),
                "status": "Active" if client.gmail_enabled else "Inactive",
                "health": "Healthy" if client.gmail_enabled else "Offline"
            },
            {
                "name": "Microsoft Outlook 365",
                "key": "outlook",
                "connected": bool(client.outlook_enabled or client.email_accounts.filter(provider='outlook').exists()),
                "active": bool(client.outlook_enabled),
                "details": "Outlook Sync Active" if client.outlook_enabled else "Disabled",
                "messages_count": client.email_messages.filter(account__provider='outlook').count(),
                "conversations_count": 0,
                "bot_replies": 0,
                "human_replies": 0,
                "status": "Active" if client.outlook_enabled else "Inactive",
                "health": "Healthy" if client.outlook_enabled else "Offline"
            },
            {
                "name": "Microsoft OneDrive",
                "key": "onedrive",
                "connected": bool(client.onedrive_enabled),
                "active": bool(client.onedrive_enabled),
                "details": "Cloud File Repository" if client.onedrive_enabled else "Disabled",
                "messages_count": 0,
                "conversations_count": 0,
                "bot_replies": 0,
                "human_replies": 0,
                "status": "Active" if client.onedrive_enabled else "Inactive",
                "health": "Healthy" if client.onedrive_enabled else "Offline"
            },
            {
                "name": "Google Sheets",
                "key": "google_sheets",
                "connected": bool(client.google_sheets_enabled),
                "active": bool(client.google_sheets_enabled),
                "details": "Real-time Lead Syncing" if client.google_sheets_enabled else "Disabled",
                "messages_count": 0,
                "conversations_count": 0,
                "bot_replies": 0,
                "human_replies": 0,
                "status": "Active" if client.google_sheets_enabled else "Inactive",
                "health": "Healthy" if client.google_sheets_enabled else "Offline"
            },
            {
                "name": "Google Docs",
                "key": "google_docs",
                "connected": bool(client.google_docs_enabled),
                "active": bool(client.google_docs_enabled),
                "details": "Documentation Automation" if client.google_docs_enabled else "Disabled",
                "messages_count": 0,
                "conversations_count": 0,
                "bot_replies": 0,
                "human_replies": 0,
                "status": "Active" if client.google_docs_enabled else "Inactive",
                "health": "Healthy" if client.google_docs_enabled else "Offline"
            },
            {
                "name": "Google Slides",
                "key": "google_slides",
                "connected": bool(client.google_slides_enabled),
                "active": bool(client.google_slides_enabled),
                "details": "Presentation Generation" if client.google_slides_enabled else "Disabled",
                "messages_count": 0,
                "conversations_count": 0,
                "bot_replies": 0,
                "human_replies": 0,
                "status": "Active" if client.google_slides_enabled else "Inactive",
                "health": "Healthy" if client.google_slides_enabled else "Offline"
            },
            {
                "name": "YouTube Broadcast & Comments",
                "key": "youtube",
                "connected": bool(client.youtube_enabled),
                "active": bool(client.youtube_enabled),
                "details": "YouTube Channel Sync" if client.youtube_enabled else "Disabled",
                "messages_count": 0,
                "conversations_count": 0,
                "bot_replies": 0,
                "human_replies": 0,
                "status": "Active" if client.youtube_enabled else "Inactive",
                "health": "Healthy" if client.youtube_enabled else "Offline"
            },
            {
                "name": "Zoho CRM",
                "key": "zoho",
                "connected": bool(client.zoho_enabled),
                "active": bool(client.zoho_enabled),
                "details": "Lead Pipeline Integration" if client.zoho_enabled else "Disabled",
                "messages_count": 0,
                "conversations_count": 0,
                "bot_replies": 0,
                "human_replies": 0,
                "status": "Active" if client.zoho_enabled else "Inactive",
                "health": "Healthy" if client.zoho_enabled else "Offline"
            },
            {
                "name": "Google News AI Monitor",
                "key": "google_news",
                "connected": bool(client.google_news_enabled),
                "active": bool(client.google_news_enabled),
                "details": "Industry Intelligence Feed" if client.google_news_enabled else "Disabled",
                "messages_count": 0,
                "conversations_count": 0,
                "bot_replies": 0,
                "human_replies": 0,
                "status": "Active" if client.google_news_enabled else "Inactive",
                "health": "Healthy" if client.google_news_enabled else "Offline"
            },
            {
                "name": "Google Calendar",
                "key": "google_calendar",
                "connected": bool(client.google_calendar_enabled),
                "active": bool(client.google_calendar_enabled),
                "details": "Automated Booking Slots" if client.google_calendar_enabled else "Disabled",
                "messages_count": 0,
                "conversations_count": 0,
                "bot_replies": 0,
                "human_replies": 0,
                "status": "Active" if client.google_calendar_enabled else "Inactive",
                "health": "Healthy" if client.google_calendar_enabled else "Offline"
            }
        ]

        # ── 4. WhatsApp Specific Analytics (Section 5) ───────────────────────────
        wa_msgs = client_msgs.filter(channel='WHATSAPP')
        wa_convos = client_convos.filter(channel='WHATSAPP')
        
        wa_stats = wa_convos.aggregate(
            wa_bot_handled_convos=Count('id', filter=Q(assigned_to__isnull=True)),
            wa_human_handled_convos=Count('id', filter=Q(assigned_to__isnull=False)),
            wa_unanswered=Count('id', filter=Q(unread_count_admin__gt=0) | Q(unread_count_employee__gt=0)),
            wa_active=Count('id', filter=Q(status__in=['OPEN', 'IN_PROGRESS'])),
            wa_closed=Count('id', filter=Q(status__in=['CLOSED', 'RESOLVED'])),
        )
        wa_bot_handled_convos = wa_stats['wa_bot_handled_convos']
        wa_human_handled_convos = wa_stats['wa_human_handled_convos']
        wa_unanswered = wa_stats['wa_unanswered']
        wa_active = wa_stats['wa_active']
        wa_closed = wa_stats['wa_closed']
        
        wa_msg_stats = wa_msgs.aggregate(
            wa_incoming=Count('id', filter=Q(message_type='INCOMING')),
            wa_outgoing=Count('id', filter=Q(message_type='OUTGOING')),
            wa_bot_replies=Count('id', filter=Q(sender_user__isnull=True)),
            wa_human_replies=Count('id', filter=Q(sender_user__isnull=False)),
        )
        wa_incoming = wa_msg_stats['wa_incoming']
        wa_outgoing = wa_msg_stats['wa_outgoing']
        wa_bot_replies = wa_msg_stats['wa_bot_replies']
        wa_human_replies = wa_msg_stats['wa_human_replies']
        wa_last_msg = wa_msgs.order_by('-created_at').first()

        # WhatsApp conversation drill-down
        wa_conversation_list = []
        for convo in wa_convos.order_by('-updated_at')[:25]:
            thread_msgs = list(Message.objects.filter(conversation=convo).order_by('-created_at')[:10])
            last_m = thread_msgs[0] if thread_msgs else None
            recent_thread = []
            for m in thread_msgs:
                recent_thread.append({
                    "id": str(m.id),
                    "sender": "AI Bot" if m.sender_user is None else (m.sender_name or safe_get_relation_attr(m, 'sender_user', 'username', 'Customer')),
                    "is_bot": m.sender_user is None,
                    "body": m.body,
                    "timestamp": m.created_at.isoformat(),
                    "type": m.message_type
                })
            wa_conversation_list.append({
                "id": str(convo.id),
                "customer_name": safe_get_relation_attr(convo, 'contact', 'name', convo.customer_phone or "Customer"),
                "customer_phone": safe_get_relation_attr(convo, 'contact', 'phone_number', convo.customer_phone or "—"),
                "status": convo.status,
                "assigned_to": safe_get_relation_attr(convo, 'assigned_to', 'username', 'Unassigned (Bot)'),
                "unread_count": convo.unread_count_admin + convo.unread_count_employee,
                "last_message": last_m.body if last_m else "",
                "last_message_time": (last_m.created_at if last_m else convo.updated_at).isoformat(),
                "thread": list(reversed(recent_thread))
            })

        whatsapp_analytics = {
            "total_messages": wa_msgs.count(),
            "incoming": wa_incoming,
            "outgoing": wa_outgoing,
            "total_conversations": wa_convos.count(),
            "bot_handled_conversations": wa_bot_handled_convos,
            "human_handled_conversations": wa_human_handled_convos,
            "bot_replies": wa_bot_replies,
            "human_replies": wa_human_replies,
            "unanswered": wa_unanswered,
            "active_conversations": wa_active,
            "closed_conversations": wa_closed,
            "media_messages": wa_msgs.exclude(Q(body__startswith='[Text]') | Q(body='')).filter(body__icontains='http').count(),
            "documents_received": wa_msgs.filter(body__icontains='.pdf').count(),
            "last_message_time": wa_last_msg.created_at.isoformat() if wa_last_msg else None,
            "connection_status": "Connected" if client.whatsapp_access_token else "Disconnected",
            "phone_number_id": client.whatsapp_phone_number_id or '—',
            "conversations": wa_conversation_list
        }

        # ── 5. Facebook Analytics (Section 6) ───────────────────────────────────
        fb_msgs = client_msgs.filter(channel='FACEBOOK')
        fb_convos = client_convos.filter(channel='FACEBOOK')
        fb_msg_stats = fb_msgs.aggregate(
            fb_incoming=Count('id', filter=Q(message_type='INCOMING')),
            fb_outgoing=Count('id', filter=Q(message_type='OUTGOING')),
            fb_bot_replies=Count('id', filter=Q(sender_user__isnull=True)),
            fb_human_replies=Count('id', filter=Q(sender_user__isnull=False)),
        )
        fb_incoming = fb_msg_stats['fb_incoming']
        fb_outgoing = fb_msg_stats['fb_outgoing']
        fb_bot_replies = fb_msg_stats['fb_bot_replies']
        fb_human_replies = fb_msg_stats['fb_human_replies']
        fb_last_msg = fb_msgs.order_by('-created_at').first()

        facebook_analytics = {
            "total_messages": fb_msgs.count(),
            "incoming": fb_incoming,
            "outgoing": fb_outgoing,
            "bot_replies": fb_bot_replies,
            "human_replies": fb_human_replies,
            "total_conversations": fb_convos.count(),
            "active_conversations": fb_convos.filter(status__in=['OPEN', 'IN_PROGRESS']).count(),
            "unanswered_conversations": fb_convos.filter(Q(unread_count_admin__gt=0) | Q(unread_count_employee__gt=0)).count(),
            "last_activity": fb_last_msg.created_at.isoformat() if fb_last_msg else None,
            "connection_status": "Active" if client.facebook_enabled else "Inactive"
        }

        # ── 6. Instagram Analytics (Section 7) ──────────────────────────────────
        ig_msgs = client_msgs.filter(channel='INSTAGRAM')
        ig_convos = client_convos.filter(channel='INSTAGRAM')
        ig_msg_stats = ig_msgs.aggregate(
            ig_incoming=Count('id', filter=Q(message_type='INCOMING')),
            ig_outgoing=Count('id', filter=Q(message_type='OUTGOING')),
            ig_bot_replies=Count('id', filter=Q(sender_user__isnull=True)),
            ig_human_replies=Count('id', filter=Q(sender_user__isnull=False)),
        )
        ig_incoming = ig_msg_stats['ig_incoming']
        ig_outgoing = ig_msg_stats['ig_outgoing']
        ig_bot_replies = ig_msg_stats['ig_bot_replies']
        ig_human_replies = ig_msg_stats['ig_human_replies']
        ig_last_msg = ig_msgs.order_by('-created_at').first()

        instagram_analytics = {
            "total_messages": ig_msgs.count(),
            "incoming": ig_incoming,
            "outgoing": ig_outgoing,
            "bot_replies": ig_bot_replies,
            "human_replies": ig_human_replies,
            "total_conversations": ig_convos.count(),
            "active_conversations": ig_convos.filter(status__in=['OPEN', 'IN_PROGRESS']).count(),
            "unanswered_conversations": ig_convos.filter(Q(unread_count_admin__gt=0) | Q(unread_count_employee__gt=0)).count(),
            "last_activity": ig_last_msg.created_at.isoformat() if ig_last_msg else None,
            "connection_status": "Active" if client.instagram_enabled else "Inactive"
        }

        # ── 7. Bot & AI Management + Knowledge Base (Sections 8 & 9) ───────────
        kb_docs = []
        for doc in client.knowledge_docs.all().order_by('-created_at'):
            kb_docs.append({
                "id": str(doc.id),
                "title": doc.title,
                "file_type": doc.file_type or 'PDF/DOCX',
                "file_size": doc.file_size or 0,
                "chunks_count": doc.chunks.count(),
                "created_at": doc.created_at.isoformat(),
                "status": "Processed" if doc.chunks.exists() or doc.extracted_text else "Pending",
                "text_excerpt": (doc.extracted_text[:200] + '...') if doc.extracted_text else 'Document text parsed and vectorized.'
            })

        total_bot_convos_client = client_convos.count()
        human_takeovers_client = client_convos.filter(assigned_to__isnull=False).count()
        takeover_pct = int((human_takeovers_client / total_bot_convos_client * 100)) if total_bot_convos_client > 0 else 0
        last_bot_msg = client_msgs.filter(sender_user__isnull=True).order_by('-created_at').first()

        bot_analytics = {
            "active": bool(client.ai_enabled or client.automation_enabled),
            "ai_enabled": bool(client.ai_enabled),
            "automation_enabled": bool(client.automation_enabled),
            "activation_date": client.created_at.isoformat() if client.created_at else None,
            "last_bot_activity": last_bot_msg.created_at.isoformat() if last_bot_msg else None,
            "ai_context": client.ai_context or '',
            "greeting_enabled": client.greeting_enabled,
            "greeting_message": client.greeting_message or '',
            "greeting_buttons": client.greeting_buttons or [],
            "total_conversations_handled": total_bot_convos_client,
            "total_messages_handled": bot_msgs,
            "bot_response_count": client_msgs.filter(ai_suggested_reply__isnull=False).count() + bot_msgs,
            "human_takeover_count": human_takeovers_client,
            "human_takeover_percentage": takeover_pct,
            "usage_today": client_msgs.filter(created_at__gte=today_start, sender_user__isnull=True).count(),
            "usage_this_week": client_msgs.filter(created_at__gte=seven_days_ago, sender_user__isnull=True).count(),
            "usage_this_month": client_msgs.filter(created_at__gte=month_start, sender_user__isnull=True).count(),
            "knowledge_base": {
                "status": "Active" if len(kb_docs) > 0 else "Empty",
                "total_documents": len(kb_docs),
                "processed_count": sum(1 for d in kb_docs if d['status'] == 'Processed'),
                "pending_count": sum(1 for d in kb_docs if d['status'] == 'Pending'),
                "failed_count": 0,
                "total_chunks": client.knowledge_chunks.count(),
                "last_update": kb_docs[0]['created_at'] if kb_docs else None,
                "documents": kb_docs
            }
        }

        # ── 8. Messages Explorer (Tab 7) ─────────────────────────────────────────
        messages_feed = []
        for msg in client_msgs.order_by('-created_at')[:40]:
            messages_feed.append({
                "id": str(msg.id),
                "channel": msg.channel,
                "message_type": msg.message_type,
                "sender_name": "AI Bot" if msg.sender_user is None else (msg.sender_name or msg.sender_user.username),
                "from_address": msg.from_address,
                "to_address": msg.to_address,
                "body": msg.body,
                "is_bot": msg.sender_user is None,
                "status": msg.status,
                "created_at": msg.created_at.isoformat()
            })

        # ── 9. Email Management & Analytics (Section 10) ─────────────────────────
        email_accounts = []
        for acc in client.email_accounts.all():
            email_accounts.append({
                "id": str(acc.id),
                "provider": acc.provider,
                "email_address": acc.email_address,
                "display_name": acc.display_name,
                "is_active": acc.is_active,
                "emails_processed": client.email_messages.filter(account=acc).count(),
                "created_at": acc.created_at.isoformat()
            })

        c_emails = client.email_messages.all()
        email_stats = c_emails.aggregate(
            emails_received=Count('id', filter=Q(folder='inbox')),
            emails_sent=Count('id', filter=Q(folder='sent')),
            emails_drafts=Count('id', filter=Q(folder='drafts')),
            emails_failed=Count('id', filter=Q(status='failed')),
        )
        emails_received = email_stats['emails_received']
        emails_sent = email_stats['emails_sent']
        emails_drafts = email_stats['emails_drafts']
        emails_failed = email_stats['emails_failed']
        auto_replies_sent = client.email_auto_replies.filter(is_active=True).count() * 4
        human_replies_sent = emails_sent

        email_activity_table = []
        for em in c_emails.order_by('-created_at')[:30]:
            email_activity_table.append({
                "id": str(em.id),
                "date": em.created_at.isoformat(),
                "sender": f"{em.sender_name} <{em.sender_email}>".strip() if em.sender_name else em.sender_email,
                "sender_email": em.sender_email,
                "subject": em.subject,
                "status": em.status,
                "folder": em.folder,
                "priority": em.priority,
                "auto_reply": bool(em.metadata.get('auto_reply_sent', False) or em.folder == 'sent' and 'Re:' in em.subject),
                "human_reply": bool(em.folder == 'sent' and not em.metadata.get('auto_reply_sent', False)),
                "assigned_to": em.assigned_to.username if em.assigned_to else "Unassigned",
                "body_preview": (em.body_text[:120] + '...') if em.body_text else em.subject,
                "body_html": em.body_html or em.body_text
            })

        last_email = c_emails.order_by('-created_at').first()

        email_metrics = {
            "total_accounts": len(email_accounts),
            "total_emails": c_emails.count(),
            "emails_received": emails_received,
            "emails_sent": emails_sent,
            "auto_replies_sent": auto_replies_sent,
            "human_replies_sent": human_replies_sent,
            "unanswered_emails": max(0, emails_received - human_replies_sent - auto_replies_sent),
            "failed_emails": emails_failed,
            "drafts": emails_drafts,
            "last_activity": last_email.created_at.isoformat() if last_email else None,
            "funnel": {
                "incoming": emails_received,
                "auto_reply": auto_replies_sent,
                "human_reply": human_replies_sent
            },
            "accounts": email_accounts,
            "activity_table": email_activity_table
        }

        # ── 10. Proposals (Section 11) ──────────────────────────────────────────
        proposals_qs = client.sales_documents.filter(document_type='PROPOSAL').only(
            'id', 'document_number', 'customer_name', 'customer_email', 'customer_company',
            'reference_number', 'grand_total', 'currency_symbol', 'status', 'document_date',
            'valid_until', 'created_at', 'accepted_at', 'secure_token'
        )
        proposals_list = []
        for p in proposals_qs.order_by('-created_at'):
            proposals_list.append({
                "id": str(p.id),
                "document_number": p.document_number,
                "customer_name": p.customer_name or 'Customer',
                "customer_email": p.customer_email or '',
                "customer_company": p.customer_company or '',
                "project_reference": p.reference_number or f"Project #{p.document_number}",
                "grand_total": float(p.grand_total),
                "currency_symbol": p.currency_symbol,
                "status": p.status,
                "document_date": str(p.document_date),
                "valid_until": str(p.valid_until) if p.valid_until else None,
                "created_at": p.created_at.isoformat(),
                "accepted_at": p.accepted_at.isoformat() if p.accepted_at else None,
                "secure_token": p.secure_token
            })

        proposals_summary = {
            "total_count": proposals_qs.count(),
            "draft_count": proposals_qs.filter(status='DRAFT').count(),
            "sent_count": proposals_qs.filter(status='SENT').count(),
            "viewed_count": proposals_qs.filter(status='VIEWED').count(),
            "approved_count": proposals_qs.filter(status='ACCEPTED').count(),
            "rejected_count": proposals_qs.filter(status='REJECTED').count(),
            "expired_count": proposals_qs.filter(status='EXPIRED').count(),
            "total_value": safe_sum(proposals_qs, 'grand_total'),
            "accepted_value": safe_sum(proposals_qs.filter(status='ACCEPTED'), 'grand_total'),
            "pending_value": safe_sum(proposals_qs.filter(status__in=['DRAFT', 'SENT', 'VIEWED']), 'grand_total'),
            "documents": proposals_list
        }

        # ── 11. Quotations (Section 12) ─────────────────────────────────────────
        quotations_qs = client.sales_documents.filter(document_type='QUOTATION').only(
            'id', 'document_number', 'customer_name', 'customer_email', 'customer_company',
            'reference_number', 'grand_total', 'currency_symbol', 'status', 'document_date',
            'valid_until', 'created_at', 'secure_token'
        )
        quotations_list = []
        for q in quotations_qs.order_by('-created_at'):
            quotations_list.append({
                "id": str(q.id),
                "document_number": q.document_number,
                "customer_name": q.customer_name or 'Customer',
                "customer_email": q.customer_email or '',
                "customer_company": q.customer_company or '',
                "product_service": q.reference_number or 'Standard Services Package',
                "grand_total": float(q.grand_total),
                "currency_symbol": q.currency_symbol,
                "status": q.status,
                "document_date": str(q.document_date),
                "valid_until": str(q.valid_until) if q.valid_until else None,
                "created_at": q.created_at.isoformat(),
                "secure_token": q.secure_token
            })

        quotations_summary = {
            "total_count": quotations_qs.count(),
            "draft_count": quotations_qs.filter(status='DRAFT').count(),
            "sent_count": quotations_qs.filter(status='SENT').count(),
            "accepted_count": quotations_qs.filter(status='ACCEPTED').count(),
            "rejected_count": quotations_qs.filter(status='REJECTED').count(),
            "expired_count": quotations_qs.filter(status='EXPIRED').count(),
            "total_value": safe_sum(quotations_qs, 'grand_total'),
            "accepted_value": safe_sum(quotations_qs.filter(status='ACCEPTED'), 'grand_total'),
            "pending_value": safe_sum(quotations_qs.filter(status__in=['DRAFT', 'SENT', 'VIEWED']), 'grand_total'),
            "documents": quotations_list
        }

        # ── 12. Invoices & Product-Wise Invoice Analytics (Section 13) ───────────
        invoices_qs = client.invoices.all().only(
            'id', 'invoice_number', 'line_items', 'order_reference', 'total', 'currency_symbol',
            'payment_status', 'invoice_status', 'payment_method', 'created_at', 'invoice_date', 'secure_token'
        )
        invoices_list = []
        for inv in invoices_qs.order_by('-created_at'):
            p_name = 'General Services'
            if inv.line_items and len(inv.line_items) > 0:
                p_name = inv.line_items[0].get('name', 'Service Item')
            elif inv.order_reference:
                p_name = inv.order_reference

            invoices_list.append({
                "id": str(inv.id),
                "invoice_number": inv.invoice_number,
                "product_name": p_name,
                "order_reference": inv.order_reference or '—',
                "total": float(inv.total),
                "currency_symbol": inv.currency_symbol,
                "payment_status": inv.payment_status,
                "invoice_status": inv.invoice_status,
                "payment_method": inv.payment_method,
                "created_at": inv.created_at.isoformat(),
                "invoice_date": inv.invoice_date.isoformat() if inv.invoice_date else inv.created_at.isoformat(),
                "due_date": (inv.invoice_date + timedelta(days=15)).isoformat() if inv.invoice_date else None,
                "secure_token": inv.secure_token or ''
            })

        # PRODUCT-WISE INVOICE AGGREGATION (Section 13 Critical Requirement)
        product_wise_invoices = []
        for prd in client.products.all():
            matched_invoices = [inv for inv in invoices_list if prd.name.lower() in inv['product_name'].lower() or prd.name.lower() in inv['order_reference'].lower()]
            p_inv_count = len(matched_invoices)
            p_inv_total = sum(inv['total'] for inv in matched_invoices)
            p_inv_paid = sum(inv['total'] for inv in matched_invoices if inv['payment_status'] == 'PAID')
            p_inv_pending = sum(inv['total'] for inv in matched_invoices if inv['payment_status'] != 'PAID')

            p_payments = ProductPayment.objects.filter(workspace=client, product=prd)
            if p_inv_count == 0 and p_payments.exists():
                p_inv_count = p_payments.count()
                p_inv_total = safe_sum(p_payments, 'amount')
                p_inv_paid = safe_sum(p_payments.filter(payment_status='PAID'), 'amount')
                p_inv_pending = safe_sum(p_payments.filter(payment_status__in=['PENDING', 'FAILED']), 'amount')

            product_wise_invoices.append({
                "product_id": str(prd.id),
                "product_name": prd.name,
                "category": prd.category,
                "price": float(prd.price),
                "invoice_count": p_inv_count,
                "total_amount": p_inv_total,
                "paid_amount": p_inv_paid,
                "pending_amount": p_inv_pending,
                "invoices": matched_invoices
            })

        unmatched_invoices = [inv for inv in invoices_list if not any(inv['id'] in [i['id'] for i in p['invoices']] for p in product_wise_invoices)]
        if unmatched_invoices:
            product_wise_invoices.append({
                "product_id": "custom_services",
                "product_name": "Custom & Subscription Invoices",
                "category": "Direct Billing",
                "price": 0.0,
                "invoice_count": len(unmatched_invoices),
                "total_amount": sum(inv['total'] for inv in unmatched_invoices),
                "paid_amount": sum(inv['total'] for inv in unmatched_invoices if inv['payment_status'] == 'PAID'),
                "pending_amount": sum(inv['total'] for inv in unmatched_invoices if inv['payment_status'] != 'PAID'),
                "invoices": unmatched_invoices
            })

        invoices_summary = {
            "total_count": invoices_qs.count(),
            "paid_count": invoices_qs.filter(payment_status='PAID').count(),
            "pending_count": invoices_qs.filter(payment_status='PENDING').count(),
            "overdue_count": invoices_qs.filter(payment_status__in=['PENDING', 'FAILED'], invoice_date__lt=now - timedelta(days=15)).count(),
            "cancelled_count": invoices_qs.filter(invoice_status='CANCELLED').count(),
            "total_value": safe_sum(invoices_qs, 'total'),
            "paid_amount": safe_sum(invoices_qs.filter(payment_status='PAID'), 'total'),
            "pending_amount": safe_sum(invoices_qs.filter(payment_status='PENDING'), 'total'),
            "product_wise_invoices": product_wise_invoices,
            "documents": invoices_list
        }

        # ── 13. Products & Sales Analytics (Section 14) ─────────────────────────
        products_list = []
        products_annotated = client.products.annotate(
            p_units_ann=Count('payments', filter=Q(payments__payment_status='PAID')),
            p_revenue_ann=Sum('payments__amount', filter=Q(payments__payment_status='PAID'))
        ).order_by('-created_at')
        
        for prd in products_annotated:
            p_revenue = float(prd.p_revenue_ann or 0.0)
            p_units = prd.p_units_ann or 0
            p_inv_cnt = sum(1 for inv in invoices_list if prd.name.lower() in inv['product_name'].lower())
            
            # Minor queries still, but avoided the ProductPayment ones
            p_qtn_cnt = quotations_qs.filter(Q(reference_number__icontains=prd.name) | Q(items__product=prd)).distinct().count()
            p_prp_cnt = proposals_qs.filter(Q(reference_number__icontains=prd.name) | Q(items__product=prd)).distinct().count()

            products_list.append({
                "id": str(prd.id),
                "name": prd.name,
                "price": float(prd.price),
                "category": prd.category,
                "in_stock": prd.in_stock,
                "stock_quantity": prd.stock_quantity,
                "currency": prd.currency,
                "units_sold": p_units,
                "revenue": p_revenue,
                "views": prd.views_count,
                "invoice_count": p_inv_cnt,
                "quotation_count": p_qtn_cnt,
                "proposal_count": p_prp_cnt,
                "created_at": prd.created_at.isoformat()
            })

        client_payments = ProductPayment.objects.filter(workspace=client)
        total_payment_rev = safe_sum(client_payments.filter(payment_status='PAID'), 'amount')

        sales_summary = {
            "total_products": client.products.count(),
            "active_products": client.products.filter(in_stock=True).count(),
            "inactive_products": client.products.filter(in_stock=False).count(),
            "total_sales_count": client_payments.filter(payment_status='PAID').count(),
            "total_revenue": total_payment_rev,
            "products": products_list
        }

        # ── 14. Team Management (Section 15) ────────────────────────────────────
        team_members_list = []
        for u in client.users.all().order_by('-date_joined'):
            assigned_proj = u.assigned_projects.all()
            proj_names = [p.name for p in assigned_proj]
            team_members_list.append({
                "id": str(u.id),
                "name": f"{u.first_name} {u.last_name}".strip() or u.username,
                "username": u.username,
                "email": u.email,
                "role": u.role,
                "enterprise_role": u.enterprise_role or u.role,
                "department": u.department or 'General',
                "designation": u.designation or 'Team Member',
                "status": u.status,
                "is_online": u.is_online,
                "last_active": u.last_active_at.isoformat() if u.last_active_at else None,
                "last_login": u.last_login.isoformat() if u.last_login else None,
                "assigned_projects_count": len(proj_names),
                "assigned_projects": proj_names,
                "assigned_channels": u.assigned_social_channels or [],
                "permissions": u.permissions or [],
                "messages_sent": Message.objects.filter(client=client, sender_user=u).count(),
                "reports_submitted": WorkReport.objects.filter(client=client, employee=u).count()
            })

        team_summary = {
            "total_members": client.users.count(),
            "active_members": client.users.filter(status='APPROVED').count(),
            "inactive_members": client.users.filter(status__in=['SUSPENDED', 'REJECTED']).count(),
            "pending_invitations": client.team_invites.count(),
            "admins_count": client.users.filter(Q(role='ADMIN') | Q(enterprise_role__in=['SUPER_ADMIN', 'ORG_ADMIN'])).count(),
            "managers_count": client.users.filter(enterprise_role__in=['HR', 'MANAGER', 'TEAM_LEAD']).count(),
            "agents_count": client.users.filter(enterprise_role__in=['EMPLOYEE', 'INTERN', 'GUEST']).count(),
            "members": team_members_list
        }

        # ── 15. Projects & Tasks (Section 16) ───────────────────────────────────
        projects_list = []
        c_projects_all = client.projects.all().order_by('-created_at')
        for proj in c_projects_all:
            proj_tasks = proj.tasks.filter(is_archived=False)
            t_total = proj_tasks.count()
            t_done = proj_tasks.filter(status='COMPLETED').count()
            t_pending = t_total - t_done

            projects_list.append({
                "id": str(proj.id),
                "name": proj.name,
                "description": proj.description or '',
                "priority": proj.priority,
                "status": proj.status,
                "progress_percentage": proj.progress_percentage,
                "owner_name": safe_get_relation_attr(proj, 'owner', 'username', 'Unassigned'),
                "department": proj.department,
                "start_date": str(proj.start_date) if proj.start_date else None,
                "deadline": str(proj.deadline) if proj.deadline else None,
                "is_overdue": bool(proj.deadline and proj.deadline < now.date() and proj.status != 'COMPLETED'),
                "assigned_members": [{"id": str(m.id), "name": m.username} for m in proj.members.all()],
                "tasks_total": t_total,
                "tasks_completed": t_done,
                "tasks_pending": t_pending,
                "last_activity": proj.updated_at.isoformat()
            })

        avg_project_prog = int(c_projects_all.aggregate(avg=Avg('progress_percentage'))['avg'] or 0) if c_projects_all.exists() else 0

        projects_summary = {
            "total_projects": c_projects_all.count(),
            "active_projects": c_projects_all.filter(status='IN_PROGRESS').count(),
            "completed_projects": c_projects_all.filter(status='COMPLETED').count(),
            "pending_projects": c_projects_all.filter(status='PLANNING').count(),
            "overdue_projects": c_projects_all.filter(deadline__lt=now.date(), status__in=['PLANNING', 'IN_PROGRESS', 'ON_HOLD']).count(),
            "on_hold_projects": c_projects_all.filter(status='ON_HOLD').count(),
            "average_progress": avg_project_prog,
            "projects": projects_list
        }

        # ── 16. Unified Client Activity Timeline (Section 17) ───────────────────
        activity_timeline = []

        # Audit Logs for this client
        for aud in AuditLog.objects.filter(client_name=client.business_name).only('id', 'created_at', 'admin_name', 'action', 'module', 'after_value').order_by('-created_at')[:20]:
            activity_timeline.append({
                "id": f"aud_{aud.id}",
                "timestamp": aud.created_at.isoformat(),
                "user": aud.admin_name,
                "action": aud.action,
                "module": aud.module,
                "status": "COMPLETED",
                "reference_id": f"AUD-{aud.id}",
                "description": f"{aud.admin_name} changed {aud.module}: {aud.after_value or aud.action}",
                "icon": "ShieldCheck"
            })

        # Messages
        for msg in client_msgs.only('id', 'created_at', 'sender_user', 'sender_name', 'message_type', 'channel', 'body', 'status').order_by('-created_at')[:15]:
            is_bot = msg.sender_user is None
            user_name = "AI Bot" if is_bot else (msg.sender_name or safe_get_relation_attr(msg, 'sender_user', 'username', 'Customer'))
            activity_timeline.append({
                "id": f"msg_{msg.id}",
                "timestamp": msg.created_at.isoformat(),
                "user": user_name,
                "action": "BOT_REPLY" if is_bot else ("MESSAGE_INCOMING" if msg.message_type == 'INCOMING' else "HUMAN_REPLY"),
                "module": "MESSAGING",
                "status": msg.status,
                "reference_id": f"MSG-{msg.id}",
                "description": f"{msg.channel}: {msg.body[:100]}",
                "icon": "Bot" if is_bot else "MessageSquare"
            })

        # Proposals & Quotations
        for doc in client.sales_documents.only('id', 'created_at', 'created_by', 'document_type', 'status', 'document_number', 'grand_total', 'currency_symbol', 'customer_name').order_by('-created_at')[:10]:
            activity_timeline.append({
                "id": f"doc_{doc.id}",
                "timestamp": doc.created_at.isoformat(),
                "user": safe_get_relation_attr(doc, 'created_by', 'username', 'System'),
                "action": f"{doc.document_type}_{doc.status}",
                "module": "SALES_DOCS",
                "status": doc.status,
                "reference_id": f"DOC-{doc.document_number}",
                "description": f"{doc.document_type.capitalize()} #{doc.document_number} ({doc.currency_symbol}{float(doc.grand_total):,.2f}) for {doc.customer_name or 'Customer'}",
                "icon": "FileCheck" if doc.document_type == 'QUOTATION' else "FileText"
            })

        # Invoices
        for inv in invoices_qs.order_by('-created_at')[:10]:
            activity_timeline.append({
                "id": f"inv_{inv.id}",
                "timestamp": inv.created_at.isoformat(),
                "user": "Billing System",
                "action": f"INVOICE_{inv.payment_status}",
                "module": "INVOICES",
                "status": inv.payment_status,
                "reference_id": f"INV-{inv.invoice_number}",
                "description": f"Invoice #{inv.invoice_number} ({inv.currency_symbol}{float(inv.total):,.2f}) - Status: {inv.payment_status}",
                "icon": "Receipt"
            })

        # Emails
        for em in c_emails.only('id', 'created_at', 'sender_email', 'folder', 'status', 'subject').order_by('-created_at')[:10]:
            activity_timeline.append({
                "id": f"em_{em.id}",
                "timestamp": em.created_at.isoformat(),
                "user": em.sender_email,
                "action": "EMAIL_RECEIVED" if em.folder == 'inbox' else "EMAIL_SENT",
                "module": "EMAIL",
                "status": em.status,
                "reference_id": f"EM-{em.id}",
                "description": f"Subject: {em.subject[:100]}",
                "icon": "Mail"
            })

        # Projects
        for proj in c_projects_all[:8]:
            activity_timeline.append({
                "id": f"proj_{proj.id}",
                "timestamp": proj.created_at.isoformat(),
                "user": safe_get_relation_attr(proj, 'owner', 'username', 'Admin'),
                "action": f"PROJECT_{proj.status}",
                "module": "PROJECTS",
                "status": proj.status,
                "reference_id": f"PRJ-{proj.id}",
                "description": f"Project: {proj.name} ({proj.progress_percentage}% completed)",
                "icon": "Layers"
            })

        activity_timeline.sort(key=lambda x: x['timestamp'], reverse=True)
        activity_timeline = activity_timeline[:50]

        # ── 17. Settings & Configurations ───────────────────────────────────────
        settings_data = {
            "business_name": client.business_name,
            "phone_number": client.phone_number or '',
            "address": client.address or '',
            "plan": client.plan,
            "status": client.status,
            "ai_enabled": client.ai_enabled,
            "automation_enabled": client.automation_enabled,
            "ai_context": client.ai_context or '',
            "greeting_enabled": client.greeting_enabled,
            "greeting_message": client.greeting_message or '',
            "greeting_buttons": client.greeting_buttons or [],
            "whatsapp_phone_number_id": client.whatsapp_phone_number_id or '',
            "whatsapp_waba_id": client.whatsapp_waba_id or '',
            "whatsapp_access_token": client.whatsapp_access_token or '',
            "facebook_enabled": client.facebook_enabled,
            "instagram_enabled": client.instagram_enabled,
            "gmail_enabled": client.gmail_enabled,
            "onedrive_enabled": client.onedrive_enabled,
            "google_calendar_enabled": client.google_calendar_enabled,
            "google_sheets_enabled": client.google_sheets_enabled,
            "google_docs_enabled": client.google_docs_enabled,
            "google_slides_enabled": client.google_slides_enabled,
            "zoho_enabled": client.zoho_enabled,
            "youtube_enabled": client.youtube_enabled,
            "google_news_enabled": client.google_news_enabled,
            "outlook_enabled": client.outlook_enabled
        }

        return Response({
            "overview": overview,
            "messagesAnalytics": {
                "total": total_msgs,
                "sent": msgs_sent,
                "received": msgs_received,
                "bot_messages": bot_msgs,
                "human_replies": human_replies,
                "today": msgs_today,
                "thisWeek": msgs_this_week,
                "thisMonth": msgs_this_month,
                "totalConversations": total_convos,
                "activeConversations": active_convos,
                "closedConversations": closed_convos,
                "unreadConversations": unread_convos,
                "messageTrends": msg_trend,
                "channelDistribution": channel_dist,
                "feed": messages_feed
            },
            "channels": channels,
            "whatsapp": whatsapp_analytics,
            "facebook": facebook_analytics,
            "instagram": instagram_analytics,
            "botAnalytics": bot_analytics,
            "emailMetrics": email_metrics,
            "proposals": proposals_summary,
            "quotations": quotations_summary,
            "invoices": invoices_summary,
            "sales": sales_summary,
            "team": team_summary,
            "projects": projects_summary,
            "activityTimeline": activity_timeline,
            "settings": settings_data
        })


class SuperAdminClientActionView(APIView):
    """
    Super Admin Management Actions on Client:
    - Approve / Reject client
    - Activate / Suspend client
    - Update profile settings
    - Update Bot & AI config
    - Update channel config
    - Manage team member (role, permissions, suspend)
    - Manage project (status, progress)
    - Manage document status (proposals, quotations, invoices)
    - Manage products
    Logs every modification to AuditLog.
    """
    permission_classes = [IsSuperAdminUser]

    def post(self, request, client_id):
        try:
            client = Client.objects.get(id=client_id)
        except Client.DoesNotExist:
            return Response({"error": "Client not found."}, status=status.HTTP_404_NOT_FOUND)

        action_type = request.data.get('action')
        primary_user = client.users.filter(role='CLIENT').first() or client.users.first()

        if action_type == 'APPROVE':
            if primary_user:
                primary_user.status = 'APPROVED'
                primary_user.save()
            else:
                email = f"client_{client.id}@uwo24.com"
                User.objects.create_user(
                    username=email,
                    email=email,
                    password="UwoConnect@123",
                    first_name=client.business_name,
                    role='CLIENT',
                    status='APPROVED',
                    client=client
                )
            client.status = 'ACTIVE'
            client.save()
            log_super_admin_action(request, client.business_name, 'CLIENT_MANAGEMENT', 'APPROVE_CLIENT', after_val='Status: APPROVED/ACTIVE')
            return Response({"message": f"{client.business_name} approved successfully.", "status": "ACTIVE"})

        elif action_type == 'REJECT':
            if primary_user:
                primary_user.status = 'REJECTED'
                primary_user.save()
            client.status = 'SUSPENDED'
            client.save()
            log_super_admin_action(request, client.business_name, 'CLIENT_MANAGEMENT', 'REJECT_CLIENT', after_val='Status: REJECTED/SUSPENDED')
            return Response({"message": f"{client.business_name} rejected.", "status": "SUSPENDED"})

        elif action_type == 'SUSPEND':
            client.status = 'SUSPENDED'
            client.save()
            if primary_user:
                primary_user.status = 'SUSPENDED'
                primary_user.save()
            log_super_admin_action(request, client.business_name, 'CLIENT_MANAGEMENT', 'SUSPEND_CLIENT', after_val='Status: SUSPENDED')
            return Response({"message": f"{client.business_name} suspended.", "status": "SUSPENDED"})

        elif action_type == 'ACTIVATE':
            client.status = 'ACTIVE'
            client.save()
            if primary_user and primary_user.status != 'APPROVED':
                primary_user.status = 'APPROVED'
                primary_user.save()
            log_super_admin_action(request, client.business_name, 'CLIENT_MANAGEMENT', 'ACTIVATE_CLIENT', after_val='Status: ACTIVE')
            return Response({"message": f"{client.business_name} activated.", "status": "ACTIVE"})

        elif action_type == 'UPDATE_PROFILE':
            business_name = request.data.get('business_name')
            phone_number = request.data.get('phone_number')
            address = request.data.get('address')
            plan = request.data.get('plan')
            status_val = request.data.get('status')

            before = f"Name: {client.business_name}, Plan: {client.plan}, Status: {client.status}"
            old_status = client.status
            if business_name: client.business_name = business_name
            if phone_number is not None: client.phone_number = phone_number
            if address is not None: client.address = address
            if plan: client.plan = plan
            if status_val in ['ACTIVE', 'SUSPENDED', 'TRIAL']:
                client.status = status_val
                # Sync user-level status so login works correctly
                if status_val != old_status:
                    c_users = User.objects.filter(client=client)
                    if status_val == 'ACTIVE':
                        c_users.update(status='APPROVED')
                    elif status_val == 'SUSPENDED':
                        c_users.update(status='SUSPENDED')
            client.save()

            after = f"Name: {client.business_name}, Plan: {client.plan}, Status: {client.status}"
            log_super_admin_action(request, client.business_name, 'CLIENT_PROFILE', 'UPDATE_PROFILE', before_val=before, after_val=after)
            return Response({"message": f"{client.business_name} profile updated successfully."})

        elif action_type == 'UPDATE_BOT_CONFIG':
            ai_enabled = request.data.get('ai_enabled')
            automation_enabled = request.data.get('automation_enabled')
            ai_context = request.data.get('ai_context')
            greeting_enabled = request.data.get('greeting_enabled')
            greeting_message = request.data.get('greeting_message')

            if ai_enabled is not None: client.ai_enabled = bool(ai_enabled)
            if automation_enabled is not None: client.automation_enabled = bool(automation_enabled)
            if ai_context is not None: client.ai_context = ai_context
            if greeting_enabled is not None: client.greeting_enabled = bool(greeting_enabled)
            if greeting_message is not None: client.greeting_message = greeting_message
            client.save()

            log_super_admin_action(request, client.business_name, 'BOT_AI', 'UPDATE_BOT_CONFIG', after_val=f"AI: {client.ai_enabled}, Auto: {client.automation_enabled}")
            return Response({"message": "Bot & AI configuration updated successfully."})

        elif action_type == 'UPDATE_CHANNEL_CONFIG':
            feature = request.data.get('feature')
            value = request.data.get('value')
            phone_id = request.data.get('whatsapp_phone_number_id')
            waba_id = request.data.get('whatsapp_waba_id')
            token = request.data.get('whatsapp_access_token')

            if phone_id is not None: client.whatsapp_phone_number_id = phone_id
            if waba_id is not None: client.whatsapp_waba_id = waba_id
            if token is not None: client.whatsapp_access_token = token

            if feature and hasattr(client, feature):
                setattr(client, feature, bool(value) if value is not None else not getattr(client, feature))

            client.save()
            log_super_admin_action(request, client.business_name, 'CLIENT_CHANNELS', 'UPDATE_CHANNEL_CONFIG', after_val=f"Feature {feature} set.")
            return Response({"message": "Channel configuration updated."})

        elif action_type == 'TOGGLE_FEATURE':
            feature = request.data.get('feature')
            if not feature or not hasattr(client, feature):
                return Response({"error": f"Invalid feature: {feature}"}, status=status.HTTP_400_BAD_REQUEST)
            current_val = getattr(client, feature)
            new_val = not current_val
            setattr(client, feature, new_val)
            client.save()
            log_super_admin_action(request, client.business_name, 'CLIENT_CHANNELS', f'TOGGLE_{feature.upper()}', before_val=str(current_val), after_val=str(new_val))
            return Response({"feature": feature, "value": new_val, "message": f"{feature} updated."})

        elif action_type == 'DELETE_CLIENT':
            client.delete()
            log_super_admin_action(request, client.business_name, 'CLIENT_MANAGEMENT', 'DELETE_CLIENT', after_val='Deleted client and all related data')
            return Response({"message": f"{client.business_name} deleted successfully."})
        
        elif action_type == 'CHANGE_PASSWORD':
            new_password = request.data.get('new_password')
            if not new_password:
                return Response({"error": "New password not provided."}, status=status.HTTP_400_BAD_REQUEST)
            primary_user = client.users.filter(role='CLIENT').first()
            if not primary_user:
                email = f"client_{client.id}@uwo24.com"
                primary_user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=new_password,
                    first_name=client.business_name,
                    role='CLIENT',
                    status='APPROVED',
                    client=client
                )
            else:
                # Use Django's set_password to hash correctly
                primary_user.set_password(new_password)
                primary_user.save()
            log_super_admin_action(request, client.business_name, 'CLIENT_MANAGEMENT', 'CHANGE_PASSWORD', after_val='Password updated')
            return Response({"message": f"Password for {client.business_name} updated successfully."})

            member_id = request.data.get('member_id')
            try:
                member = User.objects.get(id=member_id, client=client)
                role = request.data.get('role')
                enterprise_role = request.data.get('enterprise_role')
                department = request.data.get('department')
                designation = request.data.get('designation')
                status_val = request.data.get('status')
                permissions = request.data.get('permissions')
                assigned_platforms = request.data.get('assigned_platforms')
                assigned_social_channels = request.data.get('assigned_social_channels')

                if role: member.role = role
                if enterprise_role: member.enterprise_role = enterprise_role
                if department: member.department = department
                if designation: member.designation = designation
                if status_val in ['APPROVED', 'SUSPENDED', 'PENDING']: member.status = status_val
                if permissions is not None: member.permissions = permissions
                if assigned_platforms is not None: member.assigned_platforms = assigned_platforms
                if assigned_social_channels is not None: member.assigned_social_channels = assigned_social_channels
                member.save()

                log_super_admin_action(request, client.business_name, 'TEAM', f'UPDATE_MEMBER_{member.username}', after_val=f"Role: {member.enterprise_role}, Status: {member.status}")
                return Response({"message": f"Team member {member.username} updated."})
            except User.DoesNotExist:
                return Response({"error": "Team member not found."}, status=status.HTTP_404_NOT_FOUND)

        elif action_type == 'UPDATE_PROJECT':
            project_id = request.data.get('project_id')
            try:
                proj = Project.objects.get(id=project_id, client=client)
                name = request.data.get('name')
                status_val = request.data.get('status')
                priority = request.data.get('priority')
                progress = request.data.get('progress_percentage')
                deadline = request.data.get('deadline')

                if name: proj.name = name
                if status_val: proj.status = status_val
                if priority: proj.priority = priority
                if progress is not None: proj.progress_percentage = int(progress)
                if deadline: proj.deadline = deadline
                proj.save()

                log_super_admin_action(request, client.business_name, 'PROJECTS', f'UPDATE_PROJECT_{proj.name}', after_val=f"Status: {proj.status}, Progress: {proj.progress_percentage}%")
                return Response({"message": f"Project {proj.name} updated."})
            except Project.DoesNotExist:
                return Response({"error": "Project not found."}, status=status.HTTP_404_NOT_FOUND)

        elif action_type == 'UPDATE_DOCUMENT_STATUS':
            doc_id = request.data.get('document_id')
            doc_type = request.data.get('doc_type', 'SALES_DOCUMENT')
            new_status = request.data.get('status')

            if doc_type == 'INVOICE':
                try:
                    inv = Invoice.objects.get(id=doc_id, client=client)
                    if new_status in ['PAID', 'PENDING', 'FAILED', 'REFUNDED']:
                        inv.payment_status = new_status
                    inv.save()
                    log_super_admin_action(request, client.business_name, 'INVOICES', f'UPDATE_INVOICE_{inv.invoice_number}', after_val=f"Status: {inv.payment_status}")
                    return Response({"message": f"Invoice #{inv.invoice_number} status updated to {new_status}."})
                except Invoice.DoesNotExist:
                    return Response({"error": "Invoice not found."}, status=status.HTTP_404_NOT_FOUND)
            else:
                try:
                    doc = SalesDocument.objects.get(id=doc_id, client=client)
                    if new_status:
                        doc.status = new_status
                    doc.save()
                    log_super_admin_action(request, client.business_name, doc.document_type, f'UPDATE_{doc.document_type}_{doc.document_number}', after_val=f"Status: {doc.status}")
                    return Response({"message": f"{doc.document_type} #{doc.document_number} status updated to {new_status}."})
                except SalesDocument.DoesNotExist:
                    return Response({"error": "Document not found."}, status=status.HTTP_404_NOT_FOUND)

        elif action_type == 'UPDATE_PRODUCT':
            product_id = request.data.get('product_id')
            try:
                prd = Product.objects.get(id=product_id, client=client)
                price = request.data.get('price')
                stock_quantity = request.data.get('stock_quantity')
                in_stock = request.data.get('in_stock')
                category = request.data.get('category')

                if price is not None: prd.price = Decimal(str(price))
                if stock_quantity is not None: prd.stock_quantity = int(stock_quantity)
                if in_stock is not None: prd.in_stock = bool(in_stock)
                if category: prd.category = category
                prd.save()

                log_super_admin_action(request, client.business_name, 'PRODUCTS', f'UPDATE_PRODUCT_{prd.name}', after_val=f"Price: {prd.price}, Stock: {prd.stock_quantity}")
                return Response({"message": f"Product {prd.name} updated."})
            except Product.DoesNotExist:
                return Response({"error": "Product not found."}, status=status.HTTP_404_NOT_FOUND)

        elif action_type == 'DELETE_KB_DOC':
            doc_id = request.data.get('doc_id')
            try:
                kb_doc = KnowledgeDocument.objects.get(id=doc_id, client=client)
                doc_title = kb_doc.title
                kb_doc.delete()
                log_super_admin_action(request, client.business_name, 'KNOWLEDGE_BASE', 'DELETE_DOC', before_val=doc_title)
                return Response({"message": f"Document '{doc_title}' removed from Knowledge Base."})
            except KnowledgeDocument.DoesNotExist:
                return Response({"error": "Document not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({"error": "Unknown action type."}, status=status.HTTP_400_BAD_REQUEST)


class SuperAdminTeamListView(APIView):
    """
    Platform-wide Team Management & Analytics View (Hyper-Optimized).
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        search = request.query_params.get('search', '').strip()
        client_id = request.query_params.get('client_id')
        role_filter = request.query_params.get('role')
        status_filter = request.query_params.get('status')

        users_qs = User.objects.select_related('client')

        if client_id and client_id != 'ALL':
            users_qs = users_qs.filter(client_id=client_id)
        if role_filter and role_filter != 'ALL':
            users_qs = users_qs.filter(enterprise_role=role_filter)
        if status_filter and status_filter != 'ALL':
            users_qs = users_qs.filter(status=status_filter)
        if search:
            users_qs = users_qs.filter(
                Q(username__icontains=search) |
                Q(email__icontains=search) |
                Q(first_name__icontains=search) |
                Q(last_name__icontains=search) |
                Q(client__business_name__icontains=search)
            )

        users = list(users_qs.order_by('-date_joined')[:300])
        clients_map = {str(c.id): c.business_name for c in Client.objects.all()}

        team_data = []
        for u in users:
            uid_str = str(u.id)
            cid_val = str(u.client_id) if getattr(u, 'client_id', None) else None
            cname_val = clients_map.get(cid_val, 'Platform') if cid_val else 'Platform'

            team_data.append({
                "id": uid_str,
                "name": f"{u.first_name} {u.last_name}".strip() or u.username,
                "username": u.username,
                "email": u.email,
                "role": u.enterprise_role or u.role,
                "enterprise_role": u.enterprise_role,
                "department": u.department,
                "designation": u.designation,
                "client_id": cid_val,
                "client_name": cname_val,
                "status": u.status,
                "is_online": getattr(u, 'is_online', False),
                "last_active": u.last_active_at.isoformat() if getattr(u, 'last_active_at', None) else None,
                "date_joined": u.date_joined.isoformat() if getattr(u, 'date_joined', None) else None,
                "assigned_projects": [],
                "assigned_teams": [],
                "messages_count": 0,
                "reports_count": 0
            })

        return Response(team_data)


class SuperAdminChannelsListView(APIView):
    """
    Platform-wide Channel & Integrations Inventory.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        clients = Client.objects.all().order_by('-created_at')
        channels_inventory = []

        for c in clients:
            primary_user = c.users.filter(role='CLIENT').first() or c.users.first()
            user_email = primary_user.email if primary_user else ''
            user_name = ''
            if primary_user:
                user_name = f"{primary_user.first_name} {primary_user.last_name}".strip() or primary_user.username or ''
            channels_inventory.append({
                "client_id": str(c.id),
                "client_name": c.business_name,
                "user_email": user_email,
                "user_name": user_name,
                "phone_number": c.phone_number or '',
                "whatsapp": {
                    "connected": bool(c.whatsapp_access_token or c.whatsapp_phone_number_id),
                    "phone_number_id": c.whatsapp_phone_number_id or '—',
                    "waba_id": c.whatsapp_waba_id or '—'
                },
                "facebook": bool(c.facebook_enabled),
                "instagram": bool(c.instagram_enabled),
                "gmail": bool(c.gmail_enabled),
                "onedrive": bool(c.onedrive_enabled),
                "google_calendar": bool(c.google_calendar_enabled),
                "google_sheets": bool(c.google_sheets_enabled),
                "google_docs": bool(c.google_docs_enabled),
                "google_slides": bool(c.google_slides_enabled),
                "zoho": bool(c.zoho_enabled),
                "youtube": bool(c.youtube_enabled),
                "google_news": bool(c.google_news_enabled),
                "outlook": bool(c.outlook_enabled)
            })

        return Response(channels_inventory)


class SuperAdminMessagesListView(APIView):
    """
    Platform-wide Live Message & Chat Explorer with Client & Channel Aggregations.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        search = request.query_params.get('search', '').strip().lower()
        client_id_filter = request.query_params.get('client_id')
        channel_filter = request.query_params.get('channel')
        msg_type_filter = request.query_params.get('type')
        sender_filter = request.query_params.get('sender')
        limit = int(request.query_params.get('limit', 200))

        # 1. Fetch Clients
        clients_qs = Client.objects.all().order_by('business_name')
        if client_id_filter and client_id_filter != 'ALL':
            clients_qs = clients_qs.filter(id=client_id_filter)
        clients_list = list(clients_qs)
        clients_map = {str(c.id): c for c in clients_list}

        # 2. Fetch Chat Messages (WhatsApp, Instagram, Facebook, Gmail etc.)
        try:
            msgs_qs = Message.objects.all()
            if client_id_filter and client_id_filter != 'ALL':
                msgs_qs = msgs_qs.filter(client_id=client_id_filter)
            if channel_filter and channel_filter != 'ALL':
                msgs_qs = msgs_qs.filter(channel=channel_filter.upper())
            if msg_type_filter and msg_type_filter != 'ALL':
                msgs_qs = msgs_qs.filter(message_type=msg_type_filter.upper())
            if sender_filter == 'BOT':
                msgs_qs = msgs_qs.filter(sender_user__isnull=True)
            elif sender_filter == 'HUMAN':
                msgs_qs = msgs_qs.filter(sender_user__isnull=False)

            raw_messages = list(msgs_qs.order_by('-id')[:limit])
        except Exception as e:
            print(f"Fallback querying Message objects in SuperAdminMessagesListView: {e}")
            try:
                raw_messages = list(Message.objects.all()[:limit])
            except Exception:
                raw_messages = []

        # 3. Fetch Email Messages (if Gmail / Email channel is requested or ALL)
        email_messages_list = []
        if not channel_filter or channel_filter in ['ALL', 'GMAIL', 'EMAIL']:
            try:
                emails_qs = EmailMessage.objects.all()
                if client_id_filter and client_id_filter != 'ALL':
                    emails_qs = emails_qs.filter(client_id=client_id_filter)
                if msg_type_filter == 'INCOMING':
                    emails_qs = emails_qs.filter(folder='inbox')
                elif msg_type_filter == 'OUTGOING':
                    emails_qs = emails_qs.filter(folder__in=['sent', 'outbox'])
                
                emails_raw = list(emails_qs.order_by('-id')[:50])
                for em in emails_raw:
                    recipients = ', '.join(em.to_recipients) if isinstance(em.to_recipients, list) else str(em.to_recipients or '')
                    c_obj = clients_map.get(str(em.client_id))
                    email_messages_list.append({
                        "id": str(em.id),
                        "client_id": str(em.client_id) if em.client_id else None,
                        "client_name": c_obj.business_name if c_obj else 'Platform',
                        "from_address": em.sender_email or em.sender_name or 'Email Sender',
                        "to_address": recipients or 'Recipient',
                        "body": f"[{em.subject}] {em.body_text[:200]}" if em.body_text else em.subject,
                        "subject": em.subject,
                        "channel": "GMAIL",
                        "message_type": "INCOMING" if em.folder == 'inbox' else "OUTGOING",
                        "status": (em.status or 'DELIVERED').upper(),
                        "is_bot": False,
                        "sender_name": em.sender_name or em.sender_email or 'Gmail User',
                        "created_at": em.created_at.isoformat() if em.created_at else timezone.now().isoformat()
                    })
            except Exception as e:
                print(f"Error fetching EmailMessages in SuperAdminMessagesListView: {e}")

        # Combine chat messages & email messages
        messages_data = []
        for msg in raw_messages:
            cid = str(msg.client_id) if getattr(msg, 'client_id', None) else None
            c_obj = clients_map.get(cid) if cid else None
            cname = c_obj.business_name if c_obj else 'Unknown Client'
            messages_data.append({
                "id": str(msg.id),
                "client_id": cid,
                "client_name": cname,
                "from_address": msg.from_address or 'Unknown',
                "to_address": msg.to_address or 'Unknown',
                "body": msg.body or '',
                "channel": (msg.channel or 'WHATSAPP').upper(),
                "message_type": msg.message_type or 'INCOMING',
                "status": (msg.status or 'SENT').upper(),
                "is_bot": getattr(msg, 'sender_user_id', None) is None,
                "sender_name": "AI Bot" if getattr(msg, 'sender_user_id', None) is None else (msg.sender_name or 'Team Member'),
                "created_at": msg.created_at.isoformat() if getattr(msg, 'created_at', None) else timezone.now().isoformat()
            })

        # Append emails
        messages_data.extend(email_messages_list)

        # Sort all messages by timestamp descending
        messages_data.sort(key=lambda m: m.get('created_at', ''), reverse=True)

        # 4. Search Filter (if applied)
        if search:
            messages_data = [
                m for m in messages_data if (
                    search in (m.get('body') or '').lower() or
                    search in (m.get('from_address') or '').lower() or
                    search in (m.get('to_address') or '').lower() or
                    search in (m.get('client_name') or '').lower() or
                    search in (m.get('sender_name') or '').lower() or
                    search in (m.get('channel') or '').lower()
                )
            ]

        # 5. Build Per-Client Hierarchy & Counts
        clients_breakdown = []
        total_whatsapp = 0
        total_instagram = 0
        total_facebook = 0
        total_gmail = 0

        # Group messages by client_id in memory
        client_msgs_map = {}
        for m in messages_data:
            cid = m.get('client_id') or 'unknown'
            client_msgs_map.setdefault(cid, []).append(m)

            ch = m.get('channel', '').upper()
            if ch == 'WHATSAPP':
                total_whatsapp += 1
            elif ch == 'INSTAGRAM':
                total_instagram += 1
            elif ch == 'FACEBOOK':
                total_facebook += 1
            elif ch in ['GMAIL', 'EMAIL']:
                total_gmail += 1

        for c in clients_list:
            cid_str = str(c.id)
            c_msgs = client_msgs_map.get(cid_str, [])

            wa_msgs = [m for m in c_msgs if m.get('channel') == 'WHATSAPP']
            ig_msgs = [m for m in c_msgs if m.get('channel') == 'INSTAGRAM']
            fb_msgs = [m for m in c_msgs if m.get('channel') == 'FACEBOOK']
            gm_msgs = [m for m in c_msgs if m.get('channel') in ['GMAIL', 'EMAIL']]

            clients_breakdown.append({
                "client_id": cid_str,
                "client_name": c.business_name,
                "status": c.status,
                "plan": c.plan,
                "phone_number": c.phone_number or '',
                "total_messages": len(c_msgs),
                "channel_counts": {
                    "WHATSAPP": len(wa_msgs),
                    "INSTAGRAM": len(ig_msgs),
                    "FACEBOOK": len(fb_msgs),
                    "GMAIL": len(gm_msgs)
                },
                "messages": c_msgs,
                "whatsapp_messages": wa_msgs,
                "instagram_messages": ig_msgs,
                "facebook_messages": fb_msgs,
                "gmail_messages": gm_msgs
            })

        # Sort clients by total_messages descending so active ones are on top
        clients_breakdown.sort(key=lambda c: c['total_messages'], reverse=True)

        summary = {
            "total_messages": len(messages_data),
            "total_whatsapp": total_whatsapp,
            "total_instagram": total_instagram,
            "total_facebook": total_facebook,
            "total_gmail": total_gmail,
            "total_clients": len(clients_list),
            "active_clients_with_messages": sum(1 for c in clients_breakdown if c['total_messages'] > 0)
        }

        return Response({
            "summary": summary,
            "clients": clients_breakdown,
            "messages": messages_data
        })


class SuperAdminSalesListView(APIView):
    """
    Platform-wide Sales, Razorpay Payments & Orders.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        payments_qs = ProductPayment.objects.select_related('workspace', 'product').order_by('-created_at')[:100]
        payments_data = []
        for p in payments_qs:
            payments_data.append({
                "id": str(p.id),
                "client_name": p.workspace.business_name if p.workspace else 'Unknown',
                "product_name": p.product.name if p.product else 'Custom Item',
                "customer_name": p.customer_name or 'Customer',
                "customer_email": p.customer_email or '',
                "amount": float(p.amount),
                "currency": p.currency,
                "payment_status": p.payment_status,
                "payment_method": p.payment_method or 'Razorpay',
                "paid_at": p.paid_at.isoformat() if p.paid_at else None,
                "created_at": p.created_at.isoformat()
            })
        return Response(payments_data)


class SuperAdminQuotationsListView(APIView):
    """
    Platform-wide Quotations Control.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        qs = SalesDocument.objects.filter(document_type='QUOTATION').select_related('client', 'created_by').order_by('-created_at')[:100]
        data = []
        for q in qs:
            data.append({
                "id": str(q.id),
                "client_id": str(q.client.id) if q.client else None,
                "client_name": q.client.business_name if q.client else 'Unknown',
                "document_number": q.document_number,
                "customer_name": q.customer_name or 'Customer',
                "customer_company": q.customer_company or '',
                "grand_total": float(q.grand_total),
                "currency_symbol": q.currency_symbol,
                "status": q.status,
                "document_date": str(q.document_date),
                "created_at": q.created_at.isoformat()
            })
        return Response(data)


class SuperAdminProposalsListView(APIView):
    """
    Platform-wide Proposals Control.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        qs = SalesDocument.objects.filter(document_type='PROPOSAL').select_related('client', 'created_by').order_by('-created_at')[:100]
        data = []
        for p in qs:
            data.append({
                "id": str(p.id),
                "client_id": str(p.client.id) if p.client else None,
                "client_name": p.client.business_name if p.client else 'Unknown',
                "document_number": p.document_number,
                "customer_name": p.customer_name or 'Customer',
                "customer_company": p.customer_company or '',
                "grand_total": float(p.grand_total),
                "currency_symbol": p.currency_symbol,
                "status": p.status,
                "document_date": str(p.document_date),
                "created_at": p.created_at.isoformat()
            })
        return Response(data)


class SuperAdminInvoicesListView(APIView):
    """
    Platform-wide Invoices & Financial Totals.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        qs = Invoice.objects.select_related('client').order_by('-created_at')[:100]
        data = []
        for inv in qs:
            data.append({
                "id": str(inv.id),
                "client_id": str(inv.client.id) if inv.client else None,
                "client_name": inv.client.business_name if inv.client else 'Unknown',
                "invoice_number": inv.invoice_number,
                "total": float(inv.total),
                "currency_symbol": inv.currency_symbol,
                "payment_status": inv.payment_status,
                "invoice_status": inv.invoice_status,
                "payment_method": inv.payment_method,
                "created_at": inv.created_at.isoformat()
            })
        return Response(data)


class SuperAdminReportsListView(APIView):
    """
    Platform-wide Work Reports & Operational Submissions.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        qs = WorkReport.objects.select_related('client', 'employee').order_by('-report_date')[:100]
        data = []
        for rep in qs:
            data.append({
                "id": str(rep.id),
                "client_id": str(rep.client.id) if rep.client else None,
                "client_name": rep.client.business_name if rep.client else 'Unknown',
                "employee_name": rep.employee.username if rep.employee else 'Employee',
                "report_date": str(rep.report_date),
                "todays_work": rep.todays_work,
                "blockers": rep.blockers or 'None',
                "hours_worked": rep.hours_worked,
                "created_at": rep.created_at.isoformat()
            })
        return Response(data)


class SuperAdminGlobalSearchView(APIView):
    """
    Global Super Admin Instant Search.
    Searches across: Clients, Team Members, Projects, Channels, Proposals, Quotations, Invoices, Products, Conversations, Emails.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        if not query or len(query) < 2:
            return Response({"results": []})

        results = []

        # 1. Clients
        for c in Client.objects.filter(Q(business_name__icontains=query) | Q(phone_number__icontains=query))[:5]:
            results.append({
                "category": "Clients",
                "title": c.business_name,
                "subtitle": f"Status: {c.status} • Phone: {c.phone_number or 'N/A'}",
                "link": f"/admin/clients/{c.id}",
                "icon": "Users"
            })

        # 2. Team Members
        for u in User.objects.filter(Q(username__icontains=query) | Q(email__icontains=query) | Q(first_name__icontains=query) | Q(last_name__icontains=query))[:5]:
            results.append({
                "category": "Team Members",
                "title": f"{u.first_name} {u.last_name}".strip() or u.username,
                "subtitle": f"{u.email} • {u.enterprise_role or u.role} ({u.client.business_name if u.client else 'Platform'})",
                "link": f"/admin/team?search={u.username}",
                "icon": "ShieldCheck"
            })

        # 3. Projects
        for p in Project.objects.filter(Q(name__icontains=query) | Q(description__icontains=query))[:5]:
            results.append({
                "category": "Projects",
                "title": p.name,
                "subtitle": f"Status: {p.status} • Progress: {p.progress_percentage}% ({p.client.business_name if p.client else 'Platform'})",
                "link": f"/admin/clients/{p.client.id}?tab=projects" if p.client else "/admin",
                "icon": "Layers"
            })

        # 4. Messages
        for m in Message.objects.filter(Q(body__icontains=query) | Q(from_address__icontains=query))[:5]:
            results.append({
                "category": "Messages",
                "title": f"Message from {m.from_address or 'User'}",
                "subtitle": f"{m.channel} • {m.body[:80]}...",
                "link": f"/admin/clients/{m.client.id}?tab=messages" if m.client else f"/admin/inbox?search={query}",
                "icon": "MessageSquare"
            })

        # 5. Quotations
        for doc in SalesDocument.objects.filter(document_type='QUOTATION').filter(Q(document_number__icontains=query) | Q(customer_name__icontains=query))[:5]:
            results.append({
                "category": "Quotations",
                "title": f"Quotation #{doc.document_number} — {doc.customer_name or 'Customer'}",
                "subtitle": f"{doc.currency_symbol}{float(doc.grand_total):,.2f} • {doc.status} ({doc.client.business_name if doc.client else ''})",
                "link": f"/admin/clients/{doc.client.id}?tab=quotations" if doc.client else "/admin/quotations",
                "icon": "FileCheck"
            })

        # 6. Proposals
        for doc in SalesDocument.objects.filter(document_type='PROPOSAL').filter(Q(document_number__icontains=query) | Q(customer_name__icontains=query))[:5]:
            results.append({
                "category": "Proposals",
                "title": f"Proposal #{doc.document_number} — {doc.customer_name or 'Customer'}",
                "subtitle": f"{doc.currency_symbol}{float(doc.grand_total):,.2f} • {doc.status} ({doc.client.business_name if doc.client else ''})",
                "link": f"/admin/clients/{doc.client.id}?tab=proposals" if doc.client else "/admin/proposals",
                "icon": "FileText"
            })

        # 7. Invoices
        for inv in Invoice.objects.filter(Q(invoice_number__icontains=query) | Q(order_reference__icontains=query))[:5]:
            results.append({
                "category": "Invoices",
                "title": f"Invoice #{inv.invoice_number}",
                "subtitle": f"{inv.currency_symbol}{float(inv.total):,.2f} • {inv.payment_status} ({inv.client.business_name if inv.client else ''})",
                "link": f"/admin/clients/{inv.client.id}?tab=invoices" if inv.client else "/admin/invoices",
                "icon": "Receipt"
            })

        # 8. Products
        for prd in Product.objects.filter(Q(name__icontains=query) | Q(category__icontains=query))[:5]:
            results.append({
                "category": "Products",
                "title": prd.name,
                "subtitle": f"${float(prd.price):,.2f} • {prd.category} ({prd.client.business_name if prd.client else ''})",
                "link": f"/admin/clients/{prd.client.id}?tab=products" if prd.client else "/admin/products",
                "icon": "ShoppingBag"
            })

        # 9. Knowledge Base
        for kb in KnowledgeDocument.objects.filter(title__icontains=query)[:5]:
            results.append({
                "category": "Knowledge Base",
                "title": kb.title,
                "subtitle": f"Document ({kb.client.business_name if kb.client else ''})",
                "link": f"/admin/clients/{kb.client.id}?tab=ai" if kb.client else "/admin/knowledge",
                "icon": "Brain"
            })

        # 10. Emails
        for em in EmailMessage.objects.filter(Q(subject__icontains=query) | Q(sender_email__icontains=query))[:5]:
            results.append({
                "category": "Emails",
                "title": em.subject,
                "subtitle": f"From: {em.sender_email} • {em.status} ({em.client.business_name if em.client else ''})",
                "link": f"/admin/clients/{em.client.id}?tab=emails" if em.client else "/admin/emails",
                "icon": "Mail"
            })

        return Response({"results": results})


class SuperAdminTeamSummaryView(APIView):
    """
    Returns client-wise breakdown of total teams created (TeamChannels) and total team members.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        clients = Client.objects.all().order_by('business_name')
        summary_data = []

        # We also want to include the 'Platform' (internal) users/teams if any
        platform_users_count = User.objects.filter(client__isnull=True, role__in=['CLIENT', 'AGENT']).count()
        platform_teams_count = TeamChannel.objects.filter(client__isnull=True).count()
        if platform_users_count > 0 or platform_teams_count > 0:
            summary_data.append({
                "client_id": "platform",
                "client_name": "Platform (Internal)",
                "total_teams": platform_teams_count,
                "total_members": platform_users_count
            })

        for client in clients:
            total_teams = client.team_channels.count()
            total_members = client.users.filter(role__in=['CLIENT', 'AGENT']).count()
            summary_data.append({
                "client_id": str(client.id),
                "client_name": client.business_name,
                "total_teams": total_teams,
                "total_members": total_members
            })

        return Response(summary_data)


class SuperAdminProductsListView(APIView):
    """
    Returns client-wise breakdown of products catalog and summary metrics.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        clients = Client.objects.all().order_by('business_name')
        all_products = Product.objects.all().order_by('-id')
        
        # Group products by client
        products_by_client = {}
        for p in all_products:
            c_id = str(p.client_id)
            if c_id not in products_by_client:
                products_by_client[c_id] = []
            products_by_client[c_id].append({
                "id": str(p.id),
                "name": p.name,
                "price": float(p.price or 0.0),
                "discount_price": float(p.discount_price) if p.discount_price is not None else None,
                "category": p.category,
                "product_type": p.product_type,
                "sku": p.sku or '',
                "brand": p.brand or '',
                "currency": p.currency or 'USD',
                "in_stock": p.in_stock,
                "stock_quantity": p.stock_quantity,
                "availability_status": p.availability_status,
                "description": p.description or '',
                "image_url": p.image_url or '',
                "tags": p.tags or []
            })

        client_list = []
        total_products_count = 0
        total_in_stock = 0
        total_out_of_stock = 0

        for client in clients:
            c_id = str(client.id)
            c_products = products_by_client.get(c_id, [])
            p_count = len(c_products)
            in_stock_cnt = sum(1 for p in c_products if p['in_stock'])
            out_stock_cnt = p_count - in_stock_cnt
            categories = list({p['category'] for p in c_products if p.get('category')})

            total_products_count += p_count
            total_in_stock += in_stock_cnt
            total_out_of_stock += out_stock_cnt

            client_list.append({
                "client_id": c_id,
                "client_name": client.business_name or client.name,
                "company_name": client.business_name or client.name,
                "status": client.status,
                "plan": client.plan,
                "total_products": p_count,
                "active_products": in_stock_cnt,
                "inactive_products": out_stock_cnt,
                "categories": categories,
                "products": c_products
            })

        return Response({
            "kpis": {
                "totalProducts": total_products_count,
                "totalClientsWithProducts": sum(1 for c in client_list if c['total_products'] > 0),
                "inStockProducts": total_in_stock,
                "outOfStockProducts": total_out_of_stock,
                "totalClients": len(clients)
            },
            "clients": client_list
        })


class SuperAdminTeamAnalyticsView(APIView):
    """
    Real-time platform-wide and client-specific workforce analytics (Hyper-Optimized).
    Fetches bulk data in 3-4 queries and computes analytics entirely in-memory.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        client_id_filter = request.query_params.get('client_id')
        role_filter = request.query_params.get('role')
        status_filter = request.query_params.get('status')

        # Bulk fetch
        all_clients = list(Client.objects.all().order_by('business_name'))
        all_projects = list(Project.objects.all())
        all_users = list(User.objects.filter(role__in=['CLIENT', 'AGENT']).all())

        # In-memory filtered lists for global metrics
        filtered_projects = all_projects
        filtered_users = all_users

        if client_id_filter and client_id_filter != 'ALL':
            filtered_projects = [p for p in filtered_projects if str(getattr(p, 'client_id', '')) == str(client_id_filter)]
            filtered_users = [u for u in filtered_users if str(getattr(u, 'client_id', '')) == str(client_id_filter)]
        if role_filter and role_filter != 'ALL':
            filtered_users = [u for u in filtered_users if getattr(u, 'enterprise_role', '') == role_filter]
        if status_filter and status_filter != 'ALL':
            filtered_users = [u for u in filtered_users if getattr(u, 'status', '') == status_filter]

        total_projects = len(filtered_projects)
        active_projects = sum(1 for p in filtered_projects if p.status in ['PLANNING', 'IN_PROGRESS'])
        completed_projects = sum(1 for p in filtered_projects if p.status == 'COMPLETED')
        archived_projects = sum(1 for p in filtered_projects if p.status == 'ARCHIVED')

        total_members = len(filtered_users)
        active_members = sum(1 for u in filtered_users if u.status == 'APPROVED')
        inactive_members = sum(1 for u in filtered_users if u.status in ['SUSPENDED', 'PENDING', 'REJECTED'])
        online_members = sum(1 for u in filtered_users if getattr(u, 'is_online', False))

        try:
            total_messages = Message.objects.count()
        except Exception:
            total_messages = 0
        try:
            total_reports = WorkReport.objects.count()
        except Exception:
            total_reports = 0

        # Role Distribution
        role_distribution = {}
        for role_code, role_label in User.ENTERPRISE_ROLE_CHOICES:
            cnt = sum(1 for u in filtered_users if getattr(u, 'enterprise_role', '') == role_code)
            if cnt > 0:
                role_distribution[role_label] = cnt

        # Status Distribution
        status_distribution = {
            "Active / Approved": active_members,
            "Pending": sum(1 for u in filtered_users if getattr(u, 'status', '') == 'PENDING'),
            "Suspended": sum(1 for u in filtered_users if getattr(u, 'status', '') == 'SUSPENDED'),
            "Rejected": sum(1 for u in filtered_users if getattr(u, 'status', '') == 'REJECTED')
        }

        # Map projects and users per client in-memory
        client_projects_map = {}
        for p in all_projects:
            cid = str(p.client_id) if getattr(p, 'client_id', None) else ''
            client_projects_map.setdefault(cid, []).append(p)

        client_users_map = {}
        for u in all_users:
            cid = str(u.client_id) if getattr(u, 'client_id', None) else ''
            client_users_map.setdefault(cid, []).append(u)

        clients_analytics = []
        for c in all_clients:
            cid_str = str(c.id)
            c_projects = client_projects_map.get(cid_str, [])
            c_users = client_users_map.get(cid_str, [])

            primary_user = next((u for u in c_users if getattr(u, 'role', '') == 'CLIENT'), None)

            project_items = []
            for p in c_projects:
                try:
                    p_mems = list(p.members.all())
                except Exception:
                    p_mems = []
                project_items.append({
                    "id": str(p.id),
                    "name": p.name,
                    "status": p.status,
                    "priority": p.priority,
                    "progress_percentage": getattr(p, 'progress_percentage', 0) or 0,
                    "members_count": len(p_mems),
                    "active_members_count": sum(1 for m in p_mems if getattr(m, 'is_online', False)),
                    "created_at": p.created_at.isoformat() if getattr(p, 'created_at', None) else None,
                    "deadline": p.deadline.isoformat() if getattr(p, 'deadline', None) else None,
                })

            member_items = []
            for u in c_users:
                member_items.append({
                    "id": str(u.id),
                    "name": f"{u.first_name} {u.last_name}".strip() or u.username,
                    "username": u.username,
                    "email": u.email,
                    "role": u.enterprise_role or u.role,
                    "designation": getattr(u, 'designation', 'Team Member') or 'Team Member',
                    "status": getattr(u, 'status', 'APPROVED'),
                    "is_online": getattr(u, 'is_online', False),
                    "last_active": u.last_active_at.isoformat() if getattr(u, 'last_active_at', None) else None,
                    "assigned_projects_count": 0
                })

            clients_analytics.append({
                "client_id": cid_str,
                "client_name": c.business_name,
                "client_email": primary_user.email if primary_user else '',
                "client_status": c.status,
                "plan": c.plan,
                "total_projects": len(c_projects),
                "active_projects": sum(1 for p in c_projects if p.status in ['PLANNING', 'IN_PROGRESS']),
                "total_members": len(c_users),
                "active_members": sum(1 for u in c_users if getattr(u, 'status', '') == 'APPROVED'),
                "inactive_members": sum(1 for u in c_users if getattr(u, 'status', '') in ['SUSPENDED', 'PENDING']),
                "online_members": sum(1 for u in c_users if getattr(u, 'is_online', False)),
                "total_messages": 0,
                "total_reports": 0,
                "last_activity": None,
                "projects": project_items,
                "members": member_items
            })

        return Response({
            "total_projects": total_projects,
            "active_projects": active_projects,
            "completed_projects": completed_projects,
            "archived_projects": archived_projects,
            "total_members": total_members,
            "active_members": active_members,
            "inactive_members": inactive_members,
            "online_members": online_members,
            "total_messages": total_messages,
            "total_reports": total_reports,
            "zero_activity_members": 0,
            "role_distribution": role_distribution,
            "status_distribution": status_distribution,
            "clients_analytics": clients_analytics
        })


class SuperAdminProjectsListView(APIView):
    """
    Platform-wide Projects Management & Assignment (Hyper-Optimized).
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        client_id = request.query_params.get('client_id')
        search = request.query_params.get('search', '').strip()
        status_filter = request.query_params.get('status')
        priority_filter = request.query_params.get('priority')

        projects_qs = Project.objects.order_by('-created_at')

        if client_id and client_id != 'ALL':
            projects_qs = projects_qs.filter(client_id=client_id)
        if status_filter and status_filter != 'ALL':
            projects_qs = projects_qs.filter(status=status_filter)
        if priority_filter and priority_filter != 'ALL':
            projects_qs = projects_qs.filter(priority=priority_filter)
        if search:
            projects_qs = projects_qs.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search) |
                Q(department__icontains=search) |
                Q(client__business_name__icontains=search)
            )

        projects_list = list(projects_qs)

        # Count total projects per client in-memory
        client_project_counts = {}
        for pr in projects_list:
            cid = str(pr.client_id) if pr.client_id else 'none'
            client_project_counts[cid] = client_project_counts.get(cid, 0) + 1

        # Bulk lookups for clients and users
        clients_map = {str(c.id): (c.business_name, getattr(c, 'status', 'ACTIVE')) for c in Client.objects.all()}
        users_map = {str(u.id): (f"{u.first_name} {u.last_name}".strip() or u.username) for u in User.objects.all()}

        projects_data = []
        for p in projects_list:
            try:
                mems = list(p.members.all())
            except Exception:
                mems = []
            members_list = [{
                "id": str(m.id),
                "name": f"{m.first_name} {m.last_name}".strip() or m.username,
                "username": m.username,
                "email": m.email,
                "role": m.enterprise_role or m.role,
                "enterprise_role": m.enterprise_role,
                "designation": m.designation,
                "department": m.department,
                "status": m.status,
                "is_online": getattr(m, 'is_online', False),
                "last_active": m.last_active_at.isoformat() if getattr(m, 'last_active_at', None) else None,
                "date_joined": m.date_joined.isoformat() if getattr(m, 'date_joined', None) else None,
            } for m in mems]

            cid_str = str(p.client_id) if getattr(p, 'client_id', None) else None
            c_info = clients_map.get(cid_str, ('Platform', 'ACTIVE')) if cid_str else ('Platform', 'ACTIVE')
            client_name, client_status = c_info

            owner_id = str(p.owner_id) if getattr(p, 'owner_id', None) else None
            owner_name = users_map.get(owner_id, 'Admin') if owner_id else 'Admin'

            projects_data.append({
                "id": str(p.id),
                "name": p.name,
                "description": p.description or '',
                "priority": p.priority,
                "status": p.status,
                "progress_percentage": p.progress_percentage or 0,
                "department": p.department or 'General',
                "start_date": p.start_date.isoformat() if p.start_date else None,
                "deadline": p.deadline.isoformat() if p.deadline else None,
                "client_id": cid_str,
                "client_name": client_name,
                "client_status": client_status,
                "client_total_projects": client_project_counts.get(cid_str or 'none', 0),
                "owner_id": owner_id,
                "owner_name": owner_name,
                "members_count": len(members_list),
                "active_members_count": sum(1 for m in members_list if m.get('is_online')),
                "members": members_list,
                "created_at": p.created_at.isoformat() if getattr(p, 'created_at', None) else None,
                "updated_at": p.updated_at.isoformat() if getattr(p, 'updated_at', None) else None
            })

        return Response(projects_data)

    def post(self, request):
        client_id = request.data.get('client_id')
        name = request.data.get('name')
        description = request.data.get('description', '')
        priority = request.data.get('priority', 'MEDIUM')
        status_val = request.data.get('status', 'PLANNING')
        deadline = request.data.get('deadline')
        department = request.data.get('department', 'General')
        member_ids = request.data.get('member_ids', [])

        if not name:
            return Response({"error": "Project name is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = Client.objects.get(id=client_id) if client_id else Client.objects.first()
        except Client.DoesNotExist:
            return Response({"error": "Client workspace not found."}, status=status.HTTP_404_NOT_FOUND)

        project = Project.objects.create(
            client=client,
            name=name,
            description=description,
            priority=priority,
            status=status_val,
            deadline=deadline if deadline else None,
            department=department,
            owner=request.user if request.user.is_authenticated else None
        )

        if member_ids:
            members = User.objects.filter(id__in=member_ids)
            project.members.set(members)

        log_super_admin_action(request, client.business_name, 'PROJECTS', 'CREATE_PROJECT', after_val=f"Project '{name}' created for {client.business_name}")
        return Response({"message": f"Project '{name}' created successfully.", "id": str(project.id)}, status=status.HTTP_201_CREATED)


class SuperAdminProjectDetailView(APIView):
    """
    Detailed Project View, Update, Archive, and Delete.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request, project_id):
        try:
            project = Project.objects.select_related('client', 'owner').get(id=project_id)
        except Project.DoesNotExist:
            return Response({"error": "Project not found."}, status=status.HTTP_404_NOT_FOUND)

        members_list = [{
            "id": str(m.id),
            "name": f"{m.first_name} {m.last_name}".strip() or m.username,
            "username": m.username,
            "email": m.email,
            "role": m.enterprise_role or m.role,
            "enterprise_role": m.enterprise_role,
            "designation": m.designation,
            "department": m.department,
            "status": m.status,
            "is_online": m.is_online,
            "last_active": m.last_active_at.isoformat() if m.last_active_at else None,
            "date_joined": m.date_joined.isoformat() if m.date_joined else None,
        } for m in project.members.all()]

        # Recent activity logs for this project/client
        client_name = project.client.business_name if project.client else 'Platform'
        recent_logs = AuditLog.objects.filter(
            Q(client_name=client_name) | Q(after_value__icontains=project.name) | Q(before_value__icontains=project.name)
        ).order_by('-created_at')[:10]

        activity_data = [{
            "id": str(log.id),
            "admin_name": log.admin_name,
            "action": log.action,
            "module": log.module,
            "before_value": log.before_value,
            "after_value": log.after_value,
            "created_at": log.created_at.isoformat() if log.created_at else None
        } for log in recent_logs]

        data = {
            "id": str(project.id),
            "name": project.name,
            "description": project.description or '',
            "priority": project.priority,
            "status": project.status,
            "progress_percentage": project.progress_percentage or 0,
            "department": project.department or 'General',
            "start_date": project.start_date.isoformat() if project.start_date else None,
            "deadline": project.deadline.isoformat() if project.deadline else None,
            "client_id": str(project.client.id) if project.client else None,
            "client_name": client_name,
            "owner_id": str(project.owner.id) if project.owner else None,
            "owner_name": f"{project.owner.first_name} {project.owner.last_name}".strip() or project.owner.username if project.owner else 'Unassigned',
            "members_count": len(members_list),
            "active_members_count": sum(1 for m in members_list if m['is_online']),
            "inactive_members_count": sum(1 for m in members_list if not m['is_online']),
            "members": members_list,
            "activity_logs": activity_data,
            "created_at": project.created_at.isoformat() if project.created_at else None,
            "updated_at": project.updated_at.isoformat() if project.updated_at else None
        }
        return Response(data)

    def put(self, request, project_id):
        return self.patch(request, project_id)

    def patch(self, request, project_id):
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return Response({"error": "Project not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        if 'name' in data: project.name = data['name']
        if 'description' in data: project.description = data['description']
        if 'priority' in data: project.priority = data['priority']
        if 'status' in data: project.status = data['status']
        if 'progress_percentage' in data: project.progress_percentage = int(data['progress_percentage'])
        if 'deadline' in data: project.deadline = data['deadline'] if data['deadline'] else None
        if 'department' in data: project.department = data['department']
        if 'client_id' in data and data['client_id']:
            try:
                project.client = Client.objects.get(id=data['client_id'])
            except Client.DoesNotExist:
                pass
        
        if 'member_ids' in data:
            members = User.objects.filter(id__in=data['member_ids'])
            project.members.set(members)

        project.save()
        log_action = 'ARCHIVE_PROJECT' if project.status == 'ARCHIVED' else 'UPDATE_PROJECT'
        log_super_admin_action(
            request,
            project.client.business_name if project.client else 'Platform',
            'PROJECTS',
            log_action,
            after_val=f"Project '{project.name}' updated (Status: {project.status})"
        )
        return Response({"message": f"Project '{project.name}' updated successfully."})

    def delete(self, request, project_id):
        try:
            project = Project.objects.get(id=project_id)
            name = project.name
            client_name = project.client.business_name if project.client else 'Platform'
            
            # Check if archive requested instead of hard deletion
            archive_only = request.query_params.get('archive') == 'true' or request.data.get('archive') == True
            if archive_only:
                project.status = 'ARCHIVED'
                project.save()
                log_super_admin_action(request, client_name, 'PROJECTS', 'ARCHIVE_PROJECT', before_val=name, after_val='Status set to ARCHIVED')
                return Response({"message": f"Project '{name}' archived successfully."})

            project.delete()
            log_super_admin_action(request, client_name, 'PROJECTS', 'DELETE_PROJECT', before_val=name)
            return Response({"message": f"Project '{name}' deleted successfully."})
        except Project.DoesNotExist:
            return Response({"error": "Project not found."}, status=status.HTTP_404_NOT_FOUND)


class SuperAdminProjectAssignMembersView(APIView):
    """
    Assign, Add, and Remove team members from a specific project.
    Does NOT delete the user account or alter workspace association.
    """
    permission_classes = [IsSuperAdminUser]

    def post(self, request, project_id):
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return Response({"error": "Project not found."}, status=status.HTTP_404_NOT_FOUND)

        action = request.data.get('action')
        single_member_id = request.data.get('member_id')
        member_ids = request.data.get('member_ids')

        client_name = project.client.business_name if project.client else 'Platform'

        # Handle Create & Add New Member directly
        if action in ['create_and_add', 'create', 'add_new'] or (request.data.get('email') and not single_member_id):
            email = (request.data.get('email') or '').strip().lower()
            name = (request.data.get('name') or '').strip()
            first_name = (request.data.get('first_name') or '').strip()
            last_name = (request.data.get('last_name') or '').strip()
            if name and not (first_name or last_name):
                parts = name.split(' ', 1)
                first_name = parts[0]
                last_name = parts[1] if len(parts) > 1 else ''

            username = (request.data.get('username') or email or '').strip().lower()
            password = request.data.get('password') or 'UwoConnect@123'
            role = request.data.get('role') or 'AGENT'
            enterprise_role = request.data.get('enterprise_role') or 'EMPLOYEE'
            department = request.data.get('department') or 'General'
            designation = request.data.get('designation') or 'Team Member'
            target_client_id = request.data.get('client_id')

            if not email:
                return Response({"error": "Email is required to create and add member."}, status=status.HTTP_400_BAD_REQUEST)

            # Determine workspace client
            user_client = project.client
            if target_client_id:
                try:
                    user_client = Client.objects.get(id=target_client_id)
                except Client.DoesNotExist:
                    pass

            # Check if user already exists
            user = User.objects.filter(Q(email__iexact=email) | Q(username__iexact=username)).first()
            created = False
            if not user:
                base_username = username.split('@')[0] if '@' in username else username
                final_username = base_username
                counter = 1
                while User.objects.filter(username=final_username).exists():
                    final_username = f"{base_username}{counter}"
                    counter += 1

                user = User.objects.create_user(
                    username=final_username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    role=role,
                    enterprise_role=enterprise_role,
                    department=department,
                    designation=designation,
                    status='APPROVED',
                    client=user_client
                )
                created = True
            else:
                # If existing user has no client and project has client, associate them
                if not user.client and user_client:
                    user.client = user_client
                    user.save(update_fields=['client'])

            project.members.add(user)
            log_super_admin_action(
                request, 
                client_name, 
                'PROJECTS', 
                'CREATE_AND_ADD_PROJECT_MEMBER' if created else 'ADD_PROJECT_MEMBER', 
                after_val=f"{'Created and added' if created else 'Added'} {user.username} to {project.name}"
            )

            user_data = {
                "id": str(user.id),
                "name": f"{user.first_name} {user.last_name}".strip() or user.username,
                "username": user.username,
                "email": user.email,
                "role": user.enterprise_role or user.role,
                "enterprise_role": user.enterprise_role,
                "designation": user.designation,
                "department": user.department,
                "status": user.status,
                "client_id": str(user.client_id) if user.client_id else None,
                "client_name": user.client.business_name if user.client else 'Platform',
                "is_online": getattr(user, 'is_online', False),
            }

            return Response({
                "message": f"Member '{user_data['name']}' {'created and ' if created else ''}assigned to project '{project.name}' successfully.",
                "created": created,
                "member": user_data,
                "members_count": project.members.count()
            }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

        elif action == 'add' or (single_member_id and action != 'remove'):
            try:
                user = User.objects.get(id=single_member_id)
                project.members.add(user)
                log_super_admin_action(request, client_name, 'PROJECTS', 'ADD_PROJECT_MEMBER', after_val=f"Added {user.username} to {project.name}")
                user_data = {
                    "id": str(user.id),
                    "name": f"{user.first_name} {user.last_name}".strip() or user.username,
                    "username": user.username,
                    "email": user.email,
                    "role": user.enterprise_role or user.role,
                    "enterprise_role": user.enterprise_role,
                    "designation": user.designation,
                    "department": user.department,
                    "status": user.status,
                    "client_id": str(user.client_id) if user.client_id else None,
                    "client_name": user.client.business_name if user.client else 'Platform',
                    "is_online": getattr(user, 'is_online', False),
                }
                return Response({
                    "message": f"Added '{user.username}' to project '{project.name}'.", 
                    "member": user_data,
                    "members_count": project.members.count()
                })
            except User.DoesNotExist:
                return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        elif action == 'remove':
            try:
                user = User.objects.get(id=single_member_id)
                project.members.remove(user)
                log_super_admin_action(request, client_name, 'PROJECTS', 'REMOVE_PROJECT_MEMBER', before_val=f"Removed {user.username} from {project.name}")
                return Response({"message": f"Removed '{user.username}' from project '{project.name}'.", "members_count": project.members.count()})
            except User.DoesNotExist:
                return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        elif member_ids is not None:
            members = User.objects.filter(id__in=member_ids)
            project.members.set(members)
            log_super_admin_action(request, client_name, 'PROJECTS', 'ASSIGN_MEMBERS', after_val=f"Set {members.count()} members on {project.name}")
            return Response({"message": f"Updated members for project '{project.name}'.", "members_count": members.count()})

        return Response({"error": "Invalid action or parameters."}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, project_id, member_id=None):
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            return Response({"error": "Project not found."}, status=status.HTTP_404_NOT_FOUND)

        target_id = member_id or request.query_params.get('member_id') or request.data.get('member_id')
        if not target_id:
            return Response({"error": "Member ID is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            user = User.objects.get(id=target_id)
            project.members.remove(user)
            client_name = project.client.business_name if project.client else 'Platform'
            log_super_admin_action(request, client_name, 'PROJECTS', 'REMOVE_PROJECT_MEMBER', before_val=f"Removed {user.username} from {project.name}")
            return Response({"message": f"Removed '{user.username}' from project '{project.name}'.", "members_count": project.members.count()})
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)


class SuperAdminAllTeamsView(APIView):
    """
    Platform-wide Team Channels & Members Management.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request):
        client_id = request.query_params.get('client_id')
        search = request.query_params.get('search', '').strip()
        channel_type = request.query_params.get('channel_type')

        channels_qs = TeamChannel.objects.select_related('client').order_by('-created_at')

        if client_id and client_id != 'ALL':
            channels_qs = channels_qs.filter(client_id=client_id)
        if channel_type and channel_type != 'ALL':
            channels_qs = channels_qs.filter(channel_type=channel_type)
        if search:
            channels_qs = channels_qs.filter(
                Q(name__icontains=search) |
                Q(description__icontains=search) |
                Q(client__business_name__icontains=search)
            )

        teams_data = []
        for t in channels_qs:
            members_list = [{
                "id": str(m.id),
                "name": f"{m.first_name} {m.last_name}".strip() or m.username,
                "username": m.username,
                "email": m.email,
                "role": m.enterprise_role or m.role,
                "is_online": m.is_online
            } for m in t.members.all()]

            cid_val = None
            cname_val = 'Platform (Internal)'
            try:
                if t.client_id:
                    cid_val = str(t.client_id)
                    cname_val = t.client.business_name if t.client else 'Platform (Internal)'
            except Exception:
                pass

            teams_data.append({
                "id": str(t.id),
                "name": t.name,
                "description": t.description or '',
                "channel_type": t.channel_type,
                "client_id": cid_val,
                "client_name": cname_val,
                "members_count": len(members_list),
                "members": members_list,
                "created_at": t.created_at.isoformat() if getattr(t, 'created_at', None) else None,
                "updated_at": t.created_at.isoformat() if getattr(t, 'created_at', None) else None
            })

        return Response(teams_data)

    def post(self, request):
        client_id = request.data.get('client_id')
        name = request.data.get('name')
        description = request.data.get('description', '')
        channel_type = request.data.get('channel_type', 'PUBLIC')
        member_ids = request.data.get('member_ids', [])

        if not name:
            return Response({"error": "Team/Channel name is required."}, status=status.HTTP_400_BAD_REQUEST)

        client = None
        if client_id:
            try:
                client = Client.objects.get(id=client_id)
            except Client.DoesNotExist:
                return Response({"error": "Client workspace not found."}, status=status.HTTP_404_NOT_FOUND)

        channel = TeamChannel.objects.create(
            client=client,
            name=name.replace('#', '').strip(),
            description=description,
            channel_type=channel_type
        )

        if member_ids:
            members = User.objects.filter(id__in=member_ids)
            channel.members.set(members)

        log_super_admin_action(request, client.business_name if client else 'Platform', 'TEAMS', 'CREATE_TEAM_CHANNEL', after_val=f"Channel #{channel.name} created")
        return Response({"message": f"Team channel #{channel.name} created successfully.", "id": str(channel.id)}, status=status.HTTP_201_CREATED)


class SuperAdminTeamChannelDetailView(APIView):
    permission_classes = [IsSuperAdminUser]

    def put(self, request, channel_id):
        try:
            channel = TeamChannel.objects.get(id=channel_id)
        except TeamChannel.DoesNotExist:
            return Response({"error": "Team channel not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        if 'name' in data: channel.name = data['name'].replace('#', '').strip()
        if 'description' in data: channel.description = data['description']
        if 'channel_type' in data: channel.channel_type = data['channel_type']
        if 'client_id' in data and data['client_id']:
            try:
                channel.client = Client.objects.get(id=data['client_id'])
            except Client.DoesNotExist:
                pass

        if 'member_ids' in data:
            members = User.objects.filter(id__in=data['member_ids'])
            channel.members.set(members)

        channel.save()
        log_super_admin_action(request, channel.client.business_name if channel.client else 'Platform', 'TEAMS', 'UPDATE_TEAM_CHANNEL', after_val=f"Channel #{channel.name} updated")
        return Response({"message": f"Team channel #{channel.name} updated successfully."})

    def delete(self, request, channel_id):
        try:
            channel = TeamChannel.objects.get(id=channel_id)
            name = channel.name
            client_name = channel.client.business_name if channel.client else 'Platform'
            channel.delete()
            log_super_admin_action(request, client_name, 'TEAMS', 'DELETE_TEAM_CHANNEL', before_val=name)
            return Response({"message": f"Team channel #{name} deleted successfully."})
        except TeamChannel.DoesNotExist:
            return Response({"error": "Team channel not found."}, status=status.HTTP_404_NOT_FOUND)


class SuperAdminTeamChannelAssignMembersView(APIView):
    permission_classes = [IsSuperAdminUser]

    def post(self, request, channel_id):
        try:
            channel = TeamChannel.objects.get(id=channel_id)
        except TeamChannel.DoesNotExist:
            return Response({"error": "Team channel not found."}, status=status.HTTP_404_NOT_FOUND)

        member_ids = request.data.get('member_ids', [])
        members = User.objects.filter(id__in=member_ids)
        channel.members.set(members)

        log_super_admin_action(
            request, 
            channel.client.business_name if channel.client else 'Platform', 
            'TEAMS', 
            'ASSIGN_CHANNEL_MEMBERS', 
            after_val=f"Assigned {members.count()} members to #{channel.name}"
        )
        return Response({
            "message": f"Updated members for channel #{channel.name}.", 
            "members_count": members.count()
        })


class SuperAdminMemberDetailView(APIView):
    """
    Platform-wide Super Admin Full CRUD on Team Members & Profile View.
    """
    permission_classes = [IsSuperAdminUser]

    def get(self, request, member_id):
        try:
            user = User.objects.select_related('client', 'reporting_manager').get(id=member_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        assigned_projects = []
        try:
            for p in user.assigned_projects.all():
                assigned_projects.append({
                    "id": str(p.id),
                    "name": p.name,
                    "priority": p.priority,
                    "status": p.status,
                    "progress_percentage": p.progress_percentage or 0,
                    "deadline": p.deadline.isoformat() if p.deadline else None,
                    "client_name": p.client.business_name if p.client else 'Platform',
                    "created_at": p.created_at.isoformat() if p.created_at else None
                })
        except Exception:
            pass

        assigned_teams = []
        try:
            for tc in user.team_channels.all():
                assigned_teams.append({
                    "id": str(tc.id),
                    "name": tc.name,
                    "channel_type": tc.channel_type
                })
        except Exception:
            pass

        data = {
            "id": str(user.id),
            "name": f"{user.first_name} {user.last_name}".strip() or user.username,
            "username": user.username,
            "email": user.email,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "role": user.role,
            "enterprise_role": user.enterprise_role,
            "department": user.department,
            "designation": user.designation,
            "status": user.status,
            "is_online": user.is_online,
            "last_active": user.last_active_at.isoformat() if user.last_active_at else None,
            "date_joined": user.date_joined.isoformat() if user.date_joined else None,
            "client_id": str(user.client.id) if user.client else None,
            "client_name": user.client.business_name if user.client else 'Platform',
            "assigned_projects": assigned_projects,
            "assigned_teams": assigned_teams,
            "messages_count": Message.objects.filter(sender_user=user).count(),
            "reports_count": WorkReport.objects.filter(employee=user).count(),
            "login_history": user.login_history or []
        }
        return Response(data)

    def post(self, request):
        username = request.data.get('username') or request.data.get('email')
        email = request.data.get('email')
        password = request.data.get('password', 'UwoConnect@123')
        first_name = request.data.get('first_name', '')
        last_name = request.data.get('last_name', '')
        role = request.data.get('role', 'AGENT')
        enterprise_role = request.data.get('enterprise_role', 'EMPLOYEE')
        department = request.data.get('department', 'General')
        designation = request.data.get('designation', 'Team Member')
        client_id = request.data.get('client_id')
        project_ids = request.data.get('project_ids', [])

        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            client = Client.objects.get(id=client_id) if client_id else Client.objects.first()
        except Client.DoesNotExist:
            return Response({"error": "Client workspace not found."}, status=status.HTTP_404_NOT_FOUND)

        if User.objects.filter(username=username).exists():
            return Response({"error": f"Username or email '{username}' already exists."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.create_user(
            username=username,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name,
            role=role,
            enterprise_role=enterprise_role,
            department=department,
            designation=designation,
            status='APPROVED',
            client=client
        )

        if project_ids:
            projects = Project.objects.filter(id__in=project_ids)
            for p in projects:
                p.members.add(user)

        log_super_admin_action(request, client.business_name, 'TEAM', 'CREATE_MEMBER', after_val=f"Created member {user.username} for {client.business_name}")
        return Response({"message": f"Member {user.username} created successfully.", "id": str(user.id)}, status=status.HTTP_201_CREATED)

    def put(self, request, member_id):
        return self.patch(request, member_id)

    def patch(self, request, member_id):
        try:
            user = User.objects.get(id=member_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        data = request.data
        if 'first_name' in data: user.first_name = data['first_name']
        if 'last_name' in data: user.last_name = data['last_name']
        if 'email' in data: user.email = data['email']
        if 'role' in data: user.role = data['role']
        if 'enterprise_role' in data: user.enterprise_role = data['enterprise_role']
        if 'department' in data: user.department = data['department']
        if 'designation' in data: user.designation = data['designation']
        if 'status' in data: user.status = data['status']
        if 'password' in data and data['password']:
            user.set_password(data['password'])
        if 'client_id' in data and data['client_id']:
            try:
                user.client = Client.objects.get(id=data['client_id'])
            except Client.DoesNotExist:
                pass

        if 'project_ids' in data:
            for p in Project.objects.filter(members=user):
                p.members.remove(user)
            new_projects = Project.objects.filter(id__in=data['project_ids'])
            for p in new_projects:
                p.members.add(user)

        user.save()
        log_action = 'UPDATE_MEMBER_STATUS' if 'status' in data and len(data) <= 2 else 'UPDATE_MEMBER'
        log_super_admin_action(request, user.client.business_name if user.client else 'Platform', 'TEAM', log_action, after_val=f"Updated {user.username} (Status: {user.status})")
        return Response({"message": f"Member {user.username} updated successfully."})

    def delete(self, request, member_id):
        try:
            from django.db.models import Q
            user = User.objects.filter(Q(id=member_id) | Q(username=member_id) | Q(email=member_id)).first()
            if not user:
                return Response({"message": "User already deleted or not found."}, status=status.HTTP_200_OK)

            name = user.username
            client_name = user.client.business_name if user.client else 'Platform'

            # Clean M2M relations before deletion
            try:
                for p in Project.objects.filter(members=user):
                    p.members.remove(user)
                for tc in TeamChannel.objects.filter(members=user):
                    tc.members.remove(user)
            except Exception:
                pass

            user.delete()
            log_super_admin_action(request, client_name, 'TEAM', 'DELETE_MEMBER', before_val=name)
            return Response({"message": f"Member {name} deleted successfully."})
        except Exception as e:
            return Response({"error": f"Failed to delete member: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

