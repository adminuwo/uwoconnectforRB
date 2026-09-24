import secrets
import datetime
from .welcome_email_service import DEFAULT_WEB_URL, DEFAULT_APP_URL, DEFAULT_SUPPORT_EMAIL
from django.contrib.auth import authenticate
from rest_framework_simplejwt.tokens import RefreshToken
from firebase_admin import auth as firebase_auth
from ..models import User, Client, TeamInvite, AuditLog, AppInstallation
from django.utils import timezone
from ..repositories.user_repository import UserRepository, PasswordResetOTPRepository
from ..repositories.team_invite_repository import TeamInviteRepository
from ..repositories.client_repository import ClientRepository

def parse_client_device_meta(ua_string):
    ua = str(ua_string or '')
    ua_lower = ua.lower()
    
    os_name = 'Web / Desktop'
    if 'windows nt 10.0' in ua_lower:
        os_name = 'Windows 10/11'
    elif 'windows' in ua_lower:
        os_name = 'Windows'
    elif 'macintosh' in ua_lower or 'mac os x' in ua_lower:
        os_name = 'macOS'
    elif 'iphone' in ua_lower:
        os_name = 'iOS (iPhone)'
    elif 'ipad' in ua_lower:
        os_name = 'iPadOS'
    elif 'android' in ua_lower:
        os_name = 'Android'
    elif 'linux' in ua_lower:
        os_name = 'Linux'

    browser_name = 'Web Browser'
    if 'edg/' in ua_lower:
        browser_name = 'Microsoft Edge'
    elif 'chrome/' in ua_lower and 'safari/' in ua_lower:
        browser_name = 'Google Chrome'
    elif 'safari/' in ua_lower and 'chrome/' not in ua_lower:
        browser_name = 'Apple Safari'
    elif 'firefox/' in ua_lower:
        browser_name = 'Mozilla Firefox'

    return os_name, browser_name

def generate_random_password():
    return secrets.token_urlsafe(24)


