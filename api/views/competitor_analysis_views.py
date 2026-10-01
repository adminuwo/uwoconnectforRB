import logging
from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError

from ..models import CompetitorAnalysis, Client, Product
from ..serializers import CompetitorAnalysisSerializer
from ..repositories.client_repository import ClientRepository
from ..services.competitor_analysis_service import generate_competitor_intelligence, discover_industry_competitors

logger = logging.getLogger(__name__)

def get_tenant_client(request):
    if not request.user or not request.user.is_authenticated:
        return None
    if getattr(request.user, 'role', '') == 'ADMIN':
        client_id = request.query_params.get('client_id') if hasattr(request, 'query_params') else None
        if not client_id and isinstance(getattr(request, 'data', None), dict):
            client_id = request.data.get('client_id')
        if client_id:
            try:
                return ClientRepository.get_client(id=client_id)
            except Exception:
                pass
        return getattr(request.user, 'client', None)
    return getattr(request.user, 'client', None)


def _resolve_client_business_context(client, request_data=None):
    """
    Extracts rich business context for the client: what business they own,
    their industry, their descriptions, and catalog products.
    """
    data = request_data or {}
    wp_profile = client.settings.get('whatsapp_business_profile', {}) if isinstance(getattr(client, 'settings', None), dict) else {}
    wp_desc = wp_profile.get('description', '') if isinstance(wp_profile, dict) else ''
    
    client_business_name = client.business_name or "Your Business"
    if client_business_name.strip().upper() == "EFV":
        client_business_name = "EFV Framework"

    # Products / Offerings
    product_qs = Product.objects.filter(client=client)
    product_names = list(product_qs.values_list('name', flat=True)[:10])
    client_offerings = ", ".join(product_names) if product_names else data.get('client_offerings', '').strip()

    # Grab product catalog context if available
    product_context = ""
    for p in product_qs[:3]:
        if p.description and len(p.description.strip()) > 10:
            product_context = p.description.strip()
            break
    
    # Priority: explicit request payload > client ai_context > whatsapp profile description > general settings
    client_business_description = (
        data.get('client_business_description', '').strip() or
        (client.ai_context or '').strip() or
        wp_desc.strip() or
        (client.settings.get('description', '') if isinstance(client.settings, dict) else '') or
        f"{client_business_name} commercial operations"
    )

    if product_context and product_context not in client_business_description:
        client_business_description += f"\nCatalog & Offerings Context: {product_context}"

    # Industry / Niche
    industry = (
        data.get('industry', '').strip() or
        getattr(client, 'industry', '') or
        (wp_profile.get('vertical') if isinstance(wp_profile, dict) and wp_profile.get('vertical') not in ['OTHER', 'PROF_SERVICES'] else '') or
        (client.settings.get('industry', '') if isinstance(client.settings, dict) else '') or
        ''
    )

    # Intelligent vertical inference if unset or generic
    if not industry or industry in ['General Business', 'OTHER', 'PROF_SERVICES']:
        if 'EFV' in client_business_name.upper() or any('EFV' in p.upper() or 'MINDOS' in p.upper() or 'ORIGIN CODE' in p.upper() for p in product_names):
            industry = 'Personal Development, Mindset Mastery & Book Publishing'
        elif not industry:
            industry = 'General Business'

    return client_business_name, client_business_description, industry, client_offerings



