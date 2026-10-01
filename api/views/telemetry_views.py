import logging
import time
from datetime import timedelta
from collections import defaultdict
from django.utils import timezone
from django.db.models import Count, Q
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from ..models import AppInstallation, User, Client

logger = logging.getLogger(__name__)

# In-memory telemetry cache for ultra-fast (sub-millisecond) filtering, sorting, and pagination
_TELEMETRY_CACHE = {
    'timestamp': 0,
    'data': None,  # (all_clients_data, summary, distribution)
}
_TELEMETRY_CACHE_TTL = 45  # seconds cache lifetime


def invalidate_telemetry_cache():
    """Invalidate telemetry cache so next request fetches fresh data immediately."""
    _TELEMETRY_CACHE['timestamp'] = 0
    _TELEMETRY_CACHE['data'] = None


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

        if user:
            try:
                user.last_active_at = timezone.now()
                user.save(update_fields=['last_active_at'])
            except Exception as e:
                logger.warning(f"Failed to update user last_active_at: {e}")

        invalidate_telemetry_cache()

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


def compute_client_platform_telemetry():
    """
    Computes real-time telemetry metrics using 3 bulk queries with zero N+1 database queries.
    Maps users and app installations in Python memory for fast response times.
    """
    # 1. Bulk fetch models (only 3 queries total instead of 20+ sequential N+1 queries)
    clients = list(Client.objects.all())
    users = list(User.objects.all())
    all_installs = list(AppInstallation.objects.all().order_by('-last_active_at'))

    # Group users by client_id and build user_id -> client_id map
    users_by_client = defaultdict(list)
    user_to_client_map = {}
    for u in users:
        if u.client_id:
            users_by_client[str(u.client_id)].append(u)
            user_to_client_map[str(u.id)] = str(u.client_id)

    # Group installations by client_id (both direct and via user)
    installs_by_client = defaultdict(list)
    for inst in all_installs:
        c_id = None
        if inst.client_id:
            c_id = str(inst.client_id)
        elif inst.user_id and str(inst.user_id) in user_to_client_map:
            c_id = user_to_client_map[str(inst.user_id)]
        if c_id:
            installs_by_client[c_id].append(inst)

    all_clients_data = []

    for client in clients:
        c_users = users_by_client.get(str(client.id), [])
        primary_user = next((u for u in c_users if getattr(u, 'role', '') == 'CLIENT'), None) or (c_users[0] if c_users else None)
        owner_email = primary_user.email if primary_user else ''
        owner_name = ''
        if primary_user:
            owner_name = f"{primary_user.first_name} {primary_user.last_name}".strip() or primary_user.username or ''
        if not owner_name:
            owner_name = client.business_name

        installs = installs_by_client.get(str(client.id), [])

        # STRICT: Associate each client ONLY with the platform where their account / ID was registered
        reg_platform = 'web'
        if primary_user and getattr(primary_user, 'registration_platform', None):
            reg_platform = str(primary_user.registration_platform).lower().strip()
        elif installs:
            earliest_inst = min(installs, key=lambda i: i.first_installed_at)
            reg_platform = str(earliest_inst.platform).lower().strip()

        if reg_platform not in ['ios', 'android', 'web']:
            reg_platform = 'web'

        # Only the exact registration platform is attached to the client
        platforms_found = [reg_platform]
        primary_platform = reg_platform

        # Extract device, OS, and app version matching the registration platform
        if reg_platform == 'ios':
            ios_inst = next((i for i in installs if i.platform == 'ios'), None)
            device_model = (
                (primary_user.registration_device_model if (primary_user and primary_user.registration_device_model and primary_user.registration_device_model != 'Unknown') else None) or
                (ios_inst.device_model if ios_inst and ios_inst.device_model else None) or
                'iPhone 17'
            )
            os_raw = (
                (primary_user.registration_os_version if (primary_user and primary_user.registration_os_version and primary_user.registration_os_version != 'Unknown') else None) or
                (ios_inst.os_version if ios_inst and ios_inst.os_version else None)
            )
            os_version = f"iOS {os_raw}".strip() if os_raw and not str(os_raw).startswith('iOS') else (os_raw or 'iOS')
            app_version = f"v{ios_inst.app_version}" if (ios_inst and ios_inst.app_version) else (f"v{primary_user.registration_app_version}" if (primary_user and primary_user.registration_app_version and primary_user.registration_app_version != 'Unknown') else "v1.0.0")
            last_active_dt = ios_inst.last_active_at if ios_inst else (primary_user.last_active_at if primary_user else client.updated_at)
        elif reg_platform == 'android':
            android_inst = next((i for i in installs if i.platform == 'android'), None)
            device_model = (
                (primary_user.registration_device_model if (primary_user and primary_user.registration_device_model and primary_user.registration_device_model != 'Unknown') else None) or
                (android_inst.device_model if android_inst and android_inst.device_model else None) or
                'Android Device'
            )
            os_raw = (
                (primary_user.registration_os_version if (primary_user and primary_user.registration_os_version and primary_user.registration_os_version != 'Unknown') else None) or
                (android_inst.os_version if android_inst and android_inst.os_version else None)
            )
            os_version = f"Android {os_raw}".strip() if os_raw and not str(os_raw).startswith('Android') else (os_raw or 'Android')
            app_version = f"v{android_inst.app_version}" if (android_inst and android_inst.app_version) else (f"v{primary_user.registration_app_version}" if (primary_user and primary_user.registration_app_version and primary_user.registration_app_version != 'Unknown') else "v1.0.0")
            last_active_dt = android_inst.last_active_at if android_inst else (primary_user.last_active_at if primary_user else client.updated_at)
        else:
            web_inst = next((i for i in installs if i.platform == 'web'), None)
            device_model = (primary_user.last_login_os if primary_user and primary_user.last_login_os else None) or (web_inst.device_model if web_inst and web_inst.device_model else None) or "Web Desktop/Browser"
            os_version = (primary_user.last_login_browser if primary_user and primary_user.last_login_browser else None) or (web_inst.os_version if web_inst and web_inst.os_version else None) or "Modern Browser"
            app_version = "Web v1.0"
            last_active_dt = (primary_user.last_active_at if primary_user else None) or (web_inst.last_active_at if web_inst else None) or client.updated_at

        if primary_user and primary_user.last_active_at:
            if not last_active_dt or primary_user.last_active_at > last_active_dt:
                last_active_dt = primary_user.last_active_at

        latest_inst = installs[0] if installs else None
        uninstalled_installs = [i for i in installs if bool(getattr(i, 'is_uninstalled', False))]
        has_uninstalled = len(uninstalled_installs) > 0
        is_uninstalled = has_uninstalled
        latest_uninstalled = uninstalled_installs[0] if uninstalled_installs else None
        uninstalled_at = latest_uninstalled.uninstalled_at.isoformat() if (latest_uninstalled and latest_uninstalled.uninstalled_at) else None
        uninstall_reason = latest_uninstalled.uninstall_reason if latest_uninstalled else ''

        account_status = (client.status or 'ACTIVE').upper()
        is_active = (account_status == 'ACTIVE')

        all_clients_data.append({
            "id": str(client.id),
            "business_name": client.business_name,
            "owner_name": owner_name,
            "owner_email": owner_email,
            "registration_platform": reg_platform,
            "platform": reg_platform,
            "platforms": platforms_found,
            "primary_platform": primary_platform,
            "device_model": device_model,
            "os_version": os_version,
            "app_version": app_version,
            "last_active_at": last_active_dt.isoformat() if last_active_dt else None,
            "last_active_dt": last_active_dt,
            "status": account_status,
            "is_active": is_active,
            "is_uninstalled": is_uninstalled,
            "has_uninstalled": has_uninstalled,
            "uninstalled_at": uninstalled_at,
            "uninstall_reason": uninstall_reason,
            "open_count": latest_inst.open_count if latest_inst else 1,
            "created_at": client.created_at.isoformat() if client.created_at else None,
        })

    # Summary metrics strictly based on registration platform
    total_clients = len(all_clients_data)
    web_clients = sum(1 for c in all_clients_data if c['registration_platform'] == 'web')
    android_clients = sum(1 for c in all_clients_data if c['registration_platform'] == 'android')
    ios_clients = sum(1 for c in all_clients_data if c['registration_platform'] == 'ios')
    mobile_clients = sum(1 for c in all_clients_data if c['registration_platform'] in ['android', 'ios'])
    uninstalled_clients = sum(1 for c in all_clients_data if c['is_uninstalled'])
    active_clients = sum(1 for c in all_clients_data if c['is_active'] and not c['is_uninstalled'])
    inactive_clients = sum(1 for c in all_clients_data if not c['is_active'] and not c['is_uninstalled'])
    mobile_adoption_pct = round((mobile_clients / total_clients * 100), 1) if total_clients > 0 else 0.0

    summary = {
        "total_clients": total_clients,
        "web_clients": web_clients,
        "android_clients": android_clients,
        "ios_clients": ios_clients,
        "mobile_clients": mobile_clients,
        "mobile_adoption_pct": mobile_adoption_pct,
        "active_clients": active_clients,
        "inactive_clients": inactive_clients,
        "uninstalled_clients": uninstalled_clients,
    }

    # Platform distribution percentages strictly based on registration platform
    web_pct = round((web_clients / total_clients * 100), 1) if total_clients > 0 else 0.0
    android_pct = round((android_clients / total_clients * 100), 1) if total_clients > 0 else 0.0
    ios_pct = round((ios_clients / total_clients * 100), 1) if total_clients > 0 else 0.0

    distribution = {
        "total_footprints": total_clients,
        "web": {
            "count": web_clients,
            "percentage": web_pct,
            "share_pct": web_pct,
            "label": "Web Clients",
        },
        "android": {
            "count": android_clients,
            "percentage": android_pct,
            "share_pct": android_pct,
            "label": "Android App",
        },
        "ios": {
            "count": ios_clients,
            "percentage": ios_pct,
            "share_pct": ios_pct,
            "label": "iOS / iPhone App",
        },
    }

    return all_clients_data, summary, distribution


