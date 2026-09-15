import logging
from django.utils import timezone
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import BasePermission, AllowAny
from api.models import (
    DynamicContentItem,
    DynamicBanner,
    AppMaintenanceConfig,
    AppFeatureFlag,
    DynamicContentVersionSnapshot,
    LegalDocumentVersion,
    AuditLog
)
from api.cms_serializers import (
    DynamicContentItemSerializer,
    DynamicBannerSerializer,
    AppMaintenanceConfigSerializer,
    AppFeatureFlagSerializer,
    DynamicContentVersionSnapshotSerializer
)
from api.utils.content_sanitizer import sanitize_html

logger = logging.getLogger(__name__)


class IsCMSAdmin(BasePermission):
    """
    Permission check ensuring only authorized Admins can manage CMS content.
    """
    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False
        return (
            getattr(request.user, 'role', '') == 'ADMIN' or
            getattr(request.user, 'enterprise_role', '') in ['SUPER_ADMIN', 'ORG_ADMIN'] or
            request.user.is_staff or
            request.user.is_superuser
        )


def get_current_global_version() -> int:
    """Returns the latest published global content version number."""
    latest = DynamicContentVersionSnapshot.objects.order_by('-version_number').first()
    if latest:
        return latest.version_number
    # Fallback to highest item version or 1
    highest_item = DynamicContentItem.objects.order_by('-version').first()
    return highest_item.version if highest_item else 1


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def record_cms_audit(user, action: str, details: str = '', before_val: str = None, after_val: str = None, ip_address: str = None):
    """Records an audit log entry under module 'CMS'."""
    try:
        username = user.username if (user and hasattr(user, 'username')) else 'Admin'
        AuditLog.objects.create(
            admin_name=username,
            client_name='Platform Global',
            module='CMS',
            action=action,
            before_value=str(before_val) if before_val is not None else '',
            after_value=str(after_val) if after_val is not None else details,
            ip_address=ip_address
        )
    except Exception as e:
        logger.error(f"[CMS AuditLog Error] {e}")


# ══════════════════════════════════════════════════════════════════════════════
# 1. PUBLIC / MOBILE APP CONTENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

class AppContentVersionView(APIView):
    """
    GET /api/app/content/version/
    Ultra-lightweight endpoint returning current content version & maintenance status.
    Mobile app calls this on launch and resume (AppState active).
    Supports HTTP 304 Not Modified when version has not changed.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        current_version = get_current_global_version()
        etag = f'"v{current_version}"'

        maint = AppMaintenanceConfig.objects.first()
        maint_data = {
            "is_active": maint.is_enabled if maint else False,
            "title": maint.title if maint else "Under Maintenance",
            "message": maint.message if maint else "System is being updated.",
            "estimated_completion": maint.estimated_completion if maint else ""
        }

        latest_snapshot = DynamicContentVersionSnapshot.objects.order_by('-version_number').first()
        updated_at = latest_snapshot.published_at.isoformat() if latest_snapshot else timezone.now().isoformat()

        response = Response({
            "version": current_version,
            "updated_at": updated_at,
            "maintenance": maint_data
        }, status=status.HTTP_200_OK)
        response['ETag'] = etag
        return response



class AppContentView(APIView):
    """
    GET /api/app/content/
    Returns full published active content for requested language with fallback to English.
    Also returns active banners, feature flags, legal doc versions, and maintenance state.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request):
        target_lang = (request.query_params.get('lang') or 'en').lower().strip()
        current_version = get_current_global_version()
        etag = f'"v{current_version}_{target_lang}"'

        if_none_match = request.headers.get('If-None-Match') or request.META.get('HTTP_IF_NONE_MATCH')
        if if_none_match and if_none_match.strip() == etag:
            response = Response(status=status.HTTP_304_NOT_MODIFIED)
            response['ETag'] = etag
            return response

        # 1. Build content dictionary with language fallback
        # Base: English items
        en_items = {
            item.key: item.published_value
            for item in DynamicContentItem.objects.filter(is_active=True, language='en')
        }

        # Override with target language if available and not English
        if target_lang != 'en':
            target_items = DynamicContentItem.objects.filter(is_active=True, language=target_lang)
            for item in target_items:
                if item.published_value.strip():
                    en_items[item.key] = item.published_value

        # 2. Active Banners
        banners_qs = DynamicBanner.objects.filter(is_active=True, draft_mode=False).order_by('display_order', '-created_at')
        banners_data = DynamicBannerSerializer(banners_qs, many=True, context={'request': request}).data

        # 3. Feature Flags
        flags_qs = AppFeatureFlag.objects.all()
        features_dict = {f.feature_key: f.is_enabled for f in flags_qs}

        # 4. Maintenance Config
        maint = AppMaintenanceConfig.objects.first()
        maint_data = {
            "is_active": maint.is_enabled if maint else False,
            "title": maint.title if maint else "Under Maintenance",
            "message": maint.message if maint else "System is being updated.",
            "estimated_completion": maint.estimated_completion if maint else ""
        }

        # 5. Legal Versions
        terms = LegalDocumentVersion.objects.filter(document_type='TERMS', is_active=True).first()
        privacy = LegalDocumentVersion.objects.filter(document_type='PRIVACY_POLICY', is_active=True).first()
        legal_data = {
            "terms_version": terms.version if terms else "1.0",
            "terms_effective_date": terms.effective_date.isoformat() if terms and terms.effective_date else None,
            "privacy_version": privacy.version if privacy else "1.0",
            "privacy_effective_date": privacy.effective_date.isoformat() if privacy and privacy.effective_date else None,
        }

        latest_snapshot = DynamicContentVersionSnapshot.objects.order_by('-version_number').first()
        updated_at = latest_snapshot.published_at.isoformat() if latest_snapshot else timezone.now().isoformat()

        payload = {
            "version": current_version,
            "lang": target_lang,
            "updated_at": updated_at,
            "content": en_items,
            "banners": banners_data,
            "features": features_dict,
            "maintenance": maint_data,
            "legal": legal_data
        }

        response = Response(payload, status=status.HTTP_200_OK)
        response['ETag'] = etag
        return response


