import os
import json
import secrets
import logging
from urllib.parse import urlencode

from django.core.cache import cache
from django.http import HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser

from ..serializers import ClientSerializer

logger = logging.getLogger(__name__)

GOOGLE_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_ENDPOINT = "https://www.googleapis.com/oauth2/v2/userinfo"

YOUTUBE_SCOPES = " ".join([
    "https://www.googleapis.com/auth/youtube.readonly",
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
])

def _get_credentials():
    try:
        from dotenv import load_dotenv
        load_dotenv(override=True)
    except Exception:
        pass

    return {
        "client_id": os.environ.get("GMAIL_CLIENT_ID", ""),
        "client_secret": os.environ.get("GMAIL_CLIENT_SECRET", ""),
        "redirect_uri": os.environ.get("YOUTUBE_REDIRECT_URI", "http://localhost:8080/api/auth/youtube/callback"),
    }


class YouTubeConnectView(APIView):
    """Initiate Google OAuth flow for YouTube integration."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        creds = _get_credentials()
        if not creds["client_id"] or not creds["client_secret"]:
            return Response(
                {"error": "Google OAuth credentials not configured on backend (GMAIL_CLIENT_ID / GMAIL_CLIENT_SECRET)."},
                status=500,
            )

        state = secrets.token_urlsafe(32)
        cache.set(f"youtube_state_{state}", client.id, timeout=600)

        auth_url = (
            f"{GOOGLE_AUTH_ENDPOINT}"
            f"?client_id={creds['client_id']}"
            f"&redirect_uri={creds['redirect_uri']}"
            f"&response_type=code"
            f"&scope={YOUTUBE_SCOPES}"
            f"&state={state}"
            f"&access_type=offline"
            f"&prompt=consent"
        )
        return Response({"url": auth_url})


class YouTubeCallbackView(APIView):
    """Handle the OAuth2 callback from Google for YouTube."""
    permission_classes = []  # No auth needed — Google redirects here directly
    authentication_classes = []

    def get(self, request):
        frontend_url = os.environ.get("FRONTEND_URL", "http://localhost:3000")
        code = request.GET.get("code")
        state = request.GET.get("state")
        error = request.GET.get("error")

        if error:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?youtube_error={error}")

        if not code or not state:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?youtube_error=missing_params")

        client_id_from_cache = cache.get(f"youtube_state_{state}")
        # Fallback: look up client via all states in cache (handles server restarts)
        if not client_id_from_cache:
            # Try to find any pending youtube state for authenticated user
            if request.user and request.user.is_authenticated:
                try:
                    client_id_from_cache = request.user.client.id
                except Exception:
                    pass
        if not client_id_from_cache:
            return HttpResponseRedirect(f"{frontend_url}/client/channels?youtube_error=invalid_state")

        creds = _get_credentials()
        import requests as http_requests

        # Exchange code for tokens
        try:
            token_res = http_requests.post(GOOGLE_TOKEN_ENDPOINT, data={
                "code": code,
                "client_id": creds["client_id"],
                "client_secret": creds["client_secret"],
                "redirect_uri": creds["redirect_uri"],
                "grant_type": "authorization_code",
            }, timeout=10)
            token_data = token_res.json()
        except Exception as e:
            logger.error(f"YouTube token exchange failed: {e}")
            return HttpResponseRedirect(f"{frontend_url}/client/channels?youtube_error=token_exchange_failed")

        if "error" in token_data:
            logger.error(f"YouTube token error: {token_data}")
            return HttpResponseRedirect(f"{frontend_url}/client/channels?youtube_error={token_data.get('error', 'unknown')}")

        access_token = token_data.get("access_token")
        refresh_token = token_data.get("refresh_token")

        # Fetch user info
        try:
            user_info_res = http_requests.get(
                GOOGLE_USERINFO_ENDPOINT,
                headers={"Authorization": f"Bearer {access_token}"}
            )
            user_info = user_info_res.json()
        except Exception:
            user_info = {}

        # Fetch channel ID & details
        channel_id = ""
        channel_title = ""
        try:
            ch_res = http_requests.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "id,snippet", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"}
            )
            items = ch_res.json().get("items", [])
            if items:
                channel_id = items[0].get("id", "")
                channel_title = items[0].get("snippet", {}).get("title", "")
        except Exception as e:
            logger.warning(f"Failed to fetch YouTube channel details on callback: {e}")

        # Save to client
        from ..models import Client
        try:
            client_obj = Client.objects.get(id=client_id_from_cache)
            client_obj.youtube_enabled = True
            client_obj.youtube_config = {
                "access_token": access_token,
                "refresh_token": refresh_token,
                "token_uri": GOOGLE_TOKEN_ENDPOINT,
                "account_email": user_info.get("email", ""),
                "email": user_info.get("email", ""),
                "account_name": user_info.get("name", ""),
                "channel_id": channel_id,
                "channel_title": channel_title or user_info.get("name", "YouTube Channel"),
                "connected_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
            }
            client_obj.save()
            cache.delete(f"youtube_state_{state}")
            return HttpResponseRedirect(f"{frontend_url}/client/channels?youtube_connected=true")
        except Client.DoesNotExist:
            return HttpResponseRedirect("/client/channels?youtube_error=client_not_found")


class YouTubeStatusView(APIView):
    """Return YouTube connection status."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client:
            return Response({"error": "No client attached"}, status=404)
        return Response({
            "enabled": client.youtube_enabled,
            "config": client.youtube_config,
        })


