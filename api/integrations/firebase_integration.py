import firebase_admin
from firebase_admin import auth
import os
import logging

logger = logging.getLogger(__name__)

class FirebaseIntegration:
    @staticmethod
    def verify_id_token(token):
        try:
            return auth.verify_id_token(token)
        except Exception as fb_err:
            try:
                from google.oauth2 import id_token as google_id_token
                from google.auth.transport import requests as google_requests
                project_id = os.getenv('FIREBASE_PROJECT_ID', 'uwoconnect')
                return google_id_token.verify_firebase_token(
                    token,
                    google_requests.Request(),
                    audience=project_id
                )
            except Exception as google_err:
                logger.error(f"[Firebase Auth] Verification failed: fb_err={fb_err}, google_err={google_err}")
                raise fb_err
