from ..services.admin_service import AdminService
import threading
from ..repositories.template_repository import TemplateRepository
from ..repositories.campaign_repository import CampaignRepository
from ..repositories.client_repository import ClientRepository
from ..permissions.custom_permissions import IsApprovedUser
from rest_framework import status, views, viewsets
from rest_framework.response import Response
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from firebase_admin import auth as firebase_auth
from django.contrib.auth import authenticate
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.decorators import action
from rest_framework.views import APIView
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from ..serializers import RegisterSerializer, UserSerializer, ClientSerializer, AutomationSerializer, WorkflowSerializer, ContactSerializer, TemplateSerializer, CampaignSerializer, SupportMessageSerializer, AuditLogSerializer, TeamInviteSerializer, ProductSerializer, OrderSerializer
from ..models import User, Client, Automation, Message, Workflow, KnowledgeDocument, KnowledgeChunk, Contact, Template, Campaign, SupportMessage, AuditLog, TeamInvite, Product, Order
import requests
import os
import json
from ..services.ai_service import get_ai_response, get_platform_assistance, get_rag_response, get_embedding, chunk_text, find_relevant_chunks
from rest_framework.permissions import BasePermission

def get_tenant_client(request):
    if not request.user or not request.user.is_authenticated:
        return None
    if getattr(request.user, 'role', '') == 'ADMIN':
        client_id = request.query_params.get('client_id') if hasattr(request, 'query_params') else None
        if not client_id and isinstance(getattr(request, 'data', None), dict):
            client_id = request.data.get('client_id')
        if client_id:
            try:
                return ClientRepository.get_client(id=client_id)
            except Exception:
                pass
        return getattr(request.user, 'client', None)
    return getattr(request.user, 'client', None)

class TemplateViewSet(viewsets.ModelViewSet):
    serializer_class = TemplateSerializer
    permission_classes = [IsApprovedUser]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if self.request.user.role == 'ADMIN' and not client:
            return Template.objects.none()
        return TemplateRepository.filter_templates(client=client)

    def perform_create(self, serializer):
        client = get_tenant_client(self.request)
        instance = serializer.save(client=client)
        AdminService.log_admin_action(self.request, instance, 'Templates', 'CREATE', after_value=str(serializer.data))

    def perform_update(self, serializer):
        before_instance = self.get_object()
        before_data = str(self.get_serializer(before_instance).data)
        instance = serializer.save()
        AdminService.log_admin_action(self.request, instance, 'Templates', 'UPDATE', before_value=before_data, after_value=str(serializer.data))

    def perform_destroy(self, instance):
        before_data = str(self.get_serializer(instance).data)
        AdminService.log_admin_action(self.request, instance, 'Templates', 'DELETE', before_value=before_data)
        instance.delete()

    @action(detail=False, methods=['post'])
    def sync_from_meta(self, request):
        client = get_tenant_client(request) or request.user.client
        token = client.whatsapp_access_token
        if not client.whatsapp_waba_id or not token:
            return Response({"message": "WhatsApp WABA ID or Access Token is missing in client settings."}, status=400)
        
        url = f"https://graph.facebook.com/v19.0/{client.whatsapp_waba_id}/message_templates"
        headers = {
            "Authorization": f"Bearer {token}"
        }
        try:
            res = requests.get(url, headers=headers)
            data = res.json()
            if 'data' in data:
                unique_keys = set()
                for tmpl in data['data']:
                    name = tmpl.get('name')
                    lang = tmpl.get('language')
                    if not name:
                        continue
                    Template.objects.update_or_create(
                        client=client,
                        name=name,
                        language=lang,
                        defaults={
                            'category': tmpl.get('category'),
                            'status': tmpl.get('status'),
                            'components': tmpl.get('components', [])
                        }
                    )
                    unique_keys.add((name, lang))
                synced_count = len(unique_keys)
                return Response({"message": f"Successfully synced {synced_count} unique approved templates from Meta."})
            return Response({"message": "Failed to fetch templates from Meta.", "details": data}, status=400)
        except Exception as e:
            return Response({"message": str(e)}, status=500)


