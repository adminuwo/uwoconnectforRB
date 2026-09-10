from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from ..models import Feature, Plan, PlanFeature, ClientFeatureOverride, PlanAuditLog, Client
from ..plan_management_serializers import (
    FeatureSerializer,
    PlanSerializer,
    PlanFeatureSerializer,
    ClientFeatureOverrideSerializer,
    PlanAuditLogSerializer,
)
from ..services.entitlement_service import EntitlementService, DEFAULT_PLANS_CONFIG

class FeatureViewSet(viewsets.ModelViewSet):
    """CRUD operations for Feature model."""
    queryset = Feature.objects.all()
    serializer_class = FeatureSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]


class PlanViewSet(viewsets.ModelViewSet):
    """CRUD operations for Plan model with flexible lookup by ObjectId, slug, or name."""
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    def get_object(self):
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_val = self.kwargs.get(lookup_url_kwarg)

        # 1. Try finding by primary key (ObjectId)
        try:
            return Plan.objects.get(pk=lookup_val)
        except Exception:
            pass

        # 2. Try finding by slug (e.g. 'starter', 'growth', 'advanced', 'enterprise')
        plan = Plan.objects.filter(slug__iexact=lookup_val).first()
        if plan:
            return plan

        # 3. Try finding by name
        plan = Plan.objects.filter(name__iexact=lookup_val).first()
        if plan:
            return plan

        # 4. Handle "plan-starter", "plan-pro", "plan-enterprise" prefixes
        clean_slug = str(lookup_val).replace('plan-', '').lower()
        if clean_slug == 'pro':
            clean_slug = 'growth'
        plan = Plan.objects.filter(slug__iexact=clean_slug).first()
        if plan:
            return plan

        return super().get_object()

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def public_plans(self, request):
        """Returns active plans with complete entitlement metadata, dynamically scoped to white-label agency if applicable."""
        brand_domain = request.query_params.get('brand_domain') or request.headers.get('X-Brand-Domain')
        target_agency = None

        # 1. Resolve from Authenticated User
        if request.user.is_authenticated and hasattr(request.user, 'client') and request.user.client:
            user_client = request.user.client
            if user_client.parent_agency:
                target_agency = user_client.parent_agency
            elif user_client.is_agency or user_client.plan == 'AGENCY' or user_client.white_label_domain:
                target_agency = user_client

        # 2. Resolve from Domain if not resolved
        if not target_agency and brand_domain:
            target_agency = Client.objects.filter(white_label_domain__iexact=brand_domain).first()

        # 3. If Agency has custom plans configured, return agency custom plans
        if target_agency and isinstance(target_agency.settings, dict) and target_agency.settings.get('custom_plans'):
            custom_plans = target_agency.settings.get('custom_plans')
            agency_plan_list = []
            for p in custom_plans:
                if p.get('active', True) is False:
                    continue
                p_slug = p.get('slug', 'starter').lower()
                m_price = p.get('price_monthly') or p.get('price') or 499
                y_price = p.get('price_yearly') or (m_price * 10)
                
                agency_plan_list.append({
                    "id": f"agency-{target_agency.id}-{p_slug}",
                    "name": p.get('name', p_slug.capitalize()),
                    "slug": p_slug,
                    "description": p.get('description', 'High performance enterprise automation plan.'),
                    "price": float(m_price),
                    "monthly_price": float(m_price),
                    "yearly_price": float(y_price),
                    "yearly_discount_percent": 15.0,
                    "currency": p.get('currency', 'INR'),
                    "billing_cycle": "Monthly",
                    "status": "ACTIVE",
                    "is_active": True,
                    "is_recommended": p_slug == 'growth',
                    "badge_text": "MOST POPULAR" if p_slug == 'growth' else ("POWER HOUSE" if p_slug == 'enterprise' else "STARTER"),
                    "accent_color": "#10B981" if p_slug == 'starter' else ("#0D9488" if p_slug == 'growth' else "#6366F1"),
                    "allowed_features": p.get('features', []),
                    "additional_benefits": p.get('features', []),
                    "feature_keys": [
                        "channel_whatsapp", "channel_instagram", "channel_email",
                        "feature_crm", "feature_quotation", "feature_autoreply"
                    ] + (["feature_workflow", "feature_invoice", "feature_broadcast"] if p_slug != 'starter' else [])
                      + (["feature_voice_call", "feature_ai_kb"] if p_slug == 'enterprise' else [])
                })
            return Response(agency_plan_list, status=status.HTTP_200_OK)

        plans = Plan.objects.filter(status='ACTIVE').order_by('display_order', 'price')
        if not plans.exists():
            # Return standard seeded defaults if database has no active plans
            return Response(list(DEFAULT_PLANS_CONFIG.values()), status=status.HTTP_200_OK)

        serializer = self.get_serializer(plans, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['put', 'patch'], url_path='monthly')
    def update_monthly(self, request, pk=None):
        """Updates independent monthly configuration for a specific plan."""
        plan = self.get_object()
        monthly_config = request.data.get('monthlyConfig') or request.data.get('monthly_config') or request.data
        metadata = plan.metadata or {}
        metadata['monthlyConfig'] = monthly_config
        if isinstance(monthly_config, dict):
            if 'price' in monthly_config and monthly_config['price'] != '':
                try:
                    plan.price = float(monthly_config['price'])
                except (ValueError, TypeError):
                    pass
                metadata['monthly_price'] = monthly_config['price']
            if 'selected_feature_keys' in monthly_config:
                metadata['monthly_feature_keys'] = monthly_config['selected_feature_keys']
        plan.metadata = metadata
        plan.save()
        serializer = self.get_serializer(plan)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['put', 'patch'], url_path='yearly')
    def update_yearly(self, request, pk=None):
        """Updates independent yearly configuration for a specific plan."""
        plan = self.get_object()
        yearly_config = request.data.get('yearlyConfig') or request.data.get('yearly_config') or request.data
        metadata = plan.metadata or {}
        metadata['yearlyConfig'] = yearly_config
        if isinstance(yearly_config, dict):
            if 'price' in yearly_config and yearly_config['price'] != '':
                try:
                    metadata['yearly_price'] = yearly_config['price']
                except (ValueError, TypeError):
                    pass
            if 'selected_feature_keys' in yearly_config:
                metadata['yearly_feature_keys'] = yearly_config['selected_feature_keys']
        plan.metadata = metadata
        plan.save()
        serializer = self.get_serializer(plan)
        return Response(serializer.data, status=status.HTTP_200_OK)