# ══════════════════════════════════════════════════════════════════════════════
# 2. ADMIN CONTENT MANAGEMENT ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

class AdminContentManagementView(APIView):
    """
    GET /api/admin/content/
    Returns list of all content items, current global version, sections, and draft stats.
    """
    permission_classes = [IsCMSAdmin]

    def get(self, request):
        section = request.query_params.get('section')
        lang = request.query_params.get('lang')

        query = DynamicContentItem.objects.all()
        if section:
            query = query.filter(section=section.upper())
        if lang:
            query = query.filter(language=lang.lower())

        items = list(query.order_by('section', 'key', 'language'))
        serializer = DynamicContentItemSerializer(items, many=True)

        current_version = get_current_global_version()
        draft_changes_count = sum(1 for item in items if item.draft_value != item.published_value)

        # Distinct sections and languages available
        sections = [
            {'value': s[0], 'label': s[1]}
            for s in DynamicContentItem.SECTION_CHOICES
        ]
        languages = list(DynamicContentItem.objects.values_list('language', flat=True).distinct())
        if 'en' not in languages:
            languages.insert(0, 'en')

        latest_snapshot = DynamicContentVersionSnapshot.objects.order_by('-version_number').first()

        return Response({
            "current_version": current_version,
            "last_published_at": latest_snapshot.published_at if latest_snapshot else None,
            "last_published_by": latest_snapshot.published_by.get_full_name() or latest_snapshot.published_by.username if (latest_snapshot and latest_snapshot.published_by) else "System",
            "draft_changes_count": draft_changes_count,
            "sections": sections,
            "languages": languages,
            "items": serializer.data
        }, status=status.HTTP_200_OK)


