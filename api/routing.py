from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/inbox/$', consumers.InboxConsumer.as_asgi()),
    re_path(r'ws/team-chat/$', consumers.TeamChatConsumer.as_asgi()),
    re_path(r'ws/webrtc/$', consumers.WebRTCConsumer.as_asgi()),
    re_path(r'ws/auth/qr/(?P<session_id>[^/]+)/$', consumers.QrAuthConsumer.as_asgi()),
]
