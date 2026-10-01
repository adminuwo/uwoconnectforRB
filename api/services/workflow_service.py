import re
import json
import logging
from ..models import WorkflowSession, Workflow
from ..repositories.automation_repository import WorkflowSessionRepository
from ..repositories.workflow_repository import WorkflowRepository
from ..repositories.contact_repository import ContactRepository

logger = logging.getLogger(__name__)

class WorkflowEngine:
    @staticmethod
    def process_workflow(client, phone_number, incoming_text, channel='WHATSAPP', allow_catch_all=True, check_active_session=True):
        """
        Process the incoming text to advance an active workflow session,
        or start a new workflow session if a trigger matches.
        
        channel: 'WHATSAPP' | 'FACEBOOK' | 'INSTAGRAM'
        allow_catch_all: If True, matches '*' / 'all' wildcard workflows.
                         If False, only matches workflows with specific keywords.
        check_active_session: If True, checks and advances an existing active session.
        
        Returns a list of dicts representing messages to send, or None.
        """
        incoming_text_lower = (incoming_text or '').lower().strip()
        channel_upper = (channel or 'WHATSAPP').upper()

        # 1. Check for active session on this channel
        if check_active_session:
            sessions = WorkflowSessionRepository.filter_workflowsessions(
                client=client, 
                phone_number=phone_number, 
                is_active=True
            )
            session = None
            for s in sessions:
                s_chan = ((s.variables or {}).get('channel') or 'WHATSAPP').upper()
                if s_chan == channel_upper:
                    session = s
                    break

            if session:
                wf_channels = [c.upper() for c in (session.workflow.channels or [])]
                is_match = False
                if len(wf_channels) > 0 and channel_upper in wf_channels:
                    is_match = True
                elif len(wf_channels) == 0:
                    is_match = True
                
                if is_match:
                    res = WorkflowEngine._advance_session(session, incoming_text)
                    if res:
                        return res
                    session.is_active = False
                    session.save()

        # 2. Check for new workflow triggers
        workflows = WorkflowRepository.filter_workflows(client=client, enabled=True)
        for wf in workflows:
            wf_channels = [c.upper() for c in (wf.channels or [])]
            # Strict channel filtering:
            # If channels are configured, incoming channel MUST be in the list
            if len(wf_channels) > 0 and channel_upper not in wf_channels:
                continue

            # Reserved commercial system commands that shouldn't be hijacked by generic wildcard (*) triggers
            reserved_commercial_keywords = {'catalog', 'product', 'products', 'browse products', 'shop', 'items', 'store', 'samaan', 'buy now', 'order now'}
            is_reserved_command = any(rc in incoming_text_lower for rc in reserved_commercial_keywords)

            catch_all_tokens = {'*', 'all', 'any', 'anything'}
            is_catch_all = False
            has_keyword_match = False

            if wf.trigger_type in ['ALL', 'ANY', 'ANYTHING']:
                is_catch_all = True

            if isinstance(wf.trigger_value, list):
                trigger_keywords = [str(t).lower().strip() for t in wf.trigger_value if t]
                if any(t in catch_all_tokens for t in trigger_keywords):
                    is_catch_all = True
                for kw in trigger_keywords:
                    if kw not in catch_all_tokens and kw:
                        pattern = r'(?<!\w)' + re.escape(kw) + r'(?!\w)'
                        if re.search(pattern, incoming_text_lower, re.IGNORECASE) or kw == incoming_text_lower:
                            has_keyword_match = True
                            break
            elif isinstance(wf.trigger_value, str):
                kw = wf.trigger_value.lower().strip()
                if kw in catch_all_tokens:
                    is_catch_all = True
                elif kw:
                    pattern = r'(?<!\w)' + re.escape(kw) + r'(?!\w)'
                    if re.search(pattern, incoming_text_lower, re.IGNORECASE) or kw == incoming_text_lower:
                        has_keyword_match = True

            # Specific keyword match takes precedence
            if has_keyword_match:
                logger.info(f"[WORKFLOW MATCH] Specific keyword match for workflow '{wf.name}' (#{wf.id}) on {channel_upper}")
                return WorkflowEngine._start_workflow(client, phone_number, wf, channel=channel_upper)

            # Catch-all wildcard trigger (only if allowed and not a reserved command)
            if is_catch_all and allow_catch_all and not is_reserved_command:
                logger.info(f"[WORKFLOW MATCH] Catch-all wildcard trigger for workflow '{wf.name}' (#{wf.id}) on {channel_upper}")
                return WorkflowEngine._start_workflow(client, phone_number, wf, channel=channel_upper)

        return None

    @staticmethod
    def _start_workflow(client, phone_number, workflow, channel='WHATSAPP'):
        # Parse the JSON steps
        steps = workflow.steps
        if not steps or 'nodes' not in steps:
            return None
            
        nodes = steps.get('nodes', [])

        # Find the trigger (start) node
        start_node = next((n for n in nodes if n.get('type') == 'trigger'), None)
        if not start_node:
            return None

        # Create session with channel context in variables
        session = WorkflowSessionRepository.create_workflowsession(
            client=client,
            phone_number=phone_number,
            workflow=workflow,
            current_node_id=start_node.get('id'),
            variables={'channel': (channel or 'WHATSAPP').upper()}
        )

        # Advance it immediately to get the first real message node
        return WorkflowEngine._advance_session(session, "")

    @staticmethod
    def _advance_session(session, incoming_text):
        steps = session.workflow.steps
        nodes = steps.get('nodes', [])
        edges = steps.get('edges', [])
        
        # Get contact for checking conditions
        from ..models import Contact
        contact = ContactRepository.filter_contacts(client=session.client, platform_id=session.phone_number).first()

        messages_to_send = []
        current_node_id = session.current_node_id
        
        current_node = next((n for n in nodes if n.get('id') == current_node_id), None)
        if not current_node:
            session.is_active = False
            session.save()
            return None

        # 1. If currently at a buttons or list node, select branch based on incoming_text
        if current_node.get('type') in ['buttons', 'list', 'interactive_list']:
            is_list = current_node.get('type') in ['list', 'interactive_list']
            if is_list:
                raw_items = current_node.get('data', {}).get('rows') or current_node.get('data', {}).get('items') or []
                options = [r.get('title') if isinstance(r, dict) else str(r) for r in raw_items]
            else:
                options = current_node.get('data', {}).get('buttons', [])

            matched_index = -1
            import re
            input_clean = incoming_text.strip().lower()
            input_words = re.sub(r'[^\w\s]', '', input_clean).strip()

            for i, opt_text in enumerate(options):
                opt_clean = opt_text.strip().lower()
                opt_words = re.sub(r'[^\w\s]', '', opt_clean).strip()

                # 0. Row ID match (e.g. Meta list_reply id)
                if is_list and i < len(raw_items) and isinstance(raw_items[i], dict):
                    r_id = (raw_items[i].get('id') or '').strip().lower()
                    if r_id and input_clean == r_id:
                        matched_index = i
                        break

                # 1. Exact match
                if input_clean == opt_clean:
                    matched_index = i
                    break
                # 2. Number index match (e.g., user types "1" for 1st option)
                if input_clean in [str(i + 1), f"#{i + 1}", f"option {i + 1}"]:
                    matched_index = i
                    break
                # 3. Clean word / substring match (ignoring emojis)
                if opt_words and input_words and (opt_words == input_words or input_words in opt_words or opt_words in input_words):
                    matched_index = i
                    break
            
            if matched_index != -1:
                prefix = "list" if is_list else "btn"
                valid_handles = [f"{prefix}-{matched_index}", f"btn-{matched_index}", f"list-{matched_index}"]
                next_edge = next((e for e in edges if e.get('source') == current_node_id and e.get('sourceHandle') in valid_handles), None)
                if next_edge:
                    current_node_id = next_edge.get('target')
                else:
                    session.is_active = False
                    session.save()
                    return None
            else:
                # Check if user clicked or typed Talk to AI
                ai_keywords = ['talk to ai', 'chat with ai', 'ask ai', 'ai assistant', 'ai chat']
                if any(ak in input_clean for ak in ai_keywords):
                    import time
                    session.variables = session.variables or {}
                    session.variables['ai_mode'] = True
                    session.variables['last_ai_time'] = time.time()
                    session.save()

                    biz_name = getattr(session.client, 'business_name', 'our team')
                    ai_welcome = (
                        f"🤖 *AI Assistant Connected!*\n\n"
                        f"I am your 24/7 AI Assistant for *{biz_name}*.\n\n"
                        f"Ask me anything about our products, pricing, policies, or services!"
                    )
                    return [{
                        "type": "text",
                        "body": ai_welcome
                    }]

                # Text did not match button options: end stuck session & allow new workflow triggers
                session.is_active = False
                session.save()
                return None

        # 2. Sequential node traversal loop
        while True:
            current_node = next((n for n in nodes if n.get('id') == current_node_id), None)
            if not current_node:
                # Invalid node, end session
                session.is_active = False
                session.save()
                break

            node_type = current_node.get('type')

            if node_type == 'trigger':
                next_edge = next((e for e in edges if e.get('source') == current_node_id), None)
                if next_edge:
                    current_node_id = next_edge.get('target')
                    continue
                else:
                    session.is_active = False
                    session.save()
                    break

            elif node_type == 'condition':
                condition_text = current_node.get('data', {}).get('condition', '')
                result = WorkflowEngine._evaluate_condition(contact, condition_text)
                source_handle = 'true' if result else 'false'
                next_edge = next((e for e in edges if e.get('source') == current_node_id and e.get('sourceHandle') == source_handle), None)
                if next_edge:
                    current_node_id = next_edge.get('target')
                    continue
                else:
                    session.is_active = False
                    session.save()
                    break

            elif node_type == 'handoff':
                messages_to_send.append(WorkflowEngine._format_node_response(current_node))
                
                # Pause bot for this contact
                if contact:
                    contact.bot_paused = True
                    contact.save()
                
                # End workflow session
                session.is_active = False
                session.save()
                break

            elif node_type in ['google_meet', 'calendar']:
                data = current_node.get('data', {})
                title = data.get('title', 'Scheduled Meeting')
                duration = int(data.get('duration', 30))
                attendee_email = getattr(contact, 'email', None) if contact else None

                booking_res = None
                try:
                    from .google_calendar_service import create_calendar_event
                    booking_res = create_calendar_event(
                        client_obj=session.client,
                        summary=f"{title} - {session.phone_number}",
                        description=f"Meeting booked automatically via Chat Workflow for {session.phone_number}",
                        duration_minutes=duration,
                        attendee_email=attendee_email
                    )
                except Exception as _gerr:
                    print(f"Error creating Google Meet event in workflow: {_gerr}")

                if booking_res and booking_res.get('success'):
                    meet_url = booking_res.get('meetLink') or booking_res.get('htmlLink', '')
                    msg_body = f"📅 *Meeting Scheduled Successfully!*\n\n📹 *Google Meet Link*: {meet_url}\n⏱️ *Duration*: {duration} Mins\n⏰ *Calendar Reminder Set!*"
                else:
                    msg_body = f"📅 *Meeting Scheduled*: {title}\n⏱️ *Duration*: {duration} Mins"

                messages_to_send.append({
                    "type": "text",
                    "body": msg_body
                })

                session.current_node_id = current_node_id
                session.save()

                next_edge = next((e for e in edges if e.get('source') == current_node_id), None)
                if next_edge:
                    current_node_id = next_edge.get('target')
                    continue
                else:
                    session.is_active = False
                    session.save()
                    break

            elif node_type in ['plain', 'default', 'image', 'video', 'buttons', 'list', 'interactive_list', 'catalog_product', 'ai_chat']:
                if node_type == 'ai_chat':
                    import time
                    session.variables = session.variables or {}
                    session.variables['ai_mode'] = True
                    session.variables['last_ai_time'] = time.time()
                    session.current_node_id = current_node_id
                    session.save()

                    messages_to_send.append(WorkflowEngine._format_node_response(current_node, client=session.client))
                    break

                messages_to_send.append(WorkflowEngine._format_node_response(current_node, client=session.client))
                
                # Save the active node in session
                session.current_node_id = current_node_id
                session.save()

                if node_type in ['buttons', 'list', 'interactive_list', 'catalog_product']:
                    # Stop traversing: wait for user action / selection
                    break

                # For plain, image, video nodes: advance to next node
                next_edge = next((e for e in edges if e.get('source') == current_node_id), None)
                if next_edge:
                    current_node_id = next_edge.get('target')
                    continue
                else:
                    # End of path reached
                    session.is_active = False
                    session.save()
                    break
            else:
                # Unknown node type
                session.is_active = False
                session.save()
                break

        return messages_to_send if messages_to_send else None

    @staticmethod
    def _evaluate_condition(contact, condition_text):
        if not contact or not condition_text:
            return False
        
        condition_clean = condition_text.strip().lower()
        
        # 1. Check for Tag condition: "tag = <tagname>"
        if 'tag' in condition_clean and '=' in condition_clean:
            parts = condition_clean.split('=', 1)
            tag_target = parts[1].strip()
            if not contact.tags:
                return False
            contact_tags_lower = [t.lower().strip() for t in contact.tags if isinstance(t, str)]
            return tag_target in contact_tags_lower
            
        # 2. Check for Stage condition: "stage = <stagename>"
        if 'stage' in condition_clean and '=' in condition_clean:
            parts = condition_clean.split('=', 1)
            stage_target = parts[1].strip()
            if not contact.stage:
                return False
            stage_clean = contact.stage.lower().strip()
            return stage_target in stage_clean or stage_clean in stage_target
            
        # Fallback: exact tag check
        if contact.tags:
            contact_tags_lower = [t.lower().strip() for t in contact.tags if isinstance(t, str)]
            if condition_clean in contact_tags_lower:
                return True
                
        return False

    @staticmethod
    def _format_node_response(node, client=None):
        node_type = node.get('type')
        data = node.get('data', {})
        
        node_type_clean = node_type
        if node_type_clean in ['plain', 'default', 'handoff']:
            node_type_clean = 'text'

        res = {
            "type": node_type_clean,
            "body": data.get('message', ''),
        }
        
        if node_type == 'buttons':
            res["buttons"] = data.get('buttons', [])
        elif node_type in ['list', 'interactive_list']:
            raw_rows = data.get('rows') or data.get('items') or []
            res["type"] = "list"
            res["button_text"] = data.get('buttonText') or data.get('button_text') or "Select Option"
            res["rows"] = raw_rows
            res["items"] = raw_rows
            res["list_items"] = raw_rows
        elif node_type in ['image', 'video']:
            res["media_url"] = data.get('mediaUrl')
            res["media_type"] = node_type
        elif node_type == 'catalog_product':
            product_id = data.get('productId')
            product = None
            if product_id:
                try:
                    from ..repositories.product_repository import ProductRepository
                    from bson import ObjectId
                    product = ProductRepository.filter_products(id=product_id).first()
                    if not product:
                        try:
                            product = ProductRepository.filter_products(id=ObjectId(str(product_id))).first()
                        except Exception:
                            pass
                except Exception:
                    pass

            name = (product.name if product else None) or data.get('productName') or 'Catalog Product'
            price = (product.price if product else None) or data.get('productPrice') or ''
            desc = (product.description if product else None) or data.get('description') or ''
            media_url = (product.image_url if product else None) or data.get('mediaUrl') or None
            cta_text = data.get('ctaText') or (getattr(product, 'cta_text', None) if product else None) or 'View Product'

            # Upgrade media_url to https if external
            if media_url and isinstance(media_url, str):
                media_url = media_url.strip()
                if media_url.startswith('http://') and not ('127.0.0.1' in media_url or 'localhost' in media_url):
                    media_url = 'https://' + media_url[7:]

            body_lines = [f"🛍️ *{name}*"]
            if price:
                curr_code = getattr(product, 'currency', 'INR') if product else 'INR'
                sym = {'INR': '₹', 'USD': '$', 'EUR': '€', 'GBP': '£', 'AED': 'AED '}.get((curr_code or '').upper(), f"{curr_code} ")
                body_lines.append(f"💰 *Price*: {sym}{price}")
            if desc:
                body_lines.append(f"_{desc}_")

            import os
            base_url = os.getenv('BACKEND_URL') or os.getenv('FRONTEND_URL') or 'https://uwoconnect.aisa24.com'
            base_url = base_url.rstrip('/')
            prod_id_str = str(product.id) if product else (str(product_id) if product_id else None)
            if prod_id_str:
                body_lines.append(f"\n🔗 [{cta_text}]: {base_url}/api/products/{prod_id_str}/redirect_link/")

            body_lines.append("\n👉 Click a button below or reply to order!")

            res["type"] = "interactive"
            res["body"] = "\n".join(body_lines)
            res["media_url"] = media_url
            res["media_type"] = "image"
            res["buttons"] = [cta_text[:20], "🛒 Buy Now"]
        elif node_type == 'ai_chat':
            greeting = data.get('message') or "Hello! How can I assist you today?"
            res["type"] = "text"
            res["body"] = greeting
            
        return res
