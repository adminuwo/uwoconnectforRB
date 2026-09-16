from ..models import WorkflowSession, Workflow
import json
from ..repositories.automation_repository import WorkflowSessionRepository
from ..repositories.workflow_repository import WorkflowRepository
from ..repositories.contact_repository import ContactRepository

class WorkflowEngine:
    @staticmethod
    def process_workflow(client, phone_number, incoming_text, channel='WHATSAPP'):
        """
        Process the incoming text to advance an active workflow session,
        or start a new workflow session if a trigger matches.
        Returns a list of dicts representing messages to send:
        [
          {
            "type": "text" | "buttons" | "image" | "video",
            "body": "...",
            "buttons": ["...", ...],
            "media_url": "..."
          }
        ]
        Or returns None if no workflow logic applies.
        """
        incoming_text_lower = incoming_text.lower().strip()
        channel_upper = channel.upper()

        # 1. Check for active session
        session = WorkflowSessionRepository.filter_workflowsessions(
            client=client, 
            phone_number=phone_number, 
            is_active=True
        ).first()

        if session:
            wf_channels = session.workflow.channels or []
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
            wf_channels = wf.channels or []
            if len(wf_channels) > 0 and channel_upper not in wf_channels:
                continue

            # Reserved commercial system commands that shouldn't be hijacked by generic wildcard (*) triggers
            reserved_commercial_keywords = {'catalog', 'product', 'products', 'browse products', 'shop', 'items', 'store', 'samaan', 'buy now', 'order now'}
            is_reserved_command = any(rc in incoming_text_lower for rc in reserved_commercial_keywords)

            # Catch-all trigger: any incoming message
            catch_all_tokens = {'*', 'all', 'any', 'anything'}
            if wf.trigger_type in ['ALL', 'ANY', 'ANYTHING']:
                if not is_reserved_command:
                    return WorkflowEngine._start_workflow(client, phone_number, wf)

            if isinstance(wf.trigger_value, list):
                trigger_keywords = [t.lower().strip() for t in wf.trigger_value if isinstance(t, str)]
                has_catch_all = any(t in catch_all_tokens for t in trigger_keywords)
                has_keyword_match = any(kw and (kw == incoming_text_lower or kw in incoming_text_lower) for kw in trigger_keywords if kw not in catch_all_tokens)
                if has_keyword_match or (has_catch_all and not is_reserved_command):
                    return WorkflowEngine._start_workflow(client, phone_number, wf)
            elif isinstance(wf.trigger_value, str):
                kw = wf.trigger_value.lower().strip()
                if kw in catch_all_tokens:
                    if not is_reserved_command:
                        return WorkflowEngine._start_workflow(client, phone_number, wf)
                elif kw and (kw == incoming_text_lower or kw in incoming_text_lower):
                    return WorkflowEngine._start_workflow(client, phone_number, wf)

        return None

    @staticmethod
    def _start_workflow(client, phone_number, workflow):
        # Parse the JSON steps
        steps = workflow.steps
        if not steps or 'nodes' not in steps:
            return None
            
        nodes = steps.get('nodes', [])

        # Find the trigger (start) node
        start_node = next((n for n in nodes if n.get('type') == 'trigger'), None)
        if not start_node:
            return None

        # Create session
        session = WorkflowSessionRepository.create_workflowsession(
            client=client,
            phone_number=phone_number,
            workflow=workflow,
            current_node_id=start_node.get('id')
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

        # 1. If currently at a buttons node, select branch based on incoming_text
        if current_node.get('type') == 'buttons':
            buttons = current_node.get('data', {}).get('buttons', [])
            matched_index = -1
            import re
            input_clean = incoming_text.strip().lower()
            input_words = re.sub(r'[^\w\s]', '', input_clean).strip()

            for i, btn_text in enumerate(buttons):
                btn_clean = btn_text.strip().lower()
                btn_words = re.sub(r'[^\w\s]', '', btn_clean).strip()

                # 1. Exact match
                if input_clean == btn_clean:
                    matched_index = i
                    break
                # 2. Number index match (e.g., user types "1" for 1st button)
                if input_clean in [str(i + 1), f"#{i + 1}", f"option {i + 1}"]:
                    matched_index = i
                    break
                # 3. Clean word / substring match (ignoring emojis)
                if btn_words and input_words and (btn_words == input_words or input_words in btn_words or btn_words in input_words):
                    matched_index = i
                    break
            
            if matched_index != -1:
                source_handle = f"btn-{matched_index}"
                next_edge = next((e for e in edges if e.get('source') == current_node_id and e.get('sourceHandle') == source_handle), None)
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
                        f"Ask me anything about our products, pricing, policies, or services!\n\n"
                        f"_(Note: Session will return to menu after 2 minutes of inactivity)_"
                    )
                    return [{
                        "type": "buttons",
                        "body": ai_welcome,
                        "buttons": ["📋 Main Menu", "👤 Talk to Human"]
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

            elif node_type in ['plain', 'default', 'image', 'video', 'buttons', 'catalog_product', 'ai_chat']:
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

                if node_type in ['buttons', 'catalog_product']:
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
        elif node_type in ['image', 'video']:
            res["media_url"] = data.get('mediaUrl')
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
                body_lines.append(f"💰 *Price*: ${price}")
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
            res["buttons"] = [cta_text[:20], "🛒 Buy Now"]
        elif node_type == 'ai_chat':
            biz_name = getattr(client, 'business_name', 'our team')
            greeting = data.get('message') or (
                f"🤖 *AI Assistant Connected!*\n\n"
                f"I am your 24/7 AI Assistant for *{biz_name}*.\n\n"
                f"Ask me anything about our products, pricing, policies, or services!\n\n"
                f"_(Note: Session will return to menu after 2 minutes of inactivity)_"
            )
            res["type"] = "interactive"
            res["body"] = greeting
            res["buttons"] = ["📋 Main Menu", "👤 Talk to Human"]
            
        return res