class AdminContentDraftSaveView(APIView):
    """
    POST /api/admin/content/draft/
    Saves draft content updates without modifying live published values or bumping global version.
    """
    permission_classes = [IsCMSAdmin]

    def post(self, request):
        raw_items = request.data.get('items')
        if not raw_items:
            # Single item update
            raw_items = [request.data]

        saved_items = []
        ip = get_client_ip(request)

        for item_data in raw_items:
            key = item_data.get('key')
            if not key:
                continue

            lang = (item_data.get('language') or 'en').lower().strip()
            val = item_data.get('value', '')
            content_type = item_data.get('content_type', 'text')
            section = item_data.get('section', 'GENERAL')
            label = item_data.get('label', '')
            description = item_data.get('description', '')
            is_active = item_data.get('is_active', True)

            # Sanitize rich-text content
            if content_type == 'rich_text':
                val = sanitize_html(val)

            item, created = DynamicContentItem.objects.get_or_create(
                key=key,
                language=lang,
                defaults={
                    'section': section,
                    'content_type': content_type,
                    'label': label or key.replace('_', ' ').title(),
                    'description': description,
                    'draft_value': val,
                    'published_value': '',
                    'is_active': is_active,
                    'updated_by': request.user
                }
            )

            if not created:
                before_val = item.draft_value
                item.draft_value = val
                item.is_active = is_active
                item.updated_by = request.user
                if label:
                    item.label = label
                if description:
                    item.description = description
                if section:
                    item.section = section
                if content_type:
                    item.content_type = content_type
                item.save()

            saved_items.append(item)

        record_cms_audit(
            user=request.user,
            action='DRAFT_SAVE',
            details=f"Saved draft changes for {len(saved_items)} item(s)",
            ip_address=ip
        )

        return Response({
            "message": f"Successfully saved draft for {len(saved_items)} item(s).",
            "items": DynamicContentItemSerializer(saved_items, many=True).data
        }, status=status.HTTP_200_OK)


class AdminContentPublishView(APIView):
    """
    POST /api/admin/content/publish/
    Promotes draft content to published values, increments global content version,
    creates a historical snapshot for rollback, and logs the audit entry.
    """
    permission_classes = [IsCMSAdmin]

    def post(self, request):
        changelog = request.data.get('changelog', 'Published content updates via Admin Dashboard')
        target_keys = request.data.get('keys')  # Optional list of specific keys to publish

        query = DynamicContentItem.objects.all()
        if target_keys and isinstance(target_keys, list):
            query = query.filter(key__in=target_keys)

        published_count = 0
        now = timezone.now()

        for item in query:
            if item.draft_value != item.published_value or not item.published_at:
                item.published_value = item.draft_value
                item.version += 1
                item.published_at = now
                item.updated_by = request.user
                item.save()
                published_count += 1

        # Calculate new global version number
        current_version = get_current_global_version()
        new_version = current_version + 1

        # Create full snapshot of all active published content
        all_published_items = DynamicContentItem.objects.filter(is_active=True)
        snapshot_dict = {}
        for item in all_published_items:
            lang_dict = snapshot_dict.setdefault(item.language, {})
            lang_dict[item.key] = item.published_value

        snapshot_banners = DynamicBannerSerializer(DynamicBanner.objects.filter(is_active=True, draft_mode=False), many=True).data
        snapshot_flags = {f.feature_key: f.is_enabled for f in AppFeatureFlag.objects.all()}

        snapshot = DynamicContentVersionSnapshot.objects.create(
            version_number=new_version,
            snapshot_data={
                "content": snapshot_dict,
                "banners": snapshot_banners,
                "features": snapshot_flags
            },
            changelog=changelog,
            published_by=request.user,
            published_at=now
        )

        ip = get_client_ip(request)
        record_cms_audit(
            user=request.user,
            action='PUBLISH',
            details=f"Published v{new_version}: {changelog} ({published_count} items updated)",
            after_val=f"v{new_version}",
            ip_address=ip
        )

        return Response({
            "message": f"Successfully published v{new_version} to all mobile users.",
            "version": new_version,
            "published_items_count": published_count,
            "published_at": now.isoformat()
        }, status=status.HTTP_200_OK)


