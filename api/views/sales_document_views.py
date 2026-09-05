import secrets
from rest_framework import viewsets, status, permissions
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.decorators import action
from django.db import transaction
from django.db.models import Q, Sum, Avg, Count
from django.http import HttpResponse
from django.utils import timezone
from django.shortcuts import get_object_or_404
from decimal import Decimal
import logging

from ..models import (
    Client, User, Contact, Product,
    SalesDocumentTemplate, SalesDocument, SalesDocumentItem, SalesDocumentActivity
)
from ..serializers import (
    SalesDocumentTemplateSerializer, SalesDocumentSerializer,
    SalesDocumentItemSerializer, SalesDocumentActivitySerializer
)
from ..services.pdf_service import SalesDocumentPDFService
from ..services.notification_service import SalesDocumentNotificationService

logger = logging.getLogger(__name__)

class SalesDocumentViewSet(viewsets.ModelViewSet):
    """
    API viewset managing Quotations, Proposals, and Invoices for authenticated clients.
    """
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SalesDocumentSerializer

    def get_queryset(self):
        client = getattr(self.request.user, 'client', None)
        if not client:
            return SalesDocument.objects.none()
        
        qs = SalesDocument.objects.filter(client=client)
        
        # Filter by document type
        doc_type = self.request.query_params.get('document_type')
        if doc_type:
            qs = qs.filter(document_type=doc_type)

        # Filters
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        search = self.request.query_params.get('search')
        if search:
            qs = qs.filter(
                Q(document_number__icontains=search) |
                Q(customer_name__icontains=search) |
                Q(customer_company__icontains=search) |
                Q(customer_email__icontains=search)
            )

        salesperson = self.request.query_params.get('salesperson')
        if salesperson:
            qs = qs.filter(salesperson_id=salesperson)

        return qs

    @staticmethod
    def _generate_next_document_number(client, doc_type):
        prefix = 'QTN' if doc_type == 'QUOTATION' else 'PRP' if doc_type == 'PROPOSAL' else 'INV'
        year = timezone.now().year
        prefix_pattern = f"UWO-{prefix}-{year}-"
        
        existing_doc_numbers = SalesDocument.objects.filter(
            client=client,
            document_type=doc_type,
            document_number__startswith=prefix_pattern
        ).values_list('document_number', flat=True)
        
        max_num = 0
        for d_num in existing_doc_numbers:
            try:
                num_part = int(str(d_num).split('-')[-1])
                if num_part > max_num:
                    max_num = num_part
            except (ValueError, IndexError):
                pass
        
        next_num = max_num + 1
        while SalesDocument.objects.filter(
            client=client,
            document_number=f"UWO-{prefix}-{year}-{next_num:05d}",
            version=1
        ).exists():
            next_num += 1
            
        return f"UWO-{prefix}-{year}-{next_num:05d}"

    def perform_create(self, serializer):
        user = self.request.user
        client = getattr(user, 'client', None)
        if not client:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'client': 'No associated workspace client found for user account.'})
        
        # Determine prefix and collision-safe auto-incrementing serial number
        doc_type = self.request.data.get('document_type', 'QUOTATION')
        doc_number = self._generate_next_document_number(client, doc_type)
        
        # Secure URL token
        secure_token = secrets.token_urlsafe(32)
        
        # Build document company_details snapshot
        company_details_payload = self.request.data.get('company_details') or {}
        company_details_snapshot = {
            'business_name': company_details_payload.get('business_name') or client.business_name,
            'company_logo_url': company_details_payload.get('company_logo_url') or getattr(client, 'company_logo_url', '') or '',
            'phone_number': company_details_payload.get('phone_number') or getattr(client, 'phone_number', '') or '',
            'email': company_details_payload.get('email') or (user.email if user.email else ''),
            'address': company_details_payload.get('address') or getattr(client, 'address', '') or '',
            'tax_id_gstin': company_details_payload.get('tax_id_gstin') or getattr(client, 'tax_id_gstin', '') or '',
            'invoice_prefix': company_details_payload.get('invoice_prefix') or getattr(client, 'invoice_prefix', 'INV') or 'INV',
            'website': company_details_payload.get('website') or getattr(client, 'website', '') or '',
        }

        doc_obj = serializer.save(
            client=client,
            created_by=user,
            document_number=doc_number,
            secure_token=secure_token,
            company_details=company_details_snapshot,
            status='DRAFT'
        )
        
        # Save line items
        items_data = self.request.data.get('items', [])
        self._save_line_items(doc_obj, items_data)
        
        # Audit Log
        SalesDocumentActivity.objects.create(
            document=doc_obj,
            activity_type='CREATED',
            details=f"Draft {doc_type.lower()} created automatically.",
            performed_by=user,
            performed_by_name=user.username
        )

    def perform_update(self, serializer):
        user = self.request.user
        doc_obj = self.get_object()
        
        if doc_obj.status == 'ACCEPTED' and doc_obj.document_type != 'INVOICE':
            # Create a revised version if already accepted
            with transaction.atomic():
                next_version = doc_obj.version + 1
                secure_token = secrets.token_urlsafe(32)
                
                # Clone document
                revised_doc = SalesDocument.objects.create(
                    client=doc_obj.client,
                    document_type=doc_obj.document_type,
                    document_number=doc_obj.document_number,
                    customer=doc_obj.customer,
                    customer_name=doc_obj.customer_name,
                    customer_company=doc_obj.customer_company,
                    customer_email=doc_obj.customer_email,
                    customer_phone=doc_obj.customer_phone,
                    billing_address=doc_obj.billing_address,
                    shipping_address=doc_obj.shipping_address,
                    tax_number=doc_obj.tax_number,
                    created_by=user,
                    salesperson=doc_obj.salesperson,
                    status='DRAFT',
                    currency=doc_obj.currency,
                    currency_symbol=doc_obj.currency_symbol,
                    exchange_rate=doc_obj.exchange_rate,
                    document_date=timezone.now().date(),
                    valid_until=timezone.now().date() + timezone.timedelta(days=15),
                    payment_terms=doc_obj.payment_terms,
                    reference_number=doc_obj.reference_number,
                    subtotal=doc_obj.subtotal,
                    discount_type=doc_obj.discount_type,
                    discount_value=doc_obj.discount_value,
                    discount_amount=doc_obj.discount_amount,
                    tax_amount=doc_obj.tax_amount,
                    additional_charges=doc_obj.additional_charges,
                    grand_total=doc_obj.grand_total,
                    customer_notes=doc_obj.customer_notes,
                    internal_notes=doc_obj.internal_notes,
                    terms_conditions=doc_obj.terms_conditions,
                    secure_token=secure_token,
                    version=next_version,
                    proposal_sections=doc_obj.proposal_sections,
                    proposal_template=doc_obj.proposal_template
                )
                
                # Clone items
                for item in doc_obj.items.all():
                    SalesDocumentItem.objects.create(
                        document=revised_doc,
                        product=item.product,
                        name=item.name,
                        description=item.description,
                        sku=item.sku,
                        quantity=item.quantity,
                        unit=item.unit,
                        unit_price=item.unit_price,
                        discount_type=item.discount_type,
                        discount_value=item.discount_value,
                        tax_rate=item.tax_rate,
                        tax_amount=item.tax_amount,
                        line_total=item.line_total,
                        sort_order=item.sort_order
                    )
                
                SalesDocumentActivity.objects.create(
                    document=revised_doc,
                    activity_type='CREATED',
                    details=f"Revision v{next_version} created from v{doc_obj.version}.",
                    performed_by=user,
                    performed_by_name=user.username
                )
                
                # Serializer must return the new revised doc
                serializer.instance = revised_doc
                return

        # Regular update for non-accepted drafts
        doc_obj = serializer.save()
        items_data = self.request.data.get('items', [])
        if items_data:
            doc_obj.items.all().delete()
            self._save_line_items(doc_obj, items_data)
            
        SalesDocumentActivity.objects.create(
            document=doc_obj,
            activity_type='EDITED',
            details="Document details revised.",
            performed_by=user,
            performed_by_name=user.username
        )

    def _save_line_items(self, doc_obj, items_data):
        subtotal = Decimal('0.00')
        tax_total = Decimal('0.00')
        discount_total = Decimal('0.00')
        
        for idx, item in enumerate(items_data):
            qty = Decimal(str(item.get('quantity', 1)))
            price = Decimal(str(item.get('unit_price', 0)))
            disc_val = Decimal(str(item.get('discount_value', 0)))
            disc_type = item.get('discount_type', 'PERCENTAGE')
            tax_rate = Decimal(str(item.get('tax_rate', 0)))
            
            # Subtotal calculation
            base_total = qty * price
            
            # Item discount
            if disc_type == 'PERCENTAGE':
                item_discount = base_total * (disc_val / Decimal('100.00'))
            else:
                item_discount = disc_val
            
            taxable_amount = base_total - item_discount
            item_tax = taxable_amount * (tax_rate / Decimal('100.00'))
            line_total = taxable_amount + item_tax
            
            subtotal += base_total
            discount_total += item_discount
            tax_total += item_tax
            
            SalesDocumentItem.objects.create(
                document=doc_obj,
                product_id=item.get('product'),
                name=item.get('name', 'Line Item'),
                description=item.get('description', ''),
                sku=item.get('sku'),
                quantity=qty,
                unit=item.get('unit', 'pcs'),
                unit_price=price,
                discount_type=disc_type,
                discount_value=disc_val,
                tax_rate=tax_rate,
                tax_amount=item_tax,
                line_total=line_total,
                sort_order=idx
            )
            
        # Update grand aggregates in DB (strictly verified on backend)
        doc_obj.subtotal = subtotal
        doc_obj.discount_amount = discount_total
        doc_obj.tax_amount = tax_total
        doc_obj.grand_total = (subtotal - discount_total) + tax_total + Decimal(str(doc_obj.additional_charges))
        doc_obj.save()

    @action(detail=True, methods=['post'])
    def send(self, request, pk=None):
        doc = self.get_object()
        channel = request.data.get('channel', 'EMAIL') # EMAIL, WHATSAPP
        recipient = request.data.get('recipient') or request.data.get('email') or doc.customer_email
        
        # Build secure link using central env/host resolution
        import os
        env_frontend_url = os.getenv('NEXT_PUBLIC_APP_URL') or os.getenv('FRONTEND_URL') or os.getenv('PUBLIC_APP_URL')
        request_frontend = request.data.get('frontend_url')
        
        if env_frontend_url:
            frontend_url = env_frontend_url.rstrip('/')
        elif request_frontend:
            frontend_url = request_frontend.rstrip('/')
        else:
            frontend_url = 'https://uwoconnectforrf-743928421487.asia-south1.run.app'
            
        doc_type = (doc.document_type or 'PROPOSAL').upper()
        if doc_type == 'PROPOSAL':
            segment = 'proposal'
        elif doc_type in ['QUOTATION', 'QUOTE']:
            segment = 'quotation'
        elif doc_type == 'INVOICE':
            segment = 'invoice'
        else:
            segment = 'quote'
            
        secure_link = f"{frontend_url}/public/{segment}/{doc.secure_token}"
        company_name = doc.client.business_name if (doc.client and doc.client.business_name) else "UWOConnect"
        customer_name = doc.customer_name or "Valued Customer"
        
        if doc_type == 'PROPOSAL':
            subject = f"{company_name} - Proposal #{doc.document_number}"
            message_body = (
                f"Dear {customer_name},\n\n"
                f"Please find your proposal #{doc.document_number} from {company_name} for your review.\n\n"
                f"Total Amount: {doc.currency_symbol}{doc.grand_total}\n"
                f"Validity: {doc.valid_until or 'N/A'}\n\n"
                f"View, download, accept, or reject the proposal:\n"
                f"{secure_link}\n\n"
                f"Regards,\n"
                f"{company_name}"
            )
        elif doc_type in ['QUOTATION', 'QUOTE']:
            subject = f"{company_name} - Quotation #{doc.document_number}"
            message_body = (
                f"Dear {customer_name},\n\n"
                f"Please find quotation #{doc.document_number} from {company_name}.\n\n"
                f"Total Amount: {doc.currency_symbol}{doc.grand_total}\n\n"
                f"View and download the quotation:\n"
                f"{secure_link}\n\n"
                f"Regards,\n"
                f"{company_name}"
            )
        elif doc_type == 'INVOICE':
            subject = f"{company_name} - Invoice #{doc.document_number}"
            status_display = doc.status.title() if hasattr(doc, 'status') else 'Unpaid'
            message_body = (
                f"Dear {customer_name},\n\n"
                f"Your invoice #{doc.document_number} from {company_name} is ready.\n\n"
                f"Amount: {doc.currency_symbol}{doc.grand_total}\n"
                f"Payment Status: {status_display}\n\n"
                f"View and download your invoice:\n"
                f"{secure_link}\n\n"
                f"Regards,\n"
                f"{company_name}"
            )
        else:
            subject = f"{company_name} - Document #{doc.document_number}"
            message_body = (
                f"Dear {customer_name},\n\n"
                f"Please find your document #{doc.document_number} from {company_name}.\n\n"
                f"View and download your document:\n"
                f"{secure_link}\n\n"
                f"Regards,\n"
                f"{company_name}"
            )
        
        try:
            if channel == 'EMAIL':
                if not recipient:
                    return Response({'error': 'Recipient email address is required.'}, status=400)
                SalesDocumentNotificationService.send_document_email(doc, recipient, subject, message_body)
            elif channel == 'WHATSAPP':
                phone = request.data.get('phone') or request.data.get('recipient') or doc.customer_phone
                if not phone:
                    return Response({'error': 'Recipient phone number is required.'}, status=400)
                SalesDocumentNotificationService.send_document_whatsapp(doc, phone, message_body)
                
            # Update Status
            if doc.status == 'DRAFT':
                doc.status = 'SENT'
                doc.save()
                
            SalesDocumentActivity.objects.create(
                document=doc,
                activity_type='SENT',
                details=f"Document dispatched via {channel.title()} to {recipient or phone}.",
                performed_by=request.user,
                performed_by_name=request.user.username
            )
            return Response({'detail': f'Document successfully sent via {channel.title()}'})
        except Exception as e:
            return Response({'error': str(e)}, status=500)

    @action(detail=True, methods=['post'])
    def duplicate(self, request, pk=None):
        doc = self.get_object()
        user = request.user
        
        # New serial
        new_num = self._generate_next_document_number(doc.client, doc.document_type)
        secure_token = secrets.token_urlsafe(32)
        
        with transaction.atomic():
            new_doc = SalesDocument.objects.create(
                client=doc.client,
                document_type=doc.document_type,
                document_number=new_num,
                customer=doc.customer,
                customer_name=doc.customer_name,
                customer_company=doc.customer_company,
                customer_email=doc.customer_email,
                customer_phone=doc.customer_phone,
                billing_address=doc.billing_address,
                shipping_address=doc.shipping_address,
                tax_number=doc.tax_number,
                created_by=user,
                salesperson=doc.salesperson,
                status='DRAFT',
                currency=doc.currency,
                currency_symbol=doc.currency_symbol,
                exchange_rate=doc.exchange_rate,
                document_date=timezone.now().date(),
                valid_until=timezone.now().date() + timezone.timedelta(days=15),
                payment_terms=doc.payment_terms,
                reference_number=doc.reference_number,
                subtotal=doc.subtotal,
                discount_type=doc.discount_type,
                discount_value=doc.discount_value,
                discount_amount=doc.discount_amount,
                tax_amount=doc.tax_amount,
                additional_charges=doc.additional_charges,
                grand_total=doc.grand_total,
                customer_notes=doc.customer_notes,
                terms_conditions=doc.terms_conditions,
                secure_token=secure_token,
                version=1,
                proposal_sections=doc.proposal_sections,
                proposal_template=doc.proposal_template
            )
            
            for item in doc.items.all():
                SalesDocumentItem.objects.create(
                    document=new_doc,
                    product=item.product,
                    name=item.name,
                    description=item.description,
                    sku=item.sku,
                    quantity=item.quantity,
                    unit=item.unit,
                    unit_price=item.unit_price,
                    discount_type=item.discount_type,
                    discount_value=item.discount_value,
                    tax_rate=item.tax_rate,
                    tax_amount=item.tax_amount,
                    line_total=item.line_total,
                    sort_order=item.sort_order
                )
                
            SalesDocumentActivity.objects.create(
                document=new_doc,
                activity_type='CREATED',
                details=f"Draft duplicated from {doc.document_number}.",
                performed_by=user,
                performed_by_name=user.username
            )
            
        return Response(SalesDocumentSerializer(new_doc).data, status=201)

    @action(detail=True, methods=['post'])
    def convert_invoice(self, request, pk=None):
        doc = self.get_object()
        
        # Validation checks
        if doc.document_type != 'QUOTATION':
            return Response({'error': 'Only Quotations can be converted to invoices.'}, status=400)
            
        # Check if already converted to prevent duplicate invoice runs
        already_exists = SalesDocument.objects.filter(source_document=doc, document_type='INVOICE').first()
        if already_exists:
            return Response({
                'error': 'Invoice already created.',
                'invoice_id': str(already_exists.id),
                'invoice_number': already_exists.document_number
            }, status=400)
            
        user = request.user
        inv_num = self._generate_next_document_number(doc.client, 'INVOICE')
        secure_token = secrets.token_urlsafe(32)
        
        with transaction.atomic():
            invoice = SalesDocument.objects.create(
                client=doc.client,
                document_type='INVOICE',
                document_number=inv_num,
                customer=doc.customer,
                customer_name=doc.customer_name,
                customer_company=doc.customer_company,
                customer_email=doc.customer_email,
                customer_phone=doc.customer_phone,
                billing_address=doc.billing_address,
                shipping_address=doc.shipping_address,
                tax_number=doc.tax_number,
                created_by=user,
                salesperson=doc.salesperson,
                status='DRAFT', # Converted invoice starts as draft
                currency=doc.currency,
                currency_symbol=doc.currency_symbol,
                exchange_rate=doc.exchange_rate,
                document_date=timezone.now().date(),
                valid_until=timezone.now().date() + timezone.timedelta(days=30),
                payment_terms=doc.payment_terms,
                reference_number=doc.document_number,
                subtotal=doc.subtotal,
                discount_type=doc.discount_type,
                discount_value=doc.discount_value,
                discount_amount=doc.discount_amount,
                tax_amount=doc.tax_amount,
                additional_charges=doc.additional_charges,
                grand_total=doc.grand_total,
                customer_notes=doc.customer_notes,
                terms_conditions=doc.terms_conditions,
                secure_token=secure_token,
                version=1,
                source_document=doc
            )
            
            for item in doc.items.all():
                SalesDocumentItem.objects.create(
                    document=invoice,
                    product=item.product,
                    name=item.name,
                    description=item.description,
                    sku=item.sku,
                    quantity=item.quantity,
                    unit=item.unit,
                    unit_price=item.unit_price,
                    discount_type=item.discount_type,
                    discount_value=item.discount_value,
                    tax_rate=item.tax_rate,
                    tax_amount=item.tax_amount,
                    line_total=item.line_total,
                    sort_order=item.sort_order
                )
                
            # Log activity on original quote
            SalesDocumentActivity.objects.create(
                document=doc,
                activity_type='CONVERTED',
                details=f"Quotation converted to Invoice {inv_num}.",
                performed_by=user,
                performed_by_name=user.username
            )
            
            # Update status
            doc.status = 'CONVERTED'
            doc.save()
            
            # Log on invoice
            SalesDocumentActivity.objects.create(
                document=invoice,
                activity_type='CREATED',
                details=f"Invoice created from quotation {doc.document_number}.",
                performed_by=user,
                performed_by_name=user.username
            )
            
        return Response(SalesDocumentSerializer(invoice).data, status=201)

    @action(detail=True, methods=['get'])
    def pdf(self, request, pk=None):
        doc_obj = self.get_object()
        try:
            pdf_buffer = SalesDocumentPDFService.generate_pdf(doc_obj)
            response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{doc_obj.document_number}.pdf"'
            
            # Add viewed log
            SalesDocumentActivity.objects.create(
                document=doc_obj,
                activity_type='DOWNLOADED',
                details="PDF downloaded/viewed by internal staff.",
                performed_by=request.user,
                performed_by_name=request.user.username
            )
            return response
        except Exception as e:
            return Response({'error': f"Failed to generate PDF: {str(e)}"}, status=500)

    @action(detail=True, methods=['get'])
    def activity(self, request, pk=None):
        doc = self.get_object()
        activities = doc.activities.all()
        return Response(SalesDocumentActivitySerializer(activities, many=True).data)

    @action(detail=True, methods=['get'])
    def versions(self, request, pk=None):
        doc = self.get_object()
        versions = SalesDocument.objects.filter(client=doc.client, document_number=doc.document_number).order_by('-version')
        return Response(SalesDocumentSerializer(versions, many=True).data)


