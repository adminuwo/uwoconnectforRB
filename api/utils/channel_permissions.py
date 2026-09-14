"""
Centralized Channel & Connector Access Governance Architecture for UWO CONNECT
Enforces strict 3-level permission hierarchy:
Level 1: GLOBAL ADMIN STATUS
Level 2: CLIENT CONNECTOR ACCESS
Level 3: TEAM MEMBER CONNECTOR ASSIGNMENT
"""

from django.utils import timezone

DEFAULT_CONNECTORS = [
    # Core Channels
    {
        'key': 'whatsapp',
        'name': 'WhatsApp Business',
        'short_name': 'WhatsApp',
        'category': 'CORE',
        'is_core': True,
        'is_active': True,
        'description': 'Official WhatsApp Business Cloud API for automated conversations, broadcasts, and support bots.'
    },
    {
        'key': 'facebook',
        'name': 'Facebook Messenger',
        'short_name': 'Facebook',
        'category': 'CORE',
        'is_core': True,
        'is_active': True,
        'description': 'Connect official Facebook Business Pages for visitor inquiries, auto-replies, and lead acquisition.'
    },
    {
        'key': 'instagram',
        'name': 'Instagram Direct',
        'short_name': 'Instagram',
        'category': 'CORE',
        'is_core': True,
        'is_active': True,
        'description': 'Automate Instagram Direct Messages, story mentions, and comment-to-DM triggers.'
    },

    # Productivity, Storage & CRM Connectors
    {
        'key': 'gmail',
        'name': 'Gmail / Google Workspace',
        'short_name': 'Gmail',
        'category': 'EMAIL',
        'is_core': False,
        'is_active': True,
        'description': 'Sync Gmail inbox, send auto-responses, and trigger workflows on incoming customer emails.'
    },
    {
        'key': 'outlook',
        'name': 'Microsoft Outlook',
        'short_name': 'Outlook',
        'category': 'EMAIL',
        'is_core': False,
        'is_active': True,
        'description': 'Corporate email synchronization, calendar booking, and automated email ticketing.'
    },
    {
        'key': 'onedrive',
        'name': 'Microsoft OneDrive',
        'short_name': 'OneDrive',
        'category': 'STORAGE',
        'is_core': False,
        'is_active': True,
        'description': 'Secure enterprise cloud storage for automated PDF invoice and receipt synchronization.'
    },
    {
        'key': 'google_calendar',
        'name': 'Google Calendar',
        'short_name': 'G-Calendar',
        'category': 'EMAIL',
        'is_core': False,
        'is_active': True,
        'description': 'Auto-book customer consultations, team meetings, and appointment reminders.'
    },
    {
        'key': 'google_sheets',
        'name': 'Google Sheets',
        'short_name': 'G-Sheets',
        'category': 'STORAGE',
        'is_core': False,
        'is_active': True,
        'description': 'Export incoming leads, order logs, and chat transcripts directly to Google Sheets.'
    },
    {
        'key': 'google_docs',
        'name': 'Google Docs',
        'short_name': 'G-Docs',
        'category': 'STORAGE',
        'is_core': False,
        'is_active': True,
        'description': 'Auto-generate agreements, proposals, and customer reports in Google Docs.'
    },
    {
        'key': 'google_slides',
        'name': 'Google Slides',
        'short_name': 'G-Slides',
        'category': 'MEDIA',
        'is_core': False,
        'is_active': True,
        'description': 'Create customized client presentations and pitch decks dynamically.'
    },
    {
        'key': 'zoho',
        'name': 'Zoho CRM',
        'short_name': 'Zoho CRM',
        'category': 'CRM',
        'is_core': False,
        'is_active': True,
        'description': 'Sync customer chats and orders into Zoho CRM module contacts and deals.'
    },
    {
        'key': 'youtube',
        'name': 'YouTube Channel',
        'short_name': 'YouTube',
        'category': 'MEDIA',
        'is_core': False,
        'is_active': True,
        'description': 'Sync video comments, live stream chat moderation, and automated community replies.'
    },
    {
        'key': 'google_news',
        'name': 'Google News Feed',
        'short_name': 'G-News',
        'category': 'MEDIA',
        'is_core': False,
        'is_active': True,
        'description': 'Monitor brand keywords, press releases, and market intelligence alerts.'
    },
]

GLOBAL_ALL_CHANNELS = [c['key'] for c in DEFAULT_CONNECTORS]
GLOBAL_AVAILABLE_CHANNELS = ['whatsapp', 'facebook', 'instagram']
GLOBAL_COMING_SOON_CHANNELS = []