class AdminContentPreviewView(APIView):
    """
    POST /api/admin/content/preview/
    Returns merged draft content payload for active language so admin mockup preview
    displays exact live changes before publishing. Does NOT affect production users.
    """
    permission_classes = [IsCMSAdmin]

    def post(self, request):
        target_lang = (request.data.get('lang') or 'en').lower().strip()

        # Build preview dictionary: draft_value takes precedence over published_value
        en_items = {}
        for item in DynamicContentItem.objects.filter(language='en'):
            val = item.draft_value if item.draft_value else item.published_value
            en_items[item.key] = val

        if target_lang != 'en':
            target_items = DynamicContentItem.objects.filter(language=target_lang)
            for item in target_items:
                val = item.draft_value if item.draft_value else item.published_value
                if val.strip():
                    en_items[item.key] = val

        # Include banners (both active and draft for preview)
        banners_qs = DynamicBanner.objects.filter(is_active=True).order_by('display_order', '-created_at')
        banners_data = DynamicBannerSerializer(banners_qs, many=True, context={'request': request}).data

        flags_qs = AppFeatureFlag.objects.all()
        features_dict = {f.feature_key: f.is_enabled for f in flags_qs}

        maint = AppMaintenanceConfig.objects.first()
        maint_data = {
            "is_active": maint.is_enabled if maint else False,
            "title": maint.title if maint else "Under Maintenance",
            "message": maint.message if maint else "System is being updated.",
            "estimated_completion": maint.estimated_completion if maint else ""
        }

        return Response({
            "preview_mode": True,
            "lang": target_lang,
            "content": en_items,
            "banners": banners_data,
            "features": features_dict,
            "maintenance": maint_data
        }, status=status.HTTP_200_OK)


class AdminContentRollbackView(APIView):
    """
    POST /api/admin/content/rollback/
    Restores published content from a previous DynamicContentVersionSnapshot.
    """
    permission_classes = [IsCMSAdmin]

    def post(self, request):
        target_version = request.data.get('version_number')
        if not target_version:
            return Response({"error": "version_number is required for rollback."}, status=status.HTTP_400_BAD_REQUEST)

        snapshot = DynamicContentVersionSnapshot.objects.filter(version_number=target_version).first()
        if not snapshot:
            return Response({"error": f"Version snapshot v{target_version} not found."}, status=status.HTTP_404_NOT_FOUND)

        snapshot_content = snapshot.snapshot_data.get('content', {})
        restored_count = 0
        now = timezone.now()

        for lang, key_values in snapshot_content.items():
            for key, val in key_values.items():
                item, _ = DynamicContentItem.objects.get_or_create(
                    key=key,
                    language=lang,
                    defaults={'section': 'GENERAL', 'draft_value': val, 'published_value': val}
                )
                item.published_value = val
                item.draft_value = val
                item.published_at = now
                item.updated_by = request.user
                item.save()
        # Restore feature flags if snapshot contains them
        snapshot_flags = snapshot.snapshot_data.get('features', {})
        for f_key, is_en in snapshot_flags.items():
            AppFeatureFlag.objects.filter(feature_key=f_key).update(is_enabled=is_en)

        # Create new version representing the rollback
        current_version = get_current_global_version()
        new_version = current_version + 1
        changelog = f"Rollback to v{target_version}: {snapshot.changelog or 'Restored prior state'}"

        DynamicContentVersionSnapshot.objects.create(
            version_number=new_version,
            snapshot_data=snapshot.snapshot_data,
            changelog=changelog,
            published_by=request.user,
            published_at=now
        )

        ip = get_client_ip(request)
        record_cms_audit(
            user=request.user,
            action='ROLLBACK',
            details=f"Rolled back content to v{target_version} (created v{new_version})",
            before_val=f"v{current_version}",
            after_val=f"v{new_version} (reverted to v{target_version})",
            ip_address=ip
        )

        return Response({
            "message": f"Successfully rolled back to v{target_version}. New live version is v{new_version}.",
            "new_version": new_version,
            "restored_items_count": restored_count
        }, status=status.HTTP_200_OK)


