import os
import logging
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, Image as RLImage, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from django.utils import timezone

logger = logging.getLogger(__name__)

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically compute and print 'Page X of Y' in the footer.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_elements(num_pages)
            super().showPage()
        super().save()

    def draw_page_elements(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor('#64748B'))
        
        # Header rule and title
        self.setStrokeColor(colors.HexColor('#E2E8F0'))
        self.setLineWidth(0.5)
        self.line(54, 750, 558, 750)
        # White-label: brand name injected by build hooks
        brand_name = getattr(self, '_brand_name', 'Official Business Invoice')
        self.drawString(54, 755, brand_name)
        
        # Footer rule and page info
        self.line(54, 55, 558, 55)
        self.drawString(54, 42, "Computer generated official invoice. Valid without physical signature.")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 42, page_text)
        
        self.restoreState()


class InvoicePDFService:
    @staticmethod
    def get_currency_symbol(currency_code):
        """Map 3-letter currency code to currency symbol."""
        symbols = {
            'USD': '$',
            'INR': '₹',
            'EUR': '€',
            'GBP': '£',
            'AUD': 'A$',
            'CAD': 'C$',
            'JPY': '¥',
            'SGD': 'S$',
            'AED': 'AED ',
            'SAR': 'SAR ',
            'QAR': 'QAR ',
            'MYR': 'RM ',
            'IDR': 'Rp ',
            'BRL': 'R$ ',
            'ZAR': 'R ',
        }
        return symbols.get(str(currency_code).upper(), f"{currency_code} ")

    @staticmethod
    def format_date_safe(val):
        if not val:
            return 'N/A'
        if hasattr(val, 'strftime'):
            return val.strftime('%b %d, %Y')
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(str(val).replace('Z', '+00:00'))
            return dt.strftime('%b %d, %Y')
        except Exception:
            return str(val).split('T')[0]

    @staticmethod
    def _get_logo_flowable(logo_url, max_width=140, max_height=45):
        if not logo_url:
            return None
        try:
            img_io = None
            if logo_url.startswith('data:image/'):
                import base64
                header, encoded = logo_url.split(',', 1)
                img_bytes = base64.b64decode(encoded)
                img_io = BytesIO(img_bytes)
            elif logo_url.startswith(('http://', 'https://')):
                import requests
                resp = requests.get(logo_url, timeout=3)
                if resp.status_code == 200:
                    img_io = BytesIO(resp.content)
            elif os.path.exists(logo_url):
                with open(logo_url, 'rb') as f:
                    img_io = BytesIO(f.read())

            if not img_io:
                return None

            try:
                from PIL import Image as PILImage
                pil_img = PILImage.open(img_io)
                if pil_img.mode in ('RGBA', 'LA') or (pil_img.mode == 'P' and 'transparency' in pil_img.info):
                    bbox = pil_img.getbbox()
                    if bbox:
                        pil_img = pil_img.crop(bbox)
                
                w, h = pil_img.size
                if w <= 0 or h <= 0:
                    return None
                
                aspect = w / float(h)
                target_h = min(max_height, 45)
                target_w = target_h * aspect
                if target_w > max_width:
                    target_w = max_width
                    target_h = target_w / aspect

                out_io = BytesIO()
                pil_img.save(out_io, format='PNG')
                out_io.seek(0)

                img = RLImage(out_io, width=target_w, height=target_h)
                img.hAlign = 'LEFT'
                return img
            except Exception:
                img_io.seek(0)
                img = RLImage(img_io, width=max_width, height=max_height)
                img.hAlign = 'LEFT'
                return img
        except Exception as e:
            logger.warning(f"[InvoicePDF Logo Warning] Could not load logo: {e}")
        return None

    @staticmethod
    def generate_pdf(invoice):
        """
        Generates a professional multi-currency PDF invoice.
        Returns a BytesIO buffer stream.
        """
        buffer = BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=54,
            leftMargin=54,
            topMargin=72,
            bottomMargin=72
        )
        
        styles = getSampleStyleSheet()
        
        # Modify default styles
        styles['Normal'].textColor = colors.HexColor('#1E293B')
        styles['Normal'].fontSize = 9
        styles['Normal'].leading = 12
        
        primary_color = '#059669' # Emerald
        dark_slate = '#0F172A'
        
        title_style = ParagraphStyle(
            'InvoiceTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=22,
            leading=26,
            textColor=colors.HexColor(primary_color),
            spaceAfter=5
        )
        
        bold_label_style = ParagraphStyle(
            'InvoiceBoldLabel',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor(dark_slate)
        )

        right_bold_style = ParagraphStyle(
            'InvoiceRightBold',
            parent=bold_label_style,
            alignment=2
        )

        right_text_style = ParagraphStyle(
            'InvoiceRightText',
            parent=styles['Normal'],
            alignment=2
        )

        story = []
        
        # 1. Header Section (Top-Left Company Logo + Seller Details, Top-Right Invoice Meta)
        seller = invoice.seller_details or {}
        logo_url = seller.get('logo_url') or seller.get('company_logo_url') or getattr(invoice.client, 'company_logo_url', '')
        company_name = seller.get('company_name') or seller.get('business_name') or (invoice.client.business_name if invoice.client else 'Company Name')
        address = seller.get('address') or (invoice.client.address if invoice.client else '')
        email = seller.get('email') or (invoice.client.phone_number if invoice.client else '')
        phone = seller.get('phone') or ''
        tax_id = seller.get('tax_id_gstin') or getattr(invoice.client, 'tax_id_gstin', '')

        left_cell = []
        if logo_url:
            logo_flowable = InvoicePDFService._get_logo_flowable(logo_url)
            if logo_flowable:
                left_cell.append(logo_flowable)
                left_cell.append(Spacer(1, 4))
        
        left_cell.append(Paragraph(f"<b>{company_name}</b>", ParagraphStyle('SellerCompName', fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.HexColor('#0F172A'))))
        
        seller_info_lines = []
        if address:
            seller_info_lines.append(address)
        if email:
            seller_info_lines.append(f"Email: {email}")
        if phone:
            seller_info_lines.append(f"Phone: {phone}")
        if tax_id:
            seller_info_lines.append(f"GSTIN / Tax ID: {tax_id}")
        
        if seller_info_lines:
            left_cell.append(Paragraph("<br/>".join(seller_info_lines), ParagraphStyle('SellerCompDetails', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.HexColor('#64748B'))))

        status_color = '#059669' if invoice.payment_status == 'PAID' else '#D97706' if invoice.payment_status == 'PARTIALLY PAID' else '#DC2626'
        order_ref = invoice.order_reference or (str(invoice.order.id) if invoice.order else 'N/A')
        inv_date_str = InvoicePDFService.format_date_safe(invoice.invoice_date)

        right_cell = [
            Paragraph("<font color='#0F172A'>INVOICE</font>", ParagraphStyle('InvTitleText', fontName='Helvetica-Bold', fontSize=22, leading=26, alignment=2, textColor=colors.HexColor('#0F172A'))),
            Spacer(1, 4),
            Paragraph(f"<b># {invoice.invoice_number}</b>", ParagraphStyle('InvNumText', parent=styles['Normal'], fontSize=9, leading=12, alignment=2, textColor=colors.HexColor('#1E293B'))),
            Paragraph(f"Date: {inv_date_str}", ParagraphStyle('InvDateText', parent=styles['Normal'], fontSize=8, leading=11, alignment=2, textColor=colors.HexColor('#64748B'))),
            Paragraph(f"Order ID: {order_ref}", ParagraphStyle('InvOrderText', parent=styles['Normal'], fontSize=8, leading=11, alignment=2, textColor=colors.HexColor('#64748B'))),
            Paragraph(f"Status: <font color='{status_color}'><b>{invoice.payment_status}</b></font>", ParagraphStyle('InvStatusText', parent=styles['Normal'], fontSize=8, leading=11, alignment=2)),
        ]

        header_table = Table([[left_cell, right_cell]], colWidths=[280, 224])
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ]))
        story.append(header_table)
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E2E8F0'), spaceBefore=10, spaceAfter=15))

        # 2. Billed To Customer Card
        billing = invoice.billing_details or {}
        cust_name = billing.get('name') or (invoice.contact.name if invoice.contact else 'Valued Customer')
        cust_email = billing.get('email') or (invoice.contact.email if invoice.contact else '')
        cust_phone = billing.get('phone') or (invoice.contact.phone_number if invoice.contact else '')
        cust_address = billing.get('address') or ''

        billing_html = f"<b>BILL TO:</b><br/><b>{cust_name}</b><br/>"
        if cust_email:
            billing_html += f"Email: {cust_email}<br/>"
        if cust_phone:
            billing_html += f"Phone: {cust_phone}<br/>"
        if cust_address:
            billing_html += f"{cust_address}<br/>"

        addr_table = Table([[Paragraph(billing_html, styles['Normal'])]], colWidths=[504])
        addr_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
            ('PADDING', (0, 0), (-1, -1), 10),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ]))
        story.append(addr_table)
        story.append(Spacer(1, 15))

        # 3. Line Items Table
        cur_sym = invoice.currency_symbol or InvoicePDFService.get_currency_symbol(invoice.currency)
        cur_code = invoice.currency or 'USD'

        items_data = [[
            Paragraph("Item Description", bold_label_style),
            Paragraph("Qty", bold_label_style),
            Paragraph(f"Unit Price ({cur_code})", right_bold_style),
            Paragraph(f"Tax ({cur_code})", right_bold_style),
            Paragraph(f"Total ({cur_code})", right_bold_style)
        ]]

        items = invoice.line_items or []
        if not items:
            items = [{
                'name': 'Product Purchase',
                'quantity': 1,
                'unit_price': float(invoice.total or 0),
                'tax': 0,
                'total': float(invoice.total or 0)
            }]

        for item in items:
            name = item.get('name') or item.get('product_name') or 'Item'
            sku = item.get('sku') or ''
            if sku:
                name += f"<br/><font size=7 color='#64748B'>SKU: {sku}</font>"
            qty = str(item.get('quantity', 1))
            unit_price = float(item.get('unit_price', 0))
            tax_amt = float(item.get('tax', 0))
            line_tot = float(item.get('total', unit_price * float(qty)))

            items_data.append([
                Paragraph(name, styles['Normal']),
                Paragraph(qty, styles['Normal']),
                Paragraph(f"{cur_sym}{unit_price:,.2f}", right_text_style),
                Paragraph(f"{cur_sym}{tax_amt:,.2f}", right_text_style),
                Paragraph(f"{cur_sym}{line_tot:,.2f}", right_text_style),
            ])

        items_table = Table(items_data, colWidths=[204, 50, 80, 80, 90])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#F1F5F9')),
            ('ALIGN', (1, 0), (1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
            ('PADDING', (0, 0), (-1, -1), 8),
        ]))
        story.append(items_table)
        story.append(Spacer(1, 15))

        # 4. Summary Calculation Breakdown
        subtotal = float(invoice.subtotal or invoice.total)
        discount = float(invoice.discount or 0)
        shipping = float(invoice.shipping or 0)
        tax = float(invoice.tax or 0)
        total = float(invoice.total or 0)
        amount_paid = float(invoice.amount_paid or (total if invoice.payment_status == 'PAID' else 0))
        balance_due = float(invoice.balance_due or (total - amount_paid))

        summary_data = [
            [Paragraph("Subtotal:", right_text_style), Paragraph(f"{cur_sym}{subtotal:,.2f}", right_text_style)],
        ]
        if discount > 0:
            summary_data.append([Paragraph("Discount:", right_text_style), Paragraph(f"-{cur_sym}{discount:,.2f}", right_text_style)])
        if shipping > 0:
            summary_data.append([Paragraph("Shipping Charges:", right_text_style), Paragraph(f"{cur_sym}{shipping:,.2f}", right_text_style)])
        if tax > 0:
            summary_data.append([Paragraph("Tax / GST:", right_text_style), Paragraph(f"{cur_sym}{tax:,.2f}", right_text_style)])

        summary_data.append([
            Paragraph("<b>Grand Total:</b>", right_text_style),
            Paragraph(f"<b><font size=11 color='{primary_color}'>{cur_sym}{total:,.2f} {cur_code}</font></b>", right_text_style)
        ])
        summary_data.append([
            Paragraph("Amount Paid:", right_text_style),
            Paragraph(f"<b>{cur_sym}{amount_paid:,.2f}</b>", right_text_style)
        ])
        summary_data.append([
            Paragraph("Balance Due:", right_text_style),
            Paragraph(f"<b>{cur_sym}{balance_due:,.2f}</b>", right_text_style)
        ])

        summary_table = Table(summary_data, colWidths=[384, 120])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LINEABOVE', (0, -3), (1, -3), 1, colors.HexColor(primary_color)),
        ]))
        story.append(KeepTogether(summary_table))
        story.append(Spacer(1, 15))

        # 5. Dedicated Payment Information Block
        payment_date_str = invoice.payment_date.strftime('%b %d, %Y %I:%M %p') if invoice.payment_date else 'N/A'
        txn_id = getattr(invoice, 'transaction_id', '') or invoice.payment_id or 'N/A'
        pay_method = invoice.payment_method or 'Card/Online'

        pay_info_html = (
            f"<b>PAYMENT INFORMATION:</b><br/>"
            f"<b>Payment Status:</b> <font color='{status_color}'><b>{invoice.payment_status}</b></font> &nbsp;|&nbsp; "
            f"<b>Amount Paid:</b> {cur_sym}{amount_paid:,.2f} &nbsp;|&nbsp; "
            f"<b>Balance Due:</b> {cur_sym}{balance_due:,.2f}<br/>"
            f"<b>Payment Method:</b> {pay_method} &nbsp;|&nbsp; "
            f"<b>Payment Date:</b> {payment_date_str} &nbsp;|&nbsp; "
            f"<b>Txn / Payment ID:</b> {txn_id}"
        )
        pay_info_table = Table([[Paragraph(pay_info_html, styles['Normal'])]], colWidths=[504])
        pay_info_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F8FAFC')),
            ('PADDING', (0, 0), (-1, -1), 8),
            ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2E8F0')),
        ]))
        story.append(pay_info_table)
        story.append(Spacer(1, 15))

        # 6. Terms, Notes & Footer
        default_notes = getattr(invoice.client, 'invoice_default_notes', '') or "Thank you for your business!"
        terms = getattr(invoice.client, 'payment_terms', '') or "All payments processed via secure gateway."

        notes_html = f"<b>Terms & Notes:</b><br/>{default_notes}<br/><i>{terms}</i>"
        story.append(Paragraph(notes_html, styles['Normal']))

        # Resolve white-label brand name (no UWO footprint for agency sub-clients)
        _client = invoice.client if invoice.client else None
        _agency = getattr(_client, 'parent_agency', None) if _client else None
        if _agency and getattr(_agency, 'white_label_name', None):
            _brand_label = f"{_agency.white_label_name} — Official Business Invoice"
        elif _client and getattr(_client, 'white_label_name', None):
            _brand_label = f"{_client.white_label_name} — Official Business Invoice"
        elif _client and getattr(_client, 'business_name', None):
            _brand_label = f"{_client.business_name} — Official Business Invoice"
        else:
            _brand_label = "Official Business Invoice"

        def _on_first_page(canvas, doc):
            canvas._brand_name = _brand_label

        def _on_later_pages(canvas, doc):
            canvas._brand_name = _brand_label

        # Build document
        doc.build(story, canvasmaker=NumberedCanvas, onFirstPage=_on_first_page, onLaterPages=_on_later_pages)
        
        buffer.seek(0)
        return buffer
