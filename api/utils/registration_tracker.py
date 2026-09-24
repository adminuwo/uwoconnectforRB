import re
import time
import requests
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)

# Lightweight in-memory cache for IP geolocation to avoid repeat network requests
_GEO_CACHE = {}
_GEO_CACHE_TTL = 3600  # 1 hour


def get_client_ip(request):
    """
    Extracts the genuine client IP address from proxy headers or remote addr.
    """
    if not request:
        return '127.0.0.1'

    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        # First IP in the list is the original client
        return x_forwarded_for.split(',')[0].strip()

    x_real_ip = request.META.get('HTTP_X_REAL_IP')
    if x_real_ip:
        return x_real_ip.strip()

    return request.META.get('REMOTE_ADDR', '127.0.0.1')


def is_private_ip(ip):
    """Checks if an IP address is a private, loopback, or local IP."""
    if not ip or ip in ['127.0.0.1', '::1', 'localhost']:
        return True
    if (
        ip.startswith('10.') or
        ip.startswith('192.168.') or
        ip.startswith('172.16.') or
        ip.startswith('172.17.') or
        ip.startswith('172.18.') or
        ip.startswith('172.19.') or
        ip.startswith('172.20.') or
        ip.startswith('172.21.') or
        ip.startswith('172.22.') or
        ip.startswith('172.23.') or
        ip.startswith('172.24.') or
        ip.startswith('172.25.') or
        ip.startswith('172.26.') or
        ip.startswith('172.27.') or
        ip.startswith('172.28.') or
        ip.startswith('172.29.') or
        ip.startswith('172.30.') or
        ip.startswith('172.31.')
    ):
        return True
    return False


def resolve_ip_location(ip, request=None, payload=None):
    """
    Resolves country, country_code, region, and city safely without blocking.
    Prioritizes:
    1. Direct proxy headers (Cloudflare, AWS, etc.)
    2. Client payload hints (if legally & technical available)
    3. Cached / HTTP IP-API lookup with fast 1.5s timeout
    4. Fallback to 'Unknown'
    """
    country = 'Unknown'
    country_code = 'Unknown'
    region = 'Unknown'
    city = 'Unknown'

    payload = payload or {}

    # Check client payload overrides first if provided
    if payload.get('country') and payload.get('country') != 'Unknown':
        country = str(payload.get('country')).strip()
    if payload.get('country_code') and payload.get('country_code') != 'Unknown':
        country_code = str(payload.get('country_code')).strip().upper()
    if payload.get('region') and payload.get('region') != 'Unknown':
        region = str(payload.get('region')).strip()
    if payload.get('city') and payload.get('city') != 'Unknown':
        city = str(payload.get('city')).strip()

    # Parse from location string if provided by register form
    loc = payload.get('location')
    if loc and isinstance(loc, str) and loc.strip() and loc.strip() != 'Unknown':
        parts = [p.strip() for p in loc.strip().split(',') if p.strip()]
        if len(parts) >= 3:
            if city == 'Unknown':
                city = parts[0]
            if region == 'Unknown':
                region = parts[1]
            if country == 'Unknown':
                country = parts[-1]
        elif len(parts) == 2:
            if city == 'Unknown':
                city = parts[0]
            if country == 'Unknown':
                country = parts[1]
        elif len(parts) == 1:
            if city == 'Unknown':
                city = parts[0]

    # If full location already supplied by client, return it
    if country != 'Unknown' and city != 'Unknown':
        return country, country_code, region, city

    # Check reverse proxy headers
    if request:
        cf_country = request.META.get('HTTP_CF_IPCOUNTRY')
        if cf_country and len(cf_country) == 2:
            country_code = cf_country.upper()
            if country == 'Unknown':
                country = 'India' if country_code == 'IN' else country_code

    # For private/local IPs, return defaults
    if is_private_ip(ip):
        if country == 'Unknown':
            country = 'India'
            country_code = 'IN'
        return country, country_code, region, city

    # Check in-memory cache
    cached = _GEO_CACHE.get(ip)
    if cached and (time.time() - cached['timestamp'] < _GEO_CACHE_TTL):
        c_data = cached['data']
        return (
            country if country != 'Unknown' else c_data.get('country', 'Unknown'),
            country_code if country_code != 'Unknown' else c_data.get('country_code', 'Unknown'),
            region if region != 'Unknown' else c_data.get('region', 'Unknown'),
            city if city != 'Unknown' else c_data.get('city', 'Unknown')
        )

    # Perform fast external lookup (with strict 1.5s timeout)
    try:
        resp = requests.get(f"http://ip-api.com/json/{ip}?fields=status,country,countryCode,regionName,city", timeout=1.5)
        if resp.status_code == 200:
            res_json = resp.json()
            if res_json.get('status') == 'success':
                res_country = res_json.get('country', 'Unknown')
                res_code = res_json.get('countryCode', 'Unknown')
                res_region = res_json.get('regionName', 'Unknown')
                res_city = res_json.get('city', 'Unknown')

                _GEO_CACHE[ip] = {
                    'timestamp': time.time(),
                    'data': {
                        'country': res_country,
                        'country_code': res_code,
                        'region': res_region,
                        'city': res_city,
                    }
                }

                return (
                    country if country != 'Unknown' else res_country,
                    country_code if country_code != 'Unknown' else res_code,
                    region if region != 'Unknown' else res_region,
                    city if city != 'Unknown' else res_city,
                )
    except Exception as e:
        logger.debug(f"[GeoIP] Lookup failed for {ip}: {e}")

    return country, country_code, region, city


