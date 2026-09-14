from ..permissions.custom_permissions import IsApprovedUser
from rest_framework import status, views, viewsets
from rest_framework.response import Response
from firebase_admin import auth as firebase_auth
from django.contrib.auth import authenticate
from rest_framework.permissions import IsAuthenticated, IsAdminUser, AllowAny
from rest_framework.decorators import action
from rest_framework.views import APIView
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from ..serializers import RegisterSerializer, UserSerializer, ClientSerializer, AutomationSerializer, WorkflowSerializer, ContactSerializer, TemplateSerializer, CampaignSerializer, SupportMessageSerializer, AuditLogSerializer, TeamInviteSerializer, ProductSerializer, OrderSerializer
from ..repositories.client_repository import ClientRepository
from ..models import User, Client, Automation, Message, Workflow, KnowledgeDocument, KnowledgeChunk, Contact, Template, Campaign, SupportMessage, AuditLog, TeamInvite, Product, Order, QrAuthSession, LinkedDevice
import requests
import os
import json
from ..services.ai_service import get_ai_response, get_platform_assistance, get_rag_response, get_embedding, chunk_text, find_relevant_chunks
from ..utils.channel_permissions import validate_channel_access, safe_get_client
from rest_framework.permissions import BasePermission

def get_tenant_client(request):
    if not request.user or not request.user.is_authenticated:
        return None
    if request.user.role == 'ADMIN':
        client_id = request.query_params.get('client_id') or request.data.get('client_id')
        if client_id:
            try:
                return ClientRepository.get_client(id=client_id)
            except (Client.DoesNotExist, ValueError):
                pass
        # Fallback to user's client if present
        c = safe_get_client(request.user)
        if c:
            return c
        # Fallback to first available client
        try:
            return ClientRepository.get_all_clients().first()
        except Exception:
            return None
    return safe_get_client(request.user)