@method_decorator(csrf_exempt, name="dispatch")
class YouTubeSyncView(APIView):
    """Trigger YouTube data sync (placeholder)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)
        return Response({"detail": "Sync triggered (implementation pending)"})


def _get_youtube_access_token(client_obj):
    """Get a valid YouTube access token, refresh if needed."""
    import requests as http_requests
    config = client_obj.youtube_config or {}
    access_token = config.get("access_token")
    refresh_token = config.get("refresh_token")

    if not access_token:
        return None

    # Try to refresh using refresh_token
    if refresh_token:
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)
            res = http_requests.post("https://oauth2.googleapis.com/token", data={
                "client_id": os.environ.get("GMAIL_CLIENT_ID", ""),
                "client_secret": os.environ.get("GMAIL_CLIENT_SECRET", ""),
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }, timeout=10)
            data = res.json()
            if "access_token" in data:
                client_obj.youtube_config = {**config, "access_token": data["access_token"]}
                client_obj.save()
                return data["access_token"]
        except Exception as e:
            logger.warning(f"YouTube token refresh failed: {e}")

    return access_token


def _build_google_credentials(client_obj):
    from google.oauth2.credentials import Credentials
    config = client_obj.youtube_config or {}
    g_creds = _get_credentials()
    access_token = _get_youtube_access_token(client_obj)
    
    return Credentials(
        token=access_token,
        refresh_token=config.get("refresh_token"),
        token_uri=config.get("token_uri", GOOGLE_TOKEN_ENDPOINT),
        client_id=g_creds.get("client_id"),
        client_secret=g_creds.get("client_secret")
    )


class YouTubeAnalyticsView(APIView):
    """Fetch YouTube channel analytics (subscribers, views, video count, last video)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import requests as http_requests
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)

        cache_key = f"yt_analytics_{client.id}"
        cached_data = cache.get(cache_key)
        if cached_data:
            return Response(cached_data)

        access_token = _get_youtube_access_token(client)
        if not access_token:
            return Response({"error": "No valid access token"}, status=400)

        headers = {"Authorization": f"Bearer {access_token}"}

        # Channel stats
        try:
            ch_res = http_requests.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "snippet,statistics,contentDetails", "mine": "true"},
                headers=headers
            )
            ch_data = ch_res.json()
            channel = ch_data.get("items", [{}])[0]
            stats = channel.get("statistics", {})
            snippet = channel.get("snippet", {})
            uploads_id = channel.get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
        except Exception as e:
            logger.error(f"YouTube channel stats error: {e}")
            return Response({"error": str(e)}, status=500)

        # Fetch uploaded videos list to accurately calculate real video count
        latest_video = None
        actual_video_count = int(stats.get("videoCount", 0))
        try:
            if uploads_id:
                pl_res = http_requests.get(
                    "https://www.googleapis.com/youtube/v3/playlistItems",
                    params={"part": "snippet", "playlistId": uploads_id, "maxResults": 10},
                    headers=headers
                )
                pl_items = pl_res.json().get("items", [])
                actual_video_count = len(pl_items)
                if pl_items:
                    v_snip = pl_items[0].get("snippet", {})
                    latest_video = {
                        "id": v_snip.get("resourceId", {}).get("videoId"),
                        "title": v_snip.get("title"),
                        "thumbnail": v_snip.get("thumbnails", {}).get("medium", {}).get("url") or v_snip.get("thumbnails", {}).get("default", {}).get("url"),
                        "published_at": v_snip.get("publishedAt"),
                    }
            if not latest_video:
                vid_res = http_requests.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={"part": "snippet", "forMine": "true", "type": "video", "order": "date", "maxResults": 10},
                    headers=headers
                )
                vid_data = vid_res.json()
                items = vid_data.get("items", [])
                if items:
                    v = items[0]
                    latest_video = {
                        "id": v["id"].get("videoId"),
                        "title": v["snippet"].get("title"),
                        "thumbnail": v["snippet"].get("thumbnails", {}).get("medium", {}).get("url"),
                        "published_at": v["snippet"].get("publishedAt"),
                    }
                    actual_video_count = len(items)
                else:
                    actual_video_count = 0
        except Exception as e:
            logger.warning(f"Error checking YouTube uploads list: {e}")

        res_payload = {
            "channel_name": snippet.get("title", ""),
            "channel_thumbnail": snippet.get("thumbnails", {}).get("default", {}).get("url", ""),
            "channel_description": snippet.get("description", ""),
            "subscribers": int(stats.get("subscriberCount", 0)),
            "total_views": int(stats.get("viewCount", 0)),
            "video_count": actual_video_count,
            "latest_video": latest_video,
        }
        cache.set(cache_key, res_payload, timeout=25)
        return Response(res_payload)


