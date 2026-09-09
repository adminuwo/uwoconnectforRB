import re
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from api.models import UserPreference

HEX_COLOR_REGEX = re.compile(r'^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3}|[A-Fa-f0-9]{8})$')

def serialize_preference(pref: UserPreference) -> dict:
    return {
        "id": str(pref.id),
        "theme_mode": pref.theme_mode,
        "primary_color": pref.primary_color,
        "accent_color": pref.accent_color,
        "language": pref.language,
        "updated_at": pref.updated_at.isoformat() if pref.updated_at else None,
    }

class UserPreferenceView(APIView):
    """
    GET /api/user/preferences/ - Get current user preferences
    PATCH /api/user/preferences/ - Update current user preferences
    PUT /api/user/preferences/ - Update current user preferences
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        pref, _ = UserPreference.objects.get_or_create(
            user=request.user,
            defaults={
                'theme_mode': UserPreference.THEME_LIGHT,
                'primary_color': '#059669',
                'accent_color': '#0d9488',
                'language': 'en',
            }
        )
        return Response(serialize_preference(pref), status=status.HTTP_200_OK)

    def put(self, request):
        return self.patch(request)

    def patch(self, request):
        pref, _ = UserPreference.objects.get_or_create(
            user=request.user,
            defaults={
                'theme_mode': UserPreference.THEME_LIGHT,
                'primary_color': '#059669',
                'accent_color': '#0d9488',
                'language': 'en',
            }
        )

        data = request.data
        errors = {}

        if 'theme_mode' in data:
            mode = str(data['theme_mode']).strip().lower()
            if mode not in [UserPreference.THEME_LIGHT, UserPreference.THEME_DARK, UserPreference.THEME_CUSTOM]:
                errors['theme_mode'] = f"Invalid theme_mode '{mode}'. Allowed: light, dark, custom."
            else:
                pref.theme_mode = mode

        if 'primary_color' in data:
            color = str(data['primary_color']).strip()
            if not HEX_COLOR_REGEX.match(color):
                errors['primary_color'] = f"Invalid primary_color '{color}'. Must be a valid hex color like #059669."
            else:
                pref.primary_color = color

        if 'accent_color' in data:
            color = str(data['accent_color']).strip()
            if not HEX_COLOR_REGEX.match(color):
                errors['accent_color'] = f"Invalid accent_color '{color}'. Must be a valid hex color like #0d9488."
            else:
                pref.accent_color = color

        if 'language' in data:
            lang = str(data['language']).strip().lower()
            if not (2 <= len(lang) <= 10 and lang.replace('-', '_').isalnum()):
                errors['language'] = f"Invalid language code '{lang}'."
            else:
                pref.language = lang

        if errors:
            return Response({'errors': errors, 'message': 'Validation failed.'}, status=status.HTTP_400_BAD_REQUEST)

        pref.save()
        return Response(serialize_preference(pref), status=status.HTTP_200_OK)