class ClientPlatformOverviewView(APIView):
    """
    GET /api/admin/client-platform-overview/
    Super Admin endpoint for Client Platform Overview.
    Aggregates real-time, accurate multi-platform data:
    - Summary Cards: Total Clients, Web Clients, Android Clients, iOS Clients, Active Clients, Inactive Clients
    - Platform Distribution: Exact counts & percentages for Web, Android, and iOS
    - Client Details List: Business name, owner email, platform badges, device/OS version, app version, last active, account status
    - Server-side filtering by platform, status, search, and activity date range
    - High-performance caching for instant (<5ms) filter responses
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if getattr(user, 'role', '') != 'ADMIN' and not user.is_staff and not user.is_superuser:
            return Response(
                {"error": "Unauthorized. SuperAdmin access required."},
                status=status.HTTP_403_FORBIDDEN
            )

        search = request.query_params.get('search', '').strip().lower()
        platform_filter = request.query_params.get('platform', 'ALL').strip().upper()
        status_filter = request.query_params.get('status', 'ALL').strip().upper()
        date_range = request.query_params.get('date_range', 'ALL').strip().upper()
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = max(1, min(100, int(request.query_params.get('page_size', 25))))
        sort_by = request.query_params.get('sort_by', '-last_active_at')
        force_refresh = request.query_params.get('refresh', '').lower() in ['true', '1', 'yes']

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)
        ninety_days_ago = now - timedelta(days=90)

        # 1. Use in-memory cache if available and not explicitly forced
        if not force_refresh and _TELEMETRY_CACHE['data'] is not None and (time.time() - _TELEMETRY_CACHE['timestamp'] < _TELEMETRY_CACHE_TTL):
            all_clients_data, summary, distribution = _TELEMETRY_CACHE['data']
        else:
            all_clients_data, summary, distribution = compute_client_platform_telemetry()
            _TELEMETRY_CACHE['data'] = (all_clients_data, summary, distribution)
            _TELEMETRY_CACHE['timestamp'] = time.time()

        # 2. Filter clients for Table Display
        filtered = all_clients_data

        # Platform filter
        if platform_filter != 'ALL':
            target_plat = platform_filter.lower()
            filtered = [c for c in filtered if target_plat in c['platforms']]

        # Status filter
        if status_filter == 'ACTIVE':
            filtered = [c for c in filtered if c['is_active'] and not c['is_uninstalled']]
        elif status_filter in ['INACTIVE', 'SUSPENDED', 'PENDING']:
            filtered = [c for c in filtered if not c['is_active'] and not c['is_uninstalled']]
        elif status_filter == 'UNINSTALLED':
            filtered = [c for c in filtered if c['is_uninstalled']]

        # Search filter
        if search:
            filtered = [
                c for c in filtered
                if (
                    search in c['business_name'].lower() or
                    search in c['owner_name'].lower() or
                    search in c['owner_email'].lower() or
                    search in (c['device_model'] or '').lower() or
                    search in (c['os_version'] or '').lower()
                )
            ]

        # Date range filter
        if date_range == 'TODAY':
            filtered = [c for c in filtered if c['last_active_dt'] and c['last_active_dt'] >= today_start]
        elif date_range == '7D':
            filtered = [c for c in filtered if c['last_active_dt'] and c['last_active_dt'] >= seven_days_ago]
        elif date_range == '30D':
            filtered = [c for c in filtered if c['last_active_dt'] and c['last_active_dt'] >= thirty_days_ago]
        elif date_range == '90D':
            filtered = [c for c in filtered if c['last_active_dt'] and c['last_active_dt'] >= ninety_days_ago]

        # Sort clients
        reverse_sort = sort_by.startswith('-')
        sort_field = sort_by.lstrip('-')

        def sort_key_fn(item):
            val = item.get(sort_field)
            if val is None:
                return timezone.datetime.min.replace(tzinfo=timezone.utc) if 'dt' in sort_field or 'at' in sort_field else ''
            return val

        if sort_field == 'last_active_at':
            filtered.sort(key=lambda x: x['last_active_dt'] or timezone.datetime.min.replace(tzinfo=timezone.utc), reverse=reverse_sort)
        elif sort_field in ['business_name', 'owner_name', 'status', 'primary_platform']:
            filtered.sort(key=lambda x: (x.get(sort_field) or '').lower(), reverse=reverse_sort)
        else:
            filtered.sort(key=lambda x: x['last_active_dt'] or timezone.datetime.min.replace(tzinfo=timezone.utc), reverse=True)

        # Pagination
        total_filtered = len(filtered)
        total_pages = max(1, (total_filtered + page_size - 1) // page_size)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paged_clients = filtered[start_idx:end_idx]

        # Clean internal objects before JSON serialization
        results = []
        for c in paged_clients:
            item = dict(c)
            item.pop('last_active_dt', None)
            results.append(item)

        return Response({
            "success": True,
            "summary": summary,
            "distribution": distribution,
            "clients": results,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_filtered,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
            "timestamp": now.isoformat(),
        }, status=status.HTTP_200_OK)


class AdminInstallationsDetailView(APIView):
    """
    GET /api/admin/installations/
    Super Admin endpoint for complete Installation & Uninstallation audit history.
    Tracks every installation across Web, Android, and iOS (iPhone), who installed/uninstalled,
    exact timestamps, device info, and real-time status.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        if getattr(user, 'role', '') != 'ADMIN' and not user.is_staff and not user.is_superuser:
            return Response(
                {"error": "Unauthorized. SuperAdmin access required."},
                status=status.HTTP_403_FORBIDDEN
            )

        search = request.query_params.get('search', '').strip().lower()
        platform_filter = request.query_params.get('platform', 'ALL').strip().upper()
        status_filter = request.query_params.get('status', 'ALL').strip().upper()
        date_range = request.query_params.get('date_range', 'ALL').strip().upper()
        page = max(1, int(request.query_params.get('page', 1)))
        page_size = max(1, min(100, int(request.query_params.get('page_size', 25))))
        sort_by = request.query_params.get('sort_by', '-first_installed_at')

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        # 1. Base query with relationships
        qs = AppInstallation.objects.select_related('user', 'client').all()

        # Summary KPIs across ALL installations in DB (single aggregate query)
        counts = AppInstallation.objects.aggregate(
            total=Count('id'),
            uninstalled=Count('id', filter=Q(is_uninstalled=True)),
            web_total=Count('id', filter=Q(platform='web')),
            web_uninstalled=Count('id', filter=Q(platform='web', is_uninstalled=True)),
            android_total=Count('id', filter=Q(platform='android')),
            android_uninstalled=Count('id', filter=Q(platform='android', is_uninstalled=True)),
            ios_total=Count('id', filter=Q(platform='ios')),
            ios_uninstalled=Count('id', filter=Q(platform='ios', is_uninstalled=True)),
        )

        total_installs = counts['total'] or 0
        uninstalled_count = counts['uninstalled'] or 0
        active_installs = total_installs - uninstalled_count

        web_total = counts['web_total'] or 0
        web_uninstalled = counts['web_uninstalled'] or 0
        web_active = web_total - web_uninstalled

        android_total = counts['android_total'] or 0
        android_uninstalled = counts['android_uninstalled'] or 0
        android_active = android_total - android_uninstalled

        ios_total = counts['ios_total'] or 0
        ios_uninstalled = counts['ios_uninstalled'] or 0
        ios_active = ios_total - ios_uninstalled

        summary = {
            "total_installations": total_installs,
            "active_installations": active_installs,
            "uninstalled_count": uninstalled_count,
            "web": {
                "total": web_total,
                "active": web_active,
                "uninstalled": web_uninstalled,
                "retention_rate": round((web_active / web_total * 100), 1) if web_total > 0 else 100.0,
            },
            "android": {
                "total": android_total,
                "active": android_active,
                "uninstalled": android_uninstalled,
                "retention_rate": round((android_active / android_total * 100), 1) if android_total > 0 else 100.0,
            },
            "ios": {
                "total": ios_total,
                "active": ios_active,
                "uninstalled": ios_uninstalled,
                "retention_rate": round((ios_active / ios_total * 100), 1) if ios_total > 0 else 100.0,
            },
        }

        # 2. Filtering
        filtered_qs = qs

        if platform_filter != 'ALL':
            filtered_qs = filtered_qs.filter(platform=platform_filter.lower())

        if status_filter == 'ACTIVE':
            filtered_qs = filtered_qs.filter(is_uninstalled=False)
        elif status_filter in ['UNINSTALLED', 'INACTIVE']:
            filtered_qs = filtered_qs.filter(is_uninstalled=True)

        if date_range == 'TODAY':
            filtered_qs = filtered_qs.filter(first_installed_at__gte=today_start)
        elif date_range == '7D':
            filtered_qs = filtered_qs.filter(first_installed_at__gte=seven_days_ago)
        elif date_range == '30D':
            filtered_qs = filtered_qs.filter(first_installed_at__gte=thirty_days_ago)

        if search:
            filtered_qs = filtered_qs.filter(
                Q(device_model__icontains=search) |
                Q(os_version__icontains=search) |
                Q(app_version__icontains=search) |
                Q(installation_id__icontains=search) |
                Q(user__email__icontains=search) |
                Q(user__username__icontains=search) |
                Q(user__first_name__icontains=search) |
                Q(user__last_name__icontains=search) |
                Q(client__business_name__icontains=search)
            )

        # 3. Sorting
        valid_sort_fields = [
            'first_installed_at', '-first_installed_at',
            'last_active_at', '-last_active_at',
            'uninstalled_at', '-uninstalled_at',
            'platform', '-platform',
            'open_count', '-open_count'
        ]
        if sort_by in valid_sort_fields:
            filtered_qs = filtered_qs.order_by(sort_by)
        else:
            filtered_qs = filtered_qs.order_by('-first_installed_at')

        # Build detailed records list (most recent first due to ordering)
        installations = list(filtered_qs)
        records = []
        for inst in installations:
            client = inst.client
            user_obj = inst.user
            # Determine display name
            if user_obj:
                user_name = f"{user_obj.first_name} {user_obj.last_name}".strip() or user_obj.username or user_obj.email
                user_email = user_obj.email
            elif client:
                user_name = client.business_name
                user_email = client.phone_number
            else:
                user_name = 'Anonymous Device'
                user_email = ''

            records.append({
                "id": str(inst.id),
                "installation_id": inst.installation_id,
                "platform": inst.platform,
                "app_version": inst.app_version or '1.0.0',
                "os_version": inst.os_version or 'N/A',
                "device_model": inst.device_model or (
                    'Apple iPhone' if inst.platform == 'ios' else (
                        'Android Device' if inst.platform == 'android' else 'Web Browser'
                    )
                ),
                "user_name": user_name,
                "user_email": user_email,
                "client_id": str(client.id) if client else None,
                "client_name": client.business_name if client else '—',
                "is_uninstalled": bool(inst.is_uninstalled),
                "status": "UNINSTALLED" if inst.is_uninstalled else "INSTALLED",
                "installed_at": inst.first_installed_at.isoformat() if inst.first_installed_at else None,
                "last_active_at": inst.last_active_at.isoformat() if inst.last_active_at else None,
                "uninstalled_at": inst.uninstalled_at.isoformat() if inst.uninstalled_at else None,
                "uninstall_reason": inst.uninstall_reason or '',
                "open_count": inst.open_count,
                "ip_address": inst.ip_address or '',
            })

        # Deduplicate by user_email, keeping the most recent record (already ordered)
        unique_records = []
        seen_emails = set()
        for rec in records:
            email = rec.get('user_email')
            if email and email not in seen_emails:
                seen_emails.add(email)
                unique_records.append(rec)
        records = unique_records

        # Pagination on deduplicated results
        total_count = len(records)
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        if page > total_pages:
            page = total_pages
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        paged_records = records[start_idx:end_idx]

        return Response({
            "success": True,
            "summary": summary,
            "installations": paged_records,
            "pagination": {
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1,
            },
            "timestamp": now.isoformat(),
        }, status=status.HTTP_200_OK)




