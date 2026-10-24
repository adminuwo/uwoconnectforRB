from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import action
from ..models import Guide, GuideSection, GuideStep, GuideProgress
from ..serializers import (
    GuideListSerializer, GuideDetailSerializer, GuideSectionSerializer, 
    GuideStepSerializer, GuideProgressSerializer
)


class GuideViewSet(viewsets.ModelViewSet):
    """
    API endpoint for managing and viewing Interactive Learning Guides.
    """
    permission_classes = [IsAuthenticated]
    lookup_field = 'slug'

    def _ensure_guides_seeded(self):
        if not Guide.objects.filter(status='PUBLISHED').exists():
            try:
                import seed_learning_guides
                seed_learning_guides.seed_guides()
            except Exception as e:
                pass

    def get_queryset(self):
        self._ensure_guides_seeded()
        user = self.request.user
        # Admins can view all guides (including draft/archived), clients view PUBLISHED
        if user.is_staff or getattr(user, 'role', '') == 'ADMIN':
            return Guide.objects.all()
        return Guide.objects.filter(status='PUBLISHED')

    def get_serializer_class(self):
        if self.action == 'list':
            return GuideListSerializer
        return GuideDetailSerializer

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def add_section(self, request, slug=None):
        guide = self.get_object()
        title = request.data.get('title')
        if not title:
            return Response({'error': 'Title is required'}, status=status.HTTP_400_BAD_REQUEST)
        
        icon = request.data.get('icon', 'ChevronRight')
        order = request.data.get('order', guide.sections.count())
        section = GuideSection.objects.create(
            guide=guide,
            title=title,
            icon=icon,
            order=order
        )
        return Response(GuideSectionSerializer(section).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], permission_classes=[IsAuthenticated])
    def add_step(self, request, slug=None):
        guide = self.get_object()
        section_id = request.data.get('section_id')
        try:
            section = GuideSection.objects.get(id=section_id, guide=guide)
        except GuideSection.DoesNotExist:
            return Response({'error': 'Section not found'}, status=status.HTTP_404_NOT_FOUND)

        step = GuideStep.objects.create(
            section=section,
            title=request.data.get('title', ''),
            step_type=request.data.get('step_type', 'text'),
            content=request.data.get('content', ''),
            media_url=request.data.get('media_url'),
            code_snippet=request.data.get('code_snippet'),
            code_language=request.data.get('code_language', 'bash'),
            checklist_items=request.data.get('checklist_items', []),
            order=request.data.get('order', section.steps.count()),
            is_completable=request.data.get('is_completable', True)
        )
        return Response(GuideStepSerializer(step).data, status=status.HTTP_201_CREATED)


class GuideSectionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, section_id):
        try:
            section = GuideSection.objects.get(id=section_id)
        except GuideSection.DoesNotExist:
            return Response({'error': 'Section not found'}, status=status.HTTP_404_NOT_FOUND)

        section.title = request.data.get('title', section.title)
        section.icon = request.data.get('icon', section.icon)
        section.order = request.data.get('order', section.order)
        section.save()
        return Response(GuideSectionSerializer(section).data)

    def delete(self, request, section_id):
        try:
            section = GuideSection.objects.get(id=section_id)
            section.delete()
            return Response({'detail': 'Section deleted successfully'})
        except GuideSection.DoesNotExist:
            return Response({'error': 'Section not found'}, status=status.HTTP_404_NOT_FOUND)


class GuideStepDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def put(self, request, step_id):
        try:
            step = GuideStep.objects.get(id=step_id)
        except GuideStep.DoesNotExist:
            return Response({'error': 'Step not found'}, status=status.HTTP_404_NOT_FOUND)

        step.title = request.data.get('title', step.title)
        step.step_type = request.data.get('step_type', step.step_type)
        step.content = request.data.get('content', step.content)
        step.media_url = request.data.get('media_url', step.media_url)
        step.code_snippet = request.data.get('code_snippet', step.code_snippet)
        step.code_language = request.data.get('code_language', step.code_language)
        step.checklist_items = request.data.get('checklist_items', step.checklist_items)
        step.order = request.data.get('order', step.order)
        step.save()
        return Response(GuideStepSerializer(step).data)

    def delete(self, request, step_id):
        try:
            step = GuideStep.objects.get(id=step_id)
            step.delete()
            return Response({'detail': 'Step deleted successfully'})
        except GuideStep.DoesNotExist:
            return Response({'error': 'Step not found'}, status=status.HTTP_404_NOT_FOUND)


class GuideProgressView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, slug=None):
        user = request.user
        if slug:
            try:
                guide = Guide.objects.get(slug=slug)
                progress, _ = GuideProgress.objects.get_or_create(user=user, guide=guide)
                return Response(GuideProgressSerializer(progress).data)
            except Guide.DoesNotExist:
                return Response({'error': 'Guide not found'}, status=status.HTTP_404_NOT_FOUND)
        
        progress_qs = GuideProgress.objects.filter(user=user)
        return Response(GuideProgressSerializer(progress_qs, many=True).data)

    def post(self, request, slug=None):
        user = request.user
        if not slug:
            slug = request.data.get('slug')
        
        try:
            guide = Guide.objects.get(slug=slug)
        except Guide.DoesNotExist:
            return Response({'error': 'Guide not found'}, status=status.HTTP_404_NOT_FOUND)

        progress, _ = GuideProgress.objects.get_or_create(user=user, guide=guide)

        completed_steps = request.data.get('completed_steps')
        if completed_steps is not None:
            progress.completed_steps = completed_steps

        bookmarked_sections = request.data.get('bookmarked_sections')
        if bookmarked_sections is not None:
            progress.bookmarked_sections = bookmarked_sections

        last_step_id = request.data.get('last_step_id')
        if last_step_id is not None:
            progress.last_step_id = last_step_id

        progress.save()
        return Response(GuideProgressSerializer(progress).data)