def parse_device_info(user_agent_str, payload=None):
    """
    Parses device type, model, OS name, OS version, and app version.
    """
    payload = payload or {}
    ua = str(user_agent_str or '').strip()
    ua_lower = ua.lower()

    # 1. Device Type
    device_type = payload.get('device_type')
    if not device_type:
        if any(k in ua_lower for k in ['iphone', 'android', 'mobile']):
            device_type = 'mobile'
        elif any(k in ua_lower for k in ['ipad', 'tablet']):
            device_type = 'tablet'
        else:
            device_type = 'desktop'

    # 2. OS Name & Model
    os_name = payload.get('os_name') or payload.get('os')
    device_model = payload.get('device_model') or payload.get('device')
    os_version = payload.get('os_version')
    app_version = payload.get('app_version') or '1.0.0'

    if not os_name:
        if 'iphone' in ua_lower:
            os_name = 'iOS'
            device_model = device_model or 'iPhone'
            # Extract iOS version from UA if possible (e.g. CPU iPhone OS 18_1 like Mac OS X)
            m = re.search(r'os\s+([\d_]+)\s+like', ua_lower)
            if m and not os_version:
                os_version = m.group(1).replace('_', '.')
        elif 'ipad' in ua_lower:
            os_name = 'iPadOS'
            device_model = device_model or 'iPad'
        elif 'android' in ua_lower:
            os_name = 'Android'
            device_model = device_model or 'Android Device'
            m = re.search(r'android\s+([\d.]+)', ua_lower)
            if m and not os_version:
                os_version = m.group(1)
        elif 'macintosh' in ua_lower or 'mac os x' in ua_lower:
            os_name = 'macOS'
            device_model = device_model or 'Apple Mac'
        elif 'windows' in ua_lower:
            os_name = 'Windows'
            device_model = device_model or 'PC'
        elif 'linux' in ua_lower:
            os_name = 'Linux'
            device_model = device_model or 'Linux Workstation'
        else:
            os_name = 'Unknown'
            device_model = device_model or 'Unknown'

    if not os_version:
        os_version = 'Unknown'
    if not device_model:
        device_model = 'Unknown'

    return device_type, device_model, os_name, os_version, app_version


def detect_platform(request=None, payload=None):
    """
    Detects platform: 'ios' | 'android' | 'web' | 'unknown'
    """
    payload = payload or {}

    raw_platform = str(payload.get('platform', '')).lower().strip()
    if raw_platform in ['ios', 'android', 'web']:
        return raw_platform

    # Auto-detect from User-Agent
    if request:
        ua = request.META.get('HTTP_USER_AGENT', '').lower()
        if 'iphone' in ua or 'cfnetwork' in ua or 'darwin' in ua or 'ios' in ua:
            return 'ios'
        elif 'android' in ua or 'dalvik' in ua:
            return 'android'
        elif 'mozilla' in ua or 'chrome' in ua or 'safari' in ua:
            return 'web'

    return 'web'


def extract_registration_meta(request=None, payload=None, signup_method='email'):
    """
    Master extractor returning all registration tracking metadata.
    """
    payload = payload or {}
    ip = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '') if request else ''

    platform = detect_platform(request, payload)
    country, country_code, region, city = resolve_ip_location(ip, request, payload)
    device_type, device_model, os_name, os_version, app_version = parse_device_info(user_agent, payload)

    method = payload.get('registration_method') or signup_method or 'email'
    if method not in ['email', 'google', 'apple', 'other']:
        method = 'other'

    return {
        'registration_platform': platform,
        'registration_country': country,
        'registration_country_code': country_code,
        'registration_region': region,
        'registration_city': city,
        'registered_at': timezone.now(),
        'registration_device_type': device_type,
        'registration_device_model': device_model,
        'registration_os': os_name,
        'registration_os_version': os_version,
        'registration_app_version': app_version,
        'registration_method': method,
    }


def record_login_activity(user, request=None, payload=None):
    """
    Records subsequent login activity on User model.
    STRICTLY preserves user.registration_* and user.registered_at.
    """
    if not user:
        return

    payload = payload or {}
    ip = get_client_ip(request)
    ua = request.META.get('HTTP_USER_AGENT', '') if request else ''
    now = timezone.now()

    platform = detect_platform(request, payload)
    country, country_code, region, city = resolve_ip_location(ip, request, payload)
    device_type, device_model, os_name, os_version, app_version = parse_device_info(ua, payload)

    user.last_login_ip = ip
    user.last_login_os = os_name
    user.last_login_platform = platform
    user.last_login_country = country
    user.last_login_city = city
    user.last_login_device = device_model
    user.last_login_app_version = app_version
    user.last_login_at = now
    user.is_online = True
    user.last_active_at = now

    # Append to login_history list
    history_entry = {
        'timestamp': now.isoformat(),
        'ip': ip,
        'platform': platform,
        'country': country,
        'city': city,
        'device': device_model,
        'os': os_name,
        'app_version': app_version,
    }
    history = user.login_history or []
    # Keep last 50 login entries
    history.append(history_entry)
    user.login_history = history[-50:]

    fields_to_update = [
        'last_login_ip', 'last_login_os', 'last_login_platform',
        'last_login_country', 'last_login_city', 'last_login_device',
        'last_login_app_version', 'last_login_at', 'is_online',
        'last_active_at', 'login_history'
    ]

    try:
        user.save(update_fields=fields_to_update)
    except Exception as e:
        logger.error(f"[LoginActivity Error] Failed to update user login activity: {e}")
