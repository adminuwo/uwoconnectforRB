from rest_framework import status, views
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from ..models import User, Client
from ..serializers import ClientSerializer, UserSerializer
from ..repositories.client_repository import ClientRepository
import logging

logger = logging.getLogger(__name__)

class AgencyPermissionHelper:
    @staticmethod
    def get_agency_client(user):
        if not user or not user.is_authenticated:
            return None
        if user.role == 'ADMIN':
            return user.client # Super Admin has access
        if user.role == 'CLIENT' and user.client:
            # Check if this client is an agency
            if user.client.is_agency or user.client.plan == 'AGENCY' or bool(user.client.white_label_domain):
                return user.client
        return None


class AgencyDashboardStatsView(views.APIView):
    """
    Returns high-level KPI metrics for the White-Label Agency Owner.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        agency = AgencyPermissionHelper.get_agency_client(request.user)
        if not agency:
            return Response({"error": "Only White-Label Agency Owners have access to this portal."}, status=status.HTTP_403_FORBIDDEN)

        sub_clients_qs = Client.objects.filter(parent_agency=agency)
        total_sub_clients = sub_clients_qs.count()
        
        # Sub-client users
        sub_users_qs = User.objects.filter(client__in=sub_clients_qs)
        pending_users_count = sub_users_qs.filter(status='PENDING').count()
        approved_users_count = sub_users_qs.filter(status='APPROVED').count()

        # Check Razorpay Connection
        from ..models import RazorpayConnection
        rzp_conn = RazorpayConnection.objects.filter(client=agency).first()
        gateway_connected = bool(rzp_conn and rzp_conn.linked_key_id)
        gateway_mode = rzp_conn.mode if rzp_conn else "NOT_CONNECTED"

        return Response({
            "agency_id": str(agency.id),
            "agency_name": agency.white_label_name or agency.business_name,
            "custom_domain": agency.white_label_domain or agency.settings.get('custom_domain', ''),
            "brand_logo": agency.white_label_logo or agency.company_logo_url or '/download (3).gif',
            "theme_color": agency.settings.get('primary_color', '#059669'),
            "total_sub_clients": total_sub_clients,
            "pending_approvals": pending_users_count,
            "active_workspaces": approved_users_count,
            "gateway_connected": gateway_connected,
            "gateway_mode": gateway_mode,
            "plan": agency.plan
        })


class AgencySubClientsListView(views.APIView):
    """
    List all sub-clients under this Agency or provision a new sub-client.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        agency = AgencyPermissionHelper.get_agency_client(request.user)
        if not agency:
            return Response({"error": "Agency permission required."}, status=status.HTTP_403_FORBIDDEN)

        sub_clients = Client.objects.filter(parent_agency=agency).order_by('-created_at')
        
        results = []
        for sc in sub_clients:
            primary_user = User.objects.filter(client=sc).first()
            results.append({
                "id": str(sc.id),
                "business_name": sc.business_name,
                "email": primary_user.email if primary_user else "",
                "phone_number": sc.phone_number or (primary_user.phone_number if primary_user else ""),
                "owner_name": f"{primary_user.first_name or ''} {primary_user.last_name or ''}".strip() if primary_user else "Workspace Admin",
                "plan": sc.plan or "STARTER",
                "status": primary_user.status if primary_user else "PENDING",
                "user_id": str(primary_user.id) if primary_user else None,
                "created_at": sc.created_at.strftime("%Y-%m-%d %H:%M") if sc.created_at else "",
                "logo_url": sc.company_logo_url or sc.white_label_logo or ""
            })

        return Response(results)

    def post(self, request):
        agency = AgencyPermissionHelper.get_agency_client(request.user)
        if not agency:
            return Response({"error": "Agency permission required."}, status=status.HTTP_403_FORBIDDEN)

        business_name = request.data.get('business_name', '').strip()
        email = request.data.get('email', '').strip().lower()
        password = request.data.get('password', '').strip()
        phone_number = request.data.get('phone_number', '').strip()
        plan = request.data.get('plan', 'STARTER').upper()

        if not business_name or not email:
            return Response({"error": "Business Name and Email are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Check existing user
        if User.objects.filter(email__iexact=email).exists():
            return Response({"error": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

        # Create Client workspace scoped to parent agency
        sub_client = Client.objects.create(
            business_name=business_name,
            phone_number=phone_number,
            plan=plan,
            parent_agency=agency,
            company_logo_url=request.data.get('logo_url', ''),
            settings={
                "parent_agency_id": str(agency.id),
                "parent_brand": agency.white_label_name or agency.business_name
            }
        )

        # Create sub-client admin user (APPROVED by agency owner)
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password or 'Welcome@2026',
            first_name=request.data.get('owner_name', business_name),
            phone_number=phone_number,
            role='CLIENT',
            status='APPROVED',
            client=sub_client
        )

        return Response({
            "message": f"Sub-Client '{business_name}' registered successfully under your agency!",
            "client_id": str(sub_client.id),
            "user_id": str(user.id)
        }, status=status.HTTP_201_CREATED)


class AgencySubClientActionView(views.APIView):
    """
    Perform administrative actions on a sub-client (APPROVE, SUSPEND, REACTIVATE, CHANGE_PASSWORD).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk=None):
        agency = AgencyPermissionHelper.get_agency_client(request.user)
        if not agency:
            return Response({"error": "Agency permission required."}, status=status.HTTP_403_FORBIDDEN)

        try:
            sub_client = Client.objects.get(id=pk, parent_agency=agency)
        except Client.DoesNotExist:
            return Response({"error": "Sub-Client not found under your agency."}, status=status.HTTP_404_NOT_FOUND)

        action = request.data.get('action', '').upper()
        target_user = User.objects.filter(client=sub_client).first()

        if action == 'APPROVE':
            if target_user:
                target_user.status = 'APPROVED'
                target_user.is_active = True
                target_user.save()
            return Response({"message": f"Sub-Client '{sub_client.business_name}' approved successfully!"})

        elif action == 'SUSPEND':
            if target_user:
                target_user.status = 'SUSPENDED'
                target_user.is_active = False
                target_user.save()
            return Response({"message": f"Sub-Client '{sub_client.business_name}' suspended."})

        elif action == 'REACTIVATE':
            if target_user:
                target_user.status = 'APPROVED'
                target_user.is_active = True
                target_user.save()
            return Response({"message": f"Sub-Client '{sub_client.business_name}' reactivated."})

        elif action == 'CHANGE_PASSWORD':
            new_pass = request.data.get('new_password')
            if not new_pass or len(new_pass) < 6:
                return Response({"error": "Password must be at least 6 characters."}, status=status.HTTP_400_BAD_REQUEST)
            if target_user:
                target_user.set_password(new_pass)
                target_user.save()
            return Response({"message": f"Password updated for {sub_client.business_name}."})

        elif action == 'CHANGE_PLAN':
            new_plan = request.data.get('plan', 'STARTER').upper()
            sub_client.plan = new_plan
            sub_client.save()
            return Response({"message": f"Plan updated to {new_plan}."})

        return Response({"error": "Invalid action."}, status=status.HTTP_400_BAD_REQUEST)


DEFAULT_AGENCY_PLANS = [
    {
        "slug": "starter",
        "name": "Starter Plan",
        "base_monthly_price": 499,
        "base_yearly_price": 4999,
        "markup_monthly": 1500,
        "markup_yearly": 15000,
        "price_monthly": 1999,
        "price_yearly": 19999,
        "currency": "INR",
        "currency_symbol": "₹",
        "description": "Essential automation for single clinics & local businesses",
        "features": [
            "WhatsApp & Instagram Automation",
            "Auto Replies & Lead CRM",
            "Quotations Builder",
            "Live Multi-Agent Messages",
            "Up to 1,000 Contacts"
        ],
        "active": True
    },
    {
        "slug": "growth",
        "name": "Growth Plan",
        "base_monthly_price": 999,
        "base_yearly_price": 9999,
        "markup_monthly": 3000,
        "markup_yearly": 30000,
        "price_monthly": 3999,
        "price_yearly": 39999,
        "currency": "INR",
        "currency_symbol": "₹",
        "description": "Advanced workflows, multi-channel inbox & automated invoicing",
        "features": [
            "Everything in Starter",
            "Multi-Step Visual Workflows",
            "Gmail & Outlook Integration",
            "Invoices & Proposal Contracts",
            "Broadcast Campaigns",
            "Catalog & Payment Links"
        ],
        "active": True
    },
    {
        "slug": "enterprise",
        "name": "Enterprise Plan",
        "base_monthly_price": 2499,
        "base_yearly_price": 24999,
        "markup_monthly": 7500,
        "markup_yearly": 75000,
        "price_monthly": 9999,
        "price_yearly": 99999,
        "currency": "INR",
        "currency_symbol": "₹",
        "description": "Complete power suite with AI Knowledge Base & unlimited team",
        "features": [
            "Everything in Growth",
            "Voice & Video Calling Suite",
            "AI Knowledge Base (Trained on PDFs)",
            "Unlimited Team Members & Workspaces",
            "Google News & High-Priority Webhooks",
            "Dedicated Support Desk"
        ],
        "active": True
    }
]

class AgencyCustomPlansView(views.APIView):
    """
    Get or Update Custom Subscription Pricing & Plans configured by this White-Label Agency for their sub-clients.
    Includes Base Super-Admin Cost + Agency Markup Margin = Final Sub-Client Price.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        agency = AgencyPermissionHelper.get_agency_client(request.user)
        if not agency:
            return Response({"error": "Agency permission required."}, status=status.HTTP_403_FORBIDDEN)

        custom_plans = agency.settings.get('custom_plans')
        if not custom_plans or not isinstance(custom_plans, list):
            custom_plans = DEFAULT_AGENCY_PLANS
        else:
            # Ensure base prices are synced
            for p in custom_plans:
                matching_default = next((d for d in DEFAULT_AGENCY_PLANS if d["slug"] == p.get("slug")), None)
                if matching_default:
                    p["base_monthly_price"] = matching_default["base_monthly_price"]
                    p["base_yearly_price"] = matching_default["base_yearly_price"]
                    if "markup_monthly" not in p:
                        p["markup_monthly"] = max(0, (p.get("price_monthly", 0) - p["base_monthly_price"]))
                    if "markup_yearly" not in p:
                        p["markup_yearly"] = max(0, (p.get("price_yearly", 0) - p["base_yearly_price"]))

        return Response({
            "agency_id": str(agency.id),
            "agency_name": agency.white_label_name or agency.business_name,
            "custom_plans": custom_plans
        })

    def post(self, request):
        agency = AgencyPermissionHelper.get_agency_client(request.user)
        if not agency:
            return Response({"error": "Agency permission required."}, status=status.HTTP_403_FORBIDDEN)

        plans_data = request.data.get('custom_plans') or request.data.get('plans') or []
        if not isinstance(plans_data, list) or len(plans_data) == 0:
            return Response({"error": "Plans array is required."}, status=status.HTTP_400_BAD_REQUEST)

        # Recalculate price_monthly = base_monthly_price + markup_monthly
        for p in plans_data:
            base_m = p.get("base_monthly_price", 499)
            markup_m = p.get("markup_monthly", 0)
            p["price_monthly"] = base_m + markup_m

            base_y = p.get("base_yearly_price", 4999)
            markup_y = p.get("markup_yearly", 0)
            p["price_yearly"] = base_y + markup_y

        if not isinstance(agency.settings, dict):
            agency.settings = {}

        agency.settings['custom_plans'] = plans_data
        agency.save(update_fields=['settings'])

        return Response({
            "message": "Sub-Client Subscription Markup & Prices updated successfully!",
            "custom_plans": plans_data
        })
