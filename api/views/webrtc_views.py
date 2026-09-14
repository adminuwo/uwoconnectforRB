
import uuid
import time
from datetime import timedelta
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from ..models import User, Client, CallHistory, ActiveCallSession


def cleanup_stale_sessions():
    """Remove call sessions older than 5 minutes that are still RINGING."""
    cutoff = timezone.now() - timedelta(minutes=5)
    ActiveCallSession.objects.filter(
        status='RINGING', created_at__lt=cutoff
    ).delete()
    # Also clean up CONNECTED sessions older than 2 hours
    cutoff2 = timezone.now() - timedelta(hours=2)
    ActiveCallSession.objects.filter(
        status='CONNECTED', created_at__lt=cutoff2
    ).delete()

class WebRTCIceConfigView(APIView):
    """
    Returns STUN/TURN server configuration for voice & video call sessions.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        ice_servers = [
            {"urls": "stun:stun.l.google.com:19302"},
            {"urls": "stun:stun1.l.google.com:19302"},
            {"urls": "stun:stun2.l.google.com:19302"},
            {"urls": "stun:stun3.l.google.com:19302"},
            {"urls": "stun:stun4.l.google.com:19302"}
        ]
        return Response({
            "status": "success",
            "ice_servers": ice_servers,
            "session_id": str(uuid.uuid4()),
            "codecs": ["Opus", "VP8", "H264"],
            "max_bitrate_kbps": 2500
        }, status=status.HTTP_200_OK)


class WebRTCInitiateCallView(APIView):
    """
    Initiates a WebRTC call session with workspace isolation & recipient validation.
    Persists session to MongoDB so Cloud Run stateless containers share state.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        cleanup_stale_sessions()
        caller_user = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
        caller_name = request.data.get("caller") or (caller_user.username if caller_user else "Client / Admin")
        target_input = request.data.get("recipient") or request.data.get("recipient_email") or "Team Member"
        target_display = request.data.get("recipient_name") or target_input
        call_type = str(request.data.get("call_type", "voice")).upper()
        is_video = request.data.get("is_video", call_type == "VIDEO")
        sdp_offer = request.data.get("sdp_offer")

        # Receiver & Workspace Security Check
        receiver_user = None
        if target_input:
            receiver_user = User.objects.filter(email__iexact=target_input).first() or \
                            User.objects.filter(username__iexact=target_input).first()

        if caller_user and receiver_user:
            if caller_user.client and receiver_user.client and caller_user.client.id != receiver_user.client.id:
                return Response({
                    "error": "Forbidden: Cross-workspace calling is prohibited. Both users must belong to the same UWOConnect workspace."
                }, status=status.HTTP_403_FORBIDDEN)

            if receiver_user.status in ['SUSPENDED', 'REJECTED']:
                return Response({
                    "error": "Recipient user account is suspended or inactive."
                }, status=status.HTTP_400_BAD_REQUEST)

        # Check if recipient is already in another active call
        existing = ActiveCallSession.objects.filter(
            recipient__iexact=str(target_input),
            status__in=['RINGING', 'CONNECTED']
        ).first()
        if not existing and receiver_user:
            existing = ActiveCallSession.objects.filter(
                receiver_user_id=str(receiver_user.id),
                status__in=['RINGING', 'CONNECTED']
            ).first()
        if existing:
            return Response({
                "error": "Recipient is currently in another call."
            }, status=status.HTTP_400_BAD_REQUEST)

        session_id = f"call_sess_{uuid.uuid4().hex[:12]}"

        caller_user_id_str = str(caller_user.id) if caller_user else None
        client_id_str = str(caller_user.client.id) if caller_user and caller_user.client else None
        receiver_user_id_str = str(receiver_user.id) if receiver_user else None

        ActiveCallSession.objects.create(
            session_id=session_id,
            caller=caller_name,
            caller_user_id=caller_user_id_str,
            client_id=client_id_str,
            recipient=str(target_input).lower(),
            recipient_display=target_display,
            receiver_user_id=receiver_user_id_str,
            call_type=call_type,
            is_video=is_video,
            sdp_offer=sdp_offer,
            sdp_answer=None,
            ice_candidates=[],
            status='RINGING',
        )

        return Response({
            "status": "initiated",
            "session_id": session_id,
            "caller": caller_name,
            "recipient": target_display,
            "call_type": call_type,
            "is_video": is_video,
            "signal_state": "connecting",
            "ice_servers": [{"urls": "stun:stun.l.google.com:19302"}]
        }, status=status.HTTP_200_OK)