def extract_recipients_from_spreadsheet(file_obj, filename=""):
    """
    Parses an uploaded file (.xlsx, .xls, .csv) and extracts:
    - Phone numbers (sanitized, formatted e.g. 919876543210, deduplicated)
    - Names (from corresponding column or fallback)
    Returns: (total_rows, valid_recipients, invalid_rows)
    """
    import io, csv, re

    lower_name = (filename or getattr(file_obj, 'name', '') or '').lower()
    raw_rows = []

    if lower_name.endswith('.csv') or lower_name.endswith('.txt'):
        try:
            content = file_obj.read()
            if isinstance(content, bytes):
                try:
                    text = content.decode('utf-8-sig')
                except UnicodeDecodeError:
                    text = content.decode('latin-1')
            else:
                text = str(content)
            csv_file = io.StringIO(text)
            reader = csv.reader(csv_file)
            raw_rows = [row for row in reader if any(cell.strip() for cell in row)]
        except Exception as e:
            raise ValueError(f"Error reading CSV file: {str(e)}")
    else:
        try:
            import openpyxl
            wb = openpyxl.load_workbook(file_obj, data_only=True)
            sheet = wb.active
            for row in sheet.iter_rows(values_only=True):
                if row and any(cell is not None and str(cell).strip() for cell in row):
                    raw_rows.append([str(cell).strip() if cell is not None else '' for cell in row])
        except Exception as e:
            # Fallback to CSV text reader
            try:
                file_obj.seek(0)
                content = file_obj.read()
                text = content.decode('utf-8-sig', errors='ignore') if isinstance(content, bytes) else str(content)
                csv_file = io.StringIO(text)
                reader = csv.reader(csv_file)
                raw_rows = [row for row in reader if any(cell.strip() for cell in row)]
            except Exception:
                raise ValueError(f"Could not read spreadsheet file. Please upload a valid .xlsx or .csv file.")

    if not raw_rows:
        return 0, [], []

    # Identify header vs data rows
    first_row = [str(c).strip().lower() for c in raw_rows[0]]
    phone_idx = -1
    name_idx = -1

    phone_keywords = ['phone', 'mobile', 'contact', 'whatsapp', 'number', 'cell', 'tel', 'ph']
    name_keywords = ['name', 'customer', 'client', 'lead', 'full name', 'first name', 'person']

    for idx, cell_text in enumerate(first_row):
        if phone_idx == -1 and any(kw in cell_text for kw in phone_keywords):
            phone_idx = idx
        if name_idx == -1 and any(kw in cell_text for kw in name_keywords):
            name_idx = idx

    has_header = (phone_idx != -1 or name_idx != -1)
    data_rows = raw_rows[1:] if has_header else raw_rows

    # Fallback: scan columns for majority 10-15 digit values
    if phone_idx == -1:
        col_scores = {}
        for row in data_rows[:20]:
            for c_idx, cell in enumerate(row):
                digits = re.sub(r'\D', '', str(cell))
                if 10 <= len(digits) <= 15:
                    col_scores[c_idx] = col_scores.get(c_idx, 0) + 1
        if col_scores:
            phone_idx = max(col_scores, key=col_scores.get)
        else:
            phone_idx = 0

    if name_idx == -1:
        for c_idx in range(len(raw_rows[0])):
            if c_idx != phone_idx:
                name_idx = c_idx
                break

    valid_recipients = []
    invalid_rows = []
    seen_numbers = set()

    for r_idx, row in enumerate(data_rows):
        raw_phone = row[phone_idx] if phone_idx < len(row) else ''
        raw_name = row[name_idx] if name_idx != -1 and name_idx < len(row) else ''

        digits = re.sub(r'\D', '', str(raw_phone))

        # Standardize phone numbers (10 digits -> Indian standard 91XXXXXXXXXX)
        if len(digits) == 10:
            clean_phone = f"91{digits}"
        elif len(digits) == 11 and digits.startswith('0'):
            clean_phone = f"91{digits[1:]}"
        elif 11 <= len(digits) <= 15:
            clean_phone = digits
        else:
            clean_phone = None

        if clean_phone:
            if clean_phone not in seen_numbers:
                seen_numbers.add(clean_phone)
                clean_name = str(raw_name).strip() if raw_name else f"Contact #{clean_phone[-4:]}"
                valid_recipients.append({
                    'name': clean_name,
                    'phone': clean_phone,
                    'raw_phone': str(raw_phone).strip()
                })
        else:
            if any(str(c).strip() for c in row):
                invalid_rows.append({
                    'row_index': r_idx + (2 if has_header else 1),
                    'raw_phone': str(raw_phone).strip(),
                    'reason': 'Invalid phone number (must be 10-15 digits)'
                })

    return len(data_rows), valid_recipients, invalid_rows


