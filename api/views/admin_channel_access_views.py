import json
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.shortcuts import get_object_or_404
from django.utils import timezone
from api.models import (
    Client, User, GlobalConnector, ClientConnectorAccess,
    TeamMemberConnectorAccess, ChannelAuditLog
)
from api.utils.channel_permissions import (
    DEFAULT_CONNECTORS,
    ensure_default_global_connectors,
    is_connector_globally_active,
    get_client_connector_permission,
    get_team_member_connector_permission,
    check_effective_connector_access,
    get_user_effective_connectors,
    log_channel_permission_change
)

from ..repositories.client_repository import ClientRepository


def check_admin_privileges(user):
    if not user or not user.is_authenticated:
        return False
    role = getattr(user, 'role', '').upper()
    enterprise_role = getattr(user, 'enterprise_role', '').upper()
    return (
        role == 'ADMIN' or
        enterprise_role in ('SUPER_ADMIN', 'ORG_ADMIN', 'ADMIN') or
        getattr(user, 'is_staff', False) or
        getattr(user, 'is_superuser', False)
    )


def get_client_by_id(client_id):
    try:
        c = ClientRepository.get_client(id=client_id)
        if c:
            return c
    except Exception:
        pass
    try:
        return Client.objects.filter(id=client_id).first()
    except Exception:
        return None


