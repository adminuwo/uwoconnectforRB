import logging
import requests as http_requests
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from ..services.ai_service import get_ai_response

logger = logging.getLogger(__name__)

# Category topic code map for Google News RSS
TOPIC_CODES = {
    "WORLD": "WORLD",
    "NATION": "NATION",
    "BUSINESS": "BUSINESS",
    "TECHNOLOGY": "TECHNOLOGY",
    "ENTERTAINMENT": "ENTERTAINMENT",
    "SPORTS": "SPORTS",
    "SCIENCE": "SCIENCE",
    "HEALTH": "HEALTH",
}

def parse_google_news_xml(xml_content):
    """Parse Google News RSS XML string into clean list of article dictionaries."""
    articles = []
    try:
        root = ET.fromstring(xml_content)
        channel = root.find("channel")
        if channel is None:
            return articles

        for item in channel.findall("item"):
            title = item.findtext("title", "")
            link = item.findtext("link", "")
            pub_date = item.findtext("pubDate", "")
            description = item.findtext("description", "")
            source_elem = item.find("source")
            source_name = source_elem.text if source_elem is not None else "Google News"

            import re
            clean_snippet = re.sub(r'<[^>]+>', '', description).strip()

            clean_title = title
            if " - " in title:
                parts = title.rsplit(" - ", 1)
                clean_title = parts[0].strip()
                if source_name == "Google News" and len(parts) > 1:
                    source_name = parts[1].strip()

            articles.append({
                "title": clean_title,
                "link": link,
                "pub_date": pub_date,
                "snippet": clean_snippet[:250] + ("..." if len(clean_snippet) > 250 else ""),
                "source": source_name,
            })
    except Exception as e:
        logger.error(f"Error parsing Google News RSS XML: {e}")

    return articles


def get_tenant_client(request):
    if not request.user or not request.user.is_authenticated:
        return None
    client = getattr(request.user, 'client_workspace', None) or getattr(request.user, 'client', None)
    if not client and getattr(request.user, 'role', '') == 'ADMIN':
        client_id = request.query_params.get('client_id') or request.data.get('client_id')
        if client_id:
            try:
                from ..models import Client
                return Client.objects.get(id=client_id)
            except Exception:
                pass
        from ..models import Client
        return Client.objects.first()
    return client


class GoogleNewsSettingsView(APIView):
    """Get or update Google News integration settings for the authenticated client."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"error": "No associated client found"}, status=400)

        config = client.google_news_config or {}
        return Response({
            "enabled": client.google_news_enabled,
            "default_topic": config.get("default_topic", "TECHNOLOGY"),
            "keywords": config.get("keywords", ["ai", "technology", "business"]),
            "language": config.get("language", "en"),
            "country": config.get("country", "US"),
            "auto_summary_tone": config.get("auto_summary_tone", "professional")
        })

    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"error": "No associated client found"}, status=400)

        enabled = request.data.get("enabled", client.google_news_enabled)
        default_topic = request.data.get("default_topic", "TECHNOLOGY")
        keywords = request.data.get("keywords", ["ai", "technology", "business"])
        language = request.data.get("language", "en")
        country = request.data.get("country", "US")
        auto_summary_tone = request.data.get("auto_summary_tone", "professional")

        client.google_news_enabled = bool(enabled)
        client.google_news_config = {
            "default_topic": default_topic,
            "keywords": keywords if isinstance(keywords, list) else [k.strip() for k in str(keywords).split(",") if k.strip()],
            "language": language,
            "country": country,
            "auto_summary_tone": auto_summary_tone
        }
        client.save()

        return Response({
            "detail": "Google News settings updated successfully",
            "enabled": client.google_news_enabled,
            "config": client.google_news_config
        })


class GoogleNewsFeedView(APIView):
    """Fetch live Google News RSS feed based on search query or category topic."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        client = get_tenant_client(request)
        if not client or not client.google_news_enabled:
            pass

        query = request.GET.get("query", "").strip()
        category = request.GET.get("category", "").upper().strip()
        lang = request.GET.get("language", "en")
        country = request.GET.get("country", "US")

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            if query:
                encoded_query = quote_plus(query)
                rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl={lang}-{country}&gl={country}&ceid={country}:{lang}"
            elif category and category in TOPIC_CODES:
                topic_code = TOPIC_CODES[category]
                rss_url = f"https://news.google.com/rss/headlines/section/topic/{topic_code}?hl={lang}-{country}&gl={country}&ceid={country}:{lang}"
            else:
                rss_url = f"https://news.google.com/rss?hl={lang}-{country}&gl={country}&ceid={country}:{lang}"

            res = http_requests.get(rss_url, headers=headers, timeout=10)
            if res.status_code != 200:
                return Response({"error": f"Failed to fetch Google News RSS feed (HTTP {res.status_code})"}, status=400)

            articles = parse_google_news_xml(res.content.decode('utf-8', errors='ignore'))
            return Response({
                "query": query,
                "category": category or "TOP_STORIES",
                "count": len(articles),
                "articles": articles
            })

        except Exception as e:
            logger.error(f"Error fetching Google News feed: {e}")
            return Response({"error": str(e)}, status=500)


