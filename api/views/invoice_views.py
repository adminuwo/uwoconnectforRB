import os
import logging
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django.http import HttpResponse, FileResponse, Http404
from django.conf import settings

from api.models import Invoice, Client, ProductPayment, Order, Contact
from api.serializers import InvoiceSerializer, InvoiceSettingsSerializer
from api.services.invoice_service import InvoiceService
from api.services.invoice_pdf_service import InvoicePDFService
from api.permissions.custom_permissions import IsApprovedUser

logger = logging.getLogger(__name__)

def get_tenant_client(request):
    if not request.user or not request.user.is_authenticated:
        return None
    if getattr(request.user, 'role', '') == 'ADMIN':
        client_id = request.query_params.get('client_id') or (request.data.get('client_id') if isinstance(getattr(request, 'data', None), dict) else None)
        if client_id:
            try:
                return Client.objects.get(id=client_id)
            except Exception:
                pass
        return getattr(request.user, 'client_workspace', None) or getattr(request.user, 'client', None)
    return getattr(request.user, 'client_workspace', None) or getattr(request.user, 'client', None)


class InvoiceViewSet(viewsets.ModelViewSet):
    """
    ViewSet for Invoice management, generation, and multi-currency PDF download.
    """
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if not client:
            return Invoice.objects.none()
        
        qs = Invoice.objects.filter(client=client)
        
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(payment_status=status_param.upper())
            
        contact_id = self.request.query_params.get('contact_id')
        if contact_id:
            qs = qs.filter(contact_id=contact_id)
            
        order_id = self.request.query_params.get('order_id')
        if order_id:
            qs = qs.filter(order_reference=order_id)
            
        return qs

    def perform_create(self, serializer):
        client = get_tenant_client(self.request)
        if not client:
            from rest_framework.exceptions import ValidationError
            raise ValidationError({'detail': 'No active client workspace associated with this user.'})

        inv_num = serializer.validated_data.get('invoice_number')
        if not inv_num:
            inv_num = InvoiceService.generate_next_invoice_number(client)
        
        import secrets
        sec_token = serializer.validated_data.get('secure_token') or secrets.token_urlsafe(32)

        seller_details = serializer.validated_data.get('seller_details') or {}
        if not seller_details.get('company_name'):
            seller_details['company_name'] = client.business_name or 'Company Name'
        if not seller_details.get('business_name'):
            seller_details['business_name'] = client.business_name or 'Company Name'
        if not seller_details.get('logo_url'):
            seller_details['logo_url'] = getattr(client, 'company_logo_url', '') or ''
        if not seller_details.get('company_logo_url'):
            seller_details['company_logo_url'] = getattr(client, 'company_logo_url', '') or ''
        if not seller_details.get('address'):
            seller_details['address'] = getattr(client, 'address', '') or ''
        if not seller_details.get('phone'):
            seller_details['phone'] = getattr(client, 'phone_number', '') or ''
        if not seller_details.get('email'):
            seller_details['email'] = (self.request.user.email if self.request.user and self.request.user.email else getattr(client, 'email', ''))
        if not seller_details.get('tax_id_gstin'):
            seller_details['tax_id_gstin'] = getattr(client, 'tax_id_gstin', '') or ''

        # Persist company branding back to client profile if updated
        updated = False
        logo_in_details = seller_details.get('company_logo_url') or seller_details.get('logo_url')
        if logo_in_details and logo_in_details != client.company_logo_url:
            client.company_logo_url = logo_in_details
            updated = True
        if not client.business_name and seller_details.get('company_name'):
            client.business_name = seller_details.get('company_name')
            updated = True
        if seller_details.get('address') and seller_details.get('address') != client.address:
            client.address = seller_details.get('address')
            updated = True
        if seller_details.get('tax_id_gstin') and seller_details.get('tax_id_gstin') != client.tax_id_gstin:
            client.tax_id_gstin = seller_details.get('tax_id_gstin')
            updated = True
        if updated:
            client.save()

        serializer.save(client=client, invoice_number=inv_num, secure_token=sec_token, seller_details=seller_details)

    @action(detail=False, methods=['get'], url_path='by-order/(?P<order_id>[^/.]+)')
    def by_order(self, request, order_id=None):
        """Fetch invoice associated with an order ID."""
        client = get_tenant_client(request)
        if not client:
            return Response({'error': 'No associated client found'}, status=400)
            
        invoice = Invoice.objects.filter(client=client).filter(
            order_reference=order_id
        ).first()
        
        if not invoice:
            return Response({'detail': 'No invoice found for this order'}, status=404)
            
        return Response(InvoiceSerializer(invoice).data)

    @action(detail=False, methods=['get'], url_path='by-customer/(?P<customer_id>[^/.]+)')
    def by_customer(self, request, customer_id=None):
        """Fetch invoices associated with a customer ID."""
        client = get_tenant_client(request)
        if not client:
            return Response({'error': 'No associated client found'}, status=400)
            
        invoices = Invoice.objects.filter(client=client).filter(
            contact_id=customer_id
        )
        return Response(InvoiceSerializer(invoices, many=True).data)

    @action(detail=True, methods=['get'], permission_classes=[AllowAny], url_path='download')
    def download(self, request, pk=None):
        """
        GET /api/invoices/<id>/download/
        Download the actual printable PDF file binary stream.
        """
        try:
            invoice = Invoice.objects.get(pk=pk)
        except (Invoice.DoesNotExist, ValueError):
            return Response({'error': 'Invoice not found'}, status=404)

        # Build PDF stream if file does not exist or rebuild requested
        if not invoice.pdf_file_path or not os.path.exists(invoice.pdf_file_path):
            success = InvoiceService.build_pdf_and_save(invoice)
            if not success or not invoice.pdf_file_path:
                invoice.refresh_from_db()
                error_detail = getattr(invoice, 'error_log', '') or 'Unknown PDF generation error'
                logger.error(f"[InvoiceDownload] PDF build failed for {invoice.invoice_number}: {error_detail}")
                return Response({'error': f'Failed to build PDF file: {error_detail}'}, status=500)

        try:
            filename = f"{invoice.invoice_number.replace('/', '_')}.pdf"
            response = FileResponse(
                open(invoice.pdf_file_path, 'rb'),
                content_type='application/pdf'
            )
            response['Content-Disposition'] = f'attachment; filename="{filename}"'
            return response
        except Exception as e:
            logger.error(f"Error serving PDF file: {e}")
            return Response({'error': str(e)}, status=500)

    @action(detail=True, methods=['post'], url_path='regenerate')
    def regenerate(self, request, pk=None):
        """Regenerate PDF file for an invoice."""
        client = get_tenant_client(request)
        try:
            invoice = Invoice.objects.get(pk=pk, client=client)
        except (Invoice.DoesNotExist, ValueError):
            return Response({'error': 'Invoice not found'}, status=404)

        success = InvoiceService.regenerate_invoice(invoice)
        if success:
            return Response({
                'message': 'Invoice PDF regenerated successfully!',
                'invoice': InvoiceSerializer(invoice).data
            })
        else:
            return Response({'error': 'PDF generation failed: ' + (invoice.error_log or 'Unknown error')}, status=500)

    @action(detail=True, methods=['post'], url_path='send')
    def send(self, request, pk=None):
        """
        POST /api/invoices/<id>/send/
        Dispatch invoice link and details to customer via EMAIL or WHATSAPP.
        """
        client = get_tenant_client(request)
        if not client:
            return Response({'error': 'No associated client found'}, status=400)

        try:
            invoice = Invoice.objects.get(pk=pk, client=client)
        except (Invoice.DoesNotExist, ValueError):
            return Response({'error': 'Invoice not found'}, status=404)

        channel = (request.data.get('channel') or 'EMAIL').upper()
        recipient = request.data.get('recipient')

        # Build secure link
        env_frontend_url = os.getenv('NEXT_PUBLIC_APP_URL') or os.getenv('FRONTEND_URL') or os.getenv('PUBLIC_APP_URL')
        request_frontend = request.data.get('frontend_url')

        if env_frontend_url:
            frontend_url = env_frontend_url.rstrip('/')
        elif request_frontend:
            frontend_url = request_frontend.rstrip('/')
        else:
            frontend_url = 'https://uwoconnect.aisa24.com'

        secure_link = f"{frontend_url}/public/invoice/{invoice.secure_token}"

        seller_details = invoice.seller_details if isinstance(invoice.seller_details, dict) else {}
        company_name = (
            seller_details.get('company_name')
            or seller_details.get('business_name')
            or (client.business_name if (client and client.business_name and client.business_name.lower() != 'test') else None)
            or (client.business_name if client else None)
            or "UWOConnect"
        )

        billing_details = invoice.billing_details if isinstance(invoice.billing_details, dict) else {}
        customer_name = billing_details.get('name') or "Valued Customer"

        try:
            formatted_total = f"{float(invoice.total):.2f}"
        except (ValueError, TypeError):
            formatted_total = str(invoice.total)

        status_display = invoice.payment_status or 'PAID'

        subject = f"{company_name} - Invoice #{invoice.invoice_number}"
        message_body = (
            f"Dear {customer_name},\n\n"
            f"Your invoice #{invoice.invoice_number} from {company_name} is ready.\n\n"
            f"Amount: {invoice.currency_symbol}{formatted_total} {invoice.currency}\n"
            f"Payment Status: {status_display}\n\n"
            f"View and download your official invoice:\n"
            f"{secure_link}\n\n"
            f"Regards,\n"
            f"{company_name}"
        )

        try:
            from api.services.notification_service import SalesDocumentNotificationService
            if channel == 'EMAIL':
                if not recipient:
                    recipient = billing_details.get('email')
                if not recipient:
                    return Response({'error': 'Recipient email address is required.'}, status=400)
                SalesDocumentNotificationService.send_document_email(invoice, recipient, subject, message_body)
            elif channel == 'WHATSAPP':
                phone = request.data.get('phone') or recipient or billing_details.get('phone')
                if not phone:
                    return Response({'error': 'Recipient phone number is required.'}, status=400)
                SalesDocumentNotificationService.send_document_whatsapp(invoice, phone, message_body)
            else:
                return Response({'error': f'Unsupported communication channel: {channel}'}, status=400)

            return Response({
                'success': True,
                'message': f"Invoice #{invoice.invoice_number} sent via {channel.title()} successfully.",
                'channel': channel,
                'recipient': recipient or phone
            })
        except Exception as e:
            logger.error(f"[InvoiceSendError] Failed to send invoice #{invoice.invoice_number}: {e}")
            return Response({'error': str(e)}, status=500)

    def destroy(self, request, *args, **kwargs):
        """
        DELETE /api/invoices/<id>/
        Safely delete an invoice for the authenticated tenant and clean up any physical PDF files.
        """
        client = get_tenant_client(request)
        if not client:
            return Response({'error': 'No associated client found'}, status=400)

        try:
            invoice = Invoice.objects.get(pk=kwargs.get('pk'), client=client)
        except (Invoice.DoesNotExist, ValueError):
            return Response({'error': 'Invoice not found'}, status=404)

        inv_number = invoice.invoice_number
        if invoice.pdf_file_path and os.path.exists(invoice.pdf_file_path):
            try:
                os.remove(invoice.pdf_file_path)
            except Exception as e:
                logger.warning(f"Could not remove PDF file for invoice {inv_number}: {e}")

        invoice.delete()
        return Response({
            'success': True,
            'message': f"Invoice #{inv_number} deleted successfully."
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get', 'post'], url_path='settings')
    def settings_view(self, request):
        """Get or update Invoice Branding settings for the client."""
        client = get_tenant_client(request)
        if not client:
            return Response({'error': 'No associated client found'}, status=400)

        if request.method == 'GET':
            return Response({
                'invoice_prefix': getattr(client, 'invoice_prefix', 'INV') or 'INV',
                'invoice_next_number': getattr(client, 'invoice_next_number', 1001) or 1001,
                'company_logo_url': getattr(client, 'company_logo_url', '') or '',
                'tax_id_gstin': getattr(client, 'tax_id_gstin', '') or '',
                'invoice_default_notes': getattr(client, 'invoice_default_notes', '') or '',
                'payment_terms': getattr(client, 'payment_terms', '') or '',
                'invoice_footer': getattr(client, 'invoice_footer', '') or '',
                'company_name': getattr(client, 'business_name', '') or '',
                'company_address': getattr(client, 'address', '') or '',
                'phone_number': getattr(client, 'phone_number', '') or '',
            })

        # POST update
        client.invoice_prefix = request.data.get('invoice_prefix', getattr(client, 'invoice_prefix', 'INV'))
        client.company_logo_url = request.data.get('company_logo_url', getattr(client, 'company_logo_url', ''))
        client.tax_id_gstin = request.data.get('tax_id_gstin', getattr(client, 'tax_id_gstin', ''))
        client.invoice_default_notes = request.data.get('invoice_default_notes', getattr(client, 'invoice_default_notes', ''))
        client.payment_terms = request.data.get('payment_terms', getattr(client, 'payment_terms', ''))
        client.invoice_footer = request.data.get('invoice_footer', getattr(client, 'invoice_footer', ''))
        
        if 'company_name' in request.data:
            client.business_name = request.data['company_name']
        if 'company_address' in request.data:
            client.address = request.data['company_address']
            
        client.save()

        return Response({
            'message': 'Invoice settings updated successfully!',
            'settings': {
                'invoice_prefix': client.invoice_prefix,
                'invoice_next_number': client.invoice_next_number,
                'company_logo_url': client.company_logo_url,
                'tax_id_gstin': client.tax_id_gstin,
                'invoice_default_notes': client.invoice_default_notes,
                'payment_terms': client.payment_terms,
                'invoice_footer': client.invoice_footer,
            }
        })


# ── PUBLIC UNAUTHENTICATED INVOICE VIEWS ────────────────────────────────────

from rest_framework.views import APIView

class PublicInvoiceView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            invoice = Invoice.objects.get(secure_token=token)
        except (Invoice.DoesNotExist, ValueError):
            try:
                invoice = Invoice.objects.get(pk=token)
            except Exception:
                raise Http404("Invoice not found")
        return Response(InvoiceSerializer(invoice).data)


class PublicInvoicePDFView(APIView):
    permission_classes = [AllowAny]

    def get(self, request, token):
        try:
            invoice = Invoice.objects.get(secure_token=token)
        except (Invoice.DoesNotExist, ValueError):
            try:
                invoice = Invoice.objects.get(pk=token)
            except Exception:
                raise Http404("Invoice not found")

        try:
            pdf_buffer = InvoicePDFService.generate_pdf(invoice)
            response = HttpResponse(pdf_buffer.read(), content_type='application/pdf')
            filename = f"{invoice.invoice_number.replace('/', '_')}.pdf"
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            return response
        except Exception as e:
            return Response({'error': f"Failed to generate PDF: {str(e)}"}, status=500)