class YouTubeVideosView(APIView):
    """List YouTube channel videos."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import requests as http_requests
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)

        access_token = _get_youtube_access_token(client)
        if not access_token:
            return Response({"error": "No valid access token"}, status=400)

        headers = {"Authorization": f"Bearer {access_token}"}
        order = request.GET.get("order", "date")  # date | viewCount | rating
        max_results = int(request.GET.get("max", 24))

        try:
            items = []
            video_ids = []
            video_snippets = {}

            # Strategy 1: Fetch channel's uploads playlist ID (most accurate and instant)
            try:
                ch_res = http_requests.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={"part": "contentDetails", "mine": "true"},
                    headers=headers
                )
                ch_items = ch_res.json().get("items", [])
                if ch_items:
                    uploads_id = ch_items[0].get("contentDetails", {}).get("relatedPlaylists", {}).get("uploads")
                    if uploads_id:
                        pl_res = http_requests.get(
                            "https://www.googleapis.com/youtube/v3/playlistItems",
                            params={"part": "snippet", "playlistId": uploads_id, "maxResults": max_results},
                            headers=headers
                        )
                        for item in pl_res.json().get("items", []):
                            snip = item.get("snippet", {})
                            vid_id = snip.get("resourceId", {}).get("videoId")
                            if vid_id:
                                video_ids.append(vid_id)
                                video_snippets[vid_id] = snip
            except Exception as ex:
                logger.warning(f"Failed to fetch uploads playlist: {ex}")

            # Strategy 2: Fallback to search endpoint if playlistItems returns empty
            if not video_ids:
                search_res = http_requests.get(
                    "https://www.googleapis.com/youtube/v3/search",
                    params={"part": "snippet", "forMine": "true", "type": "video",
                            "order": order, "maxResults": max_results},
                    headers=headers
                )
                for item in search_res.json().get("items", []):
                    vid_id = item.get("id", {}).get("videoId")
                    if vid_id:
                        video_ids.append(vid_id)
                        video_snippets[vid_id] = item.get("snippet", {})

            # Get video statistics
            stats_map = {}
            if video_ids:
                stats_res = http_requests.get(
                    "https://www.googleapis.com/youtube/v3/videos",
                    params={"part": "statistics,contentDetails", "id": ",".join(video_ids)},
                    headers=headers
                )
                for v in stats_res.json().get("items", []):
                    stats_map[v["id"]] = v.get("statistics", {})

            videos = []
            for vid_id in video_ids:
                s = stats_map.get(vid_id, {})
                snip = video_snippets.get(vid_id, {})
                videos.append({
                    "id": vid_id,
                    "title": snip.get("title"),
                    "description": (snip.get("description") or "")[:120],
                    "thumbnail": snip.get("thumbnails", {}).get("medium", {}).get("url") or snip.get("thumbnails", {}).get("default", {}).get("url"),
                    "published_at": snip.get("publishedAt"),
                    "views": int(s.get("viewCount", 0)),
                    "likes": int(s.get("likeCount", 0)),
                    "comments": int(s.get("commentCount", 0)),
                    "url": f"https://www.youtube.com/watch?v={vid_id}",
                })

            # Add mock videos from db if any
            db_videos = client.youtube_config.get("videos", [])
            for db_v in db_videos:
                if not any(v["id"] == db_v["id"] for v in videos):
                    videos.append(db_v)

            return Response({"videos": videos, "total": len(videos)})

        except Exception as e:
            logger.error(f"YouTube videos fetch error: {e}")
            return Response({"error": str(e)}, status=500)


class YouTubeCommentsView(APIView):
    """Fetch YouTube video comments."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        import requests as http_requests
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)

        access_token = _get_youtube_access_token(client)
        video_id = request.GET.get("video_id")
        if not video_id:
            return Response({"error": "video_id required"}, status=400)

        headers = {"Authorization": f"Bearer {access_token}"}
        try:
            res = http_requests.get(
                "https://www.googleapis.com/youtube/v3/commentThreads",
                params={"part": "snippet,replies", "videoId": video_id, "maxResults": 50, "order": "time"},
                headers=headers
            )
            data = res.json()
            comments = []
            for item in data.get("items", []):
                top = item["snippet"]["topLevelComment"]["snippet"]
                
                reply_count = item["snippet"].get("totalReplyCount", 0)
                replies_list = []
                replies_data = item.get("replies", {}).get("comments", [])
                
                # Fetch explicit replies if thread has replies but YouTube API didn't embed them
                if reply_count > 0 and not replies_data:
                    try:
                        r_res = http_requests.get(
                            "https://www.googleapis.com/youtube/v3/comments",
                            params={"part": "snippet", "parentId": item["id"], "maxResults": 20},
                            headers=headers
                        )
                        replies_data = r_res.json().get("items", [])
                    except Exception:
                        pass

                for r in reversed(replies_data):
                    r_snip = r.get("snippet", {})
                    replies_list.append({
                        "reply_id": r.get("id"),
                        "author": r_snip.get("authorDisplayName"),
                        "author_photo": r_snip.get("authorProfileImageUrl"),
                        "text": r_snip.get("textDisplay"),
                        "likes": r_snip.get("likeCount", 0),
                        "published_at": r_snip.get("publishedAt"),
                    })

                comments.append({
                    "comment_id": item["id"],
                    "author": top.get("authorDisplayName"),
                    "author_photo": top.get("authorProfileImageUrl"),
                    "text": top.get("textDisplay"),
                    "likes": top.get("likeCount", 0),
                    "published_at": top.get("publishedAt"),
                    "reply_count": reply_count,
                    "replies": replies_list,
                })
            
            # If no comments from YouTube, check if this is a mock video in DB with mock comments
            if not comments:
                db_videos = client.youtube_config.get("videos", [])
                for db_v in db_videos:
                    if db_v.get("id") == video_id and "mock_comments" in db_v:
                        comments = db_v["mock_comments"]
                        break

            return Response({"comments": comments})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def post(self, request):
        """Post a manual reply to a YouTube comment."""
        import requests as http_requests
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)

        parent_id = request.data.get("parent_id")
        reply_text = request.data.get("reply_text", "").strip()

        if not parent_id:
            return Response({"error": "parent_id is required"}, status=400)
        if not reply_text:
            return Response({"error": "reply_text cannot be empty"}, status=400)

        access_token = _get_youtube_access_token(client)
        if not access_token:
            return Response({"error": "No valid access token"}, status=400)

        try:
            reply_payload = {
                "snippet": {
                    "parentId": parent_id,
                    "textOriginal": reply_text
                }
            }
            res = http_requests.post(
                "https://www.googleapis.com/youtube/v3/comments",
                params={"part": "snippet"},
                json=reply_payload,
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Content-Type": "application/json"
                }
            )

            if res.status_code in [200, 201]:
                data = res.json()
                return Response({
                    "detail": "Reply posted successfully",
                    "comment_id": data.get("id"),
                    "text": data.get("snippet", {}).get("textDisplay"),
                })
            else:
                error_data = res.json()
                error_msg = error_data.get("error", {}).get("message", "Unknown error from YouTube API")
                logger.error(f"YouTube reply failed ({res.status_code}): {error_msg}")
                return Response({"error": error_msg}, status=res.status_code)
        except Exception as e:
            logger.error(f"YouTube comment reply failed: {e}")
            return Response({"error": str(e)}, status=500)