class AdminContentVersionsListView(APIView):
    """
    GET /api/admin/content/versions/
    Returns list of all published version snapshots with changelog and author info.
    """
    permission_classes = [IsCMSAdmin]

    def get(self, request):
        snapshots = DynamicContentVersionSnapshot.objects.all().order_by('-version_number')[:30]
        serializer = DynamicContentVersionSnapshotSerializer(snapshots, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════════════════
# 3. DYNAMIC BANNER MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class AdminBannerManagementView(APIView):
    """
    GET, POST /api/admin/content/banners/
    List, create, update, delete dynamic promotional banners and images.
    """
    permission_classes = [IsCMSAdmin]

    def get(self, request):
        banners = DynamicBanner.objects.all().order_by('display_order', '-created_at')
        serializer = DynamicBannerSerializer(banners, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        title = request.data.get('title')
        if not title:
            return Response({"error": "Title is required."}, status=status.HTTP_400_BAD_REQUEST)

        banner = DynamicBanner(
            title=title,
            description=request.data.get('description', ''),
            image_url=request.data.get('image_url', ''),
            action_type=request.data.get('action_type', 'none'),
            action_url=request.data.get('action_url', ''),
            placement=request.data.get('placement', 'home_hero'),
            display_order=int(request.data.get('display_order', 0)),
            is_active=request.data.get('is_active', 'true') in [True, 'true', '1'],
            draft_mode=request.data.get('draft_mode', 'false') in [True, 'true', '1'],
        )

        if 'image' in request.FILES:
            banner.image = request.FILES['image']

        banner.save()

        record_cms_audit(
            user=request.user,
            action='BANNER_CREATED',
            details=f"Created banner: {banner.title}",
            ip_address=get_client_ip(request)
        )

        return Response(DynamicBannerSerializer(banner, context={'request': request}).data, status=status.HTTP_201_CREATED)

    def put(self, request, pk=None):
        banner_id = pk or request.data.get('id')
        banner = DynamicBanner.objects.filter(pk=banner_id).first()
        if not banner:
            return Response({"error": "Banner not found."}, status=status.HTTP_404_NOT_FOUND)

        if 'title' in request.data:
            banner.title = request.data['title']
        if 'description' in request.data:
            banner.description = request.data['description']
        if 'image_url' in request.data:
            banner.image_url = request.data['image_url']
        if 'action_type' in request.data:
            banner.action_type = request.data['action_type']
        if 'action_url' in request.data:
            banner.action_url = request.data['action_url']
        if 'placement' in request.data:
            banner.placement = request.data['placement']
        if 'display_order' in request.data:
            banner.display_order = int(request.data['display_order'])
        if 'is_active' in request.data:
            banner.is_active = request.data['is_active'] in [True, 'true', '1']
        if 'draft_mode' in request.data:
            banner.draft_mode = request.data['draft_mode'] in [True, 'true', '1']

        if 'image' in request.FILES:
            banner.image = request.FILES['image']

        banner.save()

        record_cms_audit(
            user=request.user,
            action='BANNER_UPDATED',
            details=f"Updated banner: {banner.title}",
            ip_address=get_client_ip(request)
        )

        return Response(DynamicBannerSerializer(banner, context={'request': request}).data, status=status.HTTP_200_OK)

    def delete(self, request, pk=None):
        banner_id = pk or request.data.get('id')
        banner = DynamicBanner.objects.filter(pk=banner_id).first()
        if not banner:
            return Response({"error": "Banner not found."}, status=status.HTTP_404_NOT_FOUND)

        title = banner.title
        banner.delete()

        record_cms_audit(
            user=request.user,
            action='BANNER_DELETED',
            details=f"Deleted banner: {title}",
            ip_address=get_client_ip(request)
        )

        return Response({"message": f"Banner '{title}' deleted."}, status=status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════════════════
# 4. MAINTENANCE MODE MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class AdminMaintenanceConfigView(APIView):
    """
    GET, POST /api/admin/content/maintenance/
    Controls remote maintenance mode overlay for the mobile app.
    """
    permission_classes = [IsCMSAdmin]

    def get(self, request):
        config = AppMaintenanceConfig.objects.first()
        if not config:
            config = AppMaintenanceConfig.objects.create(
                is_enabled=False,
                title="Under Maintenance",
                message="We are currently upgrading UWO Connect. Please check back shortly.",
                estimated_completion="Within 30 minutes"
            )
        return Response(AppMaintenanceConfigSerializer(config).data, status=status.HTTP_200_OK)

    def post(self, request):
        config = AppMaintenanceConfig.objects.first()
        if not config:
            config = AppMaintenanceConfig.objects.create(
                is_enabled=False,
                title="Under Maintenance",
                message="We are currently upgrading UWO Connect. Please check back shortly.",
                estimated_completion="Within 30 minutes"
            )
        prev_status = config.is_enabled

        if 'is_enabled' in request.data:
            config.is_enabled = request.data['is_enabled'] in [True, 'true', '1']
        if 'title' in request.data:
            config.title = request.data['title']
        if 'message' in request.data:
            config.message = request.data['message']
        if 'estimated_completion' in request.data:
            config.estimated_completion = request.data['estimated_completion']
        if 'allowed_roles' in request.data:
            config.allowed_roles = request.data['allowed_roles']

        config.updated_by = request.user
        config.save()

        # Bump global content version so mobile immediately picks up the maintenance status change
        current_version = get_current_global_version()
        new_version = current_version + 1
        now = timezone.now()

        DynamicContentVersionSnapshot.objects.create(
            version_number=new_version,
            snapshot_data={"maintenance_update": config.is_enabled},
            changelog=f"Maintenance mode set to {'ON' if config.is_enabled else 'OFF'}",
            published_by=request.user,
            published_at=now
        )

        ip = get_client_ip(request)
        record_cms_audit(
            user=request.user,
            action='MAINTENANCE_TOGGLED',
            details=f"Maintenance Mode switched to {'ON' if config.is_enabled else 'OFF'}",
            before_val=str(prev_status),
            after_val=str(config.is_enabled),
            ip_address=ip
        )

        return Response({
            "message": f"Maintenance mode successfully set to {'ON' if config.is_enabled else 'OFF'}.",
            "config": AppMaintenanceConfigSerializer(config).data,
            "version": new_version
        }, status=status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════════════════
# 5. FEATURE FLAGS MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

class AdminFeatureFlagManagementView(APIView):
    """
    GET, POST /api/admin/content/feature-flags/
    Lists and toggles dynamic feature flags controlling app modules.
    """
    permission_classes = [IsCMSAdmin]

    def get(self, request):
        flags = AppFeatureFlag.objects.all().order_by('feature_key')
        return Response(AppFeatureFlagSerializer(flags, many=True).data, status=status.HTTP_200_OK)

    def post(self, request):
        feature_key = request.data.get('feature_key')
        if not feature_key:
            return Response({"error": "feature_key is required."}, status=status.HTTP_400_BAD_REQUEST)

        is_enabled = request.data.get('is_enabled', True)
        if isinstance(is_enabled, str):
            is_enabled = is_enabled.lower() in ['true', '1']

        flag, created = AppFeatureFlag.objects.get_or_create(
            feature_key=feature_key,
            defaults={
                'name': request.data.get('name', feature_key.replace('_', ' ').title()),
                'description': request.data.get('description', ''),
                'is_enabled': is_enabled
            }
        )

        prev_val = flag.is_enabled
        if not created:
            flag.is_enabled = is_enabled
            if 'name' in request.data:
                flag.name = request.data['name']
            if 'description' in request.data:
                flag.description = request.data['description']
            flag.save()

        # Bump global content version
        current_version = get_current_global_version()
        new_version = current_version + 1
        now = timezone.now()

        DynamicContentVersionSnapshot.objects.create(
            version_number=new_version,
            snapshot_data={"feature_flag_update": {feature_key: is_enabled}},
            changelog=f"Feature '{feature_key}' set to {'Enabled' if is_enabled else 'Disabled'}",
            published_by=request.user,
            published_at=now
        )

        ip = get_client_ip(request)
        record_cms_audit(
            user=request.user,
            action='FEATURE_FLAG_TOGGLED',
            details=f"Feature '{feature_key}' toggled to {is_enabled}",
            before_val=str(prev_val),
            after_val=str(is_enabled),
            ip_address=ip
        )

        return Response({
            "message": f"Feature flag '{feature_key}' updated.",
            "flag": AppFeatureFlagSerializer(flag).data,
            "version": new_version
        }, status=status.HTTP_200_OK)


# ══════════════════════════════════════════════════════════════════════════════
# 6. CMS AUDIT LOGS
# ══════════════════════════════════════════════════════════════════════════════

class AdminCMSAuditLogsView(APIView):
    """
    GET /api/admin/content/audit-logs/
    Returns audit logs for all CMS actions (drafts, publishes, rollbacks, banners, maintenance).
    """
    permission_classes = [IsCMSAdmin]

    def get(self, request):
        logs = AuditLog.objects.filter(module='CMS').order_by('-created_at')[:50]
        data = [
            {
                "id": l.id,
                "admin_name": l.admin_name,
                "action": l.action,
                "details": l.after_value or l.action,
                "before_value": l.before_value,
                "after_value": l.after_value,
                "ip_address": l.ip_address,
                "created_at": l.created_at.isoformat()
            }
            for l in logs
        ]
        return Response(data, status=status.HTTP_200_OK)
