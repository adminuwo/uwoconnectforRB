import re
import logging
from django.utils import timezone
from ..models import Contact, Product, Conversation

logger = logging.getLogger(__name__)

# Keywords that indicate Commercial / Pricing Intent (English & Hindi/Hinglish)
PRICING_KEYWORDS = [
    'price', 'pricing', 'cost', 'costs', 'how much', 'rate', 'rates', 
    'quote', 'quotation', 'discount', 'discounts', 'deal', 'offers',
    'charges', 'fee', 'fees', 'amount', 'buy now', 'order now', 'purchase',
    'payment', 'payment link', 'invoice', 'bill',
    # Hindi / Hinglish
    'kya price', 'price kya', 'rate kya', 'rate batao', 'kitne ka', 
    'kitne me', 'kitna lagega', 'kitna charge', 'kharidna hai', 'kharidna h', 
    'order karna hai', 'order krna h', 'discount milega', 'discount h kya', 
    'paise kitne', 'kitna rupya', 'kitna paisa'
]

# Keywords that indicate Product Catalog / Information Intent
PRODUCT_KEYWORDS = [
    'product', 'products', 'catalog', 'catalogue', 'brochure', 'specs', 
    'specification', 'features', 'details', 'item', 'items', 'service', 
    'services', 'samaan', 'list', 'models', 'samples'
]

class LeadQualificationService:
    @staticmethod
    def match_product_in_text(client, text_lower):
        """
        Check if text mentions any of the client's products from MongoDB.
        """
        if not client or not text_lower:
            return None
            
        try:
            products = Product.objects.filter(client=client, in_stock=True)
            for prod in products:
                prod_name = (prod.name or '').lower().strip()
                if prod_name and len(prod_name) >= 3 and prod_name in text_lower:
                    return prod
        except Exception as e:
            logger.warning(f"Error matching product in text: {e}")
        return None

    @staticmethod
    def evaluate_intent(incoming_text, matched_product=None):
        """
        Determine whether message expresses pricing intent, product inquiry, or general chat.
        """
        if not incoming_text:
            return None
            
        text_lower = incoming_text.lower().strip()
        
        # 1. Check Pricing / Commercial Intent (Top priority -> Hot Lead)
        for kw in PRICING_KEYWORDS:
            if re.search(r'\b' + re.escape(kw) + r'\b', text_lower) or kw in text_lower:
                return 'PRICING'

        # 2. If a specific product was mentioned, it is at least a Product Inquiry
        if matched_product:
            return 'PRODUCT'

        # 3. Check General Product / Catalog Inquiry Intent
        for kw in PRODUCT_KEYWORDS:
            if re.search(r'\b' + re.escape(kw) + r'\b', text_lower) or kw in text_lower:
                return 'PRODUCT'

        return None

    @classmethod
    def qualify_and_update_contact(cls, client, platform_id, incoming_text, sender_name=None):
        """
        Industrial Lead Qualification:
        Automatically upgrades contact stage (NEW -> QUALIFIED -> HOT_LEAD),
        adds qualification tags, and returns product & intent details.
        """
        if not client or not platform_id or not incoming_text:
            return None

        text_lower = incoming_text.lower().strip()
        matched_product = cls.match_product_in_text(client, text_lower)
        intent = cls.evaluate_intent(incoming_text, matched_product)

        if not intent:
            return None

        # Resolve or fetch contact
        contact = Contact.objects.filter(client=client, platform_id=platform_id).first()
        if not contact:
            formatted_num = str(platform_id).replace('+', '').strip()
            contact = Contact.objects.filter(client=client, phone_number__icontains=formatted_num).first()

        if not contact:
            contact = Contact.objects.create(
                client=client,
                platform_id=platform_id,
                phone_number=platform_id if platform_id.isdigit() else None,
                name=sender_name or 'Customer',
                stage='NEW',
                tags=[]
            )

        existing_tags = list(contact.tags or [])
        changed = False

        if intent == 'PRICING':
            # Hot Lead - Customer inquiring about price, cost, or ready to purchase
            if contact.stage not in ['WON', 'NEGOTIATION']:
                contact.stage = 'HOT_LEAD'
                changed = True

            new_tags = ['🔥 Hot Lead', 'Pricing Inquiry']
            if matched_product:
                new_tags.append(f"Product: {matched_product.name}")
                
            for t in new_tags:
                if t not in existing_tags:
                    existing_tags.append(t)
                    changed = True

        elif intent == 'PRODUCT':
            # Warm Lead - Customer inquiring about catalog or product details
            if contact.stage == 'NEW':
                contact.stage = 'QUALIFIED'
                changed = True

            new_tags = ['Product Inquiry']
            if matched_product:
                new_tags.append(f"Product: {matched_product.name}")
                
            for t in new_tags:
                if t not in existing_tags:
                    existing_tags.append(t)
                    changed = True

        if changed:
            contact.tags = existing_tags
            contact.updated_at = timezone.now()
            contact.save()

            # Also update Conversation record if present
            try:
                convo = Conversation.objects.filter(client=client, contact_platform_id=platform_id).first()
                if convo and convo.status not in ['WON', 'CLOSED']:
                    convo.status = contact.stage
                    convo.save()
            except Exception:
                pass

            # Real-time WebSocket event broadcast to CRM and Inbox
            try:
                from channels.layers import get_channel_layer
                from asgiref.sync import async_to_sync
                channel_layer = get_channel_layer()
                if channel_layer:
                    async_to_sync(channel_layer.group_send)(
                        f"inbox_{client.id}",
                        {
                            "type": "lead_qualified",
                            "contact_id": str(contact.id),
                            "stage": contact.stage,
                            "intent": intent,
                            "tags": contact.tags,
                            "matched_product": matched_product.name if matched_product else None
                        }
                    )
            except Exception as _ws_err:
                logger.debug(f"WS notification skip: {_ws_err}")

            logger.info(f"[Lead Qualification] Contact {contact.id} ({contact.name}) -> {contact.stage} (Intent: {intent})")

        return {
            'intent': intent,
            'stage': contact.stage,
            'matched_product': matched_product,
            'contact': contact
        }

    @classmethod
    def generate_pricing_reply(cls, client, matched_product):
        """
        Construct a helpful, professional pricing response with product details and buy links.
        """
        if not matched_product:
            return None

        currency_symbol = '₹' if getattr(matched_product, 'currency', 'INR') in ['INR', '₹'] else '$'
        price = matched_product.price
        discount_price = getattr(matched_product, 'discount_price', None)

        reply_parts = [
            f"🏷️ *{matched_product.name}*",
        ]

        if discount_price and discount_price < price:
            reply_parts.append(f"💰 *Special Offer Price*: {currency_symbol}{discount_price} (Regular: ~{currency_symbol}{price}~)")
        else:
            reply_parts.append(f"💰 *Price*: {currency_symbol}{price}")

        if matched_product.description:
            desc = matched_product.description.strip()
            if len(desc) > 200:
                desc = desc[:200] + '...'
            reply_parts.append(f"\n📝 {desc}")

        reply_parts.append("\n👉 Reply *BUY NOW* to purchase immediately or let us know if you need any custom quote!")

        return "\n".join(reply_parts)