class CompetitorAnalysisViewSet(viewsets.ModelViewSet):
    serializer_class = CompetitorAnalysisSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if not client:
            return CompetitorAnalysis.objects.none()
        return CompetitorAnalysis.objects.filter(client=client).order_by('-created_at')

    def create(self, request, *args, **kwargs):
        client = get_tenant_client(request)
        if not client:
            return Response({"error": "No associated client workspace found for your account."}, status=status.HTTP_400_BAD_REQUEST)

        competitor_name = request.data.get('competitor_name', '').strip()
        if not competitor_name:
            return Response({"competitor_name": ["Competitor name is required."]}, status=status.HTTP_400_BAD_REQUEST)

        competitor_website = request.data.get('competitor_website', '').strip()
        notes = request.data.get('notes', '').strip()

        # Resolve rich client business context
        client_business_name, client_desc, industry, client_offerings = _resolve_client_business_context(client, request.data)

        # Create record
        analysis_record = CompetitorAnalysis.objects.create(
            client=client,
            created_by=request.user,
            competitor_name=competitor_name,
            competitor_website=competitor_website,
            industry=industry,
            client_business_name=client_business_name,
            notes=notes,
            status='PROCESSING'
        )

        # Trigger AI Generation with client's actual business context
        try:
            intel = generate_competitor_intelligence(
                client_business_name=client_business_name,
                industry=industry,
                competitor_name=competitor_name,
                competitor_url=competitor_website,
                notes=notes,
                client_business_description=client_desc,
                client_offerings=client_offerings
            )
            analysis_record.analysis_data = intel
            analysis_record.advantage_score = int(intel.get('advantage_score', 75))
            analysis_record.status = 'COMPLETED'
            analysis_record.save()
        except Exception as e:
            logger.exception(f"Competitor analysis generation failed: {e}")
            analysis_record.status = 'FAILED'
            analysis_record.error_message = str(e)
            analysis_record.save()

        serializer = self.get_serializer(analysis_record)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'])
    def reanalyze(self, request, pk=None):
        analysis_record = self.get_object()
        analysis_record.status = 'PROCESSING'
        analysis_record.error_message = ''
        analysis_record.save()

        client = analysis_record.client or get_tenant_client(request)
        client_business_name, client_desc, industry, client_offerings = _resolve_client_business_context(
            client,
            {'industry': analysis_record.industry}
        )

        try:
            intel = generate_competitor_intelligence(
                client_business_name=analysis_record.client_business_name or client_business_name,
                industry=analysis_record.industry or industry,
                competitor_name=analysis_record.competitor_name,
                competitor_url=analysis_record.competitor_website,
                notes=analysis_record.notes,
                client_business_description=client_desc,
                client_offerings=client_offerings
            )
            analysis_record.analysis_data = intel
            analysis_record.advantage_score = int(intel.get('advantage_score', 75))
            analysis_record.status = 'COMPLETED'
            analysis_record.save()
        except Exception as e:
            logger.exception(f"Competitor re-analysis failed: {e}")
            analysis_record.status = 'FAILED'
            analysis_record.error_message = str(e)
            analysis_record.save()

        serializer = self.get_serializer(analysis_record)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def stats(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"total_competitors": 0, "avg_advantage_score": 0, "total_gaps": 0})

        qs = CompetitorAnalysis.objects.filter(client=client, status='COMPLETED')
        total = qs.count()
        if total == 0:
            return Response({
                "total_competitors": 0,
                "avg_advantage_score": 0,
                "total_gaps": 0,
                "high_advantage_count": 0
            })

        scores = [item.advantage_score for item in qs if item.advantage_score]
        avg_score = round(sum(scores) / len(scores)) if scores else 0
        high_advantage = sum(1 for s in scores if s >= 75)

        total_gaps = 0
        for item in qs:
            gaps = item.analysis_data.get('automation_audit', {}).get('critical_gaps', [])
            total_gaps += len(gaps)

        return Response({
            "total_competitors": total,
            "avg_advantage_score": avg_score,
            "total_gaps": total_gaps,
            "high_advantage_count": high_advantage
        })

    @action(detail=False, methods=['get'])
    def discover(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"client_business_name": "Your Business", "suggestions": []})

        client_business_name, client_desc, industry, client_offerings = _resolve_client_business_context(client)
        
        # Location / address
        wp_profile = client.settings.get('whatsapp_business_profile', {}) if isinstance(getattr(client, 'settings', None), dict) else {}
        location = wp_profile.get('address', '') if isinstance(wp_profile, dict) else 'India'

        # Already analyzed competitor names for this client to prevent duplicate suggestions
        already_tracked = list(
            CompetitorAnalysis.objects.filter(client=client)
            .values_list('competitor_name', flat=True)
        )

        suggestions = discover_industry_competitors(
            client_business_name=client_business_name,
            industry=industry,
            client_business_description=client_desc,
            location=location or "India",
            already_tracked_names=already_tracked
        )

        return Response({
            "client_business_name": client_business_name,
            "industry": industry,
            "suggestions": suggestions
        }, status=status.HTTP_200_OK)

