import logging
import re
from datetime import timedelta
from django.utils import timezone
from django.db.models import Q
from ..models import Contact, Conversation, ConversationAuditLog, Message
from ..repositories.message_repository import MessageRepository

logger = logging.getLogger(__name__)

# Known auto-responder / bot signature phrases (lowercased)
BOT_AUTOREPLY_PATTERNS = [
    r'\bauto[- ]?reply\b',
    r'\bautomated[- ]?reply\b',
    r'\bautomatic[- ]?reply\b',
    r'\bauto[- ]?response\b',
    r'\bautomated[- ]?response\b',
    r'\bout of (?:the )?office\b',
    r'\baway from (?:my desk|the office|office)\b',
    r'\bcurrently away\b',
    r'\bthis is an? (?:automated|automatic|system[- ]generated) message\b',
    r'\bdo not reply to this (?:message|email)\b',
    r'\bwe are currently closed\b',
    r'\bour office is currently closed\b',
    r'\bwe are closed right now\b',
    r'\bwe will get back to you as soon as possible\b',
    r'\bwe have received your message and will respond\b',
    r'\bthank you for (?:your message|contacting us|reaching out)[^.\n]*we are (?:currently )?(?:unavailable|away|closed)\b',
    r'\bundeliverable:\b',
    r'\bmail delivery subsystem\b',
    r'\bfailure notice\b',
    r'\bdelivery status notification\b',
]

COMPILED_BOT_PATTERNS = [re.compile(p, re.IGNORECASE) for p in BOT_AUTOREPLY_PATTERNS]


