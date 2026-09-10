import os
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfgen import canvas
from django.utils import timezone

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
        
        is_proposal = self.__dict__.get('_is_proposal', False)
        
        # Suppress running header on cover page of proposals
        if is_proposal and self._pageNumber == 1:
            self.restoreState()
            return

        # Running Header
        self.setStrokeColor(colors.HexColor('#E2E8F0'))
        self.setLineWidth(0.5)
        self.line(54, 750, 558, 750)
        # White-label: use brand name injected by on_first_page/on_later_pages hook
        brand_name = getattr(self, '_brand_name', 'Enterprise Sales Document')
        self.drawString(54, 755, brand_name)
        
        # Running Footer
        self.line(54, 55, 558, 55)
        self.drawString(54, 42, "Confidential & Proprietary • Computer Generated Official Business Document")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 42, page_text)
        
        self.restoreState()


class SalesDocumentPDFService:
    @staticmethod
    def get_currency_symbol(currency_code):
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
    def _get_logo_flowable_from_url(logo_url, max_width=140, max_height=45):
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

            from reportlab.platypus import Image as RLImage

            try:
                from PIL import Image as PILImage
                pil_img = PILImage.open(img_io)
                
                # Auto-trim transparent empty padding around logo graphic
                if pil_img.mode in ('RGBA', 'LA') or (pil_img.mode == 'P' and 'transparency' in pil_img.info):
                    bbox = pil_img.getbbox()
                    if bbox:
                        pil_img = pil_img.crop(bbox)
                
                w, h = pil_img.size
                if w <= 0 or h <= 0:
                    return None
                
                aspect = w / float(h)
                
                # Scale keeping exact aspect ratio
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
            except Exception as pil_err:
                print(f"[PDF Logo PIL Warning] {pil_err}")
                img_io.seek(0)
                img = RLImage(img_io, width=max_width, height=max_height)
                img.hAlign = 'LEFT'
                return img
        except Exception as e:
            print(f"[PDF Logo Warning] Could not load logo image: {e}")
        return None

    @staticmethod
    def generate_pdf(document):
        """
        Generates an executive, Fortune-500 level sales document PDF for Quotations and Proposals.
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
        
        styles['Normal'].textColor = colors.HexColor('#1E293B')
        styles['Normal'].fontSize = 9
        styles['Normal'].leading = 13
        
        primary_color = '#0F172A' # Professional neutral slate
        dark_slate = '#0F172A'
        
        title_style = ParagraphStyle(
            'DocTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=22,
            leading=26,
            textColor=colors.HexColor(primary_color),
            spaceAfter=15
        )
        
        section_style = ParagraphStyle(
            'DocSection',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=13,
            leading=16,
            textColor=colors.HexColor(dark_slate),
            spaceBefore=14,
            spaceAfter=6,
            keepWithNext=True
        )

        bold_label_style = ParagraphStyle(
            'DocBoldLabel',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=9,
            leading=12,
            textColor=colors.HexColor(dark_slate)
        )

        right_bold_style = ParagraphStyle(
            'DocRightBold',
            parent=bold_label_style,
            alignment=2
        )

        right_text_style = ParagraphStyle(
            'DocRightText',
            parent=styles['Normal'],
            alignment=2
        )

        card_title_style = ParagraphStyle(
            'CoverTitle',
            parent=styles['Normal'],
            fontName='Helvetica-Bold',
            fontSize=22,
            leading=28,
            textColor=colors.HexColor(dark_slate),
            alignment=0,
            spaceAfter=8
        )

        card_subtitle_style = ParagraphStyle(
            'CoverSubtitle',
            parent=styles['Normal'],
            fontName='Helvetica',
            fontSize=10,
            leading=14,
            textColor=colors.HexColor('#64748B'),
            alignment=0,
            spaceAfter=20
        )

        story = []

        is_proposal = document.document_type == 'PROPOSAL'

        comp_snapshot = document.company_details if (document.company_details and isinstance(document.company_details, dict) and document.company_details.get('business_name')) else {}
        logo_url = comp_snapshot.get('company_logo_url') or (document.client.company_logo_url if document.client else '')
        client_logo = SalesDocumentPDFService._get_logo_flowable_from_url(logo_url)
        client_name = comp_snapshot.get('business_name') or (document.client.business_name if document.client else "Company Name")
        client_address = comp_snapshot.get('address') or (document.client.address if document.client else "")
        client_email = comp_snapshot.get('email') or (document.created_by.email if document.created_by else "")
        client_phone = comp_snapshot.get('phone_number') or (document.client.phone_number if document.client else "")

        if is_proposal:
            # ── 1. EXECUTIVE PROPOSAL CLEAN NEUTRAL HEADER (TOP-LEFT LOGO) ──
            left_cell = []
            if client_logo:
                left_cell.append(client_logo)
                left_cell.append(Spacer(1, 4))
            left_cell.append(Paragraph(f"<b>{client_name}</b>", ParagraphStyle('BizNameProp', parent=bold_label_style, fontSize=12, leading=15, textColor=colors.HexColor('#0F172A'))))
            
            left_info = []
            if client_address:
                left_info.append(client_address)
            if client_email:
                left_info.append(f"Email: {client_email}")
            if client_phone:
                left_info.append(f"Phone: {client_phone}")
            if document.tax_number or comp_snapshot.get('tax_id_gstin'):
                tax = document.tax_number or comp_snapshot.get('tax_id_gstin')
                left_info.append(f"GSTIN / Tax ID: {tax}")
            
            if left_info:
                left_cell.append(Paragraph("<br/>".join(left_info), ParagraphStyle('BizAddrProp', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.HexColor('#64748B'))))

            right_cell = [
                Paragraph("PROPOSAL", ParagraphStyle('DocTypeProp', fontName='Helvetica-Bold', fontSize=20, leading=24, textColor=colors.HexColor('#0F172A'), alignment=2)),
                Paragraph(f"<b># {document.document_number}</b>", ParagraphStyle('DocNumProp', parent=styles['Normal'], fontSize=9, leading=12, alignment=2, textColor=colors.HexColor('#1E293B'))),
                Paragraph(f"Date: {document.document_date}", ParagraphStyle('DocDateProp', parent=styles['Normal'], fontSize=8, leading=11, alignment=2, textColor=colors.HexColor('#64748B'))),
            ]
            if document.valid_until:
                right_cell.append(Paragraph(f"Valid Until: {document.valid_until}", ParagraphStyle('DocValidProp', parent=styles['Normal'], fontSize=8, leading=11, alignment=2, textColor=colors.HexColor('#64748B'))))

            header_table = Table([[left_cell, right_cell]], colWidths=[280, 224])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 2),
                ('LEFTPADDING', (0,0), (-1,-1), 0),
                ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ]))
            story.append(header_table)
            story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#E2E8F0'), spaceBefore=10, spaceAfter=20))

            # Cover Address Cards Block
            prep_data = [
                [
                    Paragraph("<b>PREPARED FOR:</b>", ParagraphStyle('Lbl1', parent=bold_label_style, textColor=colors.HexColor('#475569'))),
                    Paragraph("<b>PREPARED BY:</b>", ParagraphStyle('Lbl2', parent=bold_label_style, textColor=colors.HexColor('#475569')))
                ],
                [
                    Paragraph(f"<b>{document.customer_name or 'Valued Customer'}</b><br/>{document.customer_company or ''}<br/>Email: {document.customer_email or ''}<br/>Phone: {document.customer_phone or ''}", styles['Normal']),
                    Paragraph(f"<b>{client_name}</b><br/>{client_address}<br/>Email: {client_email}<br/>Phone: {client_phone}", styles['Normal'])
                ]
            ]
            prep_table = Table(prep_data, colWidths=[250, 254])
            prep_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
                ('PADDING', (0,0), (-1,-1), 12),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ]))
            story.append(prep_table)
            
            story.append(Spacer(1, 20))
            
            # ── 2. PROPOSAL DYNAMIC SECTIONS ──
            sections = document.proposal_sections or []
            if not sections and document.proposal_template:
                sections = document.proposal_template.sections or []

            if not sections:
                sections = [
                    {'title': '1. Executive Summary', 'content': 'This proposal outlines our strategic approach, technical roadmap, and commercial investment structure.'},
                    {'title': '2. Scope of Work & Deliverables', 'content': 'Detailed breakdown of deliverables, milestones, and project execution phases.'},
                    {'title': '3. Project Timeline & Milestones', 'content': 'Phase 1: Discovery & Planning\nPhase 2: Execution & Testing\nPhase 3: Deployment & Handover'},
                    {'title': '4. Terms & Warranty', 'content': 'Includes 12 months comprehensive support and SLA guarantees.'}
                ]

            for sec in sections:
                title = sec.get('title', '')
                content = sec.get('content', '')
                
                story.append(Paragraph(title, section_style))
                story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceBefore=2, spaceAfter=8))
                story.append(Paragraph(content.replace('\n', '<br/>'), styles['Normal']))
                story.append(Spacer(1, 14))

            # Proposal Commercial Table
            if document.items.exists():
                story.append(Spacer(1, 10))
                story.append(Paragraph("Commercial Investment Summary", section_style))
                story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor('#E2E8F0'), spaceBefore=2, spaceAfter=10))
                SalesDocumentPDFService._build_items_table(document, story, styles, bold_label_style, right_bold_style, right_text_style, primary_color)

            # Proposal Acceptance Block
            story.append(Spacer(1, 20))
            story.append(KeepTogether([
                Paragraph("Acceptance & Authorization", section_style),
                Paragraph("By signing below, the customer accepts this proposal and agrees to the proposed scope and pricing.", styles['Normal']),
                Spacer(1, 15),
                Table([
                    [Paragraph("<b>Customer Signature:</b>", bold_label_style), Paragraph("<b>Authorized Representative:</b>", bold_label_style)],
                    [Spacer(1, 30), Spacer(1, 30)],
                    [Paragraph("___________________________", styles['Normal']), Paragraph("___________________________", styles['Normal'])],
                    [Paragraph("Date: ", styles['Normal']), Paragraph("Date: ", styles['Normal'])],
                ], colWidths=[250, 254], style=[('VALIGN', (0,0), (-1,-1), 'TOP')])
            ]))

        else:
            # ── QUOTATION & INVOICE PAGE LAYOUT ──
            cur_sym = document.currency_symbol or SalesDocumentPDFService.get_currency_symbol(document.currency)
            cur_code = document.currency or 'USD'
            doc_type_label = "QUOTATION" if document.document_type == 'QUOTATION' else "TAX INVOICE"
            
            # Header Block
            left_cell = []
            if client_logo:
                left_cell.append(client_logo)
                left_cell.append(Spacer(1, 4))
            left_cell.append(Paragraph(f"<b>{client_name}</b>", ParagraphStyle('BizName', parent=bold_label_style, fontSize=14, leading=17)))
            left_cell.append(Paragraph(f"{client_address}<br/>Email: {client_email}<br/>Phone: {client_phone}", ParagraphStyle('BizAddr', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.HexColor('#64748B'))))

            right_cell = [
                Paragraph(doc_type_label, ParagraphStyle('DocType', fontName='Helvetica-Bold', fontSize=18, leading=22, textColor=colors.HexColor('#0F172A'), alignment=2)),
                Paragraph(f"<b># {document.document_number}</b><br/>Date: {document.document_date}<br/>Valid Until: {document.valid_until or 'N/A'}", ParagraphStyle('DocNum', parent=styles['Normal'], fontSize=9, leading=12, alignment=2))
            ]

            header_data = [[left_cell, right_cell]]
            header_table = Table(header_data, colWidths=[280, 224])
            header_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ]))
            story.append(header_table)
            story.append(Spacer(1, 15))

            # Customer & Document Details Grid
            cust_html = (
                f"<b>Billed To:</b><br/>"
                f"<b>{document.customer_name or 'Valued Customer'}</b><br/>"
                f"{document.customer_company or ''}<br/>"
                f"Email: {document.customer_email or 'N/A'}<br/>"
                f"Phone: {document.customer_phone or 'N/A'}<br/>"
                f"Tax ID: {document.tax_number or 'N/A'}"
            )

            details_html = (
                f"<b>Commercial Overview:</b><br/>"
                f"Currency: <b>{cur_code} ({cur_sym})</b><br/>"
                f"Salesperson: {document.salesperson.username if document.salesperson else 'System'}<br/>"
                f"Ref Number: {document.reference_number or 'N/A'}<br/>"
                f"Status: <b><font color='{primary_color}'>{document.status}</font></b>"
            )

            meta_table = Table(
                [[Paragraph(cust_html, styles['Normal']), Paragraph(details_html, styles['Normal'])]],
                colWidths=[250, 254]
            )
            meta_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('BACKGROUND', (0,0), (-1,-1), colors.HexColor('#F8FAFC')),
                ('PADDING', (0,0), (-1,-1), 10),
                ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ]))
            story.append(meta_table)
            story.append(Spacer(1, 15))
            
            # Line items table
            SalesDocumentPDFService._build_items_table(document, story, styles, bold_label_style, right_bold_style, right_text_style, primary_color)

            # Terms & Notes
            story.append(Spacer(1, 15))
            bottom_data = [
                [
                    Paragraph("<b>Customer Notes:</b>", bold_label_style),
                    Paragraph("<b>Terms & Conditions:</b>", bold_label_style)
                ],
                [
                    Paragraph(document.customer_notes or "Thank you for your business!", ParagraphStyle('NotesText', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.HexColor('#475569'))),
                    Paragraph(document.terms_conditions or "1. Payment is due as per agreed terms.\n2. Goods/Services subject to warranty rules.", ParagraphStyle('TermsText', parent=styles['Normal'], fontSize=8, leading=11, textColor=colors.HexColor('#475569')))
                ]
            ]
            bottom_table = Table(bottom_data, colWidths=[250, 254])
            bottom_table.setStyle(TableStyle([
                ('VALIGN', (0,0), (-1,-1), 'TOP'),
                ('TOPPADDING', (0,0), (-1,-1), 2),
                ('BOTTOMPADDING', (0,0), (-1,-1), 4),
            ]))
            story.append(KeepTogether([
                Spacer(1, 10),
                bottom_table
            ]))

        # Resolve white-label brand name (no UWO footprint for agency sub-clients)
        _client = document.client if document.client else None
        _agency = getattr(_client, 'parent_agency', None) if _client else None
        if _agency and getattr(_agency, 'white_label_name', None):
            _brand_label = f"{_agency.white_label_name} — Official Sales Document"
        elif _client and getattr(_client, 'white_label_name', None):
            _brand_label = f"{_client.white_label_name} — Official Sales Document"
        elif _client and getattr(_client, 'business_name', None):
            _brand_label = f"{_client.business_name} — Official Sales Document"
        else:
            _brand_label = "Official Sales Document"

        def on_first_page(canvas, doc):
            canvas._is_proposal = is_proposal
            canvas._brand_name = _brand_label

        def on_later_pages(canvas, doc):
            canvas._is_proposal = is_proposal
            canvas._brand_name = _brand_label

        doc.build(story, canvasmaker=NumberedCanvas, onFirstPage=on_first_page, onLaterPages=on_later_pages)
        buffer.seek(0)
        return buffer

    @staticmethod
    def _build_items_table(document, story, styles, bold_label_style, right_bold_style, right_text_style, primary_color='#059669'):
        cur_sym = document.currency_symbol or SalesDocumentPDFService.get_currency_symbol(document.currency)
        cur_code = document.currency or 'USD'

        items_data = [[
            Paragraph("Item Description", bold_label_style),
            Paragraph("Qty", bold_label_style),
            Paragraph(f"Unit Price ({cur_code})", right_bold_style),
            Paragraph(f"Disc ({cur_code})", right_bold_style),
            Paragraph(f"Tax ({cur_code})", right_bold_style),
            Paragraph(f"Total ({cur_code})", right_bold_style)
        ]]

        items = document.items.all()
        if not items.exists():
            items_data.append([
                Paragraph("Product / Service Item", styles['Normal']),
                Paragraph("1", styles['Normal']),
                Paragraph(f"{cur_sym}{float(document.subtotal or 0):,.2f}", right_text_style),
                Paragraph(f"{cur_sym}0.00", right_text_style),
                Paragraph(f"{cur_sym}{float(document.tax_amount or 0):,.2f}", right_text_style),
                Paragraph(f"{cur_sym}{float(document.grand_total or 0):,.2f}", right_text_style),
            ])
        else:
            for item in items:
                items_data.append([
                    Paragraph(f"<b>{item.name}</b><br/><font color='#64748B' size=7>{item.description or ''}</font>", styles['Normal']),
                    Paragraph(str(item.quantity), styles['Normal']),
                    Paragraph(f"{cur_sym}{float(item.unit_price):,.2f}", right_text_style),
                    Paragraph(f"{cur_sym}{float(item.discount_value if item.discount_type == 'FIXED' else (float(item.unit_price)*float(item.quantity)*(float(item.discount_value)/100))):,.2f}", right_text_style),
                    Paragraph(f"{cur_sym}{float(item.tax_amount):,.2f}", right_text_style),
                    Paragraph(f"{cur_sym}{float(item.line_total):,.2f}", right_text_style),
                ])

        items_table = Table(items_data, colWidths=[184, 40, 70, 70, 70, 70])
        items_table.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,0), colors.HexColor('#F1F5F9')),
            ('ALIGN', (1,0), (1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor('#E2E8F0')),
            ('PADDING', (0,0), (-1,-1), 6),
        ]))
        story.append(items_table)
        story.append(Spacer(1, 10))

        # Financial Calculations Summary
        subtotal = float(document.subtotal or 0)
        disc_amt = float(document.discount_amount or 0)
        tax_amt = float(document.tax_amount or 0)
        charges = float(document.additional_charges or 0)
        grand = float(document.grand_total or subtotal - disc_amt + tax_amt + charges)

        summary_data = [
            [Paragraph("Subtotal:", right_text_style), Paragraph(f"{cur_sym}{subtotal:,.2f}", right_text_style)],
        ]
        if disc_amt > 0:
            summary_data.append([Paragraph("Discount:", right_text_style), Paragraph(f"-{cur_sym}{disc_amt:,.2f}", right_text_style)])
        if tax_amt > 0:
            summary_data.append([Paragraph("Tax / GST:", right_text_style), Paragraph(f"{cur_sym}{tax_amt:,.2f}", right_text_style)])
        if charges > 0:
            summary_data.append([Paragraph("Additional Charges:", right_text_style), Paragraph(f"{cur_sym}{charges:,.2f}", right_text_style)])

        summary_data.append([
            Paragraph("<b>Grand Total:</b>", right_text_style),
            Paragraph(f"<b><font size=11 color='{primary_color}'>{cur_sym}{grand:,.2f} {cur_code}</font></b>", right_text_style)
        ])

        summary_table = Table(summary_data, colWidths=[384, 120])
        summary_table.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'RIGHT'),
            ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
            ('LEFTPADDING', (0,0), (-1,-1), 0),
            ('RIGHTPADDING', (0,0), (-1,-1), 0),
            ('TOPPADDING', (0,0), (-1,-1), 3),
            ('BOTTOMPADDING', (0,0), (-1,-1), 3),
            ('LINEABOVE', (0,-1), (1,-1), 1, colors.HexColor(primary_color)),
        ]))
        story.append(KeepTogether(summary_table))
