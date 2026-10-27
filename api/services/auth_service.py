import secrets
import datetime
import os
import logging
logger = logging.getLogger(__name__)
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

        # If user registered with an invite_token, team member was explicitly invited by workspace admin
        has_invite = bool(serializer.validated_data.get('invite_token'))
        if has_invite:
            user.email_verified = True
            user.email_verified_at = timezone.now()
            user.status = 'APPROVED'
            user.save(update_fields=['email_verified', 'email_verified_at', 'status'])

            try:
                from .welcome_email_service import WelcomeEmailService
                WelcomeEmailService.send_welcome_email(user)
            except Exception as e:
                print(f"[WelcomeEmail Error] {e}")

            refresh = RefreshToken.for_user(user)
            return {
                "status": "APPROVED",
                "user": AuthService._serialize_user(user),
                "token": str(refresh.access_token)
            }

        # Standard new user registration -> Send Verification OTP
        user.email_verified = False
        user.status = 'PENDING'
        user.save(update_fields=['email_verified', 'status'])

        from .email_verification_service import EmailVerificationService
        otp_res = EmailVerificationService.create_and_send_otp(
            email=user.email,
            name=user.first_name or user.username
        )

        return {
            "status": "PENDING_VERIFICATION",
            "message": "Verification code sent to your registered email address.",
            "email": user.email,
            "userId": str(user.id),
            "requires_otp": True,
            **({"otp_debug": otp_res.get("otp_debug")} if otp_res.get("otp_debug") else {})
        }

    @staticmethod
    def verify_registration_otp(email, otp):
        if not email or not otp:
            return {"error": "Email and verification code are required.", "status_code": 400}

        clean_email = email.strip().lower()
        user = UserRepository.filter_users(email=clean_email).first() or UserRepository.filter_users(username=clean_email).first()
        if not user:
            return {"error": "No account found with this email address.", "status_code": 404}

        from .email_verification_service import EmailVerificationService
        res = EmailVerificationService.verify_otp(clean_email, otp)
        if not res.get("success"):
            return {"error": res.get("message", "Invalid or expired verification code."), "status_code": 400}

        user.refresh_from_db()

        # User is verified - trigger welcome email
        try:
            from .welcome_email_service import WelcomeEmailService
            WelcomeEmailService.send_welcome_email(user)
        except Exception as e:
            print(f"[WelcomeEmail Error] {e}")

        refresh = RefreshToken.for_user(user)
        return {
            "status": "APPROVED",
            "message": "Email verified successfully! Your account is activated.",
            "user": AuthService._serialize_user(user),
            "token": str(refresh.access_token)
        }

    @staticmethod
    def resend_registration_otp(email):
        if not email:
            return {"error": "Email address is required.", "status_code": 400}

        clean_email = email.strip().lower()
        user = UserRepository.filter_users(email=clean_email).first() or UserRepository.filter_users(username=clean_email).first()
        if not user:
            return {"error": "No account found with this email address.", "status_code": 404}

        if getattr(user, 'email_verified', False):
            return {"error": "This email address is already verified. You can sign in directly.", "status_code": 400}

        from .email_verification_service import EmailVerificationService
        res = EmailVerificationService.create_and_send_otp(clean_email, name=user.first_name or user.username)
        if not res.get("success"):
            return {
                "error": res.get("message", "Please wait before requesting a new code."),
                "cooldown": res.get("cooldown", False),
                "remaining_seconds": res.get("remaining_seconds", 30),
                "status_code": 429 if res.get("cooldown") else 400
            }

        return {
            "message": "A fresh 6-digit verification code has been sent to your email.",
            "email": clean_email,
            **({"otp_debug": res.get("otp_debug")} if res.get("otp_debug") else {})
        }

    @staticmethod
    def login_user(email, password, ip_address=None, user_agent=None, request=None, payload=None):
        if not email or not password:
            return {"error": "Email and password are required.", "status_code": 400}

        clean_email = email.strip().lower()
        user = authenticate(username=clean_email, password=password) or authenticate(username=email.strip(), password=password)
        
        if not user:
            user_obj = (
                UserRepository.filter_users(email__iexact=clean_email).first() or
                UserRepository.filter_users(email=clean_email).first() or
                UserRepository.filter_users(email=email.strip()).first()
            )
            if user_obj and user_obj.check_password(password):
                user = user_obj
        
        if not user:
            return {"error": "Invalid email or password.", "status_code": 401}

        # Check if email verification is required
        if not getattr(user, 'email_verified', False):
            from .email_verification_service import EmailVerificationService
            # Send a fresh OTP to help user verify seamlessly
            otp_res = EmailVerificationService.create_and_send_otp(user.email, name=user.first_name or user.username)
            return {
                "error": "Your email address is not verified yet. We have sent a verification code to your email.",
                "is_email_unverified": True,
                "email": user.email,
                "status_code": 403,
                **({"otp_debug": otp_res.get("otp_debug")} if otp_res.get("otp_debug") else {})
            }

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

        # 1. Google OAuth2 server-side cryptographic token verification
        # SECURITY: No unverified-decode fallback. The token audience must be one of OUR OAuth clients,
        # otherwise a Google token issued to any other app could be replayed here.
        try:
            from google.oauth2 import id_token as google_id_token
            from google.auth.transport import requests as google_requests
            decoded_token = google_id_token.verify_oauth2_token(
                id_token_str, 
                google_requests.Request()
            )
            allowed_auds = [a.strip() for a in os.getenv('GOOGLE_ALLOWED_CLIENT_IDS', '').split(',') if a.strip()]
            project_prefix = os.getenv('GOOGLE_OAUTH_PROJECT_NUMBER', '876129590251').strip() + '-'
            token_aud = str(decoded_token.get('aud', ''))
            if token_aud not in allowed_auds and not token_aud.startswith(project_prefix):
                return {"error": "Google token was not issued for this application.", "status_code": 401}
            if decoded_token.get('email_verified') is False:
                return {"error": "Google email address is not verified.", "status_code": 401}
        except Exception as google_err:
            # 2. Firebase ID Token verification (cryptographically verified by firebase_admin)
            try:
                decoded_token = firebase_auth.verify_id_token(id_token_str)
            except Exception:
                return {
                    "error": "Invalid Google token. Verification failed.", 
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
                # SECURITY: signature, expiry, issuer AND audience must all be valid.
                decoded_token = pyjwt.decode(
                    identity_token_str,
                    public_key,
                    algorithms=["RS256"],
                    audience=["com.uwo.uwoconnect", "host.exp.Exponent", "com.uwo.uwoconnect.service"],
                    issuer="https://appleid.apple.com",
                    options={"verify_exp": True},
                )
            else:
                raise ValueError("Matching Apple public key not found")
        except Exception as apple_err:
            # No unverified fallback — reject the token.
            logger.warning(f"[AppleLogin] Apple token verification failed: {apple_err}")
            return {"error": "Apple token verification failed.", "status_code": 401}

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
        except Exception:
            # SECURITY: No unverified-decode fallback.
            return {"error": "Firebase token verification failed.", "status_code": 401}

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
            "status": getattr(user, 'status', 'PENDING'),
            "email_verified": getattr(user, 'email_verified', False),
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
        
        html_body = f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="x-apple-disable-message-reformatting">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>Password Reset - UWO Connect</title>
  <!--[if mso]>
  <style type="text/css">
    table {{border-collapse:collapse;border-spacing:0;margin:0;}}
    div, td, a, span {{font-family:Arial, sans-serif !important;}}
  </style>
  <![endif]-->
  <style>
    :root {{
      color-scheme: light;
      supported-color-schemes: light;
    }}
    body {{
      margin: 0 !important;
      padding: 0 !important;
      -webkit-text-size-adjust: 100% !important;
      -ms-text-size-adjust: 100% !important;
      background-color: #f1f5f9 !important;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
    }}
    table {{
      border-collapse: collapse;
      mso-table-lspace: 0pt;
      mso-table-rspace: 0pt;
    }}
    img {{
      border: 0;
      line-height: 100%;
      outline: none;
      text-decoration: none;
      -ms-interpolation-mode: bicubic;
    }}
    @media only screen and (max-width: 620px) {{
      .wrapper-table {{
        width: 100% !important;
        padding: 10px !important;
      }}
      .main-container {{
        width: 100% !important;
        border-radius: 16px !important;
      }}
      .content-padding {{
        padding: 24px 20px !important;
      }}
      .hero-padding {{
        padding: 32px 20px 28px !important;
      }}
      .cta-button {{
        display: block !important;
        width: 100% !important;
        text-align: center !important;
        box-sizing: border-box !important;
      }}
    }}
    /* Force light mode — override any dark-mode auto-inversion */
    @media (prefers-color-scheme: dark) {{
      body {{ background-color: #f1f5f9 !important; color: #0f172a !important; }}
      .main-container {{ background-color: #ffffff !important; }}
      .footer-bg {{ background-color: #f8fafc !important; }}
      .otp-card {{ background-color: #f0fdf4 !important; border-color: #86efac !important; }}
    }}
  </style>
</head>
<body style="margin:0;padding:0;background-color:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;-webkit-font-smoothing:antialiased;color:#0f172a;">

  <!-- Email Wrapper -->
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" class="wrapper-table" style="background-color:#f1f5f9;padding:32px 12px;">
    <tr>
      <td align="center">
        <!--[if (gte mso 9)|(IE)]>
        <table align="center" border="0" cellspacing="0" cellpadding="0" width="600">
        <tr>
        <td align="center" valign="top" width="600">
        <![endif]-->
        <table role="presentation" width="100%" class="main-container" style="max-width:600px;background-color:#ffffff;border-radius:22px;overflow:hidden;box-shadow:0 12px 36px rgba(15,23,42,0.08);border:1px solid #e2e8f0;" cellspacing="0" cellpadding="0">

          <!-- Top Brand Bar -->
          <tr>
            <td style="padding:22px 32px 20px;background-color:#ffffff;border-bottom:1px solid #f1f5f9;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="left" valign="middle">
                    <table role="presentation" cellspacing="0" cellpadding="0">
                      <tr>
                        <td valign="middle" style="padding-right:12px;">
                          <div style="width:42px;height:42px;border-radius:12px;background:#f0fdf4;border:1.5px solid #d1fae5;overflow:hidden;text-align:center;line-height:42px;">
                            <img src="https://uwoconnect.aisa24.com/download%20(3).gif" alt="UWO Connect Logo" width="42" height="42" style="display:block;width:42px;height:42px;object-fit:cover;border-radius:10px;" onerror="this.style.display='none';">
                          </div>
                        </td>
                        <td valign="middle">
                          <span style="font-size:20px;font-weight:800;color:#0f172a;letter-spacing:-0.5px;display:inline-block;line-height:1.1;">
                            UWO <span style="color:#059669;">Connect</span>
                          </span>
                          <br>
                          <span style="font-size:10px;font-weight:700;color:#64748b;text-transform:uppercase;letter-spacing:1.4px;display:inline-block;margin-top:2px;">
                            AI Workspace &amp; CRM
                          </span>
                        </td>
                      </tr>
                    </table>
                  </td>
                  <td align="right" valign="middle">
                    <div style="display:inline-block;background:#ecfdf5;border:1px solid #a7f3d0;padding:5px 12px;border-radius:20px;">
                      <span style="color:#047857;font-size:11px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;">&#128274; Secure Request</span>
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Green Hero Banner -->
          <tr>
            <td class="hero-padding" style="background:linear-gradient(135deg, #059669 0%, #047857 50%, #064e3b 100%);padding:42px 36px 36px;text-align:center;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <div style="display:inline-block;background:rgba(255,255,255,0.18);border:1px solid rgba(255,255,255,0.25);padding:8px 20px;border-radius:30px;margin-bottom:16px;">
                      <span style="color:#ffffff;font-size:12px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;">Password Reset Request</span>
                    </div>
                    <h1 style="color:#ffffff;margin:0 0 10px;font-size:26px;font-weight:800;letter-spacing:-0.6px;line-height:1.25;">
                      Reset Your Password
                    </h1>
                    <p style="color:#d1fae5;margin:0;font-size:15px;font-weight:500;line-height:1.5;max-width:460px;">
                      Use the one-time code below to securely reset your account password.
                    </p>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

          <!-- Main Content -->
          <tr>
            <td class="content-padding" style="padding:36px 36px 30px;background-color:#ffffff;">

              <!-- Greeting -->
              <p style="margin:0 0 16px;font-size:17px;font-weight:700;color:#0f172a;">
                Hi there,
              </p>

              <p style="margin:0 0 24px;font-size:15px;line-height:1.7;color:#334155;">
                We received a request to reset the password for your UWO Connect account. Use the one-time code below &mdash; it expires in <strong style="color:#047857;">15 minutes</strong>.
              </p>

              <!-- OTP Card — matches Welcome email credential block style -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" class="otp-card" style="margin:4px 0 28px;background-color:#f0fdf4;border:1.5px solid #86efac;border-radius:14px;overflow:hidden;">
                <tr>
                  <td style="padding:28px 24px;text-align:center;">
                    <div style="font-size:11px;font-weight:700;color:#166534;text-transform:uppercase;letter-spacing:2px;margin-bottom:14px;">
                      Your One-Time Password
                    </div>
                    <div style="font-family:'Courier New',Courier,monospace;font-size:42px;font-weight:800;color:#047857;letter-spacing:10px;line-height:1.1;">
                      {otp}
                    </div>
                    <div style="font-size:12px;color:#166534;margin-top:14px;line-height:1.5;">
                      This code is valid for <strong>15 minutes only</strong>. Do not share it with anyone.
                    </div>
                  </td>
                </tr>
              </table>

              <!-- Security Notice — same light card style -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin-bottom:24px;background-color:#fffbeb;border:1px solid #fde68a;border-radius:14px;overflow:hidden;">
                <tr>
                  <td style="padding:16px 20px;">
                    <div style="font-size:13px;font-weight:700;color:#92400e;margin-bottom:5px;">Security Notice</div>
                    <div style="font-size:13px;color:#78350f;line-height:1.6;">
                      If you did not request a password reset, you can safely ignore this email. Your account remains secure.
                    </div>
                  </td>
                </tr>
              </table>

              <!-- Need Help -->
              <p style="margin:0 0 6px;font-size:14px;font-weight:700;color:#0f172a;">Need help?</p>
              <p style="margin:0 0 28px;font-size:14px;color:#334155;">
                Reach us at <a href="mailto:{DEFAULT_SUPPORT_EMAIL}" style="color:#059669;font-weight:700;text-decoration:none;">{DEFAULT_SUPPORT_EMAIL}</a>
              </p>

              <!-- CTA Buttons — exactly matching Welcome email button style -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:8px 0 24px;">
                <tr>
                  <td align="center">
                    <!-- Web Button -->
                    <table role="presentation" cellspacing="0" cellpadding="0" style="display:inline-table;margin:6px 6px;">
                      <tr>
                        <td align="center" style="border-radius:12px;background:linear-gradient(135deg, #10b981 0%, #059669 100%);box-shadow:0 6px 18px rgba(16,185,129,0.35);">
                          <a href="{DEFAULT_WEB_URL}" class="cta-button" style="display:inline-block;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:15px 30px;letter-spacing:0.3px;text-align:center;" target="_blank">
                            &#127760; Open UWO Connect Web &rarr;
                          </a>
                        </td>
                      </tr>
                    </table>

                    <!-- App Button -->
                    <table role="presentation" cellspacing="0" cellpadding="0" style="display:inline-table;margin:6px 6px;">
                      <tr>
                        <td align="center" style="border-radius:12px;background:#0f172a;box-shadow:0 6px 18px rgba(15,23,42,0.22);">
                          <a href="{DEFAULT_APP_URL}" class="cta-button" style="display:inline-block;color:#ffffff;text-decoration:none;font-size:15px;font-weight:700;padding:15px 30px;letter-spacing:0.3px;text-align:center;" target="_blank">
                            &#128241; Download Mobile App &rarr;
                          </a>
                        </td>
                      </tr>
                    </table>
                  </td>
                </tr>
                <tr>
                  <td align="center" style="padding-top:12px;">
                    <span style="font-size:12px;color:#64748b;">
                      Available on Web Browser &bull; Android (Google Play) &bull; iOS
                    </span>
                  </td>
                </tr>
              </table>

              <!-- Team Tagline — same as Welcome email -->
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:10px 0 8px;background-color:#f0fdf4;border:1px solid #bbf7d0;border-radius:14px;overflow:hidden;">
                <tr>
                  <td style="padding:18px 24px;text-align:center;">
                    <div style="font-size:15px;font-weight:800;color:#047857;letter-spacing:0.2px;margin-bottom:6px;">
                      Connect everything. Automate anything.
                    </div>
                    <div style="font-size:13px;font-weight:700;color:#059669;">
                      &mdash; Team UWO Connect
                    </div>
                  </td>
                </tr>
              </table>

            </td>
          </tr>

          <!-- Footer — exact match with Welcome email -->
          <tr>
            <td class="footer-bg" style="background-color:#f8fafc;padding:28px 36px 32px;border-top:1px solid #e2e8f0;text-align:center;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td align="center">
                    <div style="font-size:14px;font-weight:800;color:#0f172a;letter-spacing:-0.3px;margin-bottom:4px;">
                      UWO <span style="color:#059669;">Connect</span>
                    </div>
                    <div style="font-size:12px;color:#64748b;line-height:1.5;margin-bottom:14px;">
                      Unified Communication &amp; Business Automation Platform
                    </div>

                    <div style="font-size:12px;color:#94a3b8;line-height:1.6;margin-bottom:14px;">
                      Support: <a href="mailto:{DEFAULT_SUPPORT_EMAIL}" style="color:#059669;font-weight:700;text-decoration:none;">{DEFAULT_SUPPORT_EMAIL}</a>
                      &nbsp;&bull;&nbsp;
                      <a href="{DEFAULT_WEB_URL}" style="color:#059669;font-weight:600;text-decoration:none;">Web Dashboard</a>
                      &nbsp;&bull;&nbsp;
                      <a href="{DEFAULT_APP_URL}" style="color:#059669;font-weight:600;text-decoration:none;">Mobile App</a>
                    </div>

                    <div style="font-size:11px;color:#94a3b8;line-height:1.5;border-top:1px solid #f1f5f9;padding-top:14px;margin-top:10px;">
                      &copy; {datetime.datetime.now().year} UWO Connect. All rights reserved.
                    </div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>

        </table>
        <!--[if (gte mso 9)|(IE)]>
        </td>
        </tr>
        </table>
        <![endif]-->
      </td>
    </tr>
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
            import traceback
            print(f"\n[OTP EMAIL ERROR] Failed to send OTP email to {email}")
            print(f"[OTP EMAIL ERROR] Error type: {type(e).__name__}")
            print(f"[OTP EMAIL ERROR] Error detail: {str(e)}")
            print(f"[OTP EMAIL ERROR] Traceback:\n{traceback.format_exc()}")
            # In debug mode without active SMTP, still provide OTP for development
            if getattr(settings, 'DEBUG', False):
                return {
                    "message": "A 6-digit OTP code has been generated (Dev Mode).",
                    "status_code": 200,
                    "otp_debug": otp,
                    "email": email,
                    "smtp_error": str(e)  # temporary: shows real error
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
            
        from ..utils.password_validator import validate_password_strength
        is_valid, errors = validate_password_strength(password)
        if not is_valid:
            msg = errors[0] if len(errors) == 1 else " ".join(errors)
            return {"message": msg, "error": msg, "status_code": 400}
            
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