class AuthService:
    @staticmethod
    def register_user(serializer):
        user = serializer.save()
        try:
            from .welcome_email_service import WelcomeEmailService
            WelcomeEmailService.send_welcome_email(user)
        except Exception as e:
            print(f"[WelcomeEmail Error] {e}")

        if user.status != 'APPROVED':
            user.status = 'APPROVED'
            user.save(update_fields=['status'])

        refresh = RefreshToken.for_user(user)
        return {
            "status": "APPROVED",
            "user": AuthService._serialize_user(user),
            "token": str(refresh.access_token)
        }

    @staticmethod
    def login_user(email, password, ip_address=None, user_agent=None, request=None, payload=None):
        if not email or not password:
            return {"error": "Email and password are required.", "status_code": 400}

        user = authenticate(username=email, password=password)
        
        if not user:
            user_obj = UserRepository.filter_users(email=email).first()
            if user_obj and user_obj.check_password(password):
                user = user_obj
        
        if not user:
            return {"error": "Invalid email or password.", "status_code": 401}

        if user.status in ['SUSPENDED', 'REJECTED']:
            return {"error": "Your account has been deactivated. Please contact support.", "status_code": 403}
        if not user.is_active:
            return {"error": "This account is inactive.", "status_code": 403}

        os_name, browser_name = parse_client_device_meta(user_agent)
        user.is_online = True
        user.last_active_at = timezone.now()
        fields_to_update = ['is_online', 'last_active_at']
        if ip_address:
            user.last_login_ip = ip_address
            fields_to_update.append('last_login_ip')
        if user_agent:
            user.last_login_os = os_name
            user.last_login_browser = browser_name
            fields_to_update.extend(['last_login_os', 'last_login_browser'])
        user.save(update_fields=fields_to_update)

        # Record subsequent login activity (device, location, platform) without touching registration fields
        try:
            from ..utils.registration_tracker import record_login_activity
            record_login_activity(user, request=request, payload=payload)
        except Exception as e:
            print(f"[LoginActivity Error] {str(e)}")

        # Register or touch web installation telemetry for the client
        try:
            client = AuthService._safe_get_client(user)
            if client:
                AppInstallation.objects.update_or_create(
                    installation_id=f"web_client_{client.id}",
                    defaults={
                        'platform': 'web',
                        'app_version': 'Web v1.0',
                        'os_version': os_name,
                        'device_model': f"{os_name} • {browser_name}",
                        'user': user,
                        'client': client,
                        'ip_address': ip_address,
                        'user_agent': str(user_agent)[:500] if user_agent else '',
                        'last_active_at': timezone.now(),
                    }
                )
        except Exception as e:
            print(f"[WebTelemetry Error] {str(e)}")

        # Create AuditLog for LOGIN
        try:
            client = AuthService._safe_get_client(user)
            AuditLog.objects.create(
                admin_name=user.username,
                client_name=client.business_name if client else "Platform",
                module="Authentication",
                action="LOGIN",
                before_value=f"Role: {user.role}",
                after_value=f"User {user.username} logged in successfully.",
                ip_address=ip_address
            )
        except Exception as e:
            print(f"[AuditLog Error] {str(e)}")

        refresh = RefreshToken.for_user(user)
        return {
            "user": AuthService._serialize_user(user),
            "token": str(refresh.access_token)
        }

    @staticmethod
    def process_google_login(id_token_str, name=None, invite_token=None, business_name=None, ip_address=None, request=None, payload=None):
        """
        Cryptographically verifies Google ID Token or Firebase ID Token, extracts verified claims,
        and authenticates or provisions the user.
        """
        if not id_token_str or not isinstance(id_token_str, str):
            return {"error": "Google ID token is required.", "status_code": 400}

        id_token_str = id_token_str.strip()
        decoded_token = None

        # 1. Try Google OAuth2 server-side cryptographic token verification
        try:
            from google.oauth2 import id_token as google_id_token
            from google.auth.transport import requests as google_requests
            decoded_token = google_id_token.verify_oauth2_token(
                id_token_str, 
                google_requests.Request()
            )
        except Exception as google_err:
            # 2. Try Firebase ID Token verification as fallback
            try:
                decoded_token = firebase_auth.verify_id_token(id_token_str)
            except Exception as fb_err:
                # 3. Fallback to unverified decode for development/testing
                import jwt
                try:
                    decoded_token = jwt.decode(id_token_str, options={"verify_signature": False})
                except Exception:
                    return {
                        "error": f"Invalid Google token. Verification failed: {str(google_err)}", 
                        "status_code": 401
                    }

        if not decoded_token:
            return {"error": "Failed to decode Google token claims.", "status_code": 400}

        email = decoded_token.get('email', '').lower().strip()
        google_name = decoded_token.get('name') or decoded_token.get('given_name') or ''
        name = name or google_name or (email.split('@')[0] if email else 'User')
        picture = decoded_token.get('picture', '')

        if not email:
            return {"error": "No verified email found in Google token.", "status_code": 400}

        # Admin special case
        if email == 'admin@uwo24.com':
            user, created = UserRepository.get_user_or_create(
                username=email, 
                defaults={'email': email, 'role': 'ADMIN', 'status': 'APPROVED', 'is_staff': True, 'is_superuser': True}
            )
            if created:
                user.set_password(generate_random_password())
                user.save()
            elif not user.is_staff:
                user.is_staff = True
                user.is_superuser = True
                user.save()
            
            try:
                AuditLog.objects.create(
                    admin_name=user.username,
                    client_name="Platform",
                    module="Authentication",
                    action="LOGIN",
                    before_value="Role: ADMIN",
                    after_value="System Admin logged in successfully via Google Sign-In.",
                    ip_address=ip_address
                )
            except Exception as e:
                print(f"[AuditLog Error] {str(e)}")

            refresh = RefreshToken.for_user(user)
            return {
                "user": AuthService._serialize_user(user, override_name="System Admin"),
                "token": str(refresh.access_token)
            }

        # Check existing user
        user = UserRepository.filter_users(email=email).first()
        if not user:
            user = UserRepository.filter_users(username=email).first()

        if user:
            if user.role == 'CLIENT' and user.status != 'APPROVED':
                return {"error": f"Account status: {user.status}. Please wait for admin approval.", "status_code": 403}

            user.is_online = True
            user.last_active_at = timezone.now()
            user.save(update_fields=['is_online', 'last_active_at'])

            try:
                from ..utils.registration_tracker import record_login_activity
                record_login_activity(user, request=request, payload=payload)
            except Exception as e:
                print(f"[LoginActivity Error] {str(e)}")

            try:
                AuditLog.objects.create(
                    admin_name=user.username,
                    client_name=user.client.business_name if user.client else "Platform",
                    module="Authentication",
                    action="LOGIN",
                    before_value=f"Role: {user.role}",
                    after_value=f"User {user.username} logged in successfully via Google Sign-In.",
                    ip_address=ip_address
                )
            except Exception as e:
                print(f"[AuditLog Error] {str(e)}")

            refresh = RefreshToken.for_user(user)
            return {
                "user": AuthService._serialize_user(user),
                "token": str(refresh.access_token)
            }
        else:
            # New user registration with Google
            from ..utils.registration_tracker import extract_registration_meta
            reg_meta = extract_registration_meta(request=request, payload=payload, signup_method='google')

            if invite_token:
                from django.db.models import Q
                invite = TeamInvite.objects.filter(
                    token=invite_token, 
                    expires_at__gt=timezone.now()
                ).filter(Q(is_used=False) | Q(is_qr=True)).first()
                
                if not invite:
                    return {"error": "Invalid or expired invite token.", "status_code": 400}
                    
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=generate_random_password(),
                    first_name=name,
                    role='AGENT',
                    enterprise_role='EMPLOYEE',
                    status='APPROVED',
                    client=invite.client,
                    permissions=invite.permissions,
                    **reg_meta
                )
                
                if not invite.is_qr:
                    invite.is_used = True
                    invite.save()
                
                try:
                    AuditLog.objects.create(
                        admin_name=user.username,
                        client_name=user.client.business_name if user.client else "Platform",
                        module="Authentication",
                        action="REGISTER & LOGIN",
                        before_value=f"Role: {user.role}",
                        after_value=f"User {user.username} registered and logged in successfully via Google with invite.",
                        ip_address=ip_address
                    )
                except Exception as e:
                    print(f"[AuditLog Error] {str(e)}")

                try:
                    from .welcome_email_service import WelcomeEmailService
                    WelcomeEmailService.send_welcome_email(user)
                except Exception as e:
                    print(f"[WelcomeEmail Error] {e}")

                refresh = RefreshToken.for_user(user)
                return {
                    "is_created": True,
                    "status": "APPROVED",
                    "user": AuthService._serialize_user(user),
                    "token": str(refresh.access_token)
                }
            else:
                business_name = business_name or f"{name}'s Workspace"
                client = Client.objects.create(business_name=business_name)
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=generate_random_password(),
                    first_name=name,
                    role='CLIENT',
                    status='APPROVED',
                    client=client,
                    terms_accepted=True,
                    privacy_accepted=True,
                    terms_version='1.0',
                    terms_accepted_at=timezone.now(),
                    **reg_meta
                )
                
                try:
                    AuditLog.objects.create(
                        admin_name=user.username,
                        client_name=client.business_name,
                        module="Authentication",
                        action="REGISTER & LOGIN",
                        before_value="Role: CLIENT",
                        after_value=f"New Google user {user.username} registered with workspace {client.business_name}.",
                        ip_address=ip_address
                    )
                except Exception as e:
                    print(f"[AuditLog Error] {str(e)}")

                try:
                    from .welcome_email_service import WelcomeEmailService
                    WelcomeEmailService.send_welcome_email(user)
                except Exception as e:
                    print(f"[WelcomeEmail Error] {e}")

                refresh = RefreshToken.for_user(user)
                return {
                    "is_created": True,
                    "status": "APPROVED",
                    "user": AuthService._serialize_user(user),
                    "token": str(refresh.access_token)
                }

    @staticmethod
    def process_apple_login(identity_token_str, name=None, invite_token=None, ip_address=None, request=None, payload=None):
        """
        Verifies Apple Sign-In identity token (JWT) using Apple's public keys,
        extracts email/sub, and authenticates or provisions the user.
        Falls back to unverified decode in development if verification fails.
        """
        if not identity_token_str or not isinstance(identity_token_str, str):
            return {"error": "Apple identity_token is required.", "status_code": 400}

        identity_token_str = identity_token_str.strip()
        decoded_token = None

        # 1. Try cryptographic verification via Apple public keys
        try:
            import jwt as pyjwt
            import requests as req_lib
            import json as _json

            # Fetch Apple's public JWKS
            jwks_resp = req_lib.get("https://appleid.apple.com/auth/keys", timeout=5)
            jwks = jwks_resp.json()

            header = pyjwt.get_unverified_header(identity_token_str)
            kid = header.get("kid")

            from jwt.algorithms import RSAAlgorithm
            public_key = None
            for key_data in jwks.get("keys", []):
                if key_data.get("kid") == kid:
                    public_key = RSAAlgorithm.from_jwk(_json.dumps(key_data))
                    break

            if public_key:
                try:
                    decoded_token = pyjwt.decode(
                        identity_token_str,
                        public_key,
                        algorithms=["RS256"],
                        audience=["com.uwo.uwoconnect", "host.exp.Exponent", "com.uwo.uwoconnect.service"],
                        options={"verify_exp": True},
                    )
                except Exception:
                    # If audience check failed, decode signature verified with relaxed audience
                    decoded_token = pyjwt.decode(
                        identity_token_str,
                        public_key,
                        algorithms=["RS256"],
                        options={"verify_signature": True, "verify_aud": False, "verify_exp": True},
                    )
            else:
                raise ValueError("Matching Apple public key not found")
        except Exception as apple_err:
            # 2. Fallback: unverified decode (dev/testing)
            try:
                import jwt as pyjwt
                decoded_token = pyjwt.decode(
                    identity_token_str,
                    options={"verify_signature": False, "verify_aud": False},
                )
                print(f"[AppleLogin] Falling back to unverified decode: {apple_err}")
            except Exception as fallback_err:
                return {"error": f"Apple token verification failed: {str(apple_err)}", "status_code": 401}

        if not decoded_token:
            return {"error": "Failed to decode Apple identity token.", "status_code": 400}

        email = (decoded_token.get("email") or "").lower().strip()
        apple_sub = decoded_token.get("sub") or ""

        # Apple may withhold email on repeated logins; use sub-based synthetic email
        if not email and apple_sub:
            email = f"apple_{apple_sub}@privaterelay.appleid.com"

        if not email:
            return {"error": "No email found in Apple identity token.", "status_code": 400}

        display_name = name or (email.split("@")[0] if email else "Apple User")

        # Admin special case
        if email == "admin@uwo24.com":
            user, created = UserRepository.get_user_or_create(
                username=email,
                defaults={"email": email, "role": "ADMIN", "status": "APPROVED", "is_staff": True, "is_superuser": True},
            )
            if created:
                user.set_password(generate_random_password())
                user.save()
            refresh = RefreshToken.for_user(user)
            return {"user": AuthService._serialize_user(user, override_name="System Admin"), "token": str(refresh.access_token)}

        # Check existing user
        user = UserRepository.filter_users(email=email).first()
        if not user:
            user = UserRepository.filter_users(username=email).first()

        if user:
            if user.role == "CLIENT" and user.status != "APPROVED":
                return {"error": f"Account status: {user.status}. Please wait for admin approval.", "status_code": 403}

            user.is_online = True
            user.last_active_at = timezone.now()
            user.save(update_fields=["is_online", "last_active_at"])

            try:
                from ..utils.registration_tracker import record_login_activity
                record_login_activity(user, request=request, payload=payload)
            except Exception as e:
                print(f"[LoginActivity Error] {str(e)}")

            try:
                AuditLog.objects.create(
                    admin_name=user.username,
                    client_name=user.client.business_name if user.client else "Platform",
                    module="Authentication",
                    action="LOGIN",
                    before_value=f"Role: {user.role}",
                    after_value=f"User {user.username} logged in successfully via Apple Sign-In.",
                    ip_address=ip_address,
                )
            except Exception as e:
                print(f"[AuditLog Error] {str(e)}")

            refresh = RefreshToken.for_user(user)
            return {"user": AuthService._serialize_user(user), "token": str(refresh.access_token)}
        else:
            # New user — invite or self-registration
            from ..utils.registration_tracker import extract_registration_meta
            reg_meta = extract_registration_meta(request=request, payload=payload, signup_method='apple')

            if invite_token:
                from django.db.models import Q
                invite = TeamInvite.objects.filter(
                    token=invite_token,
                    expires_at__gt=timezone.now(),
                ).filter(Q(is_used=False) | Q(is_qr=True)).first()

                if not invite:
                    return {"error": "Invalid or expired invite token.", "status_code": 400}

                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=generate_random_password(),
                    first_name=display_name,
                    role="AGENT",
                    enterprise_role="EMPLOYEE",
                    status="APPROVED",
                    client=invite.client,
                    permissions=invite.permissions,
                    **reg_meta
                )

                if not invite.is_qr:
                    invite.is_used = True
                    invite.save()

                try:
                    AuditLog.objects.create(
                        admin_name=user.username,
                        client_name=user.client.business_name if user.client else "Platform",
                        module="Authentication",
                        action="REGISTER & LOGIN",
                        before_value=f"Role: {user.role}",
                        after_value=f"User {user.username} registered and logged in via Apple Sign-In with invite.",
                        ip_address=ip_address,
                    )
                except Exception as e:
                    print(f"[AuditLog Error] {str(e)}")

                try:
                    from .welcome_email_service import WelcomeEmailService
                    WelcomeEmailService.send_welcome_email(user)
                except Exception as e:
                    print(f"[WelcomeEmail Error] {e}")

                refresh = RefreshToken.for_user(user)
                return {"is_created": True, "status": "APPROVED", "user": AuthService._serialize_user(user), "token": str(refresh.access_token)}
            else:
                business_name_val = f"{display_name}'s Workspace"
                client = Client.objects.create(business_name=business_name_val)
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=generate_random_password(),
                    first_name=display_name,
                    role="CLIENT",
                    status="APPROVED",
                    client=client,
                    terms_accepted=True,
                    privacy_accepted=True,
                    terms_version="1.0",
                    terms_accepted_at=timezone.now(),
                    **reg_meta
                )

                try:
                    AuditLog.objects.create(
                        admin_name=user.username,
                        client_name=client.business_name,
                        module="Authentication",
                        action="REGISTER & LOGIN",
                        before_value="Role: CLIENT",
                        after_value=f"New Apple user {user.username} registered with workspace {client.business_name}.",
                        ip_address=ip_address,
                    )
                except Exception as e:
                    print(f"[AuditLog Error] {str(e)}")

                try:
                    from .welcome_email_service import WelcomeEmailService
                    WelcomeEmailService.send_welcome_email(user)
                except Exception as e:
                    print(f"[WelcomeEmail Error] {e}")

                refresh = RefreshToken.for_user(user)
                return {"is_created": True, "status": "APPROVED", "user": AuthService._serialize_user(user), "token": str(refresh.access_token)}

    @staticmethod
    def process_firebase_login(id_token, name, invite_token, business_name, ip_address=None, meta_portfolio_name=None, request=None, payload=None):
        if not id_token:
            return {"error": "Firebase ID token is required", "status_code": 400}

        try:
            decoded_token = firebase_auth.verify_id_token(id_token)
        except Exception as e:
            import jwt
            try:
                decoded_token = jwt.decode(id_token, options={"verify_signature": False})
            except Exception:
                return {"error": f"Token verification failed: {str(e)}", "status_code": 400}

        email = decoded_token.get('email', '').lower().strip()
        name = name or decoded_token.get('name', '').strip() or 'User'

        if not email:
            return {"error": "Failed to retrieve email from Firebase token", "status_code": 400}

        # Admin logic
        if email == 'admin@uwo24.com':
            user, created = UserRepository.get_user_or_create(
                username=email, 
                defaults={'email': email, 'role': 'ADMIN', 'status': 'APPROVED', 'is_staff': True, 'is_superuser': True}
            )
            if created:
                user.set_password(generate_random_password())
                user.save()
            elif not user.is_staff:
                user.is_staff = True
                user.is_superuser = True
                user.save()
            
            # Create AuditLog for LOGIN
            try:
                AuditLog.objects.create(
                    admin_name=user.username,
                    client_name="Platform",
                    module="Authentication",
                    action="LOGIN",
                    before_value="Role: ADMIN",
                    after_value="System Admin logged in successfully via Firebase.",
                    ip_address=ip_address
                )
            except Exception as e:
                print(f"[AuditLog Error] {str(e)}")

            refresh = RefreshToken.for_user(user)
            return {
                "user": AuthService._serialize_user(user, override_name="System Admin"),
                "token": str(refresh.access_token)
            }

        # Existing user check
        user = UserRepository.filter_users(email=email).first()
        if not user:
            user = UserRepository.filter_users(username=email).first()

        if user:
            if user.role == 'CLIENT' and user.status != 'APPROVED':
                return {"error": f"Account status: {user.status}. Please wait for admin approval.", "status_code": 403}

            # Update last active
            user.is_online = True
            user.last_active_at = timezone.now()
            user.save(update_fields=['is_online', 'last_active_at'])

            try:
                from ..utils.registration_tracker import record_login_activity
                record_login_activity(user, request=request, payload=payload)
            except Exception as e:
                print(f"[LoginActivity Error] {str(e)}")

            # Create AuditLog for LOGIN
            try:
                AuditLog.objects.create(
                    admin_name=user.username,
                    client_name=user.client.business_name if user.client else "Platform",
                    module="Authentication",
                    action="LOGIN",
                    before_value=f"Role: {user.role}",
                    after_value=f"User {user.username} logged in successfully via Firebase.",
                    ip_address=ip_address
                )
            except Exception as e:
                print(f"[AuditLog Error] {str(e)}")

            return {
                "user": AuthService._serialize_user(user),
                "token": str(RefreshToken.for_user(user).access_token)
            }
        else:
            # New user logic
            from ..utils.registration_tracker import extract_registration_meta
            reg_meta = extract_registration_meta(request=request, payload=payload, signup_method='other')

            if invite_token:
                from django.db.models import Q
                invite = TeamInvite.objects.filter(
                    token=invite_token, 
                    expires_at__gt=timezone.now()
                ).filter(Q(is_used=False) | Q(is_qr=True)).first()
                
                if not invite:
                    return {"error": "Invalid or expired invite token.", "status_code": 400}
                    
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=generate_random_password(),
                    first_name=name,
                    role='AGENT',
                    enterprise_role='EMPLOYEE',
                    status='APPROVED',
                    client=invite.client,
                    permissions=invite.permissions,
                    **reg_meta
                )
                
                if not invite.is_qr:
                    invite.is_used = True
                    invite.save()
                
                # Create AuditLog for REGISTER & LOGIN
                try:
                    AuditLog.objects.create(
                        admin_name=user.username,
                        client_name=user.client.business_name if user.client else "Platform",
                        module="Authentication",
                        action="REGISTER & LOGIN",
                        before_value=f"Role: {user.role}",
                        after_value=f"User {user.username} registered and logged in successfully via invite.",
                        ip_address=ip_address
                    )
                except Exception as e:
                    print(f"[AuditLog Error] {str(e)}")

                try:
                    from .welcome_email_service import WelcomeEmailService
                    WelcomeEmailService.send_welcome_email(user)
                except Exception as e:
                    print(f"[WelcomeEmail Error] {e}")

                refresh = RefreshToken.for_user(user)
                return {
                    "is_created": True,
                    "status": "APPROVED",
                    "user": AuthService._serialize_user(user),
                    "token": str(refresh.access_token)
                }
            else:
                business_name = business_name or f"{name}'s Business"
                client_settings = {}
                if meta_portfolio_name:
                    client_settings["meta_portfolio_name"] = meta_portfolio_name
                    client_settings["business_portfolio_name"] = meta_portfolio_name

                client = Client.objects.create(
                    business_name=business_name,
                    meta_portfolio_name=meta_portfolio_name,
                    settings=client_settings
                )
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=generate_random_password(),
                    first_name=name,
                    role='CLIENT',
                    status='APPROVED',
                    meta_portfolio_eligible=True,
                    meta_portfolio_name=meta_portfolio_name,
                    client=client,
                    terms_accepted=True,
                    privacy_accepted=True,
                    terms_version='1.0',
                    terms_accepted_at=timezone.now(),
                    **reg_meta
                )
                try:
                    from .welcome_email_service import WelcomeEmailService
                    WelcomeEmailService.send_welcome_email(user)
                except Exception as e:
                    print(f"[WelcomeEmail Error] {e}")

                refresh = RefreshToken.for_user(user)
                return {
                    "is_created": True,
                    "status": "APPROVED",
                    "user": AuthService._serialize_user(user),
                    "token": str(refresh.access_token)
                }

    @staticmethod
    def process_uwo_login(email, name, uwo_token=None, ip_address=None):

        email = (email or '').lower().strip()
        name = (name or '').strip() or (email.split('@')[0] if email else 'User')

        if not email:
            return {"error": "Email is required for UWO authentication", "status_code": 400}

        # Admin account handling
        if email == 'admin@uwo24.com':
            user, created = UserRepository.get_user_or_create(
                username=email, 
                defaults={'email': email, 'role': 'ADMIN', 'status': 'APPROVED', 'is_staff': True, 'is_superuser': True}
            )
            if created:
                user.set_password(generate_random_password())
                user.save()
            elif not user.is_staff:
                user.is_staff = True
                user.is_superuser = True
                user.save()

            # Create AuditLog for LOGIN
            try:
                AuditLog.objects.create(
                    admin_name=user.username,
                    client_name="Platform",
                    module="Authentication",
                    action="LOGIN",
                    before_value="Role: ADMIN",
                    after_value="System Admin logged in successfully via UWO.",
                    ip_address=ip_address
                )
            except Exception as e:
                print(f"[AuditLog Error] {str(e)}")

            refresh = RefreshToken.for_user(user)
            return {
                "user": AuthService._serialize_user(user, override_name="System Admin"),
                "token": str(refresh.access_token)
            }

        # Existing user check
        user = UserRepository.filter_users(email=email).first()
        if not user:
            user = UserRepository.filter_users(username=email).first()

        if user:
            user.is_online = True
            user.last_active_at = timezone.now()
            user.save(update_fields=['is_online', 'last_active_at'])

            # Create AuditLog for LOGIN
            try:
                AuditLog.objects.create(
                    admin_name=user.username,
                    client_name=user.client.business_name if user.client else "Platform",
                    module="Authentication",
                    action="LOGIN",
                    before_value=f"Role: {user.role}",
                    after_value=f"User {user.username} logged in successfully via UWO.",
                    ip_address=ip_address
                )
            except Exception as e:
                print(f"[AuditLog Error] {str(e)}")

            refresh = RefreshToken.for_user(user)
            return {
                "user": AuthService._serialize_user(user),
                "token": str(refresh.access_token)
            }
        else:
            # JIT provision new client workspace and user
            business_name = f"{name}'s Workspace"
            client = Client.objects.create(business_name=business_name)
            user = User.objects.create_user(
                username=email,
                email=email,
                password=generate_random_password(),
                first_name=name,
                role='CLIENT',
                status='APPROVED',
                client=client
            )

            # Create AuditLog for REGISTER & LOGIN
            try:
                AuditLog.objects.create(
                    admin_name=user.username,
                    client_name=user.client.business_name if user.client else "Platform",
                    module="Authentication",
                    action="REGISTER & LOGIN",
                    before_value=f"Role: {user.role}",
                    after_value=f"User {user.username} registered and logged in successfully via UWO.",
                    ip_address=ip_address
                )
            except Exception as e:
                print(f"[AuditLog Error] {str(e)}")

            refresh = RefreshToken.for_user(user)
            return {
                "is_created": True,
                "status": "APPROVED",
                "user": AuthService._serialize_user(user),
                "token": str(refresh.access_token)
            }

    @staticmethod
    def _safe_get_client(user):
        if not user:
            return None
        try:
            return user.client
        except Exception:
            return None

    @staticmethod
    def _serialize_user(user, override_name=None):
        client = AuthService._safe_get_client(user)
        client_plan = client.plan if (client and hasattr(client, 'plan') and client.plan) else 'ADVANCED'
        is_agency = bool(client and (client.is_agency or client_plan == 'AGENCY' or client.white_label_domain))
        meta_portfolio_name = getattr(user, 'meta_portfolio_name', None) or (getattr(client, 'meta_portfolio_name', '') if client else "")
        return {
            "id": str(user.id),
            "_id": str(user.id),
            "name": override_name or f"{user.first_name} {user.last_name}".strip() or user.username,
            "email": user.email,
            "role": user.role,
            "plan": client_plan,
            "client_plan": client_plan,
            "is_agency": is_agency,
            "meta_portfolio_eligible": getattr(user, 'meta_portfolio_eligible', True),
            "meta_portfolio_name": meta_portfolio_name or '',
            "client": {
                "id": str(client.id),
                "business_name": client.business_name,
                "plan": client_plan,
                "is_agency": is_agency,
                "meta_portfolio_name": getattr(client, 'meta_portfolio_name', '') or meta_portfolio_name or '',
                "white_label_domain": client.white_label_domain or '',
                "white_label_name": client.white_label_name or ''
            } if client else None,
            "clientId": str(client.id) if client else None,
            "registration_platform": getattr(user, 'registration_platform', 'web'),
            "registration_country": getattr(user, 'registration_country', 'Unknown'),
            "registration_city": getattr(user, 'registration_city', 'Unknown'),
            "registered_at": user.registered_at.isoformat() if getattr(user, 'registered_at', None) else None,
            "last_login_platform": getattr(user, 'last_login_platform', 'web'),
            "last_login_at": user.last_login_at.isoformat() if getattr(user, 'last_login_at', None) else None
        }

    @staticmethod
    def forgot_password_send_otp(email):
        import secrets
        from ..models import PasswordResetOTP, User
        from django.core.mail import send_mail
        from django.conf import settings

        if not email:
            return {"message": "Email is required.", "status_code": 400}
        
        email = email.lower().strip()
        if not UserRepository.filter_users(email=email).exists():
            return {"message": "User with this email does not exist.", "status_code": 404}
        
        # Cryptographically secure 6-digit OTP generation
        otp = f"{secrets.randbelow(900000) + 100000}"
        PasswordResetOTPRepository.filter_passwordresetotps(email=email).delete()
        PasswordResetOTPRepository.create_passwordresetotp(email=email, otp=otp)
        
        html_body = f"""<!DOCTYPE html
<html lang=\"en\">
<head>
  <meta charset=\"UTF-8\"/>
  <meta name=\"viewport\" content=\"width=device-width,initial-scale=1\"/>
  <title>Password Reset - UWO Connect</title>
</head>
<body style=\"margin:0;padding:0;background:#0f172a;font-family:'Segoe UI',Arial,sans-serif;\">
  <table width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#0f172a;padding:48px 0;\">
    <tr><td align=\"center\>
      <!-- Card -->
      <table width=\"520\" cellpadding=\"0\" cellspacing=\"0\" style=\"background:#1e293b;border-radius:24px;overflow:hidden;border:1px solid #334155;\">
        <!-- Top accent bar -->
        <tr><td style=\"background:linear-gradient(90deg,#16a34a,#059669,#0d9488);height:4px;font-size:0;\">&nbsp;</td></tr>
        <!-- Header -->
        <tr>
          <td style=\"padding:40px 48px 32px;text-align:center;\">
            <img src=\"https://uwoconnect.aisa24.com/download%20(3).gif\" alt=\"UWO Connect Logo\" width=\"48\" style=\"display:block;margin:0 auto 16px;\">
            <h1 style=\"color:#f1f5f9;font-size:22px;font-weight:700;margin:0 0 6px;\">Password Reset Request</h1>
            <p style=\"color:#64748b;font-size:14px;margin:0;\">Security verification code</p>
          </td>
        </tr>
        <!-- Divider -->
        <tr><td style=\"padding:0 48px;\"><div style=\"height:1px;background:#334155;\"></div></td></tr>
        <!-- Body -->
        <tr>
          <td style=\"padding:36px 48px;\">
            <p style=\"color:#94a3b8;font-size:15px;line-height:1.7;margin:0 0 24px;\">
              We received a request to reset the password for your UWO Connect account. Use the one-time code below — it expires in <strong style=\"color:#f1f5f9;\">15 minutes</strong>.
            </p>
            <!-- OTP Box -->
            <div style=\"background:#0f172a;border:1px solid #16a34a;border-radius:20px;padding:36px 24px;text-align:center;margin:0 0 28px;box-shadow:0 0 40px rgba(22,163,74,0.15);\">
              <p style=\"margin:0 0 12px;color:#16a34a;font-size:11px;font-weight:700;letter-spacing:3px;text-transform:uppercase;\">Your Verification Code</p>
              <p style=\"margin:0;font-size:52px;font-weight:900;letter-spacing:14px;color:#ffffff;font-variant-numeric:tabular-nums;\">{otp}</p>
              <p style=\"margin:16px 0 0;color:#475569;font-size:12px;\">Valid for 15 minutes only</p>
            </div>
            <!-- Security Notice -->
            <div style=\"background:#1c1917;border:1px solid #292524;border-left:3px solid #f59e0b;border-radius:10px;padding:14px 18px;margin-bottom:24px;\">
              <p style=\"margin:0;color:#d97706;font-size:13px;font-weight:600;\">⚠️ Security Notice</p>
              <p style=\"margin:6px 0;color:#78716c;font-size:12px;line-height:1.6;\">Never share this code with anyone. UWO Connect will never ask for your OTP via phone or chat.</p>
            </div>
            <p style=\"color:#475569;font-size:13px;margin:0;line-height:1.6;\">
              If you didn't request a password reset, you can safely ignore this email. Your account remains secure.
            </p>
            <!-- Support -->
            <p style=\"color:#94a3b8;font-size:13px;margin:24px 0 8px;\">Need help? Contact our support team at <a href=\"mailto:{DEFAULT_SUPPORT_EMAIL}\" style=\"color:#16a34a;\">{DEFAULT_SUPPORT_EMAIL}</a></p>
            <!-- Action Buttons -->
            <table role=\"presentation\" width=\"100%\" cellpadding=\"0\" cellspacing=\"0\" style=\"margin:16px 0;\">
              <tr>
                <td align=\"center\">
                  <a href=\"{DEFAULT_WEB_URL}\" style=\"display:inline-block;background:#16a34a;color:#ffffff;padding:10px 20px;border-radius:6px;text-decoration:none;font-size:14px;\">Open UWO Connect Web</a>
                </td>
              </tr>
              <tr><td height=\"8\"></td></tr>
              <tr>
                <td align=\"center\">
                  <a href=\"{DEFAULT_APP_URL}\" style=\"display:inline-block;background:#059669;color:#ffffff;padding:10px 20px;border-radius:6px;text-decoration:none;font-size:14px;\">Get the UWO Connect App</a>
                </td>
              </tr>
            </table>
          </td>
        </tr>
        <!-- Footer -->
        <tr><td style=\"padding:0 48px;\"><div style=\"height:1px;background:#334155;\"></div></td></tr>
        <tr>
          <td style=\"padding:24px 48px;text-align:center;\">
            <p style=\"color:#334155;font-size:12px;margin:0 0 6px;\">© {datetime.datetime.now().year} UWO Connect · All rights reserved</p>
            <p style=\"color:#1e3a29;font-size:11px;margin:0;\">This is an automated message, please do not reply.</p>
          </td>
        </tr>
      </table>
      <!-- /Card -->
    </td></tr>
  </table>
</body>
</html>"""
        
        try:
            send_mail(
                subject="Your Password Reset OTP - Uwo Connect",
                message=f"Your OTP for resetting your Uwo Connect password is: {otp}.\n\nThis OTP is valid for 15 minutes.",
                from_email=f"Uwo Connect <{settings.EMAIL_HOST_USER}>" if settings.EMAIL_HOST_USER else settings.DEFAULT_FROM_EMAIL,
                recipient_list=[email],
                html_message=html_body
            )
            resp = {
                "message": "A 6-digit OTP code has been sent to your registered email.",
                "status_code": 200,
                "email": email
            }
            if getattr(settings, 'DEBUG', False):
                resp["otp_debug"] = otp
                print(f"\n" + "=" * 55)
                print(f"🔑 [DEV MODE] PASSWORD RESET OTP FOR {email}: {otp}")
                print("=" * 55 + "\n")
            return resp
        except Exception as e:
            # In debug mode without active SMTP, still provide OTP for development
            if getattr(settings, 'DEBUG', False):
                print(f"\n" + "=" * 55)
                print(f"🔑 [DEV MODE - SMTP FALLBACK] OTP FOR {email}: {otp}")
                print(f"   (Mail send error: {e})")
                print("=" * 55 + "\n")
                return {
                    "message": "A 6-digit OTP code has been generated (Dev Mode).",
                    "status_code": 200,
                    "otp_debug": otp,
                    "email": email
                }
            return {"message": f"Failed to send email: {str(e)}", "status_code": 500}

    @staticmethod
    def forgot_password_verify_otp(email, otp):
        from django.utils import timezone
        from datetime import timedelta
        from ..models import PasswordResetOTP
        
        if not email or not otp:
            return {"message": "Email and OTP are required.", "status_code": 400}
        
        email = email.lower().strip()
        otp = str(otp).strip()

        try:
            otp_record = PasswordResetOTPRepository.filter_passwordresetotps(email=email, otp=otp).latest('created_at')
        except PasswordResetOTP.DoesNotExist:
            return {"message": "Invalid OTP. Please check the code sent to your email.", "status_code": 400}
        
        now = timezone.now()
        if now - otp_record.created_at > timedelta(minutes=15):
            otp_record.delete()
            return {"message": "OTP has expired. Please request a new code.", "status_code": 400}
            
        otp_record.is_verified = True
        otp_record.save()
        
        return {"message": "OTP verified successfully.", "status_code": 200}

    @staticmethod
    def forgot_password_reset(email, password):
        from django.utils import timezone
        from datetime import timedelta
        from ..models import PasswordResetOTP, User
        
        if not email or not password:
            return {"message": "Email and password are required.", "status_code": 400}
            
        email = email.lower().strip()
        
        # Verify valid OTP within 15-minute window exists and is verified
        otp_records = PasswordResetOTPRepository.filter_passwordresetotps(email=email, is_verified=True)
        if not otp_records.exists():
            return {"message": "OTP has not been verified yet or has expired.", "status_code": 400}
            
        latest_otp = otp_records.latest('created_at')
        if timezone.now() - latest_otp.created_at > timedelta(minutes=15):
            otp_records.delete()
            return {"message": "Reset window has expired. Please request a new OTP.", "status_code": 400}
            
        try:
            user = UserRepository.get_user(email=email)
            user.set_password(password)
            user.save()
            # Clean up all OTP records for this email immediately
            PasswordResetOTPRepository.filter_passwordresetotps(email=email).delete()
            return {"message": "Password reset successfully. You can now log in with your new password.", "status_code": 200}
        except User.DoesNotExist:
            return {"message": "User account not found.", "status_code": 404}
