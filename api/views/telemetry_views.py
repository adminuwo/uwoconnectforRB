import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from ..models import AppInstallation, User, Client

logger = logging.getLogger(__name__)


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


class AppInstallTelemetryView(APIView):
    """
    POST /api/telemetry/app-install/
    Public telemetry ingestion endpoint.
    Called when the mobile app is first installed, opened, or resumes.
    Registers a persistent device UUID and updates engagement telemetry.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data or {}
        installation_id = data.get('installation_id', '').strip()

        if not installation_id:
            return Response(
                {"error": "installation_id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        raw_platform = str(data.get('platform', 'android')).lower().strip()
        platform = raw_platform if raw_platform in ['android', 'ios', 'web', 'other'] else 'other'
        app_version = str(data.get('app_version', '1.0.0')).strip()[:50]
        os_version = str(data.get('os_version', '')).strip()[:50]
        device_model = str(data.get('device_model', '')).strip()[:150]

        ip_addr = get_client_ip(request)
        user_agent = request.META.get('HTTP_USER_AGENT', '')

        user = request.user if request.user and request.user.is_authenticated else None
        client = None
        if user and hasattr(user, 'client') and user.client:
            client = user.client

        inst, created = AppInstallation.objects.get_or_create(
            installation_id=installation_id,
            defaults={
                'platform': platform,
                'app_version': app_version,
                'os_version': os_version,
                'device_model': device_model,
                'ip_address': ip_addr,
                'user_agent': user_agent,
                'user': user,
                'client': client,
                'open_count': 1,
            }
        )

        if not created:
            # Update existing installation record
            inst.platform = platform or inst.platform
            inst.app_version = app_version or inst.app_version
            if os_version:
                inst.os_version = os_version
            if device_model:
                inst.device_model = device_model
            if ip_addr:
                inst.ip_address = ip_addr
            if user:
                inst.user = user
            if client:
                inst.client = client
            inst.open_count += 1
            inst.last_active_at = timezone.now()
            inst.save()

        return Response({
            "success": True,
            "installation_id": inst.installation_id,
            "is_first_install": created,
            "open_count": inst.open_count,
            "registered_at": inst.first_installed_at.isoformat()
        }, status=status.HTTP_200_OK if not created else status.HTTP_201_CREATED)


class AdminAppAnalyticsView(APIView):
    """
    GET /api/admin/app-analytics/
    SuperAdmin analytics endpoint for mobile app installations,
    platform split (Android vs iOS), active devices, version distribution,
    and recent device installation activity.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if getattr(user, 'role', '') != 'ADMIN' and not user.is_staff and not user.is_superuser:
            return Response({"error": "Unauthorized. SuperAdmin access required."}, status=status.HTTP_403_FORBIDDEN)

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)
        twenty_four_hours_ago = now - timedelta(hours=24)

        # 1. High-level KPI metrics
        total_installs = AppInstallation.objects.count()
        today_installs = AppInstallation.objects.filter(first_installed_at__gte=today_start).count()
        week_installs = AppInstallation.objects.filter(first_installed_at__gte=seven_days_ago).count()
        month_installs = AppInstallation.objects.filter(first_installed_at__gte=thirty_days_ago).count()

        active_24h = AppInstallation.objects.filter(last_active_at__gte=twenty_four_hours_ago).count()
        active_30d = AppInstallation.objects.filter(last_active_at__gte=thirty_days_ago).count()

        # 2. Platform breakdown
        android_count = AppInstallation.objects.filter(platform='android').count()
        ios_count = AppInstallation.objects.filter(platform='ios').count()
        web_count = AppInstallation.objects.filter(platform='web').count()
        other_count = total_installs - (android_count + ios_count + web_count)

        platform_breakdown = {
            "android": android_count,
            "ios": ios_count,
            "web": web_count,
            "other": max(0, other_count),
        }

        # 3. Version breakdown
        version_qs = AppInstallation.objects.values('app_version').annotate(
            count=Count('id')
        ).order_by('-count')[:6]
        version_breakdown = [
            {"version": item['app_version'] or 'Unknown', "count": item['count']}
            for item in version_qs
        ]

        # 4. Daily install trend for the last 14 days
        daily_trend = []
        for i in range(13, -1, -1):
            day_date = (now - timedelta(days=i)).date()
            day_start = timezone.make_aware(timezone.datetime.combine(day_date, timezone.datetime.min.time()))
            day_end = timezone.make_aware(timezone.datetime.combine(day_date, timezone.datetime.max.time()))

            day_qs = AppInstallation.objects.filter(first_installed_at__range=(day_start, day_end))
            daily_trend.append({
                "date": day_date.strftime('%b %d'),
                "total": day_qs.count(),
                "android": day_qs.filter(platform='android').count(),
                "ios": day_qs.filter(platform='ios').count(),
            })

        # 5. Recent installations log (last 20)
        recent_qs = AppInstallation.objects.select_related('user', 'client').order_by('-first_installed_at')[:20]
        recent_installations = []
        for inst in recent_qs:
            user_name = None
            if inst.user:
                user_name = inst.user.get_full_name() or inst.user.username
            client_name = inst.client.business_name if inst.client else None

            recent_installations.append({
                "id": inst.id,
                "installation_id": inst.installation_id,
                "platform": inst.platform,
                "app_version": inst.app_version,
                "os_version": inst.os_version,
                "device_model": inst.device_model or "Unknown Device",
                "user_name": user_name,
                "client_name": client_name,
                "open_count": inst.open_count,
                "first_installed_at": inst.first_installed_at.isoformat(),
                "last_active_at": inst.last_active_at.isoformat(),
            })

        return Response({
            "kpis": {
                "total_installs": total_installs,
                "today_installs": today_installs,
                "week_installs": week_installs,
                "month_installs": month_installs,
                "active_devices_24h": active_24h,
                "active_devices_30d": active_30d,
            },
            "platforms": platform_breakdown,
            "versions": version_breakdown,
            "daily_trend": daily_trend,
            "recent_installations": recent_installations,
        }, status=status.HTTP_200_OK)