class PlanFeatureViewSet(viewsets.ModelViewSet):
    """CRUD operations for PlanFeature model linking Features to Plans."""
    queryset = PlanFeature.objects.all()
    serializer_class = PlanFeatureSerializer


class ClientFeatureOverrideViewSet(viewsets.ModelViewSet):
    """CRUD for per-client feature overrides."""
    queryset = ClientFeatureOverride.objects.all()
    serializer_class = ClientFeatureOverrideSerializer


class PlanAuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """Read-only viewset for audit logs of plan changes."""
    queryset = PlanAuditLog.objects.all().order_by('-timestamp')
    serializer_class = PlanAuditLogSerializer


class ClientEntitlementsView(APIView):
    """
    API View for Client Entitlement Status, Channel Selection, and Subscriptions.
    """
    permission_classes = [permissions.IsAuthenticated]

    def _get_client_for_request(self, request):
        user = request.user
        client_id = request.headers.get('X-Client-ID') or request.query_params.get('client_id')
        if client_id:
            try:
                return Client.objects.get(id=client_id)
            except Exception:
                pass
        if user and user.is_authenticated:
            if hasattr(user, 'client') and user.client:
                return user.client
            return Client.objects.filter(users=user).first()
        return None

    def get(self, request):
        """Get evaluated entitlements, selected channels, and limits for the logged-in client."""
        client = self._get_client_for_request(request)
        if not client:
            return Response({"error": "No client workspace associated with this user."}, status=status.HTTP_404_NOT_FOUND)

        entitlements = EntitlementService.get_full_client_entitlements(client)
        return Response(entitlements, status=status.HTTP_200_OK)

    def post(self, request):
        """Action handler for channel selection or plan subscription."""
        action_type = request.data.get('action') or request.data.get('type')
        client = self._get_client_for_request(request)
        if not client:
            return Response({"error": "No client workspace found."}, status=status.HTTP_404_NOT_FOUND)

        if action_type == 'select_channel':
            channel_key = request.data.get('channel') or request.data.get('channel_key')
            if not channel_key:
                return Response({"error": "Channel key is required."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                res = EntitlementService.select_channel_for_client(client, channel_key)
                return Response(res, status=status.HTTP_200_OK)
            except Exception as e:
                return Response({"error": str(e), "code": "UPGRADE_REQUIRED"}, status=status.HTTP_403_FORBIDDEN)

        elif action_type == 'subscribe':
            plan_slug = request.data.get('plan_slug') or request.data.get('plan')
            billing_period = request.data.get('billing_period', 'MONTHLY').upper()

            plan_obj = Plan.objects.filter(slug__iexact=plan_slug).first()
            if not plan_obj and plan_slug:
                plan_obj = Plan.objects.filter(name__iexact=plan_slug).first()

            if plan_obj:
                client.assigned_plan = plan_obj
                client.plan = plan_obj.name.upper()

            client.billing_period = billing_period
            client.save()

            entitlements = EntitlementService.get_full_client_entitlements(client)
            return Response({
                "message": f"Successfully subscribed to {client.plan} ({billing_period}).",
                "entitlements": entitlements
            }, status=status.HTTP_200_OK)

        return Response({"error": "Invalid action. Supported actions: 'select_channel', 'subscribe'."}, status=status.HTTP_400_BAD_REQUEST)