import re

def _sanitize_ai_output(text, action="SUMMARIZE", title="", snippet="", source="", link=""):
    """Sanitize AI generated news output: strip conversational preambles, markdown code fences,
    extraneous closing remarks, and leading/trailing dashes/bullets/quotes. Provide instant fallback if needed."""
    if not text or not isinstance(text, str) or "ai service is not configured" in text.lower():
        if action == "BROADCAST":
            return (
                f"📰 *BREAKING NEWS ALERT*\n\n"
                f"*{title}*\n\n"
                f"🔹 {snippet}\n\n"
                f"📌 *Source:* {source or 'Google News'}\n"
                f"🔗 *Read Full Story:* {link}"
            )
        elif action == "SOCIAL":
            return (
                f"🚀 Top Industry Development: {title}\n\n"
                f"{snippet}\n\n"
                f"What are your thoughts on this? Read more below 👇\n{link}\n\n"
                f"#TechNews #BreakingNews #BusinessGrowth #Trends"
            )
        else:
            return (
                f"• {title}\n"
                f"• {snippet}\n"
                f"• Monitored via {source or 'Google News'} for key real-time market updates."
            )

    # 1. Strip conversational preambles like "Certainly! Here is...", "Sure, here's..."
    cleaned = re.sub(
        r'^(?:certainly!?|sure!?|of course!?|here(?:[\'’]s| is| are)|below is|as an ai)[\s\S]*?:(?:\r?\n)+',
        '',
        text,
        flags=re.IGNORECASE
    ).strip()

    # 2. Strip conversational closings
    cleaned = re.sub(
        r'(?:\r?\n)+(?:feel free to|hope this helps|let me know if|please let me know|don\'t hesitate to)[\s\S]*$',
        '',
        cleaned,
        flags=re.IGNORECASE
    ).strip()

    # 3. Repeatedly clean markdown code fences, dividers, dashes, and quotes
    changed = True
    while changed:
        prev = cleaned
        if cleaned.startswith("```"):
            cleaned = re.sub(r'^```[a-zA-Z]*\n?', '', cleaned)
            cleaned = re.sub(r'\n?```$', '', cleaned).strip()

        # Remove leading divider lines or bullets
        cleaned = re.sub(r'^[-–—_*~•#\s]+(?:\r?\n)+', '', cleaned).strip()
        if cleaned.startswith(('-', '–', '—')):
            cleaned = re.sub(r'^[-–—_*~•\s]+', '', cleaned).strip()

        # Remove trailing divider lines or bullets
        cleaned = re.sub(r'(?:\r?\n)+[-–—_*~•#\s]+$', '', cleaned).strip()
        if cleaned.endswith(('-', '–', '—')):
            cleaned = re.sub(r'[-–—_*~•\s]+$', '', cleaned).strip()

        # Remove surrounding quotes
        if (
            (cleaned.startswith('"') and cleaned.endswith('"')) or
            (cleaned.startswith('“') and cleaned.endswith('”')) or
            (cleaned.startswith("'") and cleaned.endswith("'")) or
            (cleaned.startswith('‘') and cleaned.endswith('’'))
        ):
            cleaned = cleaned[1:-1].strip()

        changed = (cleaned != prev)

    return cleaned if cleaned else text.strip()