_CONNECTORS_ENSURED = False
_GLOBAL_CONNECTORS_CACHE = {'timestamp': 0.0, 'active_keys': set()}
_USER_ALLOWED_CHANNELS_CACHE = {}  # key: (user_id_str, client_id_str) -> (timestamp, allowed_list)
_CACHE_TTL = 60.0  # 60 seconds TTL


def clear_channel_permissions_cache(user_id=None, client_id=None):
    """
    Clears in-memory caches. If user_id/client_id provided, clears specific entry,
    otherwise clears all caches.
    """
    global _GLOBAL_CONNECTORS_CACHE, _USER_ALLOWED_CHANNELS_CACHE
    if user_id or client_id:
        keys_to_delete = [
            k for k in _USER_ALLOWED_CHANNELS_CACHE.keys()
            if (user_id and k[0] == str(user_id)) or (client_id and k[1] == str(client_id))
        ]
        for k in keys_to_delete:
            _USER_ALLOWED_CHANNELS_CACHE.pop(k, None)
    else:
        _USER_ALLOWED_CHANNELS_CACHE.clear()
        _GLOBAL_CONNECTORS_CACHE = {'timestamp': 0.0, 'active_keys': set()}


def ensure_default_global_connectors():
    """
    Seeds/Ensures all default global connectors exist in the database.
    Guarded by memory flag to avoid redundant DB queries on every request.
    """
    global _CONNECTORS_ENSURED
    if _CONNECTORS_ENSURED:
        return

    try:
        from api.models import GlobalConnector
        existing_keys = set(GlobalConnector.objects.values_list('connector_key', flat=True))
        for item in DEFAULT_CONNECTORS:
            if item['key'] not in existing_keys:
                GlobalConnector.objects.create(
                    connector_key=item['key'],
                    name=item['name'],
                    short_name=item.get('short_name', item['name']),
                    category=item.get('category', 'MESSAGING'),
                    is_core=item.get('is_core', False),
                    is_active=item.get('is_active', True),
                    description=item.get('description', '')
                )
        _CONNECTORS_ENSURED = True
    except Exception as e:
        print(f"[GlobalConnector] Error seeding connectors: {e}")


def _get_cached_global_active_keys():
    """
    Returns set of lowercase connector keys that are globally active, cached for 60s.
    """
    global _GLOBAL_CONNECTORS_CACHE
    import time
    now = time.time()
    if now - _GLOBAL_CONNECTORS_CACHE['timestamp'] < _CACHE_TTL and _GLOBAL_CONNECTORS_CACHE['active_keys']:
        return _GLOBAL_CONNECTORS_CACHE['active_keys']

    try:
        from api.models import GlobalConnector
        records = list(GlobalConnector.objects.all().values('connector_key', 'is_active'))
        if not records:
            ensure_default_global_connectors()
            records = list(GlobalConnector.objects.all().values('connector_key', 'is_active'))

        active_keys = {
            r['connector_key'].lower().strip()
            for r in records
            if r.get('is_active', True)
        }
        _GLOBAL_CONNECTORS_CACHE = {'timestamp': now, 'active_keys': active_keys}
        return active_keys
    except Exception as e:
        print(f"[_get_cached_global_active_keys] Error: {e}")
        # Default fallback to all default connectors
        return {c['key'] for c in DEFAULT_CONNECTORS}


def is_connector_globally_active(connector_key):
    """
    LEVEL 1 CHECK: Returns True if connector is globally active.
    Uses in-memory cached active set (0ms).
    """
    if not connector_key:
        return False
    key = str(connector_key).lower().strip()
    active_keys = _get_cached_global_active_keys()
    return key in active_keys


def get_client_connector_permission(client, connector_key):
    """
    LEVEL 2 CHECK: Returns True if client workspace has permission for this connector.
    """
    if not client or not connector_key:
        return False
    key = str(connector_key).lower().strip()
    try:
        from api.models import ClientConnectorAccess
        cca = ClientConnectorAccess.objects.filter(client=client, connector_key=key).first()
        if cca is not None:
            return bool(cca.is_enabled)
        # Fallback to Client model method
        if hasattr(client, 'has_channel_access'):
            return client.has_channel_access(key)
    except Exception as e:
        print(f"[get_client_connector_permission] Error: {e}")
        if hasattr(client, 'has_channel_access'):
            return client.has_channel_access(key)
    return True