class WebRTCActiveCallCheckView(APIView):
    """
    Returns active ringing/connected calls targeted for the authenticated workspace user.
    Reads from MongoDB so works across Cloud Run container instances.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        # Removed cleanup_stale_sessions() here because this endpoint is polled every 1.8s
        # Executing 2 delete queries + 1 select query sequentially with high MongoDB latency
        # causes the request to take 10-19s, blocking all other network requests.
        user_email = ""
        user_name = ""
        user_client_id = None

        if getattr(request, 'user', None) and request.user.is_authenticated:
            user_email = str(getattr(request.user, 'email', '') or '').lower()
            user_name = str(getattr(request.user, 'username', '') or '').lower()
            try:
                if getattr(request.user, 'client_id', None) and request.user.client:
                    user_client_id = str(request.user.client.id)
            except Exception:
                user_client_id = None
            user_id_str = str(request.user.id)
        else:
            return Response({"active_call": False}, status=status.HTTP_200_OK)

        # Find session where this user is recipient or caller
        active_sess = None
        sessions = ActiveCallSession.objects.filter(status__in=['RINGING', 'CONNECTED']).order_by('-created_at')

        for sess in sessions:
            # Workspace isolation
            if user_client_id and sess.client_id and user_client_id != sess.client_id:
                continue

            recip = str(sess.recipient or '').lower()
            is_recipient = (
                recip in ['all', 'team member', '', user_email, user_name] or
                (user_email and (user_email in recip or recip in user_email)) or
                (sess.receiver_user_id and sess.receiver_user_id == user_id_str)
            )
            is_caller = (
                (sess.caller_user_id and sess.caller_user_id == user_id_str) or
                (user_name and sess.caller.lower() == user_name) or
                (user_email and sess.caller.lower() == user_email)
            )

            if is_recipient or is_caller:
                active_sess = sess
                break

        if active_sess:
            is_caller_user = (
                (active_sess.caller_user_id and active_sess.caller_user_id == user_id_str) or
                (user_name and active_sess.caller.lower() == user_name) or
                (user_email and active_sess.caller.lower() == user_email)
            )
            return Response({
                "active_call": True,
                "session_id": active_sess.session_id,
                "caller": active_sess.caller,
                "recipient": active_sess.recipient_display or active_sess.recipient,
                "is_video": active_sess.is_video,
                "call_type": active_sess.call_type,
                "sdp_offer": active_sess.sdp_offer,
                "sdp_answer": active_sess.sdp_answer,
                "status": active_sess.status,
                "is_caller": is_caller_user
            }, status=status.HTTP_200_OK)

        return Response({"active_call": False}, status=status.HTTP_200_OK)


class WebRTCCallActionView(APIView):
    """
    Accepts, declines, ends, or updates call state and records CallHistory.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        session_id = request.data.get("session_id")
        action = request.data.get("action")
        duration_str = request.data.get("duration", "0s")

        try:
            sess = ActiveCallSession.objects.get(session_id=session_id)
        except ActiveCallSession.DoesNotExist:
            return Response({"status": "not_found", "action": action}, status=status.HTTP_200_OK)

        if action in ['decline', 'end', 'missed']:
            final_status = 'REJECTED' if action == 'decline' else ('MISSED' if action == 'missed' else 'COMPLETED')

            try:
                client_obj = None
                if sess.client_id:
                    client_obj = Client.objects.filter(id=sess.client_id).first()
                elif getattr(request.user, 'client', None):
                    client_obj = request.user.client

                CallHistory.objects.create(
                    client=client_obj,
                    caller_name=sess.caller,
                    receiver_name=sess.recipient_display or sess.recipient,
                    call_type=sess.call_type,
                    status=final_status,
                    duration=duration_str if final_status == 'COMPLETED' else "0s",
                    session_id=session_id
                )
            except Exception as e:
                pass

            sess.delete()

        elif action == 'accept':
            sess.status = 'CONNECTED'
            sess.save(update_fields=['status', 'updated_at'])

        return Response({"status": "updated", "action": action}, status=status.HTTP_200_OK)


