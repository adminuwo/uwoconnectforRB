from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from django.db.models import Q
from ..models import Client

class WhiteLabelConfigView(APIView):
    """
    Public Endpoint to dynamically resolve branding assets and theme
    configuration based on the requesting domain (or client_id query param).
    Used by the frontend BrandProvider to customize UI in real-time.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        domain = request.query_params.get('domain', '').strip().lower()
        client_id = request.query_params.get('client_id', '').strip()

        client = None

        if domain:
            # Strip protocol and port if provided
            clean_domain = domain.replace('https://', '').replace('http://', '').split(':')[0]
            # Ignore standard default development / staging domains
            is_default_domain = clean_domain in (
                'localhost', '127.0.0.1', 'uwoconnect.aisa24.com',
                'uwoconnectforrf-743928421487.asia-south1.run.app',
                'uwoconnectforrf-743978421487.asia-south1.run.app'
            )
            if not is_default_domain:
                client = Client.objects.filter(
                    Q(white_label_domain__iexact=clean_domain) |
                    Q(settings__custom_domain__iexact=clean_domain)
                ).first()

        if not client and client_id:
            try:
                client = Client.objects.filter(id=client_id).first()
            except Exception:
                client = None

        if client and (client.white_label_name or client.white_label_logo or client.white_label_domain or client.company_logo_url):
            client_settings = client.settings if isinstance(client.settings, dict) else {}
            logo_url = client.white_label_logo or client.company_logo_url or "/download (3).gif"
            favicon_url = client_settings.get('favicon_url') or logo_url
            primary_color = client_settings.get('primary_color') or '#059669'
            accent_color = client_settings.get('accent_color') or '#10B981'
            support_email = client_settings.get('support_email') or client.phone_number or 'support@uwoconnect.com'
            brand_name = client.white_label_name or client.business_name or 'UwoConnect'
            tagline = client_settings.get('tagline') or 'Multi-channel automation platform'
            copyright_text = client_settings.get('copyright_text') or f"© {brand_name}. All rights reserved."

            return Response({
                "is_whitelabel": True,
                "client_id": str(client.id),
                "brand_name": brand_name,
                "tagline": tagline,
                "logo_url": logo_url,
                "favicon_url": favicon_url,
                "primary_color": primary_color,
                "accent_color": accent_color,
                "support_email": support_email,
                "copyright_text": copyright_text,
                "custom_domain": client.white_label_domain or clean_domain if domain else ""
            })

        # Default platform branding
        return Response({
            "is_whitelabel": False,
            "client_id": None,
            "brand_name": "UwoConnect",
            "tagline": "Multi-channel automation platform",
            "logo_url": "/download (3).gif",
            "favicon_url": "/download (3).gif",
            "primary_color": "#059669",
            "accent_color": "#10B981",
            "support_email": "support@uwoconnect.com",
            "copyright_text": "© UwoConnect Automation. All rights reserved.",
            "custom_domain": ""
        })


from rest_framework.permissions import IsAuthenticated
from ..models import PaymentOrder

class SuperAdminWhiteLabelRevenueView(APIView):
    """
    Super Admin Intelligence Endpoint:
    Provides complete breakdown of all payments and revenues collected across all White-Label Agencies
    and their sub-clients.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if getattr(request.user, 'role', '') != 'ADMIN' and getattr(request.user, 'enterprise_role', '') not in ['SUPER_ADMIN', 'ORG_ADMIN']:
            return Response({"error": "Admin authorization required."}, status=403)

        # Get all white-label agencies
        agencies = Client.objects.filter(
            Q(is_agency=True) |
            Q(white_label_domain__isnull=False, white_label_domain__gt='') |
            Q(settings__custom_domain__isnull=False, settings__custom_domain__gt='') |
            Q(plan='AGENCY')
        ).distinct()

        agency_breakdown = []
        total_revenue = 0.0
        total_sub_clients_count = 0
        all_transactions = []

        for agency in agencies:
            # Sub-clients under this agency
            sub_clients = Client.objects.filter(parent_agency=agency)
            sub_client_ids = list(sub_clients.values_list('id', flat=True))
            total_sub_clients_count += len(sub_client_ids)

            # Orders for these sub-clients or the agency
            sub_orders = PaymentOrder.objects.filter(
                Q(client_id__in=sub_client_ids) | Q(client=agency)
            ).order_by('-created_at')

            agency_revenue = 0.0
            tx_list = []
            for ord_item in sub_orders:
                is_paid = ord_item.status.upper() in ['PAID', 'SUCCESS', 'COMPLETED']
                amt = float(ord_item.amount or 0.0)
                if is_paid:
                    agency_revenue += amt
                    total_revenue += amt

                sub_u = ord_item.user or (ord_item.client.users.first() if ord_item.client.users.exists() else None)
                tx_data = {
                    "order_id": ord_item.order_id,
                    "razorpay_payment_id": ord_item.razorpay_payment_id or ord_item.razorpay_order_id or "N/A",
                    "agency_name": agency.white_label_name or agency.business_name,
                    "agency_domain": agency.white_label_domain or agency.settings.get('custom_domain', ''),
                    "sub_client_name": ord_item.client.business_name,
                    "sub_client_email": sub_u.email if sub_u else "N/A",
                    "plan": ord_item.plan,
                    "billing_cycle": ord_item.billing_cycle,
                    "amount": amt,
                    "status": ord_item.status.upper(),
                    "created_at": ord_item.created_at.strftime("%d %b %Y, %I:%M %p") if ord_item.created_at else "Recent"
                }
                tx_list.append(tx_data)
                all_transactions.append(tx_data)

            agency_breakdown.append({
                "agency_id": str(agency.id),
                "agency_name": agency.white_label_name or agency.business_name,
                "custom_domain": agency.white_label_domain or agency.settings.get('custom_domain', 'N/A'),
                "logo_url": agency.white_label_logo or agency.company_logo_url or "/download (3).gif",
                "theme_color": agency.settings.get('primary_color', '#059669'),
                "owner_name": agency.users.first().first_name if agency.users.exists() else "Agency Owner",
                "owner_email": agency.users.first().email if agency.users.exists() else "agency@uwo.com",
                "total_sub_clients": len(sub_client_ids),
                "total_revenue_generated": agency_revenue,
                "transactions_count": len(tx_list),
                "recent_transactions": tx_list[:5]
            })

        # Sort agencies by revenue generated desc
        agency_breakdown.sort(key=lambda x: x["total_revenue_generated"], reverse=True)
        all_transactions.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return Response({
            "total_white_label_revenue": total_revenue,
            "total_agencies_count": len(agencies),
            "total_sub_clients_count": total_sub_clients_count,
            "total_transactions_count": len(all_transactions),
            "agency_breakdown": agency_breakdown,
            "all_transactions": all_transactions[:50]
        })