def get_team_member_connector_permission(client, team_member, connector_key):
    """
    LEVEL 3 CHECK: Returns True if specific team member is granted access to this connector.
    """
    if not team_member or not connector_key:
        return False
    key = str(connector_key).lower().strip()

    # Client owner / manager always has full member-level permission
    role = getattr(team_member, 'role', '').upper()
    enterprise_role = getattr(team_member, 'enterprise_role', '').upper()
    if role in ('ADMIN', 'CLIENT') or enterprise_role in ('SUPER_ADMIN', 'ORG_ADMIN', 'MANAGER', 'HR'):
        return True

    try:
        from api.models import TeamMemberConnectorAccess
        tmca = TeamMemberConnectorAccess.objects.filter(
            client=client,
            team_member=team_member,
            connector_key=key
        ).first()
        if tmca is not None:
            return bool(tmca.is_enabled)

        # Fallback to legacy assigned_social_channels on User model
        assigned = getattr(team_member, 'assigned_social_channels', []) or []
        if assigned:
            return any(key in str(a).lower() or str(a).lower() in key for a in assigned)
    except Exception as e:
        print(f"[get_team_member_connector_permission] Error: {e}")

    # Default to True (inherited from client) if no granular restriction configured
    return True


def check_effective_connector_access(user, connector_key):
    """
    Hierarchical master check:
    Effective = Global Active AND Client Enabled AND Team Member Assigned
    """
    if not user or not user.is_authenticated:
        return False, "Authentication required.", 401

    key = str(connector_key).lower().strip()

    # Super Admin bypass
    role = getattr(user, 'role', '').upper()
    enterprise_role = getattr(user, 'enterprise_role', '').upper()
    if role == 'ADMIN' or enterprise_role in ('SUPER_ADMIN', 'ORG_ADMIN') or getattr(user, 'is_staff', False):
        return True, None, 200

    # Level 1: Global Admin Status
    if not is_connector_globally_active(key):
        return False, f"{key.capitalize()} is globally disabled by Admin.", 403

    # Level 2: Client Access Check
    try:
        client = getattr(user, 'client', None)
    except Exception:
        client = None

    if not client:
        return False, "No active client workspace associated with this user.", 403

    if not get_client_connector_permission(client, key):
        return False, f"Access to {key.capitalize()} is disabled for this workspace.", 403

    # Level 3: Team Member Granular Check
    if not get_team_member_connector_permission(client, user, key):
        return False, f"You do not have team member permission to access {key.capitalize()}.", 403

    return True, None, 200


def validate_channel_access(user, channel_name):
    """
    Backwards-compatible wrapper for check_effective_connector_access.
    """
    return check_effective_connector_access(user, channel_name)


def get_user_allowed_channels(user, client=None):
    """
    Returns list of uppercase channel names that user is currently permitted to access.
    Optimized with in-memory TTL caching and single-batch queries instead of 40 individual queries.
    """
    if not user or not user.is_authenticated:
        return []

    target_client = client
    if not target_client:
        try:
            target_client = getattr(user, 'client', None)
        except Exception:
            target_client = None

    if not target_client:
        return []

    import time
    now = time.time()
    cache_key = (str(getattr(user, 'id', '')), str(getattr(target_client, 'id', '')))
    cached = _USER_ALLOWED_CHANNELS_CACHE.get(cache_key)
    if cached and (now - cached[0] < _CACHE_TTL):
        return list(cached[1])

    role = getattr(user, 'role', '').upper()
    enterprise_role = getattr(user, 'enterprise_role', '').upper()
    is_admin = role == 'ADMIN' or enterprise_role in ('SUPER_ADMIN', 'ORG_ADMIN') or getattr(user, 'is_staff', False)

    active_keys = _get_cached_global_active_keys()

    if is_admin:
        allowed = [c['key'].upper() for c in DEFAULT_CONNECTORS if c['key'] in active_keys]
        _USER_ALLOWED_CHANNELS_CACHE[cache_key] = (now, allowed)
        return allowed

    # 1. Bulk fetch client connector access in 1 single query
    client_perms = {}
    try:
        from api.models import ClientConnectorAccess
        for cca in ClientConnectorAccess.objects.filter(client=target_client):
            client_perms[cca.connector_key.lower().strip()] = bool(cca.is_enabled)
    except Exception as e:
        print(f"[get_user_allowed_channels] ClientConnectorAccess query error: {e}")

    # 2. Bulk fetch team member permissions in 1 single query if granular check needed
    is_owner_or_mgr = role in ('ADMIN', 'CLIENT') or enterprise_role in ('SUPER_ADMIN', 'ORG_ADMIN', 'MANAGER', 'HR')
    member_perms = None
    if not is_owner_or_mgr:
        member_perms = {}
        try:
            from api.models import TeamMemberConnectorAccess
            for tmca in TeamMemberConnectorAccess.objects.filter(client=target_client, team_member=user):
                member_perms[tmca.connector_key.lower().strip()] = bool(tmca.is_enabled)
        except Exception as e:
            print(f"[get_user_allowed_channels] TeamMemberConnectorAccess query error: {e}")

    allowed = []
    for item in DEFAULT_CONNECTORS:
        key = item['key']
        if key not in active_keys:
            continue

        # Client level check
        client_ok = client_perms.get(key)
        if client_ok is None:
            if hasattr(target_client, 'has_channel_access'):
                try:
                    client_ok = target_client.has_channel_access(key)
                except Exception:
                    client_ok = True
            else:
                client_ok = True
        if not client_ok:
            continue

        # Team member level check
        if member_perms is not None:
            member_ok = member_perms.get(key)
            if member_ok is None:
                assigned = getattr(user, 'assigned_social_channels', []) or []
                if assigned:
                    member_ok = any(key in str(a).lower() or str(a).lower() in key for a in assigned)
                else:
                    member_ok = True
            if not member_ok:
                continue

        allowed.append(key.upper())

    _USER_ALLOWED_CHANNELS_CACHE[cache_key] = (now, allowed)
    return allowed