class RegisterView(views.APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, req):
        serializer = RegisterSerializer(data=req.data)
        if serializer.is_valid():
            from ..services.auth_service import AuthService
            result = AuthService.register_user(serializer)
            if result.get("status") == "APPROVED":
                return Response({
                    "user": result["user"],
                    "token": result["token"]
                }, status=status.HTTP_201_CREATED)
            else:
                return Response({
                    "message": result["message"],
                    "userId": result["userId"]
                }, status=status.HTTP_201_CREATED)
            
        first_error = next(iter(serializer.errors.values()))[0]
        return Response({"message": str(first_error)}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')


class LoginView(views.APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, req):
        email = req.data.get('email', '').strip().lower()
        password = req.data.get('password', '')

        # Extract client IP address
        x_forwarded_for = req.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = req.META.get('REMOTE_ADDR')

        from ..services.auth_service import AuthService
        result = AuthService.login_user(email, password, ip_address=ip_address)
        
        if "error" in result:
            return Response({"message": result["error"]}, status=result["status_code"])

        return Response({
            "user": result["user"],
            "token": result["token"]
        })

@method_decorator(csrf_exempt, name='dispatch')


class GoogleLoginView(views.APIView):
    """
    POST /api/auth/google/
    Verifies Google ID Token server-side, links or registers user, and returns JWT session.
    """
    permission_classes = []
    authentication_classes = []

    def post(self, req):
        try:
            id_token_raw = req.data.get('id_token')
            if not id_token_raw or not isinstance(id_token_raw, str):
                return Response({"message": "Valid Google id_token string is required."}, status=status.HTTP_400_BAD_REQUEST)
            id_token = id_token_raw.strip()

            name = str(req.data.get('name') or '').strip()
            invite_token = str(req.data.get('invite_token') or '').strip()
            business_name = str(req.data.get('business_name') or '').strip()

            # Extract client IP address
            x_forwarded_for = req.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = req.META.get('REMOTE_ADDR')

            from ..services.auth_service import AuthService
            result = AuthService.process_google_login(id_token, name=name, invite_token=invite_token, business_name=business_name, ip_address=ip_address)

            if "error" in result:
                return Response({"message": result["error"]}, status=result.get("status_code", 400))

            if result.get("is_created"):
                if result.get("status") == "PENDING":
                    return Response({
                        "message": result["message"],
                        "userId": result["userId"]
                    }, status=status.HTTP_201_CREATED)
                else:
                    return Response({
                        "user": result["user"],
                        "token": result["token"]
                    }, status=status.HTTP_201_CREATED)

            return Response({
                "user": result["user"],
                "token": result["token"]
            }, status=status.HTTP_200_OK)
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Google login unhandled error")
            return Response({"message": f"Google authentication failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

@method_decorator(csrf_exempt, name='dispatch')


class GoogleClientIdView(views.APIView):
    """Legacy Google Client ID endpoint — kept for backward compatibility."""
    permission_classes = []
    authentication_classes = []

    def get(self, req):
        return Response({"client_id": ""})

@method_decorator(csrf_exempt, name='dispatch')


class FirebaseLoginView(views.APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, req):
        try:
            id_token_raw = req.data.get('id_token')
            if not id_token_raw or not isinstance(id_token_raw, str):
                return Response({"message": "Valid id_token string is required."}, status=status.HTTP_400_BAD_REQUEST)
            id_token = id_token_raw.strip()

            name = str(req.data.get('name') or '').strip()
            invite_token = str(req.data.get('invite_token') or '').strip()
            business_name = str(req.data.get('business_name') or '').strip()

            # Extract client IP address
            x_forwarded_for = req.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded_for:
                ip_address = x_forwarded_for.split(',')[0].strip()
            else:
                ip_address = req.META.get('REMOTE_ADDR')

            meta_portfolio_name = str(req.data.get('meta_portfolio_name') or req.data.get('portfolio_name') or req.data.get('portfolioName') or '').strip()

            from ..services.auth_service import AuthService
            result = AuthService.process_firebase_login(
                id_token, name, invite_token, business_name, ip_address=ip_address, meta_portfolio_name=meta_portfolio_name
            )

            if "error" in result:
                return Response({"message": result["error"]}, status=result["status_code"])

            if result.get("is_created"):
                if result.get("status") == "PENDING":
                    return Response({
                        "message": result["message"],
                        "userId": result["userId"]
                    }, status=status.HTTP_201_CREATED)
                else:
                    return Response({
                        "user": result["user"],
                        "token": result["token"]
                    }, status=status.HTTP_201_CREATED)

            return Response({
                "user": result["user"],
                "token": result["token"]
            })
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Firebase login unhandled error")
            return Response({"message": f"Login process failed: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)


@method_decorator(csrf_exempt, name='dispatch')
class UWOLoginView(views.APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, req):
        email_raw = req.data.get('email')
        if not email_raw or not isinstance(email_raw, str):
            return Response({"message": "Valid email string is required."}, status=status.HTTP_400_BAD_REQUEST)
        email = email_raw.strip().lower()

        name = str(req.data.get('name') or '').strip()
        uwo_token = str(req.data.get('uwo_token') or '').strip()

        # Extract client IP address
        x_forwarded_for = req.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip_address = x_forwarded_for.split(',')[0].strip()
        else:
            ip_address = req.META.get('REMOTE_ADDR')

        from ..services.auth_service import AuthService
        result = AuthService.process_uwo_login(email, name, uwo_token, ip_address=ip_address)

        if "error" in result:
            return Response({"message": result["error"]}, status=result.get("status_code", 400))

        return Response({
            "user": result["user"],
            "token": result["token"]
        }, status=status.HTTP_200_OK)


class ProfileView(APIView):

    permission_classes = [IsAuthenticated]

    def get(self, request):
        user_serializer = UserSerializer(request.user)
        user_data = user_serializer.data

        client_data = {}
        global_map = {}
        effective_map = {}

        if getattr(request.user, 'client', None):
            serializer = ClientSerializer(request.user.client)
            client_data = dict(serializer.data)
            try:
                from api.utils.channel_permissions import get_user_effective_connectors
                effective_map = get_user_effective_connectors(request.user, client=request.user.client)
                global_map = {k: v['global_active'] for k, v in effective_map.items()}
                client_data['global_connectors'] = global_map
                client_data['effective_connectors'] = effective_map
            except Exception as e:
                global_map = {}
                effective_map = {}
        else:
            # Super Admin or staff user without a direct client tenant
            client_data = {
                "business_name": "Platform Super Admin",
                "email": request.user.email,
                "plan": "Super Admin",
                "plan_name": "Super Admin",
                "status": "ACTIVE"
            }

        client_plan = client_data.get('plan') or ('Super Admin' if request.user.role == 'ADMIN' else 'ADVANCED')
        is_agency = bool(client_data.get('is_agency') or client_plan == 'AGENCY' or client_data.get('white_label_domain'))

        user_data['plan'] = client_plan
        user_data['client_plan'] = client_plan
        user_data['is_agency'] = is_agency
        user_data['client'] = client_data

        return Response({
            **user_data,
            "plan": client_plan,
            "client_plan": client_plan,
            "is_agency": is_agency,
            "client": client_data,
            "user": user_data,
            "global_connectors": global_map,
            "effective_connectors": effective_map,
        })

    def put(self, request):
        return self.patch(request)

    def patch(self, request):
        user = request.user
        raw_data = dict(request.data) if isinstance(request.data, dict) else {}
        user_dict = raw_data.get('user', {}) if isinstance(raw_data.get('user'), dict) else {}
        client_dict = raw_data.get('client', {}) if isinstance(raw_data.get('client'), dict) else {}

        # Merge for user
        name = raw_data.get('name') or user_dict.get('name')
        first_name = raw_data.get('first_name') or user_dict.get('first_name')
        last_name = raw_data.get('last_name') or user_dict.get('last_name')
        phone_number = raw_data.get('phone_number') or user_dict.get('phone_number') or client_dict.get('phone_number')
        meta_portfolio_name = raw_data.get('meta_portfolio_name') or user_dict.get('meta_portfolio_name') or client_dict.get('meta_portfolio_name')

        if name:
            name_parts = str(name).strip().split(' ', 1)
            user.first_name = name_parts[0]
            user.last_name = name_parts[1] if len(name_parts) > 1 else ''
            user.save()

        if first_name:
            user.first_name = str(first_name).strip()
            user.save()

        if last_name:
            user.last_name = str(last_name).strip()
            user.save()

        if phone_number:
            user.phone_number = str(phone_number).strip()
            user.save()

        if meta_portfolio_name:
            user.meta_portfolio_name = str(meta_portfolio_name).strip()
            user.save()

        if not getattr(request.user, 'client', None):
            user_serializer = UserSerializer(user)
            return Response({
                "message": "User profile updated successfully",
                "user": user_serializer.data,
                **user_serializer.data
            })

        # Validate channel permissions if channel configurations are being updated
        if any(k in raw_data for k in ['whatsapp_access_token', 'whatsapp_phone_number_id', 'whatsapp_waba_id', 'whatsapp_config']):
            is_allowed, reason, status_code = validate_channel_access(request.user, 'whatsapp')
            if not is_allowed:
                return Response({"error": reason or "You do not have access to this channel."}, status=status_code)

        if 'facebook_config' in raw_data:
            is_allowed, reason, status_code = validate_channel_access(request.user, 'facebook')
            if not is_allowed:
                return Response({"error": reason or "You do not have access to this channel."}, status=status_code)

        if 'instagram_config' in raw_data:
            is_allowed, reason, status_code = validate_channel_access(request.user, 'instagram')
            if not is_allowed:
                return Response({"error": reason or "You do not have access to this channel."}, status=status_code)

        # Merge root data and client nested data
        merged_client_data = {**raw_data, **client_dict}
        merged_client_data.pop('user', None)
        merged_client_data.pop('client', None)

        # Update Client fields
        serializer = ClientSerializer(request.user.client, data=merged_client_data, partial=True)
        if serializer.is_valid():
            client_instance = serializer.save()
            if 'meta_portfolio_name' in request.data and client_instance:
                client_instance.meta_portfolio_name = str(request.data['meta_portfolio_name']).strip()
                client_instance.save()
            
            # --- Programmatic Webhook Auto-Subscription to Meta App ---
            import requests
            
            # 1. Handle Facebook Page Subscription
            facebook_config = request.data.get('facebook_config')
            if facebook_config and isinstance(facebook_config, dict):
                page_id = facebook_config.get('page_id')
                access_token = facebook_config.get('access_token')
                if page_id and access_token:
                     try:
                         sub_url = f"https://graph.facebook.com/v20.0/{page_id}/subscribed_apps"
                         sub_payload = {
                             "subscribed_fields": "messages,messaging_postbacks,messaging_optins,message_deliveries",
                             "access_token": access_token
                         }
                         res = requests.post(sub_url, data=sub_payload, timeout=10)
                     except Exception as e:
                         print(f"Error subscribing Facebook page {page_id}: {str(e)}")
            
            # 2. Handle Instagram Page Subscription
            instagram_config = request.data.get('instagram_config')
            if instagram_config and isinstance(instagram_config, dict):
                access_token = instagram_config.get('access_token')
                if access_token:
                    try:
                        if access_token.startswith('IG'):
                            sub_url = f"https://graph.instagram.com/v20.0/me/subscribed_apps"
                            sub_payload = {
                                "subscribed_fields": "messages,messaging_postbacks,messaging_optins,messaging_seen,message_reactions",
                                "access_token": access_token
                            }
                            res = requests.post(sub_url, data=sub_payload, timeout=10)
                        else:
                            # Find Page ID associated with the Instagram access token / Page Access Token
                            me_res = requests.get(f"https://graph.facebook.com/v20.0/me?fields=id,name&access_token={access_token}", timeout=10)
                            if me_res.status_code == 200:
                                page_id = me_res.json().get('id')
                                if page_id:
                                    sub_url = f"https://graph.facebook.com/v20.0/{page_id}/subscribed_apps"
                                    sub_payload = {
                                        "subscribed_fields": "messages,messaging_postbacks,messaging_optins,message_deliveries",
                                        "access_token": access_token
                                    }
                                    res = requests.post(sub_url, data=sub_payload, timeout=10)
                    except Exception as e:
                         print(f"Error subscribing Instagram linked page: {str(e)}")
                         
            user_serializer = UserSerializer(request.user)
            user_data = user_serializer.data
            client_data = dict(serializer.data)
            active_plan = getattr(request.user.client, 'plan', 'ADVANCED')
            user_data['plan'] = active_plan
            user_data['client_plan'] = active_plan
            user_data['client'] = client_data
            return Response({
                **user_data,
                "message": "Profile updated successfully",
                "client": client_data,
                "user": user_data,
                "plan": active_plan,
                "client_plan": active_plan,
                **client_data,
            })
        print("Profile validation errors:", serializer.errors)
        return Response(serializer.errors, status=400)

from ..models import User, Client, Automation, Workflow, GlobalSetting
from ..serializers import RegisterSerializer, UserSerializer, ClientSerializer, AutomationSerializer, WorkflowSerializer, GlobalSettingSerializer


class ForgotPasswordSendOTPView(views.APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, req):
        email = req.data.get('email', '').lower().strip()
        from ..services.auth_service import AuthService
        result = AuthService.forgot_password_send_otp(email)
        return Response(result, status=result.get("status_code", 200))

@method_decorator(csrf_exempt, name='dispatch')


class ForgotPasswordVerifyOTPView(views.APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, req):
        email = req.data.get('email', '').lower().strip()
        otp = req.data.get('otp', '').strip()
        
        from ..services.auth_service import AuthService
        result = AuthService.forgot_password_verify_otp(email, otp)
        return Response(result, status=result.get("status_code", 200))

@method_decorator(csrf_exempt, name='dispatch')


class ForgotPasswordResetView(views.APIView):
    permission_classes = []
    authentication_classes = []

    def post(self, req):
        email = req.data.get('email', '').lower().strip()
        password = req.data.get('password', '')
        
        from ..services.auth_service import AuthService
        result = AuthService.forgot_password_reset(email, password)
        return Response(result, status=result.get("status_code", 200))

class WhatsAppEmbeddedSignupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # 0. Check admin channel access
        is_allowed, reason, status_code = validate_channel_access(request.user, 'whatsapp')
        if not is_allowed:
            return Response({"error": reason or "You do not have access to this channel."}, status=status_code)

        code = request.data.get('code')
        access_token = request.data.get('access_token')
        waba_id = request.data.get('waba_id')
        phone_number_id = request.data.get('phone_number_id')
        if not code and not access_token and not (waba_id or phone_number_id):
            return Response({"error": "No authorization code or WABA details provided"}, status=400)

        import os
        import requests
        import logging
        logger = logging.getLogger(__name__)
        
        client_id = os.getenv('FACEBOOK_APP_ID')
        client_secret = os.getenv('FACEBOOK_APP_SECRET')
        
        if not client_id or not client_secret:
            return Response({"error": "Facebook App credentials not configured on server."}, status=500)

        client = safe_get_client(request.user)

        # 1. Exchange code for access token if supplied
        if not access_token and code:
            token_url = "https://graph.facebook.com/v20.0/oauth/access_token"
            candidate_uris = []
            req_uri = request.data.get('redirect_uri')
            if req_uri:
                candidate_uris.append(req_uri)
            candidate_uris.extend([
                "https://uwoconnectforrf-743928421487.asia-south1.run.app/",
                "https://uwoconnect.aisa24.com/client/channels?state=whatsapp",
                "https://uwoconnect.aisa24.com/client/channels",
                "https://uwoconnect.aisa24.com/",
                ""
            ])
            
            token_data = {}
            for cand_uri in candidate_uris:
                token_payload = {
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "code": code
                }
                if cand_uri:
                    token_payload["redirect_uri"] = cand_uri
                
                try:
                    token_res = requests.get(token_url, params=token_payload, timeout=10)
                    token_data = token_res.json()
                    if "access_token" in token_data:
                        logger.info(f"[WhatsAppEmbeddedSignup] Token exchanged successfully with redirect_uri: '{cand_uri}'")
                        break
                except Exception as e:
                    logger.warning(f"[WhatsAppEmbeddedSignup] Token exchange attempt error with '{cand_uri}': {e}")

            if "access_token" in token_data:
                access_token = token_data.get('access_token')

        # Fallback access token if code was not returned but waba_id/phone_number_id provided
        if not access_token:
            access_token = getattr(client, 'whatsapp_access_token', None) or os.getenv('WHATSAPP_SYSTEM_TOKEN', '')
            if not access_token:
                access_token = f"{client_id}|{client_secret}"

        # 1.5 Upgrade to Long-Lived Access Token
        if access_token:
            try:
                ll_res = requests.get(
                    "https://graph.facebook.com/v20.0/oauth/access_token",
                    params={
                        "grant_type": "fb_exchange_token",
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "fb_exchange_token": access_token
                    },
                    timeout=10
                )
                ll_data = ll_res.json()
                if "access_token" in ll_data:
                    access_token = ll_data["access_token"]
            except Exception as e:
                logger.warning(f"[WhatsAppEmbeddedSignup] Long-lived token exchange warning: {e}")
        
        waba_id = request.data.get('waba_id')
        phone_number_id = request.data.get('phone_number_id')
        display_phone_number = ''

        # 2. Get shared WABA info if not provided
        client = safe_get_client(request.user)
        claimed_wabas = set(
            Client.objects.filter(whatsapp_waba_id__isnull=False)
            .exclude(id=client.id if client else None)
            .values_list('whatsapp_waba_id', flat=True)
        )

        if not waba_id:
            candidate_wabas = []
            waba_url = f"https://graph.facebook.com/v20.0/me/client_whatsapp_business_accounts?access_token={access_token}"
            try:
                waba_res = requests.get(waba_url, timeout=10)
                waba_data = waba_res.json()
                if waba_data.get('data'):
                    for item in waba_data['data']:
                        candidate_wabas.append(item.get('id'))
            except Exception as e:
                logger.warning(f"[WhatsAppEmbeddedSignup] client_waba error: {e}")

            # Fallback: check debug_token to find granular_scopes target_ids
            if not candidate_wabas:
                try:
                    debug_url = f"https://graph.facebook.com/debug_token?input_token={access_token}&access_token={client_id}|{client_secret}"
                    debug_res = requests.get(debug_url, timeout=10)
                    debug_data = debug_res.json()
                    scopes = debug_data.get('data', {}).get('granular_scopes', [])
                    for scope in scopes:
                        if scope.get('scope') == 'whatsapp_business_management' and scope.get('target_ids'):
                            candidate_wabas.extend(scope['target_ids'])
                except Exception as e:
                    logger.warning(f"[WhatsAppEmbeddedSignup] debug_token error: {e}")

            # Pick the best candidate: prefer one not already claimed by another client
            for cand in candidate_wabas:
                if str(cand) not in claimed_wabas:
                    waba_id = str(cand)
                    break
            
            # Fallback if all claimed or empty
            if not waba_id and candidate_wabas:
                waba_id = str(candidate_wabas[0])


        # 3. Get Phone Number ID if not provided
        if waba_id and not phone_number_id:
            phone_url = f"https://graph.facebook.com/v20.0/{waba_id}/phone_numbers?access_token={access_token}"
            phone_res = requests.get(phone_url)
            phone_data = phone_res.json()
            
            if phone_data.get('data') and len(phone_data['data']) > 0:
                phone_number_id = phone_data['data'][0]['id']
                display_phone_number = phone_data['data'][0].get('display_phone_number', '')

        # 3.5 Fetch display phone number if phone_number_id is known
        if phone_number_id and not display_phone_number:
            try:
                p_url = f"https://graph.facebook.com/v20.0/{phone_number_id}?fields=display_phone_number,verified_name&access_token={access_token}"
                p_res = requests.get(p_url, timeout=10)
                p_data = p_res.json()
                display_phone_number = p_data.get('display_phone_number') or p_data.get('verified_name', '')
            except Exception as e:
                logger.warning(f"[WhatsAppEmbeddedSignup] Phone details fetch warning: {e}")

        # 4. Subscribe WABA to webhook events
        if waba_id:
            try:
                sub_url = f"https://graph.facebook.com/v20.0/{waba_id}/subscribed_apps"
                sub_res = requests.post(sub_url, headers={"Authorization": f"Bearer {access_token}"}, timeout=10)
                logger.info(f"[WhatsAppEmbeddedSignup] Webhook subscribe status: {sub_res.status_code}")
            except Exception as e:
                logger.warning(f"[WhatsAppEmbeddedSignup] Could not subscribe WABA {waba_id}: {e}")
        
        # 5. Save to Client
        client = safe_get_client(request.user)
        if not client:
            return Response({"error": "No client workspace associated with this user account."}, status=400)
            
        client.whatsapp_config = {
            "access_token": access_token,
            "waba_id": waba_id,
            "phone_number_id": phone_number_id,
            "display_phone_number": display_phone_number
        }
        client.whatsapp_access_token = access_token
        client.whatsapp_waba_id = waba_id
        client.whatsapp_phone_number_id = phone_number_id
        if display_phone_number:
            client.phone_number = display_phone_number
        client.whatsapp_enabled = True
        client.save()
        
        return Response({
            "message": "WhatsApp Business connected successfully",
            "whatsapp_config": client.whatsapp_config
        })


class InstagramEmbeddedSignupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # 0. Check admin channel access
        is_allowed, reason, status_code = validate_channel_access(request.user, 'instagram')
        if not is_allowed:
            return Response({"error": reason or "You do not have access to this channel."}, status=status_code)

        access_token = request.data.get('access_token')

        import os
        import requests
        import datetime
        
        client_id = os.getenv('FACEBOOK_APP_ID')
        client_secret = os.getenv('FACEBOOK_APP_SECRET')
        
        if not client_id or not client_secret:
            return Response({"error": "Facebook App credentials not configured on server."}, status=500)

        if not access_token:
            return Response({"error": "No access_token provided"}, status=400)

        # Exchange for Long-Lived Token
        ll_res = requests.get(
            "https://graph.facebook.com/v20.0/oauth/access_token",
            params={
                "grant_type":        "fb_exchange_token",
                "client_id":         client_id,
                "client_secret":     client_secret,
                "fb_exchange_token": access_token,
            }
        )
        ll_data = ll_res.json()
        long_lived_token = ll_data.get("access_token", access_token)
        
        # Fetch connected pages and their Instagram accounts
        accounts_url = f"https://graph.facebook.com/v20.0/me/accounts?fields=id,name,access_token,instagram_business_account{{id,username,name}}&access_token={long_lived_token}"
        accounts_res = requests.get(accounts_url)
        accounts_data = accounts_res.json()
        
        if "error" in accounts_data or not accounts_data.get('data'):
            return Response({"error": "Could not find connected Facebook Pages", "details": accounts_data}, status=400)
            
        # Find the first page that has an Instagram Business Account attached
        ig_account = None
        page_access_token = long_lived_token
        fb_page_id = None
        fb_page_name = None
        
        for page in accounts_data['data']:
            if 'instagram_business_account' in page:
                ig_account = page['instagram_business_account']
                page_access_token = page.get('access_token', long_lived_token)
                fb_page_id = page['id']
                fb_page_name = page.get('name')
                break
                
        if not ig_account:
            return Response({"error": "No linked Instagram Business Account found on your Facebook Pages. Please link your Instagram account to your Facebook Page first."}, status=400)

        client = safe_get_client(request.user)
        if not client:
            return Response({"error": "No client workspace associated with this user account."}, status=400)
        
        # Save Instagram config
        client.instagram_config = {
            "access_token": page_access_token,
            "instagram_business_id": ig_account['id'],
            "page_id": fb_page_id,
            "page_name": ig_account.get('username', ig_account.get('name', 'Instagram Account')),
            "last_connected": datetime.datetime.utcnow().isoformat(),
            "last_updated": datetime.datetime.utcnow().isoformat(),
        }
        client.instagram_enabled = True
        
        # Save Facebook config since we have it
        client.facebook_config = {
            "access_token": page_access_token,
            "page_id": fb_page_id,
            "page_name": fb_page_name,
            "last_connected": datetime.datetime.utcnow().isoformat(),
            "last_updated": datetime.datetime.utcnow().isoformat(),
        }
        client.facebook_enabled = True
        
        client.save()
        
        return Response({
            "message": "Instagram connected successfully via Facebook",
            "instagram_config": client.instagram_config,
            "facebook_config": client.facebook_config
        })

class FacebookEmbeddedSignupView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        # 0. Check admin channel access
        is_allowed, reason, status_code = validate_channel_access(request.user, 'facebook')
        if not is_allowed:
            return Response({"error": reason or "You do not have access to this channel."}, status=status_code)

        code = request.data.get('code')
        access_token = request.data.get('access_token')

        import os
        import requests
        
        client_id = os.getenv('FACEBOOK_APP_ID')
        client_secret = os.getenv('FACEBOOK_APP_SECRET')
        
        if not client_id or not client_secret:
            return Response({"error": "Facebook App credentials not configured on server."}, status=500)

        long_lived_token = None

        if code:
            token_url = "https://graph.facebook.com/v20.0/oauth/access_token"
            redirect_uri = request.data.get('redirect_uri') or "https://uwoconnect.aisa24.com/client/channels?state=facebook"
            token_payload = {
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code": code
            }
            token_res = requests.get(token_url, params=token_payload)
            token_data = token_res.json()
            if "error" in token_data:
                return Response({"error": "Failed to exchange code", "details": token_data}, status=400)
            long_lived_token = token_data.get('access_token')
        elif access_token:
            ll_res = requests.get(
                "https://graph.facebook.com/v20.0/oauth/access_token",
                params={
                    "grant_type":        "fb_exchange_token",
                    "client_id":         client_id,
                    "client_secret":     client_secret,
                    "fb_exchange_token": access_token,
                }
            )
            ll_data = ll_res.json()
            long_lived_token = ll_data.get("access_token", access_token)
        else:
            return Response({"error": "No code or access_token provided"}, status=400)
            
        accounts_url = f"https://graph.facebook.com/v20.0/me/accounts?fields=id,name,access_token,category&access_token={long_lived_token}"
        accounts_res = requests.get(accounts_url)
        accounts_data = accounts_res.json()
        
        if "error" in accounts_data or not accounts_data.get('data'):
            return Response({"error": "Could not find connected Facebook Pages", "details": accounts_data}, status=400)
            
        page = accounts_data['data'][0]
        fb_page_id = page['id']
        fb_page_name = page.get('name', 'Facebook Page')
        page_access_token = page.get('access_token', long_lived_token)
        
        import datetime
        client = safe_get_client(request.user)
        if not client:
            return Response({"error": "No client workspace associated with this user account."}, status=400)
            
        client.facebook_config = {
            "access_token": page_access_token,
            "page_id": fb_page_id,
            "page_name": fb_page_name,
            "last_connected": datetime.datetime.utcnow().isoformat(),
            "last_updated": datetime.datetime.utcnow().isoformat(),
        }
        client.facebook_enabled = True
        client.save()
        
        return Response({
            "message": "Facebook Page connected successfully",
            "facebook_config": client.facebook_config
        })

class InstagramOAuthCallbackView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        import datetime
        import requests
        import os
        code         = request.data.get('code')
        redirect_uri = request.data.get('redirect_uri')

        if not code:
            return Response({"error": "No code provided"}, status=400)
        if not redirect_uri:
            return Response({"error": "No redirect_uri provided"}, status=400)

        app_id     = os.getenv('INSTAGRAM_APP_ID') or os.getenv('FACEBOOK_APP_ID')
        app_secret = os.getenv('INSTAGRAM_APP_SECRET') or os.getenv('FACEBOOK_APP_SECRET')

        if not app_id or not app_secret:
            return Response({"error": "Instagram App credentials not configured on server."}, status=500)

        token_res = requests.post(
            "https://api.instagram.com/oauth/access_token",
            data={
                "client_id":     app_id,
                "client_secret": app_secret,
                "grant_type":    "authorization_code",
                "redirect_uri":  redirect_uri,
                "code":          code,
            }
        )
        token_data = token_res.json()

        if "error_type" in token_data or "error" in token_data:
            return Response({"error": "Failed to exchange Instagram code", "details": token_data}, status=400)

        short_lived_token = token_data.get("access_token")
        instagram_user_id = token_data.get("user_id")

        if not short_lived_token:
            return Response({"error": "No access_token in Instagram response", "details": token_data}, status=400)

        ll_res = requests.get(
            "https://graph.instagram.com/access_token",
            params={
                "grant_type":    "ig_exchange_token",
                "client_secret": app_secret,
                "access_token":  short_lived_token,
            }
        )
        ll_data = ll_res.json()
        long_lived_token = ll_data.get("access_token", short_lived_token)

        ig_res = requests.get(
            f"https://graph.instagram.com/v20.0/{instagram_user_id}",
            params={
                "fields":       "id,name,username,profile_picture_url,biography,website,followers_count",
                "access_token": long_lived_token,
            }
        )
        ig_data = ig_res.json()
        ig_username = ig_data.get("username", "")
        ig_name     = ig_data.get("name", ig_username)

        # Auto-resolve real Instagram Business Account ID from conversations paging
        real_biz_id = str(instagram_user_id)
        try:
            c_test = requests.get(
                f"https://graph.instagram.com/v20.0/{instagram_user_id}/conversations",
                params={"limit": 1, "access_token": long_lived_token},
                timeout=5
            )
            if c_test.status_code == 200:
                next_url = c_test.json().get('paging', {}).get('next', '')
                import re
                m_biz = re.search(r'graph\.instagram\.com/v[^/]+/(\d+)/conversations', next_url)
                if m_biz:
                    real_biz_id = m_biz.group(1)
        except Exception as _e_biz:
            logger.warning("Could not auto-resolve real IG business ID: %s", _e_biz)

        client = safe_get_client(request.user)
        if client:
            client.instagram_config = {
                "instagram_business_id":  real_biz_id,
                "instagram_user_id":      str(instagram_user_id),
                "instagram_business_ids": list(set([real_biz_id, str(instagram_user_id)])),
                "page_name":              ig_username or ig_name,
                "username":               ig_username,
                "access_token":           long_lived_token,
                "last_connected":         datetime.datetime.utcnow().isoformat(),
                "last_updated":           datetime.datetime.utcnow().isoformat(),
            }
            client.instagram_enabled = True
            client.save()

            return Response({
                "message": "Instagram Business Account connected successfully",
                "instagram_config": client.instagram_config,
            })
        return Response({"error": "No active client workspace found for user."}, status=404)


class InstagramSyncMessagesView(APIView):
    """
    On-demand synchronization of Instagram direct messages from Meta Graph API.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = safe_get_client(request.user)
        if not client:
            return Response({"error": "No workspace found."}, status=404)

        cfg = client.instagram_config or {}
        token = cfg.get('access_token')
        biz_id = cfg.get('instagram_business_id') or '17841478503676945'
        scoped_id = cfg.get('instagram_user_id') or '28172606925699321'

        if not token:
            return Response({"error": "Instagram is not connected for this workspace."}, status=400)

        try:
            from ..models import Contact, Conversation, Message
            import requests
            from datetime import datetime

            def parse_dt(dt_str):
                if not dt_str:
                    return timezone.now()
                try:
                    return datetime.fromisoformat(dt_str.replace('+0000', '+00:00'))
                except Exception:
                    return timezone.now()

            conv_url = f"https://graph.instagram.com/v20.0/{biz_id}/conversations"
            res = requests.get(conv_url, params={"fields": "id,updated_time,participants", "limit": 20, "access_token": token}, timeout=10)
            if res.status_code != 200:
                return Response({"error": f"Graph API returned {res.status_code}", "details": res.text}, status=400)

            conv_data = res.json().get('data', [])
            synced_convs = 0
            synced_msgs = 0

            for conv_item in conv_data:
                conv_id = conv_item.get('id')
                updated_dt = parse_dt(conv_item.get('updated_time'))
                participants = conv_item.get('participants', {}).get('data', [])

                other_p = None
                for p in participants:
                    if str(p.get('id')) not in [str(biz_id), str(scoped_id)] and p.get('username') != cfg.get('username'):
                        other_p = p
                        break
                if not other_p and participants:
                    other_p = participants[0]
                if not other_p:
                    continue

                customer_ig_id = str(other_p.get('id'))
                customer_username = other_p.get('username') or f"ig_{customer_ig_id}"
                cname = f"@{customer_username}" if not customer_username.startswith('@') else customer_username

                contact, _ = Contact.objects.get_or_create(
                    client=client,
                    platform_id=customer_ig_id,
                    defaults={'phone_number': customer_ig_id, 'name': cname, 'stage': 'NEW'}
                )
                if contact.name != cname and not contact.name.startswith('@'):
                    contact.name = cname
                    contact.save()

                m_res = requests.get(
                    f"https://graph.instagram.com/v20.0/{conv_id}/messages",
                    params={"fields": "id,message,created_time,from,to,attachments", "limit": 25, "access_token": token},
                    timeout=10
                )
                messages_list = m_res.json().get('data', []) if m_res.status_code == 200 else []
                last_body = "Incoming Instagram Message"

                for m in reversed(messages_list):
                    m_id = m.get('id')
                    m_body = m.get('message', '') or ''
                    m_dt = parse_dt(m.get('created_time'))
                    sender_id = str(m.get('from', {}).get('id', ''))
                    is_incoming = (sender_id == customer_ig_id)
                    from_addr = customer_ig_id if is_incoming else biz_id
                    to_addr = biz_id if is_incoming else customer_ig_id

                    if not m_body:
                        m_body = "📷 [Photo / Video / Reel]" if m.get('attachments') else "📎 [Instagram Media / Share]"
                    last_body = m_body

                    if not Message.objects.filter(client=client, meta_message_id=m_id).exists():
                        new_msg = Message.objects.create(
                            client=client,
                            channel='INSTAGRAM',
                            from_address=from_addr,
                            to_address=to_addr,
                            body=m_body,
                            message_type='INCOMING' if is_incoming else 'OUTGOING',
                            status='RECEIVED' if is_incoming else 'DELIVERED',
                            meta_message_id=m_id,
                            metadata=m
                        )
                        Message.objects.filter(id=new_msg.id).update(created_at=m_dt)
                        synced_msgs += 1

                convo = Conversation.objects.filter(client=client, contact_platform_id=customer_ig_id).first()
                if not convo:
                    convo = Conversation.objects.create(
                        client=client,
                        contact=contact,
                        contact_platform_id=customer_ig_id,
                        channel='INSTAGRAM',
                        last_message_summary=last_body,
                        last_message_at=updated_dt
                    )
                else:
                    convo.channel = 'INSTAGRAM'
                    convo.contact = contact
                    convo.last_message_summary = last_body
                    convo.last_message_at = updated_dt
                    convo.save()
                Conversation.objects.filter(id=convo.id).update(last_message_at=updated_dt, updated_at=updated_dt)
                synced_convs += 1

            return Response({
                "success": True,
                "synced_conversations": synced_convs,
                "synced_messages": synced_msgs
            })
        except Exception as e:
            return Response({"error": str(e)}, status=500)


# ============================================================================
# QR CODE BASED WEB <-> MOBILE AUTHENTICATION / DEVICE LINKING VIEWS
# ============================================================================
import secrets
import datetime
import hashlib
from django.utils import timezone
from rest_framework_simplejwt.tokens import RefreshToken
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer


def parse_user_agent(ua_string):
    """Extract human-readable Browser, OS, and Device Name from User-Agent."""
    if not ua_string:
        return "Unknown Browser", "Unknown OS", "Desktop Device"

    ua = ua_string.lower()

    # Determine Browser
    if "edg" in ua:
        browser = "Microsoft Edge"
    elif "chrome" in ua and "safari" in ua and "edg" not in ua and "opr" not in ua:
        browser = "Google Chrome"
    elif "safari" in ua and "chrome" not in ua:
        browser = "Apple Safari"
    elif "firefox" in ua:
        browser = "Mozilla Firefox"
    elif "opr" in ua or "opera" in ua:
        browser = "Opera"
    elif "brave" in ua:
        browser = "Brave"
    else:
        browser = "Web Browser"

    # Determine OS
    if "windows" in ua or "win32" in ua or "win64" in ua:
        os_name = "Windows"
    elif "macintosh" in ua or "mac os x" in ua:
        os_name = "macOS"
    elif "linux" in ua and "android" not in ua:
        os_name = "Linux"
    elif "android" in ua:
        os_name = "Android"
    elif "iphone" in ua or "ipad" in ua or "ipod" in ua:
        os_name = "iOS"
    else:
        os_name = "Desktop"

    device_name = f"{browser} on {os_name}"
    return browser, os_name, device_name


def broadcast_qr_status(session_id, data):
    """Broadcast state updates to Desktop WebSocket group immediately."""
    try:
        channel_layer = get_channel_layer()
        if channel_layer:
            async_to_sync(channel_layer.group_send)(
                f"qr_auth_{session_id}",
                {
                    "type": "qr_status_update",
                    "data": data,
                }
            )
    except Exception:
        pass


class QrAuthCreateView(views.APIView):
    """
    Desktop web browser requests a short-lived (120s) single-use QR auth session.
    No login required.
    Returns session_id, expires_at, and qr_url / qr_payload.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        session_id = secrets.token_hex(32)
        now = timezone.now()
        expires_at = now + datetime.timedelta(seconds=120)

        # Generate a unique 4-char alphanumeric short code
        import string, random
        chars = string.ascii_uppercase + string.digits
        for _ in range(10):
            short_code = ''.join(random.choices(chars, k=4))
            if not QrAuthSession.objects.filter(short_code=short_code, status='WAITING').exists():
                break

        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        ip_address = x_forwarded.split(',')[0].strip() if x_forwarded else request.META.get('REMOTE_ADDR')
        user_agent = request.META.get('HTTP_USER_AGENT', '')

        browser, os_name, device_name = parse_user_agent(user_agent)

        qr_session = QrAuthSession.objects.create(
            session_id=session_id,
            short_code=short_code,
            status='WAITING',
            ip_address=ip_address,
            user_agent=user_agent,
            browser=browser,
            operating_system=os_name,
            device_name=device_name,
            expires_at=expires_at,
        )

        qr_url = f"uwoconnect://auth/qr?session_id={session_id}"
        web_fallback_url = f"https://uwoconnect.com/auth/qr?session_id={session_id}"

        return Response({
            "session_id": session_id,
            "short_code": short_code,
            "status": qr_session.status,
            "expires_at": expires_at.isoformat(),
            "expires_in_seconds": 120,
            "qr_payload": session_id,
            "qr_url": qr_url,
            "web_fallback_url": web_fallback_url,
            "device_name": device_name,
            "browser": browser,
            "operating_system": os_name,
        }, status=status.HTTP_201_CREATED)


class QrAuthStatusView(views.APIView):
    """
    Status endpoint for QR session. Used by desktop web for polling or verification.
    When status is APPROVED / AUTHENTICATED, returns the web JWT token and user profile once.
    """
    permission_classes = [AllowAny]

    def get(self, request, session_id):
        try:
            qr_session = QrAuthSession.objects.get(session_id=session_id)
        except QrAuthSession.DoesNotExist:
            return Response({"error": "QR Session not found"}, status=status.HTTP_404_NOT_FOUND)

        if not qr_session.is_valid() and qr_session.status not in ['CONSUMED', 'APPROVED', 'AUTHENTICATED']:
            return Response({
                "session_id": session_id,
                "status": "EXPIRED",
                "expires_in_seconds": 0
            }, status=200)

        now = timezone.now()
        rem_seconds = max(0, int((qr_session.expires_at - now).total_seconds()))

        resp_data = {
            "session_id": session_id,
            "status": qr_session.status,
            "expires_in_seconds": rem_seconds,
            "scanned_at": qr_session.scanned_at.isoformat() if qr_session.scanned_at else None,
            "approved_at": qr_session.approved_at.isoformat() if qr_session.approved_at else None,
            "device_name": qr_session.device_name,
            "browser": qr_session.browser,
            "operating_system": qr_session.operating_system,
        }

        # If approved, return token and user profile
        if qr_session.status in ['APPROVED', 'AUTHENTICATED']:
            resp_data["token"] = qr_session.auth_token
            resp_data["refresh_token"] = qr_session.refresh_token
            resp_data["user"] = qr_session.user_data

        return Response(resp_data, status=200)


def find_qr_session(code):
    if not code:
        return None
    code = str(code).strip()
    if 'session_id=' in code:
        import re
        m = re.search(r'session_id=([a-zA-Z0-9_-]+)', code)
        if m:
            code = m.group(1)
    
    # 1. Match exact session_id
    qs = QrAuthSession.objects.filter(session_id=code).first()
    if qs:
        return qs
    # 2. Match short_code (case-insensitive)
    qs = QrAuthSession.objects.filter(short_code__iexact=code).first()
    if qs:
        return qs
    return None


class QrAuthScanView(views.APIView):
    """
    Authenticated mobile app user scans the QR code or submits short code.
    Transitions session from WAITING to SCANNED, saves mobile user reference,
    and returns desktop browser/device metadata to the mobile app for user approval prompt.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_code = request.data.get('session_id', '') or request.data.get('code', '') or request.data.get('short_code', '')
        qr_session = find_qr_session(raw_code)
        if not qr_session:
            return Response({"error": "Invalid or non-existent QR session code. Please check the code and try again."}, status=404)

        if qr_session.status in ['CONSUMED', 'APPROVED', 'AUTHENTICATED']:
            return Response({"error": "This QR code has already been approved"}, status=400)

        if not qr_session.is_valid():
            return Response({"error": "This QR code has expired. Please refresh on desktop."}, status=400)

        session_id = qr_session.session_id

        # Associate scanning mobile user and advance status
        qr_session.user = request.user
        qr_session.client = getattr(request.user, 'client', None)
        qr_session.status = 'SCANNED'
        qr_session.scanned_at = timezone.now()
        qr_session.save(update_fields=['user', 'client', 'status', 'scanned_at'])

        # Notify desktop via WebSocket that phone scanned the QR
        broadcast_qr_status(session_id, {
            "type": "qr_status_update",
            "session_id": session_id,
            "status": "SCANNED",
            "user_name": getattr(request.user, 'name', '') or request.user.username,
        })

        return Response({
            "session_id": session_id,
            "status": "SCANNED",
            "device_name": qr_session.device_name or f"{qr_session.browser} on {qr_session.operating_system}",
            "browser": qr_session.browser or "Web Browser",
            "operating_system": qr_session.operating_system or "Desktop",
            "ip_address": qr_session.ip_address or "Unknown",
            "scanned_at": qr_session.scanned_at.isoformat(),
        }, status=200)


class QrAuthApproveView(views.APIView):
    """
    Authenticated mobile app user taps 'Link Device' to approve login.
    Generates new JWT tokens for the desktop web session, registers a LinkedDevice record,
    and broadcasts instant approval to the web client.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_code = request.data.get('session_id', '') or request.data.get('code', '') or request.data.get('short_code', '')
        qr_session = find_qr_session(raw_code)
        if not qr_session:
            return Response({"error": "Invalid or non-existent QR code"}, status=404)

        if qr_session.status in ['CONSUMED', 'APPROVED', 'AUTHENTICATED']:
            return Response({"error": "This QR code has already been approved"}, status=400)

        if not qr_session.is_valid():
            return Response({"error": "This QR code has expired. Please refresh on desktop."}, status=400)

        session_id = qr_session.session_id
        from ..services.auth_service import AuthService
        user = request.user
        client = getattr(user, 'client', None)

        # Generate fresh JWT token pair for the linked web session
        refresh = RefreshToken.for_user(user)
        access_token = str(refresh.access_token)
        token_hash = hashlib.sha256(access_token.encode()).hexdigest()

        # Create or update LinkedDevice record
        device_name = qr_session.device_name or f"{qr_session.browser} on {qr_session.operating_system}"
        linked_device = LinkedDevice.objects.create(
            user=user,
            client=client,
            device_name=device_name,
            browser=qr_session.browser or "Web Browser",
            operating_system=qr_session.operating_system or "Desktop",
            ip_address=qr_session.ip_address,
            user_agent=qr_session.user_agent or "",
            session_id=session_id,
            token_hash=token_hash,
            is_active=True,
        )

        serialized_user = AuthService._serialize_user(user)

        qr_session.user = user
        qr_session.client = client
        qr_session.status = 'APPROVED'
        qr_session.approved_at = timezone.now()
        qr_session.auth_token = access_token
        qr_session.refresh_token = str(refresh)
        qr_session.user_data = serialized_user
        qr_session.save(update_fields=['user', 'client', 'status', 'approved_at', 'auth_token', 'refresh_token', 'user_data'])

        # Create audit log
        try:
            AuditLog.objects.create(
                admin_name=user.username,
                client_name=client.business_name if client else "Platform",
                module="Authentication",
                action="QR_DEVICE_LINKED",
                before_value=f"Session: {session_id[:8]}...",
                after_value=f"Linked web session: {device_name} (IP: {qr_session.ip_address})",
                ip_address=request.META.get('REMOTE_ADDR')
            )
        except Exception:
            pass

        # Broadcast approval immediately to Desktop WebSocket
        broadcast_qr_status(session_id, {
            "type": "qr_status_update",
            "session_id": session_id,
            "status": "APPROVED",
            "token": access_token,
            "refresh_token": str(refresh),
            "user": serialized_user,
        })

        return Response({
            "message": "Device linked successfully",
            "device_id": str(linked_device.id),
            "device_name": device_name,
        }, status=200)


class QrAuthRejectView(views.APIView):
    """
    Authenticated mobile app user taps 'Cancel' to reject linking.
    Sets status to CANCELLED and broadcasts rejection to the web client.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        raw_code = request.data.get('session_id', '') or request.data.get('code', '') or request.data.get('short_code', '')
        qr_session = find_qr_session(raw_code)
        if not qr_session:
            return Response({"error": "Invalid or non-existent QR code"}, status=404)

        session_id = qr_session.session_id
        qr_session.status = 'CANCELLED'
        qr_session.rejected_at = timezone.now()
        qr_session.save(update_fields=['status', 'rejected_at'])

        broadcast_qr_status(session_id, {
            "type": "qr_status_update",
            "session_id": session_id,
            "status": "CANCELLED",
        })

        return Response({"message": "Device linking cancelled"}, status=200)


class LinkedDeviceListView(views.APIView):
    """
    Lists all active linked web/desktop devices for the authenticated user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        devices = LinkedDevice.objects.filter(user=request.user, is_active=True).order_by('-linked_at')
        data = []
        for d in devices:
            data.append({
                "id": str(d.id),
                "device_name": d.device_name,
                "browser": d.browser,
                "operating_system": d.operating_system,
                "ip_address": d.ip_address,
                "linked_at": d.linked_at.isoformat() if d.linked_at else None,
                "last_active_at": d.last_active_at.isoformat() if d.last_active_at else None,
                "is_active": d.is_active,
            })
        return Response(data, status=200)


class LinkedDeviceRevokeView(views.APIView):
    """
    Revokes a specific linked device.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            device = LinkedDevice.objects.get(id=pk, user=request.user, is_active=True)
        except LinkedDevice.DoesNotExist:
            return Response({"error": "Device not found or already logged out"}, status=404)

        device.is_active = False
        device.revoked_at = timezone.now()
        device.save(update_fields=['is_active', 'revoked_at'])

        # Notify any active WebSocket session for this device
        if device.session_id:
            broadcast_qr_status(device.session_id, {
                "type": "qr_status_update",
                "session_id": device.session_id,
                "status": "REVOKED",
            })

        return Response({"message": f"{device.device_name} has been logged out successfully"}, status=200)


class LinkedDeviceRevokeAllView(views.APIView):
    """
    Revokes ALL active linked devices for the user.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        active_devices = LinkedDevice.objects.filter(user=request.user, is_active=True)
        count = active_devices.count()
        now = timezone.now()

        for d in active_devices:
            if d.session_id:
                broadcast_qr_status(d.session_id, {
                    "type": "qr_status_update",
                    "session_id": d.session_id,
                    "status": "REVOKED",
                })

        active_devices.update(is_active=False, revoked_at=now)

        return Response({"message": f"All {count} linked devices logged out successfully"}, status=200)


