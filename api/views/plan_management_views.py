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
    """CRUD operations for Plan model."""
    queryset = Plan.objects.all()
    serializer_class = PlanSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def public_plans(self, request):
        """Returns active plans with complete entitlement metadata for the pricing table."""
        plans = Plan.objects.filter(status='ACTIVE').order_by('display_order', 'price')
        if not plans.exists():
            # Return standard seeded defaults if database has no active plans
            return Response(list(DEFAULT_PLANS_CONFIG.values()), status=status.HTTP_200_OK)

        serializer = self.get_serializer(plans, many=True)
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
        if hasattr(user, 'client') and user.client:
            return user.client
        return Client.objects.first()

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