def _find_keyword_reply(comment_text, keyword_rules):
    """Search if comment_text contains any keyword defined in keyword_rules."""
    if not comment_text or not keyword_rules:
        return None
    
    text_lower = comment_text.lower()
    for rule in keyword_rules:
        rule_keywords = rule.get("keywords") or rule.get("keyword") or ""
        reply_text = rule.get("reply") or rule.get("reply_text") or ""
        if not reply_text:
            continue
        
        # Split comma-separated keywords
        kw_list = [k.strip().lower() for k in rule_keywords.split(",") if k.strip()]
        for kw in kw_list:
            if kw in text_lower:
                return reply_text
    return None


class YouTubeAISuggestReplyView(APIView):
    """Generate an AI-suggested reply for a YouTube comment using RAG."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)

        comment_text = request.data.get("comment_text", "").strip()
        if not comment_text:
            return Response({"error": "comment_text is required"}, status=400)

        from ..services.ai_service import get_ai_response, get_rag_response, get_embedding, find_relevant_chunks
        from ..models import KnowledgeChunk

        config = client.youtube_config or {}

        # 1. Check keyword auto-reply rules first
        keyword_match = _find_keyword_reply(comment_text, config.get("keyword_rules", []))
        if keyword_match:
            return Response({"suggested_reply": keyword_match, "behavior": "keyword_match"})

        # Get bot behavior preference (concise / friendly / professional)
        behavior = config.get("bot_behavior", "friendly")
        behavior_instructions = {
            "concise": "Reply in 1-2 short sentences only. Be direct and to the point.",
            "friendly": "Reply in a warm, conversational and encouraging tone. Be friendly and personable.",
            "professional": "Reply in a formal, polished and professional tone. Maintain a business-like manner.",
        }
        behavior_note = behavior_instructions.get(behavior, behavior_instructions["friendly"])

        try:
            ai_reply = None

            # Try RAG-based reply first
            chunks = KnowledgeChunk.objects.filter(client=client).exclude(embedding=[])
            if chunks.exists():
                query_embedding = get_embedding(comment_text)
                if query_embedding:
                    chunks_data = [{
                        'text': c.chunk_text,
                        'embedding': c.embedding,
                        'doc_title': c.document.title
                    } for c in chunks.select_related('document')]
                    relevant = find_relevant_chunks(query_embedding, chunks_data, top_k=5)

                    if relevant and relevant[0]['score'] > 0.3:
                        ai_reply = get_rag_response(comment_text, relevant, client_model=client)

            # Fallback to general AI reply with behavior instruction
            if not ai_reply:
                context = (
                    f"{client.ai_context or 'You are a helpful YouTube channel assistant.'} "
                    f"{behavior_note}"
                )
                ai_reply = get_ai_response(comment_text, context, client_model=client)

            if ai_reply:
                return Response({"suggested_reply": ai_reply, "behavior": behavior})
            else:
                return Response({"error": "Could not generate AI reply"}, status=500)
        except Exception as e:
            logger.error(f"YouTube AI suggest reply failed: {e}")
            return Response({"error": str(e)}, status=500)


class YouTubeSettingsView(APIView):
    """Get or update YouTube broadcast and AI bot automation settings."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)
        
        config = client.youtube_config or {}
        return Response({
            "broadcast_enabled": config.get("broadcast_enabled", False),
            "broadcast_template": config.get("broadcast_template", "🎥 Check out our new video: {title}\nWatch here: {url}"),
            "bot_enabled": config.get("bot_enabled", False),
            "bot_behavior": config.get("bot_behavior", "friendly"),
            "keyword_rules": config.get("keyword_rules", []),
        })

    def post(self, request):
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)
        
        broadcast_enabled = request.data.get("broadcast_enabled", False)
        broadcast_template = request.data.get("broadcast_template", "🎥 Check out our new video: {title}\nWatch here: {url}")
        bot_enabled = request.data.get("bot_enabled", False)
        bot_behavior = request.data.get("bot_behavior", "friendly")
        keyword_rules = request.data.get("keyword_rules", [])

        # Validate bot_behavior value
        valid_behaviors = ["concise", "friendly", "professional"]
        if bot_behavior not in valid_behaviors:
            bot_behavior = "friendly"

        config = client.youtube_config or {}
        config["broadcast_enabled"] = broadcast_enabled
        config["broadcast_template"] = broadcast_template
        config["bot_enabled"] = bot_enabled
        config["bot_behavior"] = bot_behavior
        config["keyword_rules"] = keyword_rules
        client.youtube_config = config
        client.save()

        return Response({"detail": "Settings updated successfully", "config": config})

        return Response({"detail": "Settings updated successfully", "config": config})