class GoogleNewsAISummarizeView(APIView):
    """Generate an AI summary, bullet-point digest, or WhatsApp broadcast copy for a news article."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"error": "No associated client found"}, status=400)

        title = request.data.get("title", "")
        snippet = request.data.get("snippet", "")
        source = request.data.get("source", "")
        link = request.data.get("link", "")
        action = request.data.get("action", "SUMMARIZE").upper()

        if not title:
            return Response({"error": "Article title is required"}, status=400)

        tone = client.google_news_config.get("auto_summary_tone", "professional") if client.google_news_config else "professional"

        if action == "BROADCAST":
            prompt = (
                f"Format the following news story into a compelling WhatsApp broadcast alert message for customers.\n"
                f"Include relevant emojis, a catchy headline, 3 quick key takeaways, and a call-to-action link.\n"
                f"Tone: {tone}.\n"
                f"Do not include conversational preambles (e.g. 'Certainly!', 'Here is...'), markdown quotes, or trailing pleasantries. Start immediately with the broadcast message.\n\n"
                f"Title: {title}\nSource: {source}\nSnippet: {snippet}\nURL: {link}"
            )
        elif action == "SOCIAL":
            prompt = (
                f"Draft an engaging social media post (LinkedIn/Instagram caption) with 3 relevant hashtags based on this news story.\n"
                f"Do not include conversational preambles (e.g. 'Certainly!', 'Here is...'), markdown quotes, or trailing pleasantries. Output only the caption directly.\n\n"
                f"Title: {title}\nSource: {source}\nSnippet: {snippet}\nURL: {link}"
            )
        else:
            prompt = (
                f"Provide a concise, 3-bullet point executive summary and key insights for this news article.\n"
                f"Do not include conversational preambles (e.g. 'Certainly!', 'Here is...'), markdown quotes, or trailing pleasantries. Output only the bullet points.\n\n"
                f"Title: {title}\nSource: {source}\nSnippet: {snippet}\nURL: {link}"
            )

        try:
            ai_output = get_ai_response(prompt, client_model=client)
            sanitized = _sanitize_ai_output(ai_output, action=action, title=title, snippet=snippet, source=source, link=link)
            return Response({
                "action": action,
                "ai_output": sanitized
            })
        except Exception as e:
            logger.error(f"Error generating AI news summary: {e}")
            fallback = _sanitize_ai_output("", action=action, title=title, snippet=snippet, source=source, link=link)
            return Response({
                "action": action,
                "ai_output": fallback
            })


class GoogleNewsSendAlertView(APIView):
    """Broadcast a live news text alert to WhatsApp contacts, Facebook Page, and Instagram DMs."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"error": "No associated client found"}, status=400)

        title = request.data.get("title", "")
        snippet = request.data.get("snippet", "")
        link = request.data.get("link", "")
        source = request.data.get("source", "Google News")
        custom_text = request.data.get("custom_text", "").strip()
        send_channels = request.data.get("send_channels", ["WHATSAPP", "FACEBOOK", "INSTAGRAM"])

        if not title:
            return Response({"error": "Article title is required"}, status=400)

        from ..models import Contact, Message, Conversation
        from ..services.meta_webhook_service import MetaWebhookService

        if custom_text:
            message_body = custom_text
        else:
            message_body = (
                f"📰 *BREAKING NEWS ALERT*\n\n"
                f"*{title}*\n\n"
                f"{snippet}\n\n"
                f"📌 *Source:* {source}\n"
                f"🔗 *Read Full Story:* {link}"
            )

        whatsapp_count = 0
        facebook_count = 0
        instagram_count = 0
        fb_error = None
        ig_error = None

        # ── 1. WhatsApp Broadcast ────────────────────────────────────
        recipient_phone = request.data.get("recipient_phone") or request.data.get("phone")
        if "WHATSAPP" in send_channels:
            phone_number_id = client.whatsapp_phone_number_id or '100000000000000'
            contacts = Contact.objects.filter(client=client).exclude(phone_number__isnull=True).exclude(phone_number="")
            
            phone_list = [c.phone_number for c in contacts if c.phone_number]
            if recipient_phone:
                phone_list = [recipient_phone] + [p for p in phone_list if p != recipient_phone]
            elif not phone_list:
                # Fallback to recent message recipients
                recent_phones = Message.objects.filter(client=client).values_list('to_address', flat=True).distinct()
                phone_list = [p for p in recent_phones if p and any(ch.isdigit() for ch in str(p))]

            for raw_phone in phone_list:
                try:
                    to_digits = ''.join(c for c in str(raw_phone) if c.isdigit())
                    # Valid WhatsApp numbers must have 10 to 15 digits (excludes 16+ digit Meta PSIDs)
                    if 10 <= len(to_digits) <= 15:
                        to_number = to_digits if len(to_digits) != 10 else f"91{to_digits}"
                        MetaWebhookService.send_whatsapp_message(
                            client=client,
                            to_number=to_number,
                            text_body=message_body,
                            phone_number_id=phone_number_id
                        )
                        whatsapp_count += 1
                except Exception as e:
                    logger.warning(f"Error sending news alert (WA) to {raw_phone}: {e}")

        # ── 2. Facebook Broadcast — Page Feed Post ──────────────────
        if "FACEBOOK" in send_channels and client.facebook_enabled:
            fb_config = client.facebook_config or {}
            fb_token = fb_config.get("access_token")
            fb_page_id = fb_config.get("page_id")
            if fb_token and fb_page_id:
                try:
                    post_url = f"https://graph.facebook.com/v20.0/{fb_page_id}/feed"
                    post_res = http_requests.post(post_url, json={
                        "message": message_body,
                        "access_token": fb_token,
                    })
                    post_data = post_res.json()
                    logger.info(f"[News Alert] FB Page Post Response: {post_data}")
                    if "id" in post_data:
                        facebook_count = 1
                    else:
                        fb_error = post_data.get("error", {}).get("message", str(post_data))
                        logger.warning(f"[News Alert] FB page post failed: {post_data}")
                except Exception as e:
                    fb_error = str(e)
                    logger.warning(f"[News Alert] Facebook page post error: {e}")
            else:
                fb_error = f"FB not configured — token={bool(fb_token)}, page_id={fb_page_id}"
                logger.warning(fb_error)
        elif "FACEBOOK" in send_channels:
            fb_error = "Facebook not connected/enabled on this account"

        # ── 3. Instagram Broadcast — DM existing convos, FB fallback ─
        if "INSTAGRAM" in send_channels and client.instagram_enabled:
            ig_config = client.instagram_config or {}
            ig_token = ig_config.get("access_token")
            ig_business_id = ig_config.get("instagram_business_id")
            if ig_token and ig_business_id:
                try:
                    ig_conversations = Conversation.objects.filter(
                        client=client, channel="INSTAGRAM"
                    ).values_list("contact_platform_id", flat=True).distinct()

                    ig_conv_count = 0
                    for psid in ig_conversations:
                        if not psid:
                            continue
                        try:
                            MetaWebhookService.send_fb_ig_message(
                                client=client,
                                platform="INSTAGRAM",
                                recipient_id=psid,
                                text_body=message_body,
                            )
                            ig_conv_count += 1
                        except Exception as e:
                            logger.warning(f"[News Alert] IG DM error to PSID {psid}: {e}")

                    if ig_conv_count > 0:
                        instagram_count = ig_conv_count
                    else:
                        # Fallback: post to linked Facebook page using IG token
                        fb_cfg2 = client.facebook_config or {}
                        fb_token2 = fb_cfg2.get("access_token") or ig_token
                        fb_page_id2 = ig_config.get("page_id") or fb_cfg2.get("page_id")
                        if fb_page_id2 and fb_token2 and facebook_count == 0:
                            try:
                                post_url2 = f"https://graph.facebook.com/v20.0/{fb_page_id2}/feed"
                                post_res2 = http_requests.post(post_url2, json={
                                    "message": message_body,
                                    "access_token": fb_token2,
                                })
                                post_data2 = post_res2.json()
                                logger.info(f"[News Alert] IG->FB fallback: {post_data2}")
                                if "id" in post_data2:
                                    instagram_count = 1
                                else:
                                    ig_error = post_data2.get("error", {}).get("message", str(post_data2))
                            except Exception as e:
                                ig_error = str(e)
                        else:
                            ig_error = "No Instagram DM conversations found. Ask followers to message you first on Instagram."
                except Exception as e:
                    ig_error = str(e)
                    logger.warning(f"[News Alert] Instagram broadcast error: {e}")
            else:
                ig_error = f"IG not configured — token={bool(ig_token)}, ig_business_id={ig_business_id}"
                logger.warning(ig_error)
        elif "INSTAGRAM" in send_channels:
            ig_error = "Instagram not connected/enabled on this account"

        total_sent = whatsapp_count + facebook_count + instagram_count

        if total_sent > 0:
            detail_msg = f"News alert broadcasted to {total_sent} recipient(s)"
        else:
            detail_msg = "News broadcast prepared. Note: Connect your WhatsApp/Meta channels or add CRM contacts to deliver to external recipients."

        return Response({
            "detail": detail_msg,
            "sent_count": total_sent,
            "whatsapp_count": whatsapp_count,
            "facebook_count": facebook_count,
            "instagram_count": instagram_count,
            "fb_error": fb_error,
            "ig_error": ig_error,
            "message_body": message_body
        })