class CampaignViewSet(viewsets.ModelViewSet):
    serializer_class = CampaignSerializer
    permission_classes = [IsApprovedUser]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if self.request.user.role == 'ADMIN' and not client:
            return Campaign.objects.none()
        return CampaignRepository.filter_campaigns(client=client).order_by('-created_at')

    @action(detail=False, methods=['post'], parser_classes=[MultiPartParser, FormParser, JSONParser])
    def parse_excel(self, request):
        """
        Parses an uploaded Excel (.xlsx, .xls) or CSV (.csv) file.
        Extracts phone numbers, names, cleans formatting, and returns preview.
        """
        file_obj = request.FILES.get('file') or request.FILES.get('excel') or request.FILES.get('spreadsheet')
        if not file_obj:
            # Check if raw text / CSV data was pasted
            csv_text = request.data.get('csv_text')
            if csv_text and isinstance(csv_text, str):
                import io
                file_obj = io.BytesIO(csv_text.encode('utf-8'))
                file_obj.name = "pasted_data.csv"
            else:
                return Response(
                    {"error": "No file uploaded. Please upload a .xlsx, .xls, or .csv file."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        filename = getattr(file_obj, 'name', '')
        try:
            total_rows, valid_recipients, invalid_rows = extract_recipients_from_spreadsheet(file_obj, filename)
            return Response({
                "filename": filename,
                "total_rows": total_rows,
                "valid_count": len(valid_recipients),
                "invalid_count": len(invalid_rows),
                "preview": valid_recipients[:5],
                "recipients": valid_recipients,
                "sample_invalid": invalid_rows[:3] if invalid_rows else []
            })
        except Exception as e:
            return Response({"error": f"Failed to parse spreadsheet: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

    def perform_create(self, serializer):
        from django.utils import timezone
        client = get_tenant_client(self.request)

        # Resolve template from request data (support 'template', 'template_id', and 'template_name')
        template_id = self.request.data.get('template') or self.request.data.get('template_id')
        template_name = self.request.data.get('template_name')
        template_obj = None
        if template_id:
            try:
                template_obj = Template.objects.get(id=template_id)
            except Exception as ex:
                print(f"Error resolving template ID {template_id}: {ex}")
        elif template_name:
            try:
                template_obj = Template.objects.filter(client=client, name=template_name).first()
            except Exception as ex:
                print(f"Error resolving template name {template_name}: {ex}")

        # Determine channel and platforms - Broadcasts strictly route through WhatsApp Cloud API
        platforms = ['WHATSAPP']
        channel = 'WHATSAPP'

        # Handle imported recipients from Excel/CSV if provided
        imported_recipients = self.request.data.get('imported_recipients') or []
        created_contact_ids = []
        if imported_recipients and isinstance(imported_recipients, list):
            camp_name = serializer.validated_data.get('name', 'Excel Broadcast')
            camp_tag = f"Excel: {camp_name}"
            from ..models import Contact
            for r in imported_recipients:
                r_phone = str(r.get('phone') or '').strip()
                r_name = str(r.get('name') or '').strip() or f"Contact #{r_phone[-4:] if len(r_phone) >= 4 else 'Lead'}"
                if not r_phone:
                    continue
                try:
                    ct, _ = Contact.objects.get_or_create(
                        client=client,
                        platform_id=r_phone,
                        defaults={
                            'name': r_name,
                            'phone_number': r_phone,
                            'stage': 'NEW',
                            'tags': [camp_tag],
                        }
                    )
                    tags = list(getattr(ct, 'tags', []) or [])
                    if camp_tag not in tags:
                        tags.append(camp_tag)
                        ct.tags = tags
                        ct.save(update_fields=['tags'])
                    created_contact_ids.append(str(ct.id))
                except Exception as ct_err:
                    print(f"Error upserting contact for imported phone {r_phone}: {ct_err}")

        msg_content = (
            self.request.data.get('message') or 
            self.request.data.get('message_body') or 
            self.request.data.get('body') or 
            serializer.validated_data.get('message_body') or 
            serializer.validated_data.get('body') or 
            ''
        )
        scheduled_at = serializer.validated_data.get('scheduled_at')
        extra_kwargs = {
            'client': client,
            'template': template_obj,
            'channel': channel,
            'platforms': platforms,
        }
        if msg_content:
            extra_kwargs['message_body'] = msg_content
            extra_kwargs['body'] = msg_content

        if created_contact_ids:
            extra_kwargs['tags'] = created_contact_ids
            extra_kwargs['audience_filter'] = 'SPECIFIC'
            extra_kwargs['total_recipients'] = len(created_contact_ids)

        if scheduled_at and scheduled_at > timezone.now():
            campaign = serializer.save(**extra_kwargs, status='SCHEDULED')
        else:
            campaign = serializer.save(**extra_kwargs, status='SENDING')

        # Create optional follow-up
        delay_hours = self.request.data.get('followup_delay_hours')
        followup_template_id = self.request.data.get('followup_template_id')
        if delay_hours and followup_template_id:
            from ..models import CampaignFollowUp, Template
            fu_template = Template.objects.filter(id=followup_template_id, client=client).first()
            if fu_template:
                CampaignFollowUp.objects.create(
                    campaign=campaign,
                    delay_hours=int(delay_hours),
                    followup_template=fu_template
                )

        AdminService.log_admin_action(self.request, campaign, 'Campaigns', 'CREATE', after_value=str(serializer.data))
        if campaign.status == 'SENDING':
            thread = threading.Thread(target=self.process_campaign, args=(campaign.id,))
            thread.start()


    def perform_update(self, serializer):
        before_instance = self.get_object()
        before_data = str(self.get_serializer(before_instance).data)
        instance = serializer.save()
        AdminService.log_admin_action(self.request, instance, 'Campaigns', 'UPDATE', before_value=before_data, after_value=str(serializer.data))

    def perform_destroy(self, instance):
        before_data = str(self.get_serializer(instance).data)
        AdminService.log_admin_action(self.request, instance, 'Campaigns', 'DELETE', before_value=before_data)
        instance.delete()

    @action(detail=True, methods=['post'])
    def retry_failed(self, request, pk=None):
        campaign = self.get_object()
        contact_ids = request.data.get('contact_ids') # Optional list of specific contact IDs
        from ..services.campaign_service import CampaignService
        
        thread = threading.Thread(target=CampaignService.retry_failed_recipients, args=(campaign.id, contact_ids))
        thread.start()
        return Response({"message": "Retry process initiated for failed recipients."})

    @action(detail=False, methods=['post'])
    def ai_generate(self, request):
        prompt = request.data.get('prompt', '')
        action_type = request.data.get('action_type', 'generate') # generate, improve, translate, tone, fix_grammar
        tone = request.data.get('tone', 'professional')
        language = request.data.get('language', 'English')
        
        if not prompt:
            return Response({"error": "Prompt or message body is required"}, status=400)
            
        import re
        system_instruction = (
            "You are an expert copywriter. Output ONLY the raw final message/email body content. "
            "Never include preambles, introductory commentary (such as 'Certainly!', 'Here is a polished version:'), "
            "closing remarks (such as 'Feel free to...', 'Hope this helps!'), or wrapping quotation marks. "
            "Your entire output must be the message text itself, ready to send."
        )
        if action_type == 'improve':
            full_prompt = (
                f"Rewrite and polish this email message to be professional, clear, and engaging. "
                f"Output ONLY the final email body directly, with NO preambles, NO introductory commentary, and NO closing notes:\n\n{prompt}"
            )
        elif action_type == 'translate':
            full_prompt = f"Translate the following message accurately into {language}. Output ONLY the translated text:\n\n{prompt}"
        elif action_type == 'fix_grammar':
            full_prompt = f"Fix all spelling, punctuation, and grammar mistakes in this message while keeping its core meaning. Output ONLY the corrected text:\n\n{prompt}"
        elif action_type == 'tone':
            full_prompt = f"Rewrite this message in a {tone} tone. Output ONLY the rewritten text:\n\n{prompt}"
        else:
            full_prompt = f"Generate a compelling message based on this description. Output ONLY the message text:\n\n{prompt}"

        try:
            from ..services.ai_service import get_ai_response
            generated_text = get_ai_response(full_prompt, context=system_instruction)
            if not generated_text or "AI service is not configured" in generated_text:
                # Graceful smart polish fallback if OPENAI_API_KEY is not set
                cleaned = prompt.strip()
                if action_type == 'improve':
                    generated_text = f"Hello,\n\n{cleaned}\n\nBest regards,\nUWOConnect Team"
                elif action_type == 'fix_grammar':
                    generated_text = cleaned.capitalize()
                    if not generated_text.endswith(('.', '!', '?')):
                        generated_text += '.'
                else:
                    generated_text = cleaned
            else:
                # Clean any conversational preambles like "Certainly! Here's a polished version:"
                generated_text = re.sub(
                    r'^(?:certainly!?|sure!?|of course!?|here(?:[\'’]s| is| are)|below is)[\s\S]*?:(?:\r?\n)+',
                    '',
                    generated_text,
                    flags=re.IGNORECASE
                ).strip()
                # Clean any conversational closings like "Feel free to adjust any specifics!"
                generated_text = re.sub(
                    r'(?:\r?\n)+(?:feel free to|hope this helps|let me know if|please let me know|don\'t hesitate to)[\s\S]*$',
                    '',
                    generated_text,
                    flags=re.IGNORECASE
                ).strip()
                # Repeatedly clean divider lines (- or ---), bullets, and quotes
                changed = True
                while changed:
                    prev = generated_text
                    if generated_text.startswith("```"):
                        generated_text = re.sub(r'^```[a-zA-Z]*\n?', '', generated_text)
                        generated_text = re.sub(r'\n?```$', '', generated_text).strip()
                    generated_text = re.sub(r'^[-–—_*~•#\s]+(?:\r?\n)+', '', generated_text).strip()
                    generated_text = re.sub(r'^[-–—•]\s+', '', generated_text).strip()
                    if generated_text.startswith(('-', '–', '—')):
                        generated_text = re.sub(r'^[-–—_*~•\s]+', '', generated_text).strip()
                    generated_text = re.sub(r'(?:\r?\n)+[-–—_*~•#\s]+$', '', generated_text).strip()
                    if generated_text.endswith(('-', '–', '—')):
                        generated_text = re.sub(r'[-–—_*~•\s]+$', '', generated_text).strip()
                    if (generated_text.startswith('"') and generated_text.endswith('"')) or \
                       (generated_text.startswith('“') and generated_text.endswith('”')) or \
                       (generated_text.startswith("'") and generated_text.endswith("'")) or \
                       (generated_text.startswith('‘') and generated_text.endswith('’')):
                        generated_text = generated_text[1:-1].strip()
                    changed = (generated_text != prev)

            return Response({"result": generated_text, "action_type": action_type})
        except Exception as e:
            print(f"AI Generation View Error: {e}")
            cleaned = prompt.strip()
            fallback_res = f"Hello {{first_name}},\n\n{cleaned}\n\nExclusive broadcast update from UWOConnect!"
            return Response({"result": fallback_res, "action_type": action_type})

    def process_campaign(self, campaign_id):
        from ..services.campaign_service import CampaignService
        CampaignService.process_campaign(campaign_id)