class YouTubeCheckNewView(APIView):
    """Manually trigger checking for new YouTube videos to broadcast and auto-replying to comments."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)

        # Broadcast videos
        broadcast_result = check_and_broadcast_youtube_uploads(client)
        
        # Auto-reply to comments if enabled
        bot_result = auto_reply_to_youtube_comments(client)

        return Response({
            "broadcast": broadcast_result,
            "bot_replies": bot_result
        })


class YouTubeUploadView(APIView):
    """Upload videos directly to YouTube from UWO Connect dashboard."""
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)

        video_file = request.FILES.get("video")
        if not video_file:
            return Response({"error": "Video file is required"}, status=400)

        title = request.data.get("title", "My Dashboard Upload")
        description = request.data.get("description", "")
        privacy_status = request.data.get("privacy_status", "public")

        access_token = _get_youtube_access_token(client)
        if not access_token:
            return Response({"error": "No valid access token"}, status=400)

        from googleapiclient.discovery import build
        import io

        try:
            creds = _build_google_credentials(client)
            youtube = build("youtube", "v3", credentials=creds)

            video_data = video_file.read()
            from googleapiclient.http import MediaIoBaseUpload
            mimetype = video_file.content_type if video_file.content_type else "video/mp4"
            media = MediaIoBaseUpload(
                io.BytesIO(video_data),
                mimetype=mimetype,
                chunksize=-1,
                resumable=True
            )

            body = {
                "snippet": {
                    "title": title,
                    "description": description,
                    "tags": ["uwoconnect"]
                },
                "status": {
                    "privacyStatus": privacy_status
                }
            }

            request_execution = youtube.videos().insert(
                part="snippet,status",
                body=body,
                media_body=media
            )
            response = request_execution.execute()
            cache.delete(f"yt_analytics_{client.id}")
            return Response({
                "detail": "Video uploaded successfully",
                "video_id": response.get("id"),
                "title": response.get("snippet", {}).get("title"),
            })
        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            err_str = str(e)
            if "youtubeSignupRequired" in err_str:
                return Response(
                    {"error": "No YouTube Channel found on this Google Account. Please open https://www.youtube.com and create a channel first."},
                    status=400
                )
            if "insufficientPermissions" in err_str or "403" in err_str or "401" in err_str:
                return Response(
                    {"error": "Insufficient YouTube permissions or expired token. Please disconnect & reconnect YouTube under the Channels page."},
                    status=400
                )
            return Response({"error": err_str}, status=400)


class YouTubeChannelProfileView(APIView):
    """Edit YouTube channel snippet details like description."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)

        description = request.data.get("description")
        if description is None:
            return Response({"error": "description is required"}, status=400)

        access_token = _get_youtube_access_token(client)
        if not access_token:
            return Response({"error": "No valid access token"}, status=400)

        from googleapiclient.discovery import build
        import requests as http_requests

        try:
            creds = _build_google_credentials(client)
            youtube = build("youtube", "v3", credentials=creds)

            # Get channel list to inspect current configuration
            ch_res = http_requests.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "id,brandingSettings", "mine": "true"},
                headers={"Authorization": f"Bearer {access_token}"}
            )
            ch_data = ch_res.json()
            channel = ch_data.get("items", [{}])[0]
            channel_id = channel.get("id")
            branding = channel.get("brandingSettings", {})

            if not channel_id:
                return Response({"error": "Channel not found"}, status=400)

            if "channel" not in branding:
                branding["channel"] = {}
            branding["channel"]["description"] = description

            body = {
                "id": channel_id,
                "brandingSettings": branding
            }

            update_res = youtube.channels().update(
                part="brandingSettings",
                body=body
            ).execute()

            return Response({
                "detail": "Channel profile updated successfully",
                "description": update_res.get("brandingSettings", {}).get("channel", {}).get("description")
            })
        except Exception as e:
            logger.error(f"YouTube channel description update failed: {e}")
            return Response({"error": str(e)}, status=500)