class SalesDocumentTemplateViewSet(viewsets.ModelViewSet):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SalesDocumentTemplateSerializer

    def get_queryset(self):
        client = getattr(self.request.user, 'client', None)
        if not client:
            return SalesDocumentTemplate.objects.none()
        return SalesDocumentTemplate.objects.filter(client=client)

    def perform_create(self, serializer):
        serializer.save(client=self.request.user.client)


# ── CUSTOMER SECURE PORTAL CONTROLLERS ───────────────────────────────────────

class PublicSalesDocumentView(APIView):
    """
    Publicly accessible views for reviewing quotes/proposals using secure tokens.
    No login credentials required for customers.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        doc = get_object_or_404(SalesDocument, secure_token=token)
        
        # Log public viewed activity
        meta_ip = request.META.get('REMOTE_ADDR', '')
        meta_ua = request.META.get('HTTP_USER_AGENT', '')
        
        SalesDocumentActivity.objects.create(
            document=doc,
            activity_type='VIEWED',
            details=f"Document opened via secure link by customer. IP: {meta_ip}",
            performed_by_name="Customer",
            ip_address=meta_ip or None,
            user_agent=meta_ua or None
        )
        
        # Check expired and mark automatically
        if doc.status == 'SENT' and doc.valid_until and doc.valid_until < timezone.now().date():
            doc.status = 'EXPIRED'
            doc.save()
            
        return Response(SalesDocumentSerializer(doc).data)


class PublicSalesDocumentAcceptView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, token):
        doc = get_object_or_404(SalesDocument, secure_token=token)
        
        if doc.status in ['ACCEPTED', 'CONVERTED']:
            return Response({'error': 'This document has already been accepted.'}, status=400)
        if doc.status == 'REJECTED':
            return Response({'error': 'This document has already been rejected.'}, status=400)
        if doc.valid_until and doc.valid_until < timezone.now().date():
            return Response({'error': 'This document validity has expired.'}, status=400)
            
        name = request.data.get('name')
        email = request.data.get('email')
        comment = request.data.get('comment', '')
        
        if not name or not email:
            return Response({'error': 'Name and Email are required to accept the document.'}, status=400)
            
        meta_ip = request.META.get('REMOTE_ADDR', '')
        meta_ua = request.META.get('HTTP_USER_AGENT', '')
        
        with transaction.atomic():
            doc.status = 'ACCEPTED'
            doc.accepted_at = timezone.now()
            doc.accepted_by_name = name
            doc.accepted_by_email = email
            doc.accepted_comment = comment
            doc.accepted_ip = meta_ip or None
            doc.accepted_user_agent = meta_ua or None
            doc.save()
            
            SalesDocumentActivity.objects.create(
                document=doc,
                activity_type='ACCEPTED',
                details=f"Customer accepted document. Comment: {comment}",
                performed_by_name=name,
                ip_address=meta_ip or None,
                user_agent=meta_ua or None
            )
            
        return Response(SalesDocumentSerializer(doc).data)


class PublicSalesDocumentRejectView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request, token):
        doc = get_object_or_404(SalesDocument, secure_token=token)
        
        if doc.status in ['ACCEPTED', 'CONVERTED']:
            return Response({'error': 'This document has already been accepted and cannot be rejected.'}, status=400)
            
        reason = request.data.get('reason', 'Pricing')
        comment = request.data.get('comment', '')
        
        meta_ip = request.META.get('REMOTE_ADDR', '')
        meta_ua = request.META.get('HTTP_USER_AGENT', '')
        
        with transaction.atomic():
            doc.status = 'REJECTED'
            doc.rejected_at = timezone.now()
            doc.rejection_reason = reason
            doc.rejection_comment = comment
            doc.save()
            
            SalesDocumentActivity.objects.create(
                document=doc,
                activity_type='REJECTED',
                details=f"Customer rejected document. Reason: {reason}. Comment: {comment}",
                performed_by_name="Customer",
                ip_address=meta_ip or None,
                user_agent=meta_ua or None
            )
            
        return Response(SalesDocumentSerializer(doc).data)


class PublicSalesDocumentPDFView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request, token):
        doc = get_object_or_404(SalesDocument, secure_token=token)
        try:
            pdf_buffer = SalesDocumentPDFService.generate_pdf(doc)
            response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{doc.document_number}.pdf"'
            
            meta_ip = request.META.get('REMOTE_ADDR', '')
            meta_ua = request.META.get('HTTP_USER_AGENT', '')
            
            SalesDocumentActivity.objects.create(
                document=doc,
                activity_type='DOWNLOADED',
                details=f"PDF downloaded by customer. IP: {meta_ip}",
                performed_by_name="Customer",
                ip_address=meta_ip or None,
                user_agent=meta_ua or None
            )
            return response
        except Exception as e:
            return Response({'error': f"Failed to generate PDF: {str(e)}"}, status=500)


# ── SALES ANALYTICS CONTROLLER ────────────────────────────────────────────────

class SalesAnalyticsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        client = getattr(request.user, 'client', None)
        if not client:
            client_id = request.headers.get('X-Client-ID') or request.query_params.get('client_id')
            if client_id:
                client = Client.objects.filter(id=client_id).first()
            if not client:
                client = Client.objects.filter(users=request.user).first() or Client.objects.first()

        if not client:
            return Response({'error': 'Client workspace not found.'}, status=400)
            
        docs = SalesDocument.objects.filter(client=client)
        
        # Calculate key metrics
        totals = docs.aggregate(
            total_count=Count('id'),
            total_value=Sum('grand_total'),
            accepted_value=Sum('grand_total', filter=Q(status='ACCEPTED') | Q(status='CONVERTED')),
            rejected_value=Sum('grand_total', filter=Q(status='REJECTED')),
            pending_value=Sum('grand_total', filter=Q(status='SENT') | Q(status='VIEWED')),
            avg_value=Avg('grand_total')
        )
        
        # Status breakdown
        status_counts = docs.values('status').annotate(count=Count('id'), value=Sum('grand_total'))
        
        # Type breakdown
        type_counts = docs.values('document_type').annotate(count=Count('id'), value=Sum('grand_total'))
        
        # Monthly pipeline trends (past 6 months)
        trends = []
        for i in range(5, -1, -1):
            date_filter = timezone.now() - timezone.timedelta(days=i*30)
            month_num = date_filter.month
            year_num = date_filter.year
            month_label = date_filter.strftime('%b %Y')
            
            month_val = docs.filter(
                created_at__month=month_num,
                created_at__year=year_num
            ).aggregate(val=Sum('grand_total'))['val'] or Decimal('0.00')
            
            trends.append({
                'month': month_label,
                'value': month_val
            })
            
        # Calc conversion rate
        total_finished = docs.filter(status__in=['ACCEPTED', 'CONVERTED', 'REJECTED']).count()
        accepted_count = docs.filter(status__in=['ACCEPTED', 'CONVERTED']).count()
        conversion_rate = round((accepted_count / total_finished * 100), 2) if total_finished > 0 else 0.0

        return Response({
            'metrics': {
                'total_count': totals['total_count'] or 0,
                'total_value': totals['total_value'] or 0.00,
                'accepted_value': totals['accepted_value'] or 0.00,
                'rejected_value': totals['rejected_value'] or 0.00,
                'pending_value': totals['pending_value'] or 0.00,
                'average_value': totals['avg_value'] or 0.00,
                'conversion_rate': conversion_rate
            },
            'status_breakdown': status_counts,
            'type_breakdown': type_counts,
            'trends': trends
        })
