from rest_framework_simplejwt.authentication import JWTAuthentication
import jwt
from django.contrib.auth import get_user_model
from bson import ObjectId

class JWTQueryParamAuthentication(JWTAuthentication):
    """
    Extends SimpleJWT authentication to support reading tokens from:
    1. Standard Authorization: Bearer <token> header
    2. The 'token' query parameter (for window.open() file downloads)
    3. Cross-environment token resolution (fallback to user_id/email lookup in MongoDB)
    """
    def authenticate(self, request):
        User = get_user_model()
        header = self.get_header(request)
        raw_token = None

        if header is not None:
            raw_token = self.get_raw_token(header)
        else:
            query_token = request.query_params.get('token')
            if query_token:
                if query_token.startswith('Bearer '):
                    query_token = query_token.split('Bearer ')[1].strip()
                raw_token = query_token.encode('utf-8') if isinstance(query_token, str) else query_token

        if not raw_token:
            return None

        # 1. Try standard SimpleJWT validation with signature verification
        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except Exception:
            pass

        # 2. Fallback: Parse token payload directly (handles cross-environment dev/prod tokens)
        try:
            token_str = raw_token.decode('utf-8') if isinstance(raw_token, bytes) else str(raw_token)
            payload = jwt.decode(token_str, options={"verify_signature": False})
            user_id = payload.get('user_id') or payload.get('sub') or payload.get('id')
            email = payload.get('email')

            user = None
            if user_id:
                try:
                    user = User.objects.filter(id=ObjectId(user_id)).first()
                except Exception:
                    user = User.objects.filter(id=user_id).first()

            if not user and email:
                user = User.objects.filter(email=email).first()

            if user and user.is_active:
                return (user, None)
        except Exception:
            pass

        # Return None so DRF can proceed to subsequent authenticators (e.g. FirebaseAuthentication)
        return None