class YouTubeDeleteView(APIView):
    """Delete a video from YouTube channel."""
    permission_classes = [IsAuthenticated]

    def delete(self, request):
        client = request.user.client
        if not client or not client.youtube_enabled:
            return Response({"error": "YouTube not connected"}, status=400)

        video_id = request.GET.get("video_id") or request.data.get("video_id")
        if not video_id:
            return Response({"error": "video_id is required"}, status=400)

        from googleapiclient.discovery import build
        try:
            creds = _build_google_credentials(client)
            youtube = build("youtube", "v3", credentials=creds)

            youtube.videos().delete(id=video_id).execute()

            return Response({"detail": "Video deleted successfully from YouTube", "video_id": video_id})
        except Exception as e:
            logger.error(f"YouTube video delete failed: {e}")
            return Response({"error": str(e)}, status=400)


def check_and_broadcast_youtube_uploads(client):
    import requests as http_requests
    from ..services.meta_webhook_service import MetaWebhookService
    from ..models import Contact

    config = client.youtube_config or {}
    if not config.get("broadcast_enabled", False):
        return {"detail": "Broadcast not enabled for this client"}

    access_token = _get_youtube_access_token(client)
    if not access_token:
        return {"error": "No valid access token"}

    headers = {"Authorization": f"Bearer {access_token}"}
    
    try:
        vid_res = http_requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={"part": "snippet", "forMine": "true", "type": "video", "order": "date", "maxResults": 1},
            headers=headers
        )
        vid_data = vid_res.json()
        items = vid_data.get("items", [])
        if not items:
            return {"detail": "No videos found on YouTube channel"}

        v = items[0]
        vid_id = v["id"].get("videoId")
        title = v["snippet"].get("title")
        url = f"https://www.youtube.com/watch?v={vid_id}"

        last_broadcasted_id = config.get("last_broadcasted_video_id")
        if last_broadcasted_id == vid_id:
            return {"detail": "Latest video already broadcasted", "video_id": vid_id}

        template = config.get("broadcast_template", "🎥 Check out our new video: {title}\nWatch here: {url}")
        message_body = template.replace("{title}", title).replace("{url}", url)

        # Get all contacts
        contacts = Contact.objects.filter(client=client).exclude(phone_number__isnull=True).exclude(phone_number="")
        
        phone_number_id = client.whatsapp_phone_number_id
        if not phone_number_id or not client.whatsapp_access_token:
            return {"error": "WhatsApp credentials not fully configured on client for broadcasting."}

        sent_count = 0
        for contact in contacts:
            try:
                to_number = ''.join(c for c in contact.phone_number if c.isdigit() or c == '+')
                MetaWebhookService.send_whatsapp_message(
                    client=client,
                    to_number=to_number,
                    text_body=message_body,
                    phone_number_id=phone_number_id
                )
                sent_count += 1
            except Exception as e:
                logger.warning(f"Failed to send broadcast to {contact.phone_number}: {e}")

        # Update configuration
        config["last_broadcasted_video_id"] = vid_id
        client.youtube_config = config
        client.save()

        return {
            "detail": "Broadcast triggered successfully",
            "video_id": vid_id,
            "title": title,
            "recipients_count": sent_count
        }

    except Exception as e:
        logger.error(f"Error checking/broadcasting YouTube uploads: {e}")
        return {"error": str(e)}