class AdminGlobalConnectorsView(APIView):
    """
    SECTION 1: GLOBAL CHANNEL / CONNECTOR CONTROL
    Allows Admin to view and globally activate/deactivate every connector.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not check_admin_privileges(request.user):
            return Response({"error": "Admin privileges required."}, status=status.HTTP_403_FORBIDDEN)

        ensure_default_global_connectors()
        connectors = list(GlobalConnector.objects.all())
        all_clients = list(Client.objects.all())
        all_members = list(User.objects.filter(role__in=['AGENT', 'EMPLOYEE', 'CLIENT']))

        # Cache permissions in memory
        client_perms_map = {}
        for cca in ClientConnectorAccess.objects.all():
            client_perms_map[(str(cca.client_id), cca.connector_key)] = cca.is_enabled

        member_perms_map = {}
        for tmca in TeamMemberConnectorAccess.objects.all():
            member_perms_map[(str(tmca.client_id), str(tmca.team_member_id), tmca.connector_key)] = tmca.is_enabled

        now = timezone.now()
        results = []
        for c in connectors:
            # Auto-activate if schedule has arrived
            sched = getattr(c, 'scheduled_live_at', None)
            if not c.is_active and sched and sched <= now:
                c.is_active = True
                c.scheduled_live_at = None
                c.updated_by = 'System Scheduler'
                c.save()

            key = c.connector_key
            
            # Count clients using this connector
            client_access_count = 0
            for cl in all_clients:
                cid = str(cl.id)
                if (cid, key) in client_perms_map:
                    if client_perms_map[(cid, key)]:
                        client_access_count += 1
                elif cl.has_channel_access(key):
                    client_access_count += 1

            # Count team members who have permission for this connector
            member_access_count = 0
            for m in all_members:
                cid = str(m.client_id) if getattr(m, 'client_id', None) else None
                if cid:
                    mid = str(m.id)
                    if (cid, mid, key) in member_perms_map:
                        if member_perms_map[(cid, mid, key)]:
                            member_access_count += 1
                    else:
                        # Fallback to client level
                        if (cid, key) in client_perms_map:
                            if client_perms_map[(cid, key)]:
                                member_access_count += 1
                        else:
                            try:
                                if m.client and m.client.has_channel_access(key):
                                    member_access_count += 1
                            except Exception:
                                pass

            from api.utils.channel_permissions import get_item_type
            item_type = get_item_type(c.connector_key, c.category, c.is_core)

            results.append({
                'id': str(c.id),
                'key': c.connector_key,
                'name': c.name,
                'short_name': c.short_name or c.name,
                'category': c.category,
                'item_type': item_type,
                'is_core': c.is_core,
                'is_active': c.is_active,
                'scheduled_live_at': c.scheduled_live_at.isoformat() if getattr(c, 'scheduled_live_at', None) else None,
                'description': c.description,
                'clients_using_count': client_access_count,
                'team_members_count': member_access_count,
                'updated_by': c.updated_by,
                'updated_at': c.updated_at.isoformat() if c.updated_at else None
            })

        channels = [x for x in results if x.get('item_type') == 'channel']
        connectors_list = [x for x in results if x.get('item_type') == 'connector']
        features = [x for x in results if x.get('item_type') == 'feature']

        return Response({
            'connectors': results,  # legacy key
            'items': results,
            'channels': channels,
            'connectors_list': connectors_list,
            'features': features,
            'counts': {
                'channels': len(channels),
                'connectors': len(connectors_list),
                'features': len(features),
                'total': len(results),
                'active': sum(1 for x in results if x['is_active']),
                'inactive': sum(1 for x in results if not x['is_active'])
            },
            'total_active': sum(1 for x in results if x['is_active']),
            'total_inactive': sum(1 for x in results if not x['is_active'])
        })

    def patch(self, request, connector_key=None):
        if not check_admin_privileges(request.user):
            return Response({"error": "Admin privileges required."}, status=status.HTTP_403_FORBIDDEN)

        key = connector_key or request.data.get('connector_key')
        if not key:
            return Response({"error": "Connector key is required."}, status=status.HTTP_400_BAD_REQUEST)

        key = str(key).lower().strip()
        ensure_default_global_connectors()

        clean_k = key.replace('feature_', '').replace('connector_', '').replace('channel_', '')
        gc = (
            GlobalConnector.objects.filter(connector_key=key).first() or
            GlobalConnector.objects.filter(connector_key=clean_k).first()
        )

        if not gc:
            # Check Feature table and sync to GlobalConnector
            from api.models import Feature
            feat = (
                Feature.objects.filter(key=key).first() or
                Feature.objects.filter(key=clean_k).first() or
                Feature.objects.filter(key=f"feature_{clean_k}").first()
            )
            if feat:
                from api.utils.channel_permissions import get_item_type
                gc = GlobalConnector.objects.create(
                    connector_key=clean_k,
                    name=feat.name,
                    short_name=feat.name,
                    category=feat.category or 'FEATURE',
                    is_active=feat.status == 'ACTIVE',
                    is_core=False,
                    description=feat.description or ''
                )
            else:
                return Response({"error": f"Item '{key}' not found."}, status=status.HTTP_404_NOT_FOUND)

        prev_state = {
            'is_active': gc.is_active,
            'scheduled_live_at': gc.scheduled_live_at.isoformat() if getattr(gc, 'scheduled_live_at', None) else None
        }

        # Handle scheduled_live_at
        if 'scheduled_live_at' in request.data:
            sched_val = request.data.get('scheduled_live_at')
            if sched_val:
                try:
                    from django.utils.dateparse import parse_datetime
                    import datetime
                    parsed_dt = parse_datetime(sched_val)
                    if not parsed_dt:
                        parsed_dt = datetime.datetime.fromisoformat(sched_val)
                    if timezone.is_naive(parsed_dt):
                        parsed_dt = timezone.make_aware(parsed_dt)
                    gc.scheduled_live_at = parsed_dt
                    if 'is_active' not in request.data:
                        gc.is_active = False
                except Exception as e:
                    return Response({"error": f"Invalid date format: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)
            else:
                gc.scheduled_live_at = None

        if 'is_active' in request.data:
            is_active = request.data.get('is_active')
            gc.is_active = bool(is_active)
            if gc.is_active:
                gc.scheduled_live_at = None
        elif 'scheduled_live_at' not in request.data:
            # Toggle if neither is explicitly passed
            gc.is_active = not gc.is_active
            if gc.is_active:
                gc.scheduled_live_at = None

        gc.updated_by = request.user.username or request.user.email or 'Admin'
        gc.updated_at = timezone.now()
        gc.save()

        # Synchronize corresponding entries in Feature model
        try:
            from api.models import Feature
            feat_keys = [gc.connector_key, clean_k, f"feature_{clean_k}", f"connector_{clean_k}", f"channel_{clean_k}"]
            for f in Feature.objects.filter(key__in=feat_keys):
                f.status = 'ACTIVE' if gc.is_active else 'INACTIVE'
                f.is_coming_soon = not gc.is_active
                f.save()
        except Exception as sync_err:
            print(f"[AdminGlobalConnectorsView] Feature sync error: {sync_err}")

        # Invalidate all channel permission caches
        from api.utils.channel_permissions import clear_channel_permissions_cache
        clear_channel_permissions_cache()

        # Log in Audit Log
        action = 'GLOBAL_ACTIVATED' if gc.is_active else ('SCHEDULED_LIVE' if gc.scheduled_live_at else 'GLOBAL_DEACTIVATED')
        log_channel_permission_change(
            admin_user_identifier=request.user.username or request.user.email,
            client=None,
            channel=gc.connector_key,
            action=action,
            previous_state=prev_state,
            new_state={
                'is_active': gc.is_active,
                'scheduled_live_at': gc.scheduled_live_at.isoformat() if gc.scheduled_live_at else None
            },
            notes=request.data.get('notes', f"Global status updated (Active: {gc.is_active}, Scheduled: {gc.scheduled_live_at})")
        )

        from api.utils.channel_permissions import get_item_type
        return Response({
            'success': True,
            'connector': {
                'key': gc.connector_key,
                'name': gc.name,
                'item_type': get_item_type(gc.connector_key, gc.category, gc.is_core),
                'is_active': gc.is_active,
                'scheduled_live_at': gc.scheduled_live_at.isoformat() if gc.scheduled_live_at else None,
                'updated_by': gc.updated_by,
                'updated_at': gc.updated_at.isoformat()
            }
        })


class AdminChannelAccessMatrixView(APIView):
    """
    SECTION 8: CURRENT CHANNEL MATRIX & SUMMARY STATS
    Returns global channel matrix for all clients, real-time KPI counts, and connector locks.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not check_admin_privileges(request.user):
            return Response({"error": "Admin privileges required."}, status=status.HTTP_403_FORBIDDEN)

        ensure_default_global_connectors()
        global_connectors_map = {gc.connector_key: gc.is_active for gc in GlobalConnector.objects.all()}

        clients = list(Client.objects.all().order_by('-created_at'))
        search = request.query_params.get('search', '').strip().lower()
        channel_filter = request.query_params.get('channel', '').strip().lower()
        status_filter = request.query_params.get('status', '').strip().upper()

        total_wa_enabled = 0
        total_fb_enabled = 0
        total_ig_enabled = 0

        # Pre-cache client connector permissions
        client_perms_map = {}
        for cca in ClientConnectorAccess.objects.all():
            client_perms_map[(str(cca.client_id), cca.connector_key)] = cca.is_enabled

        results = []
        for client in clients:
            if search:
                matches = (
                    search in (client.business_name or '').lower() or
                    search in str(client.id) or
                    search in (client.phone_number or '').lower() or
                    search in (getattr(client.owner, 'email', '') or '').lower() or
                    search in (getattr(client.owner, 'username', '') or '').lower()
                )
                if not matches:
                    continue

            # Connection calculations
            is_wa_connected = bool(
                client.whatsapp_access_token and client.whatsapp_phone_number_id or
                client.whatsapp_waba_id
            )
            is_fb_connected = bool(
                client.facebook_enabled or 
                (client.facebook_config and client.facebook_config.get('page_id'))
            )
            is_ig_connected = bool(
                client.instagram_enabled or
                (client.instagram_config and (client.instagram_config.get('instagram_business_id') or client.instagram_config.get('username')))
            )

            # Build full channel access dictionary with cached checks
            cid = str(client.id)
            access_dict = {}
            for item in DEFAULT_CONNECTORS:
                ckey = item['key']
                if (cid, ckey) in client_perms_map:
                    client_perm = client_perms_map[(cid, ckey)]
                else:
                    client_perm = client.has_channel_access(ckey)
                access_dict[ckey] = client_perm

            if access_dict.get('whatsapp'):
                total_wa_enabled += 1
            if access_dict.get('facebook'):
                total_fb_enabled += 1
            if access_dict.get('instagram'):
                total_ig_enabled += 1

            # Channel filter check
            if channel_filter and channel_filter != 'all':
                if not access_dict.get(channel_filter):
                    continue

            # Status filter check
            if status_filter == 'ACTIVE' and client.status != 'ACTIVE':
                continue
            if status_filter == 'INACTIVE' and client.status == 'ACTIVE':
                continue

            # Team member count
            team_count = client.users.count()

            # Latest audit log
            latest_log = client.channel_audit_logs.first()
            last_audit_data = None
            if latest_log:
                last_audit_data = {
                    'admin': latest_log.admin_user,
                    'action': latest_log.action,
                    'channel': latest_log.channel,
                    'timestamp': latest_log.timestamp.isoformat()
                }

            owner_user = getattr(client, 'owner', None)
            owner_email = owner_user.email if owner_user else (getattr(client, 'email', '') or '')

            results.append({
                'client_id': str(client.id),
                'client_name': client.business_name,
                'business_name': client.business_name,
                'owner_name': owner_user.username if owner_user else (client.business_name or 'Owner'),
                'email': owner_email,
                'phone_number': getattr(client, 'phone_number', ''),
                'plan': getattr(client, 'plan', 'BASIC'),
                'status': getattr(client, 'status', 'ACTIVE'),
                'team_members_count': team_count,
                'channel_access': access_dict,
                'channels_status': {
                    'whatsapp': {'connected': is_wa_connected},
                    'facebook': {'connected': is_fb_connected},
                    'instagram': {'connected': is_ig_connected}
                },
                'last_audit': last_audit_data
            })

        global_active_count = sum(1 for is_act in global_connectors_map.values() if is_act)
        global_inactive_count = len(global_connectors_map) - global_active_count

        return Response({
            'summary': {
                'total_clients': len(clients),
                'whatsapp_enabled_count': total_wa_enabled,
                'facebook_enabled_count': total_fb_enabled,
                'instagram_enabled_count': total_ig_enabled,
                'global_active_count': global_active_count,
                'global_inactive_count': global_inactive_count
            },
            'global_connectors': global_connectors_map,
            'clients': results
        })