def get_user_effective_connectors(user, client=None):
    """
    Returns a structured dictionary of all connectors with effective accessibility for the user.
    Optimized with single-batch lookups.
    """
    target_client = client
    if not target_client and user:
        try:
            target_client = getattr(user, 'client', None)
        except Exception:
            target_client = None

    active_keys = _get_cached_global_active_keys()

    client_perms = {}
    if target_client:
        try:
            from api.models import ClientConnectorAccess
            for cca in ClientConnectorAccess.objects.filter(client=target_client):
                client_perms[cca.connector_key.lower().strip()] = bool(cca.is_enabled)
        except Exception:
            pass

    member_perms = {}
    if target_client and user:
        try:
            from api.models import TeamMemberConnectorAccess
            for tmca in TeamMemberConnectorAccess.objects.filter(client=target_client, team_member=user):
                member_perms[tmca.connector_key.lower().strip()] = bool(tmca.is_enabled)
        except Exception:
            pass

    role = getattr(user, 'role', '').upper() if user else ''
    enterprise_role = getattr(user, 'enterprise_role', '').upper() if user else ''
    is_owner_or_mgr = role in ('ADMIN', 'CLIENT') or enterprise_role in ('SUPER_ADMIN', 'ORG_ADMIN', 'MANAGER', 'HR')

    result = {}
    for item in DEFAULT_CONNECTORS:
        key = item['key']
        is_global_active = key in active_keys

        is_client_enabled = True
        if target_client:
            if key in client_perms:
                is_client_enabled = client_perms[key]
            elif hasattr(target_client, 'has_channel_access'):
                try:
                    is_client_enabled = target_client.has_channel_access(key)
                except Exception:
                    is_client_enabled = True

        is_member_assigned = True
        if target_client and user and not is_owner_or_mgr:
            if key in member_perms:
                is_member_assigned = member_perms[key]
            else:
                assigned = getattr(user, 'assigned_social_channels', []) or []
                if assigned:
                    is_member_assigned = any(key in str(a).lower() or str(a).lower() in key for a in assigned)

        effective = is_global_active and is_client_enabled and is_member_assigned

        result[key] = {
            'key': key,
            'name': item['name'],
            'category': item.get('category', 'MESSAGING'),
            'is_core': item.get('is_core', False),
            'global_active': is_global_active,
            'client_enabled': is_client_enabled,
            'team_member_assigned': is_member_assigned,
            'effective_access': effective
        }

    return result


def log_channel_permission_change(admin_user_identifier, client, channel, action, previous_state, new_state, team_member=None, team_member_name="", notes=""):
    """
    Records an entry in ChannelAuditLog and invalidates permission caches.
    """
    clear_channel_permissions_cache(
        user_id=getattr(team_member, 'id', None),
        client_id=getattr(client, 'id', None)
    )

    try:
        from api.models import ChannelAuditLog
        ChannelAuditLog.objects.create(
            admin_user=str(admin_user_identifier),
            client=client,
            client_name=client.business_name if client else '',
            team_member=team_member,
            team_member_name=team_member_name or (team_member.username if team_member else ''),
            channel=str(channel).lower().strip(),
            action=action,
            previous_state=previous_state if isinstance(previous_state, dict) else {'state': previous_state},
            new_state=new_state if isinstance(new_state, dict) else {'state': new_state},
            notes=notes
        )
    except Exception as e:
        print(f"[ChannelAuditLog] Failed to log permission change: {e}")