def auto_reply_to_youtube_comments(client):
    config = client.youtube_config or {}
    if not config.get("bot_enabled", False):
        return {"detail": "AI Bot comment auto-reply not enabled"}

    access_token = _get_youtube_access_token(client)
    if not access_token:
        return {"error": "No valid access token"}

    import requests as http_requests
    from ..services.ai_service import get_ai_response, get_rag_response, get_embedding, find_relevant_chunks
    from ..models import KnowledgeChunk

    headers = {"Authorization": f"Bearer {access_token}"}
    replied_ids = config.get("ai_replied_comment_ids", [])
    channel_id = config.get("channel_id", "")
    replied_count = 0

    # Get bot behavior preference (concise / friendly / professional)
    behavior = config.get("bot_behavior", "friendly")
    behavior_instructions = {
        "concise": "Reply in 1-2 short sentences only. Be direct and to the point.",
        "friendly": "Reply in a warm, conversational and encouraging tone. Be friendly and personable.",
        "professional": "Reply in a formal, polished and professional tone. Maintain a business-like manner.",
    }
    behavior_note = behavior_instructions.get(behavior, behavior_instructions["friendly"])

    try:
        # 1. Get the uploads playlist ID from channel details
        channel_id = config.get("channel_id", "")
        if not channel_id:
            # Fallback: fetch channel info
            ch_res = http_requests.get(
                "https://www.googleapis.com/youtube/v3/channels",
                params={"part": "contentDetails", "mine": "true"},
                headers=headers
            )
            ch_data = ch_res.json()
            ch_items = ch_data.get("items", [])
            if not ch_items:
                logger.error("[YouTube AutoReply] Could not fetch channel info.")
                return {"error": "Could not fetch channel info"}
            channel_id = ch_items[0].get("id", "")

        # Fetch the channel's uploads playlist
        ch_res = http_requests.get(
            "https://www.googleapis.com/youtube/v3/channels",
            params={"part": "contentDetails", "id": channel_id},
            headers=headers
        )
        ch_data = ch_res.json()
        ch_items = ch_data.get("items", [])
        if not ch_items:
            logger.error("[YouTube AutoReply] No channel items found.")
            return {"error": "No channel found"}

        uploads_playlist_id = ch_items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

        # 2. Get latest videos from uploads playlist (last 5)
        pl_res = http_requests.get(
            "https://www.googleapis.com/youtube/v3/playlistItems",
            params={"part": "snippet", "playlistId": uploads_playlist_id, "maxResults": 5},
            headers=headers
        )
        pl_items = pl_res.json().get("items", [])
        videos = [{"videoId": item["snippet"]["resourceId"]["videoId"]} for item in pl_items if item["snippet"]["resourceId"].get("videoId")]

        logger.info(f"[YouTube AutoReply] Found {len(videos)} videos to check for comments.")

        for video in videos:
            vid_id = video["videoId"]

            # 3. Fetch comments for this video
            comm_res = http_requests.get(
                "https://www.googleapis.com/youtube/v3/commentThreads",
                params={"part": "snippet", "videoId": vid_id, "maxResults": 20, "order": "time"},
                headers=headers
            )
            comm_data = comm_res.json()
            if "error" in comm_data:
                logger.warning(f"[YouTube AutoReply] Comments error for video {vid_id}: {comm_data['error']}")
                continue
            comments = comm_data.get("items", [])
            logger.info(f"[YouTube AutoReply] Video {vid_id}: {len(comments)} comments found.")

            for thread in comments:
                thread_id = thread["id"]
                top_comment = thread["snippet"]["topLevelComment"]
                comment_id = top_comment["id"]
                comment_text = top_comment["snippet"]["textDisplay"]
                author_channel_id = top_comment["snippet"].get("authorChannelId", {}).get("value", "")
                total_replies = thread["snippet"].get("totalReplyCount", 0)

                # Skip if already replied, if author is channel owner, or if comment thread already has replies
                if comment_id in replied_ids or author_channel_id == channel_id or total_replies > 0:
                    continue

                # 3. Generate Keyword Match / RAG / AI reply
                ai_reply = _find_keyword_reply(comment_text, config.get("keyword_rules", []))

                if not ai_reply:
                    chunks = KnowledgeChunk.objects.filter(client=client).exclude(embedding=[])
                    if chunks.exists():
                        query_embedding = get_embedding(comment_text)
                        if query_embedding:
                            chunks_data = [{
                                'text': c.chunk_text,
                                'embedding': c.embedding,
                                'doc_title': c.document.title
                            } for c in chunks.select_related('document')]
                            relevant = find_relevant_chunks(query_embedding, chunks_data, top_k=5)
                            
                            if relevant and relevant[0]['score'] > 0.3:
                                rag_query = f"{comment_text}\n\n[Instruction: Response tone must be: {behavior_note}]"
                                ai_reply = get_rag_response(rag_query, relevant, client_model=client)

                if not ai_reply:
                    context = (
                        f"{client.ai_context or 'You are a helpful YouTube channel assistant.'} "
                        f"{behavior_note}"
                    )
                    ai_reply = get_ai_response(comment_text, context, client_model=client)

                if ai_reply:
                    # 4. Post reply back to comment thread
                    reply_payload = {
                        "snippet": {
                            "parentId": comment_id,
                            "textOriginal": ai_reply
                        }
                    }
                    reply_res = http_requests.post(
                        "https://www.googleapis.com/youtube/v3/comments",
                        params={"part": "snippet"},
                        json=reply_payload,
                        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
                    )
                    
                    if reply_res.status_code in [200, 201]:
                        replied_ids.append(comment_id)
                        config["ai_replied_comment_ids"] = replied_ids
                        client.youtube_config = config
                        client.save()
                        replied_count += 1

        # Save settings
        config["ai_replied_comment_ids"] = replied_ids
        client.youtube_config = config
        client.save()

        return {
            "detail": f"AI Bot replied to {replied_count} new comments.",
            "replied_count": replied_count
        }

    except Exception as e:
        logger.error(f"YouTube AI auto-reply failed: {e}")
        return {"error": str(e)}