class BotLoopProtectionService:
    """
    Dedicated, non-intrusive safety service for detecting and preventing:
    1. Repeated consecutive identical incoming messages (Spam / Loop)
    2. Bot-to-bot auto-responder ping-pong
    3. Self-echo mirroring (contact echoing our bot's own text)
    4. Rapid reciprocal back-and-forth ping-pong
    5. High-frequency message floods / bursts

    If a loop is detected, it automatically pauses the bot for that specific
    conversation, adds an audit record and timeline notice, and notifies the UI.
    """

    # Configurable thresholds
    REPEATED_INCOMING_THRESHOLD = 3      # Consecutive identical incoming messages
    RAPID_PING_PONG_COUNT = 6             # Number of alternating messages to inspect
    RAPID_PING_PONG_WINDOW_SECS = 30      # Seconds window for rapid ping-pong
    BURST_MESSAGE_COUNT = 5               # Messages received in short window
    BURST_WINDOW_SECS = 10                # Seconds window for burst flood
    AUTOREPLY_LOOKBACK_MINUTES = 15       # Minutes to look back for bot's outgoing message

    @staticmethod
    def normalize_text(text: str) -> str:
        """
        Normalizes text for loop detection:
        - Lowercases
        - Strips whitespace
        - Collapses consecutive whitespace
        - Strips punctuation so 'Hello!', 'hello', 'Hello...' match
        """
        if not text:
            return ""
        norm = text.lower().strip()
        norm = re.sub(r'\s+', ' ', norm)
        # Remove common punctuation
        norm = re.sub(r'[\s!?,.:;\'"`\-_~#@%^&*()\[\]{}|\\/+=<>]+', ' ', norm).strip()
        return norm

    @staticmethod
    def is_auto_reply_phrase(text: str) -> tuple[bool, str]:
        """
        Detects if text contains common automated bot or auto-responder phrases.
        Returns (is_match, matched_pattern_description).
        """
        if not text:
            return False, ""
        clean_text = text.strip()
        for pattern in COMPILED_BOT_PATTERNS:
            match = pattern.search(clean_text)
            if match:
                return True, match.group(0)
        return False, ""

    @staticmethod
    def is_self_echo(incoming_text: str, last_outgoing_text: str) -> bool:
        """
        Checks if the incoming message mirrors our bot's last outgoing response.
        """
        if not incoming_text or not last_outgoing_text:
            return False
        norm_incoming = BotLoopProtectionService.normalize_text(incoming_text)
        norm_outgoing = BotLoopProtectionService.normalize_text(last_outgoing_text)
        # Only treat as echo if meaningful length (> 3 chars)
        if len(norm_incoming) > 3 and norm_incoming == norm_outgoing:
            return True
        return False

    @classmethod
    def detect_loop(
        cls,
        client,
        contact_platform_id: str,
        incoming_text: str,
        channel: str = 'WHATSAPP',
        contact: Contact = None,
        conversation: Conversation = None,
        current_message: Message = None
    ) -> tuple[bool, str, str]:
        """
        Evaluates conversation history against all loop protection rules.
        Returns:
            (is_loop_detected: bool, loop_type: str, reason: str)
        """
        try:
            if not incoming_text or not contact_platform_id:
                return False, "", ""

            now = timezone.now()
            norm_incoming = cls.normalize_text(incoming_text)
            target_str = str(contact_platform_id).strip()

            # Query recent messages involving this contact (both incoming and outgoing)
            clean_digits = re.sub(r'\D', '', target_str)
            contact_q = Q(from_address=target_str) | Q(to_address=target_str)
            if clean_digits and len(clean_digits) >= 6:
                contact_q |= Q(from_address__icontains=clean_digits) | Q(to_address__icontains=clean_digits)

            msg_qs = Message.objects.filter(Q(client=client) & contact_q)
            if current_message and getattr(current_message, 'id', None):
                msg_qs = msg_qs.exclude(id=current_message.id)

            prior_messages = list(msg_qs.order_by('-created_at')[:15])

            # Separate prior messages into incoming and outgoing
            prior_incoming = [m for m in prior_messages if m.message_type == 'INCOMING']
            prior_outgoing = [m for m in prior_messages if m.message_type == 'OUTGOING']

            # -------------------------------------------------------------
            # RULE 1: External Bot / Auto-Responder Pattern Detection
            # -------------------------------------------------------------
            is_auto, matched_phrase = cls.is_auto_reply_phrase(incoming_text)
            if is_auto:
                # Check if our bot sent an outgoing message recently (in the last 15 min)
                recent_outgoing = prior_outgoing[0] if prior_outgoing else None
                if recent_outgoing and (now - recent_outgoing.created_at) <= timedelta(minutes=cls.AUTOREPLY_LOOKBACK_MINUTES):
                    return (
                        True,
                        "BOT_AUTO_REPLY_LOOP",
                        f"External bot auto-reply signature detected ('{matched_phrase}') in response to bot"
                    )
                # Or if contact previously sent this auto-reply
                matching_count = sum(1 for m in prior_incoming[:3] if cls.is_auto_reply_phrase(m.body)[0])
                if matching_count >= 1:
                    return (
                        True,
                        "BOT_AUTO_REPLY_LOOP",
                        f"Repeated external bot auto-reply signature detected ('{matched_phrase}')"
                    )

            # -------------------------------------------------------------
            # RULE 2: Self-Echo Mirroring Detection
            # -------------------------------------------------------------
            if prior_outgoing:
                last_out = prior_outgoing[0]
                if (now - last_out.created_at) <= timedelta(minutes=cls.AUTOREPLY_LOOKBACK_MINUTES):
                    if cls.is_self_echo(incoming_text, last_out.body):
                        return (
                            True,
                            "SELF_ECHO_LOOP",
                            "Incoming message echoes bot's previous outgoing response"
                        )

            # -------------------------------------------------------------
            # RULE 3: Repeated Consecutive Incoming Messages
            # -------------------------------------------------------------
            # The current message is #1. We need (THRESHOLD - 1) consecutive identical prior messages
            if norm_incoming and len(norm_incoming) >= 2:
                needed_prior = cls.REPEATED_INCOMING_THRESHOLD - 1
                if len(prior_incoming) >= needed_prior:
                    sample_prior = [cls.normalize_text(m.body) for m in prior_incoming[:needed_prior]]
                    if all(p == norm_incoming for p in sample_prior):
                        oldest_in_group = prior_incoming[needed_prior - 1]
                        if (now - oldest_in_group.created_at) <= timedelta(hours=2):
                            return (
                                True,
                                "REPEATED_INCOMING_LOOP",
                                f"Consecutive identical incoming message repeated {cls.REPEATED_INCOMING_THRESHOLD} times"
                            )

            # -------------------------------------------------------------
            # RULE 4: Rapid Ping-Pong Alternating Loop
            # -------------------------------------------------------------
            # Sequence: [Current Incoming (now)] + prior_messages
            # Check if recent alternating sequence occurs in < 30 seconds
            class _VirtualMsg:
                def __init__(self, m_type, dt, b):
                    self.message_type = m_type
                    self.created_at = dt
                    self.body = b

            combined_seq = [_VirtualMsg('INCOMING', now, incoming_text)] + prior_messages
            if len(combined_seq) >= cls.RAPID_PING_PONG_COUNT:
                sample_set = combined_seq[:cls.RAPID_PING_PONG_COUNT]
                newest_time = sample_set[0].created_at
                oldest_time = sample_set[-1].created_at
                if (newest_time - oldest_time) <= timedelta(seconds=cls.RAPID_PING_PONG_WINDOW_SECS):
                    types = [m.message_type for m in sample_set]
                    is_alternating = all(
                        types[i] != types[i + 1]
                        for i in range(len(types) - 1)
                        if types[i] in ['INCOMING', 'OUTGOING'] and types[i + 1] in ['INCOMING', 'OUTGOING']
                    )
                    if is_alternating:
                        return (
                            True,
                            "RAPID_PING_PONG_LOOP",
                            f"Rapid alternating bot-to-bot messaging loop ({cls.RAPID_PING_PONG_COUNT} messages in <{cls.RAPID_PING_PONG_WINDOW_SECS}s)"
                        )

            # -------------------------------------------------------------
            # RULE 5: High-Frequency Message Burst Flood
            # -------------------------------------------------------------
            # Current message + prior incoming messages
            needed_prior_burst = cls.BURST_MESSAGE_COUNT - 1
            if len(prior_incoming) >= needed_prior_burst:
                burst_set = prior_incoming[:needed_prior_burst]
                if (now - burst_set[-1].created_at) <= timedelta(seconds=cls.BURST_WINDOW_SECS):
                    return (
                        True,
                        "MESSAGE_FLOOD_LOOP",
                        f"High-frequency message flood detected ({cls.BURST_MESSAGE_COUNT} messages in <{cls.BURST_WINDOW_SECS}s)"
                    )

            return False, "", ""

        except Exception as e:
            logger.error(f"[BotLoopProtection] Error detecting loop: {str(e)}", exc_info=True)
            # Fail-safe: never block normal conversation if detection throws
            return False, "", ""

    @classmethod
    def execute_loop_pause(
        cls,
        client,
        contact_platform_id: str,
        loop_type: str,
        reason: str,
        channel: str = 'WHATSAPP',
        incoming_text: str = '',
        contact: Contact = None,
        conversation: Conversation = None
    ) -> None:
        """
        Executes automatic bot pause for the contact and conversation:
        1. Sets contact.bot_paused = True
        2. Sets conversation.is_locked = True
        3. Creates ConversationAuditLog entry
        4. Inserts an INTERNAL system note in conversation timeline
        5. Emits real-time WebSocket event to inbox group
        """
        try:
            target_str = str(contact_platform_id).strip()

            # Resolve contact if not provided
            if not contact:
                clean_digits = re.sub(r'\D', '', target_str)
                contact_q = Q(platform_id=target_str)
                if clean_digits:
                    contact_q |= Q(phone_number__icontains=clean_digits) | Q(platform_id=clean_digits)
                contact = Contact.objects.filter(Q(client=client) & contact_q).first()

            # Pause bot for contact
            if contact and not contact.bot_paused:
                contact.bot_paused = True
                contact.save(update_fields=['bot_paused'])
                logger.info(f"[BotLoopProtection] Paused bot for contact '{contact.name}' ({contact.platform_id})")

            # Resolve conversation if not provided
            if not conversation:
                clean_digits = re.sub(r'\D', '', target_str)
                convo_q = Q(client=client) & (
                    Q(contact_platform_id=target_str) | Q(contact=contact)
                )
                if clean_digits:
                    convo_q |= Q(client=client) & (
                        Q(contact_platform_id__icontains=clean_digits) |
                        Q(contact__phone_number__icontains=clean_digits)
                    )
                conversation = Conversation.objects.filter(convo_q).first()

            # Lock conversation
            if conversation:
                conversation.is_locked = True
                conversation.save(update_fields=['is_locked'])

            # Create Audit Log
            effective_client = client or (conversation.client if conversation else None)
            if conversation and effective_client:
                try:
                    ConversationAuditLog.objects.create(
                        conversation=conversation,
                        client=effective_client,
                        actor=None,
                        actor_name="Loop Shield",
                        actor_role="SYSTEM",
                        event_type="BOT_AUTO_PAUSED",
                        details={
                            "action": "Bot Auto-Paused (Loop Protection)",
                            "loop_type": loop_type,
                            "reason": reason,
                            "incoming_snippet": (incoming_text or "")[:120]
                        }
                    )
                except Exception as _ae:
                    logger.warning(f"[BotLoopProtection] Failed to create audit log: {_ae}")

            # Insert an INTERNAL system note in conversation timeline
            # This makes the pause reason immediately visible to agents in the timeline
            if effective_client:
                try:
                    dest_address = target_str
                    if contact and contact.phone_number:
                        dest_address = contact.phone_number
                    elif conversation and conversation.contact_platform_id:
                        dest_address = conversation.contact_platform_id

                    MessageRepository.create_message(
                        client=effective_client,
                        channel=channel or (conversation.channel if conversation else 'WHATSAPP'),
                        from_address="Loop Shield",
                        to_address=dest_address,
                        body=f"⚠️ Bot Auto-Paused: {reason}. Click 'Resume Bot' to re-enable automated responses.",
                        message_type='INTERNAL',
                        status='SENT',
                        metadata={
                            "is_loop_shield_notice": True,
                            "loop_type": loop_type,
                            "reason": reason
                        }
                    )
                except Exception as _me:
                    logger.warning(f"[BotLoopProtection] Failed to create internal timeline note: {_me}")

            # Broadcast via WebSocket so web and mobile UIs update in real time
            if effective_client:
                try:
                    from channels.layers import get_channel_layer
                    from asgiref.sync import async_to_sync
                    channel_layer = get_channel_layer()
                    if channel_layer:
                        payload = {
                            "type": "broadcast_event",
                            "event_data": {
                                "type": "takeover_event",       # Triggers live refresh in web inbox
                                "sub_type": "bot_auto_paused",
                                "conversation_id": str(conversation.id) if conversation else None,
                                "bot_paused": True,
                                "reason": reason,
                                "loop_type": loop_type,
                                "timestamp": timezone.now().isoformat()
                            }
                        }
                        async_to_sync(channel_layer.group_send)(
                            f"inbox_{effective_client.id}",
                            payload
                        )
                except Exception as _wse:
                    logger.warning(f"[BotLoopProtection] Failed to broadcast ws event: {_wse}")

        except Exception as e:
            logger.error(f"[BotLoopProtection] Error executing loop pause: {str(e)}", exc_info=True)

    @classmethod
    def check_and_protect(
        cls,
        client,
        contact_platform_id: str,
        incoming_text: str,
        channel: str = 'WHATSAPP',
        contact: Contact = None,
        conversation: Conversation = None,
        current_message: Message = None
    ) -> bool:
        """
        Master gatekeeper method:
        Checks if the incoming message triggers any loop condition.
        If a loop is detected:
            - Executes automatic bot pause
            - Returns True (automated bot flow should STOP)
        If no loop is detected:
            - Returns False (existing bot flow proceeds normally)
        """
        try:
            # If contact is already paused, no need to detect again
            if contact and contact.bot_paused:
                return True

            is_loop, loop_type, reason = cls.detect_loop(
                client=client,
                contact_platform_id=contact_platform_id,
                incoming_text=incoming_text,
                channel=channel,
                contact=contact,
                conversation=conversation,
                current_message=current_message
            )

            if is_loop:
                logger.warning(
                    f"[BotLoopProtection] LOOP DETECTED for {channel} contact {contact_platform_id}: "
                    f"[{loop_type}] {reason}"
                )
                cls.execute_loop_pause(
                    client=client,
                    contact_platform_id=contact_platform_id,
                    loop_type=loop_type,
                    reason=reason,
                    channel=channel,
                    incoming_text=incoming_text,
                    contact=contact,
                    conversation=conversation
                )
                return True

            return False

        except Exception as e:
            logger.error(f"[BotLoopProtection] Gatekeeper error: {str(e)}", exc_info=True)
            # Fail-safe: allow normal flow on unhandled exception
            return False
