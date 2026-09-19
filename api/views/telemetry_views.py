import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import Count, Q
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

        if user:
            try:
                user.last_active_at = timezone.now()
                user.save(update_fields=['last_active_at'])
            except Exception as e:
                logger.warning(f"Failed to update user last_active_at: {e}")

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


class ClientPlatformOverviewView(APIView):
    """
    GET /api/admin/client-platform-overview/
    Super Admin endpoint for Client Platform Overview.
    Aggregates real-time, accurate multi-platform data:
    - Summary Cards: Total Clients, Web Clients, Android Clients, iOS Clients, Active Clients, Inactive Clients
    - Platform Distribution: Exact counts & percentages for Web, Android, and iOS
    - Client Details List: Business name, owner email, platform badges, device/OS version, app version, last active, account status
    - Server-side filtering by platform, status, search, and activity date range
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

        now = timezone.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)
        ninety_days_ago = now - timedelta(days=90)

        # 1. Fetch all clients and prefetch related data
        clients_qs = Client.objects.all().prefetch_related('users', 'app_installations')

        all_clients_data = []

        for client in clients_qs:
            primary_user = client.users.filter(role='CLIENT').first() or client.users.first()
            owner_email = primary_user.email if primary_user else ''
            owner_name = ''
            if primary_user:
                owner_name = f"{primary_user.first_name} {primary_user.last_name}".strip() or primary_user.username or ''
            if not owner_name:
                owner_name = client.business_name

            # Query all installations linked directly or via users of this client
            installs = list(
                AppInstallation.objects.filter(
                    Q(client=client) | Q(user__client=client)
                ).order_by('-last_active_at')
            )

            platforms_found = []
            has_android = any(i.platform == 'android' for i in installs)
            has_ios = any(i.platform == 'ios' for i in installs)
            has_web_install = any(i.platform == 'web' for i in installs)

            if has_android:
                platforms_found.append('android')
            if has_ios:
                platforms_found.append('ios')

            # Client has Web access if: web installation exists, user has web session, or client has no mobile installs
            has_web = (
                has_web_install or
                (not has_android and not has_ios) or
                bool(primary_user and (primary_user.last_login_browser or primary_user.last_active_at or primary_user.last_login_os))
            )
            if has_web and 'web' not in platforms_found:
                platforms_found.append('web')

            if not platforms_found:
                platforms_found.append('web')

            # Identify latest mobile installation if present
            latest_mobile = next((i for i in installs if i.platform in ['android', 'ios']), None)
            latest_inst = installs[0] if installs else None

            # Primary platform priority: latest active mobile install, or web
            if latest_mobile:
                primary_platform = latest_mobile.platform
                device_model = latest_mobile.device_model or ('Apple iPhone' if primary_platform == 'ios' else 'Android Device')
                os_raw = latest_mobile.os_version
                os_prefix = 'iOS' if primary_platform == 'ios' else 'Android'
                os_version = f"{os_prefix} {os_raw}".strip() if os_raw else os_prefix
                app_version = f"v{latest_mobile.app_version}" if latest_mobile.app_version else "v1.0.0"
                last_active_dt = latest_mobile.last_active_at
            else:
                primary_platform = 'web'
                device_model = (primary_user.last_login_os if primary_user else None) or "Web Desktop/Browser"
                os_version = (primary_user.last_login_browser if primary_user else None) or "Modern Browser"
                app_version = "Web v1.0"
                last_active_dt = (primary_user.last_active_at if primary_user else None) or client.updated_at

            # Check if user's last_active_at is newer
            if primary_user and primary_user.last_active_at:
                if not last_active_dt or primary_user.last_active_at > last_active_dt:
                    last_active_dt = primary_user.last_active_at

            account_status = (client.status or 'ACTIVE').upper()
            is_active = (account_status == 'ACTIVE')

            all_clients_data.append({
                "id": str(client.id),
                "business_name": client.business_name,
                "owner_name": owner_name,
                "owner_email": owner_email,
                "platforms": platforms_found,
                "primary_platform": primary_platform,
                "device_model": device_model,
                "os_version": os_version,
                "app_version": app_version,
                "last_active_at": last_active_dt.isoformat() if last_active_dt else None,
                "last_active_dt": last_active_dt,
                "status": account_status,
                "is_active": is_active,
                "open_count": latest_inst.open_count if latest_inst else 1,
                "created_at": client.created_at.isoformat() if client.created_at else None,
            })

        # 2. Overall Summary Cards calculation (across all unique registered clients)
        total_clients = len(all_clients_data)
        web_clients = sum(1 for c in all_clients_data if 'web' in c['platforms'])
        android_clients = sum(1 for c in all_clients_data if 'android' in c['platforms'])
        ios_clients = sum(1 for c in all_clients_data if 'ios' in c['platforms'])
        active_clients = sum(1 for c in all_clients_data if c['is_active'])
        inactive_clients = total_clients - active_clients

        summary = {
            "total_clients": total_clients,
            "web_clients": web_clients,
            "android_clients": android_clients,
            "ios_clients": ios_clients,
            "active_clients": active_clients,
            "inactive_clients": inactive_clients,
        }

        # 3. Platform Distribution calculation (exact counts & percentages)
        web_pct = round((web_clients / total_clients * 100), 1) if total_clients > 0 else 0.0
        android_pct = round((android_clients / total_clients * 100), 1) if total_clients > 0 else 0.0
        ios_pct = round((ios_clients / total_clients * 100), 1) if total_clients > 0 else 0.0

        distribution = {
            "web": {
                "count": web_clients,
                "percentage": web_pct,
                "label": "Web Clients",
            },
            "android": {
                "count": android_clients,
                "percentage": android_pct,
                "label": "Android App",
            },
            "ios": {
                "count": ios_clients,
                "percentage": ios_pct,
                "label": "iOS / iPhone App",
            },
        }

        # 4. Filter clients for Table Display
        filtered = all_clients_data

        # Platform filter
        if platform_filter != 'ALL':
            target_plat = platform_filter.lower()
            filtered = [c for c in filtered if target_plat in c['platforms']]

        # Status filter
        if status_filter == 'ACTIVE':
            filtered = [c for c in filtered if c['is_active']]
        elif status_filter in ['INACTIVE', 'SUSPENDED', 'PENDING']:
            filtered = [c for c in filtered if not c['is_active']]

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

        # Summary KPIs across ALL installations in DB
        total_installs = qs.count()
        uninstalled_count = qs.filter(is_uninstalled=True).count()
        active_installs = total_installs - uninstalled_count

        web_all = qs.filter(platform='web')
        web_total = web_all.count()
        web_uninstalled = web_all.filter(is_uninstalled=True).count()
        web_active = web_total - web_uninstalled

        android_all = qs.filter(platform='android')
        android_total = android_all.count()
        android_uninstalled = android_all.filter(is_uninstalled=True).count()
        android_active = android_total - android_uninstalled

        ios_all = qs.filter(platform='ios')
        ios_total = ios_all.count()
        ios_uninstalled = ios_all.filter(is_uninstalled=True).count()
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

        # 4. Pagination
        total_count = filtered_qs.count()
        total_pages = max(1, (total_count + page_size - 1) // page_size)
        start_idx = (page - 1) * page_size
        end_idx = start_idx + page_size
        page_items = filtered_qs[start_idx:end_idx]

        records = []
        for inst in page_items:
            client = inst.client or (inst.user.client if inst.user and hasattr(inst.user, 'client') else None)
            user_obj = inst.user
            user_name = ''
            if user_obj:
                user_name = f"{user_obj.first_name} {user_obj.last_name}".strip() or user_obj.username or user_obj.email
            elif client:
                user_name = client.business_name
            else:
                user_name = 'Anonymous Device'

            user_email = user_obj.email if user_obj else (client.phone_number if client else '')

            records.append({
                "id": str(inst.id),
                "installation_id": inst.installation_id,
                "platform": inst.platform,
                "app_version": inst.app_version or '1.0.0',
                "os_version": inst.os_version or 'N/A',
                "device_model": inst.device_model or ('Apple iPhone' if inst.platform == 'ios' else ('Android Device' if inst.platform == 'android' else 'Web Browser')),
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

        return Response({
            "success": True,
            "summary": summary,
            "installations": records,
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

        return Response({
            "success": True,
            "installation_id": inst.installation_id,
            "is_uninstalled": True,
            "uninstalled_at": inst.uninstalled_at.isoformat(),
            "message": "Installation record marked as uninstalled."
        }, status=status.HTTP_200_OK)