class WebRTCCallSignalView(APIView):
    """
    Exchanges signaling payloads (SDP Offer/Answer & ICE Candidates).
    Writes directly to MongoDB session record.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        session_id = request.data.get("session_id")
        signal_type = request.data.get("type")
        payload = request.data.get("payload")

        try:
            sess = ActiveCallSession.objects.get(session_id=session_id)
            if signal_type == 'offer':
                sess.sdp_offer = payload
                sess.save(update_fields=['sdp_offer', 'updated_at'])
            elif signal_type == 'answer':
                sess.sdp_answer = payload
                sess.status = 'CONNECTED'
                sess.save(update_fields=['sdp_answer', 'status', 'updated_at'])
            elif signal_type == 'candidate':
                candidates = sess.ice_candidates or []
                candidates.append(payload)
                sess.ice_candidates = candidates
                sess.save(update_fields=['ice_candidates', 'updated_at'])
        except ActiveCallSession.DoesNotExist:
            pass

        return Response({
            "status": "signal_processed",
            "session_id": session_id,
            "type": signal_type,
            "ack": True
        }, status=status.HTTP_200_OK)


class WebRTCHistoryView(APIView):
    """
    Retrieves real call history logs from database for current workspace.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        user = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None

        if user and user.client:
            records = CallHistory.objects.filter(client=user.client)[:30]
        else:
            records = CallHistory.objects.all()[:30]

        history_list = []
        for r in records:
            history_list.append({
                "id": str(r.id),
                "caller": r.caller_name,
                "receiver": r.receiver_name,
                "name": r.receiver_name,
                "dept": r.receiver_dept or 'Team',
                "callType": r.call_type.lower(),
                "type": "outgoing" if (user and r.caller_name == user.username) else "incoming",
                "date": r.created_at.strftime("%b %d, %I:%M %p"),
                "duration": r.duration,
                "status": r.status.lower()
            })

        return Response({"history": history_list}, status=status.HTTP_200_OK)


class CallScheduleView(APIView):
    """Schedule a future call between a client and team member."""
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({"status": "scheduled", "message": "Call scheduling coming soon."}, status=status.HTTP_200_OK)

    def get(self, request):
        return Response({"scheduled_calls": []}, status=status.HTTP_200_OK)


class CallAISummaryView(APIView):
    """Return an AI-generated summary for a completed call session."""
    permission_classes = [AllowAny]

    def post(self, request):
        return Response({"summary": "AI summary not yet available for this session."}, status=status.HTTP_200_OK)

    def get(self, request):
        return Response({"summary": None}, status=status.HTTP_200_OK)


class CallAnalyticsView(APIView):
    """Return call analytics data for the authenticated workspace."""
    permission_classes = [AllowAny]

    def get(self, request):
        user = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
        if user and user.client:
            total = CallHistory.objects.filter(client=user.client).count()
            completed = CallHistory.objects.filter(client=user.client, status='COMPLETED').count()
            missed = CallHistory.objects.filter(client=user.client, status='MISSED').count()
        else:
            total = CallHistory.objects.count()
            completed = CallHistory.objects.filter(status='COMPLETED').count()
            missed = CallHistory.objects.filter(status='MISSED').count()

        return Response({
            "total_calls": total,
            "completed_calls": completed,
            "missed_calls": missed,
            "answer_rate": round((completed / total * 100), 1) if total > 0 else 0,
        }, status=status.HTTP_200_OK)