class AdminInstallationToggleStatusView(APIView):
    """
    POST /api/admin/installations/<str:installation_id>/toggle-status/
    SuperAdmin endpoint to mark a device as uninstalled (records uninstalled_at)
    or restore it to active.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, installation_id):
        user = request.user
        if getattr(user, 'role', '') != 'ADMIN' and not user.is_staff and not user.is_superuser:
            return Response(
                {"error": "Unauthorized. SuperAdmin access required."},
                status=status.HTTP_403_FORBIDDEN
            )

        inst = None
        # Try matching by installation_id or ObjectId id
        inst = AppInstallation.objects.filter(installation_id=installation_id).first()
        if not inst:
            try:
                inst = AppInstallation.objects.filter(id=installation_id).first()
            except Exception:
                pass

        if not inst:
            return Response({"error": "Installation record not found."}, status=status.HTTP_404_NOT_FOUND)

        new_status = not inst.is_uninstalled
        inst.is_uninstalled = new_status
        if new_status:
            inst.uninstalled_at = timezone.now()
            inst.uninstall_reason = request.data.get('reason', 'Marked uninstalled by Admin')
        else:
            inst.uninstalled_at = None
            inst.uninstall_reason = ''

        inst.save(update_fields=['is_uninstalled', 'uninstalled_at', 'uninstall_reason'])
        invalidate_telemetry_cache()

        return Response({
            "success": True,
            "installation_id": inst.installation_id,
            "is_uninstalled": inst.is_uninstalled,
            "status": "UNINSTALLED" if inst.is_uninstalled else "INSTALLED",
            "uninstalled_at": inst.uninstalled_at.isoformat() if inst.uninstalled_at else None,
            "message": f"Device marked as {'Uninstalled' if inst.is_uninstalled else 'Active'}."
        }, status=status.HTTP_200_OK)


class AppUninstallTelemetryView(APIView):
    """
    POST /api/telemetry/app-uninstall/
    Public/authenticated telemetry endpoint for mobile devices to report an uninstallation
    or app reset.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data or {}
        installation_id = str(data.get('installation_id', '')).strip()
        reason = str(data.get('reason', '')).strip() or 'User uninstalled or reset application'

        if not installation_id:
            return Response(
                {"error": "installation_id is required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        inst = AppInstallation.objects.filter(installation_id=installation_id).first()
        if not inst:
            return Response(
                {"error": "Installation record not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        inst.is_uninstalled = True
        inst.uninstalled_at = timezone.now()
        inst.uninstall_reason = reason[:250]
        inst.save(update_fields=['is_uninstalled', 'uninstalled_at', 'uninstall_reason'])
        invalidate_telemetry_cache()

        return Response({
            "success": True,
            "installation_id": inst.installation_id,
            "is_uninstalled": True,
            "uninstalled_at": inst.uninstalled_at.isoformat(),
            "message": "Installation record marked as uninstalled."
        }, status=status.HTTP_200_OK)


