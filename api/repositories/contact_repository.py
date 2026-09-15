from ..models import Contact

class ContactRepository:
    @staticmethod
    def get_contact(id=None, phone_number=None, client=None):
        if id: return Contact.objects.filter(id=id, client=client).first() if client else Contact.objects.filter(id=id).first()
        if phone_number and client: return Contact.objects.filter(phone_number=phone_number, client=client).first()
        return None

    @staticmethod
    def filter_contacts(**kwargs):
        return Contact.objects.filter(**kwargs)
        
    @staticmethod
    def create_contact(**kwargs):
        return Contact.objects.create(**kwargs)

    @staticmethod
    def get_contact_or_create(client, platform_id, defaults=None):
        from django.db.models import Q
        clean_num = str(platform_id or '').replace('+', '').strip()
        contact = None
        if clean_num:
            contact = Contact.objects.filter(
                Q(client=client) & (Q(platform_id=platform_id) | Q(phone_number=clean_num))
            ).first()
        else:
            contact = Contact.objects.filter(client=client, platform_id=platform_id).first()

        if contact:
            if platform_id and (not contact.platform_id or str(contact.platform_id).startswith('contact_')):
                contact.platform_id = platform_id
                contact.save(update_fields=['platform_id'])
            return contact, False

        return Contact.objects.get_or_create(client=client, platform_id=platform_id, defaults=defaults or {})

    @staticmethod
    def get_all_contacts():
        return Contact.objects.all()

    @staticmethod
    def get_all():
        return Contact.objects.all()