class AdminClientChannelAccessDetailView(APIView):
    """
    SECTION 3 & 6: CLIENT-SPECIFIC & TEAM MEMBER CONNECTOR ACCESS
    Get or modify channel access and team member assignments for a single client.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, client_id):
        if not check_admin_privileges(request.user):
            return Response({"error": "Admin privileges required."}, status=status.HTTP_403_FORBIDDEN)

        client = get_client_by_id(client_id)
        if not client:
            return Response({"error": "Client not found."}, status=status.HTTP_404_NOT_FOUND)

        ensure_default_global_connectors()
        global_connectors = {gc.connector_key: gc.is_active for gc in GlobalConnector.objects.all()}

        # Build connector access details
        connectors_info = []
        for item in DEFAULT_CONNECTORS:
            ckey = item['key']
            g_active = global_connectors.get(ckey, True)
            c_enabled = get_client_connector_permission(client, ckey)

            connectors_info.append({
                'key': ckey,
                'name': item['name'],
                'short_name': item.get('short_name', item['name']),
                'category': item.get('category', 'MESSAGING'),
                'is_core': item.get('is_core', False),
                'global_active': g_active,
                'client_enabled': c_enabled,
                'description': item.get('description', '')
            })

        # Fetch client's team members
        team_members_data = []
        team_members = client.users.all()
        for member in team_members:
            member_permissions = {}
            for item in DEFAULT_CONNECTORS:
                ckey = item['key']
                member_permissions[ckey] = get_team_member_connector_permission(client, member, ckey)

            team_members_data.append({
                'id': str(member.id),
                'username': member.username,
                'first_name': member.first_name,
                'last_name': member.last_name,
                'email': member.email,
                'role': member.role,
                'enterprise_role': member.enterprise_role or member.role,
                'connector_permissions': member_permissions
            })

        return Response({
            'client_id': str(client.id),
            'business_name': client.business_name,
            'email': getattr(client.owner, 'email', '') if getattr(client, 'owner', None) else (getattr(client, 'email', '') or ''),
            'connectors': connectors_info,
            'team_members': team_members_data
        })

    def post(self, request, client_id):
        """
        Save Client-Level permissions and/or Team Member assignments.
        """
        if not check_admin_privileges(request.user):
            return Response({"error": "Admin privileges required."}, status=status.HTTP_403_FORBIDDEN)

        client = get_client_by_id(client_id)
        if not client:
            return Response({"error": "Client not found."}, status=status.HTTP_404_NOT_FOUND)

        admin_identifier = request.user.username or request.user.email or 'Admin'
        notes = request.data.get('notes', 'Channel access updated via Admin Panel')

        # 1. Update Client-Level Channel Access
        client_permissions = request.data.get('channel_access') or request.data.get('client_permissions')
        if isinstance(client_permissions, dict):
            channel_access_dict = client.channel_access if isinstance(client.channel_access, dict) else {}

            for ckey, is_enabled in client_permissions.items():
                ckey = str(ckey).lower().strip()
                val = bool(is_enabled)
                prev_val = get_client_connector_permission(client, ckey)

                if prev_val != val:
                    # Update or create ClientConnectorAccess
                    cca, _ = ClientConnectorAccess.objects.get_or_create(
                        client=client,
                        connector_key=ckey,
                        defaults={'is_enabled': val, 'updated_by': admin_identifier}
                    )
                    cca.is_enabled = val
                    cca.updated_by = admin_identifier
                    cca.save()

                    # Also sync Client model dict and boolean fields
                    channel_access_dict[ckey] = val
                    if ckey == 'whatsapp':
                        client.whatsapp_enabled = val
                    elif hasattr(client, f"{ckey}_enabled"):
                        setattr(client, f"{ckey}_enabled", val)

                    # Log in Audit Log
                    log_channel_permission_change(
                        admin_user_identifier=admin_identifier,
                        client=client,
                        channel=ckey,
                        action='ACCESS_GRANTED' if val else 'ACCESS_REVOKED',
                        previous_state={'is_enabled': prev_val},
                        new_state={'is_enabled': val},
                        notes=notes
                    )

            client.channel_access = channel_access_dict
            client.save()

        # 2. Update Team Member Connector Assignments
        team_member_assignments = request.data.get('team_member_assignments')
        # Structure: { member_id: { whatsapp: true, facebook: false, ... } }
        if isinstance(team_member_assignments, dict):
            for member_id, perms in team_member_assignments.items():
                member = client.users.filter(id=member_id).first()
                if not member or not isinstance(perms, dict):
                    continue

                for ckey, is_enabled in perms.items():
                    ckey = str(ckey).lower().strip()
                    val = bool(is_enabled)
                    prev_val = get_team_member_connector_permission(client, member, ckey)

                    if prev_val != val:
                        tmca, _ = TeamMemberConnectorAccess.objects.get_or_create(
                            client=client,
                            team_member=member,
                            connector_key=ckey,
                            defaults={'is_enabled': val, 'updated_by': admin_identifier}
                        )
                        tmca.is_enabled = val
                        tmca.updated_by = admin_identifier
                        tmca.save()

                        # Log in Audit Log
                        log_channel_permission_change(
                            admin_user_identifier=admin_identifier,
                            client=client,
                            channel=ckey,
                            action='MEMBER_ASSIGNED' if val else 'MEMBER_REVOKED',
                            previous_state={'is_enabled': prev_val},
                            new_state={'is_enabled': val},
                            team_member=member,
                            team_member_name=member.username,
                            notes=f"Team member access updated for {member.username}"
                        )

        return Response({
            'success': True,
            'message': 'Channel access and team assignments saved successfully.'
        })

    def patch(self, request, client_id):
        """
        Quick toggle single channel for client.
        """
        channel = request.data.get('channel')
        enabled = request.data.get('enabled')
        if channel is None or enabled is None:
            return Response({"error": "channel and enabled fields required."}, status=status.HTTP_400_BAD_REQUEST)

        return self.post(request, client_id)


class AdminBulkChannelAccessView(APIView):
    """
    SECTION 9: BULK ACCESS MANAGEMENT
    Enable or disable connectors across multiple clients in one batch.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not check_admin_privileges(request.user):
            return Response({"error": "Admin privileges required."}, status=status.HTTP_403_FORBIDDEN)

        client_ids = request.data.get('client_ids', [])
        channel = str(request.data.get('channel', '')).lower().strip()
        action = str(request.data.get('action', '')).lower().strip() # 'grant' or 'revoke'
        notes = request.data.get('notes', f"Bulk {action} for {channel}")

        if not client_ids or not channel or action not in ('grant', 'revoke'):
            return Response({
                "error": "client_ids list, channel, and action ('grant'/'revoke') are required."
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate that connector is globally active before granting
        if action == 'grant' and not is_connector_globally_active(channel):
            return Response({
                "error": f"Cannot enable '{channel}' because it is currently disabled globally by Admin."
            }, status=status.HTTP_400_BAD_REQUEST)

        new_val = (action == 'grant')
        admin_identifier = request.user.username or request.user.email or 'Admin'
        updated_count = 0

        for cid in client_ids:
            client = get_client_by_id(cid)
            if not client:
                continue

            prev_val = get_client_connector_permission(client, channel)
            if prev_val != new_val:
                cca, _ = ClientConnectorAccess.objects.get_or_create(
                    client=client,
                    connector_key=channel,
                    defaults={'is_enabled': new_val, 'updated_by': admin_identifier}
                )
                cca.is_enabled = new_val
                cca.updated_by = admin_identifier
                cca.save()

                ca_dict = client.channel_access if isinstance(client.channel_access, dict) else {}
                ca_dict[channel] = new_val
                client.channel_access = ca_dict
                if channel == 'whatsapp':
                    client.whatsapp_enabled = new_val
                elif hasattr(client, f"{channel}_enabled"):
                    setattr(client, f"{channel}_enabled", new_val)
                client.save()

                log_channel_permission_change(
                    admin_user_identifier=admin_identifier,
                    client=client,
                    channel=channel,
                    action='BULK_GRANTED' if new_val else 'BULK_REVOKED',
                    previous_state={'is_enabled': prev_val},
                    new_state={'is_enabled': new_val},
                    notes=notes
                )
                updated_count += 1

        return Response({
            'success': True,
            'updated_count': updated_count,
            'message': f"Successfully updated {updated_count} client(s) for {channel}."
        })


class AdminChannelAuditLogsView(APIView):
    """
    SECTION 16: AUDIT LOG
    Returns complete permission audit trail.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not check_admin_privileges(request.user):
            return Response({"error": "Admin privileges required."}, status=status.HTTP_403_FORBIDDEN)

        logs = ChannelAuditLog.objects.all().order_by('-timestamp')[:200]
        results = []
        for l in logs:
            results.append({
                'id': str(l.id),
                'admin_user': l.admin_user,
                'client_name': l.client.business_name if l.client else (l.client_name or 'Global'),
                'client_id': str(l.client.id) if l.client else None,
                'team_member_name': l.team_member_name or (l.team_member.username if l.team_member else None),
                'channel': l.channel,
                'action': l.action,
                'previous_state': l.previous_state,
                'new_state': l.new_state,
                'notes': l.notes,
                'timestamp': l.timestamp.isoformat()
            })

        return Response({
            'total_logs': ChannelAuditLog.objects.count(),
            'audit_logs': results
        })


class EffectiveConnectorsView(APIView):
    """
    SECTION 13 & 14: EFFECTIVE CONNECTORS FOR CLIENT & TEAM MEMBER DASHBOARDS
    Returns only the connectors that the currently logged-in user has permission to access.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        effective_map = get_user_effective_connectors(request.user)
        return Response({
            'effective_connectors': effective_map,
            'allowed_channel_keys': [k for k, v in effective_map.items() if v['effective_access']]
        })


class GlobalConnectorsStatusView(APIView):
    """
    Simple, direct endpoint returning live global_connectors active/coming soon status map for all clients and mobile app.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        ensure_default_global_connectors()
        now = timezone.now()
        gc_list = GlobalConnector.objects.all()
        g_map = {}
        for gc in gc_list:
            if not gc.is_active and gc.scheduled_live_at and gc.scheduled_live_at <= now:
                gc.is_active = True
                gc.scheduled_live_at = None
                gc.save()
            g_map[gc.connector_key] = bool(gc.is_active)
        return Response({
            "global_connectors": g_map,
            "status_map": {k: ("ACTIVE" if v else "COMING_SOON") for k, v in g_map.items()}
        })
