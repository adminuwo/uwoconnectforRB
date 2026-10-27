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

        # Standard SimpleJWT validation WITH signature verification.
        # SECURITY: Never fall back to decoding tokens without verifying the signature —
        # that allowed anyone to forge a token for any user (including admins).
        try:
            validated_token = self.get_validated_token(raw_token)
            return self.get_user(validated_token), validated_token
        except Exception:
            pass

        # Return None so DRF can proceed to subsequent authenticators (e.g. FirebaseAuthentication)
        return None
