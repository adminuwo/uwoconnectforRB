"""
Google Workspace AI Command View
Centralized AI intelligence bar for natural language execution across the Google ecosystem:
Gmail, Calendar, Drive, Docs, Sheets, and Slides.
"""
import json
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ..services.ai_service import _get_client
from ..services.google_calendar_service import ai_calendar_assistant
from ..services.google_docs_service import ai_generate_google_doc
from ..services.google_slides_service import ai_generate_google_presentation
from ..services.google_sheets_service import ai_generate_google_spreadsheet

logger = logging.getLogger(__name__)


class GoogleWorkspaceAICommandView(APIView):
    """
    POST /api/google/ai-command
    Executes or drafts an action based on natural language intent across Google Workspace.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = getattr(request.user, "client", None)
        if not client:
            return Response({"error": "No client associated with user."}, status=400)

        command = request.data.get("command", "").strip()
        if not command:
            return Response({"error": "Command string is required."}, status=400)

        ai_client = _get_client()
        sys_prompt = (
            "You are the central Google Workspace AI Commander for UWO Connect. "
            "Analyze the user's instruction and categorize it into exactly one target service:\n"
            "- 'CALENDAR': scheduling, meetings, appointments, calendar, availability, reminders\n"
            "- 'SLIDES': presentation, pitch deck, slides, slideshow, deck\n"
            "- 'DOCS': document, proposal, agreement, contract, report, minutes, letter, doc\n"
            "- 'SHEETS': spreadsheet, sheet, excel, tracker, rows, table, inventory, budget\n"
            "- 'GMAIL': email, send mail, compose, message, reply, inbox search\n"
            "- 'DRIVE': files, folder, upload, storage, drive\n\n"
            "Respond with a JSON object: {\"target\": \"SERVICE_NAME\", \"summary\": \"Clean action title\", \"prompt\": \"Extracted relevant details\"}\n"
            "Do not output markdown codeblocks, only pure JSON."
        )

        target = "DOCS"
        parsed_intent = None
        if ai_client:
            try:
                comp = ai_client.chat.completions.create(
                    model="gpt-4o-mini",
                    messages=[
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": command}
                    ],
                    temperature=0.2,
                    max_tokens=300,
                )
                raw = comp.choices[0].message.content.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:].strip()
                parsed_intent = json.loads(raw)
                target = parsed_intent.get("target", "DOCS").upper()
            except Exception as e:
                logger.error("AI Command parse error: %s", e)

        # Fallback keyword matching if parsing missed
        cmd_lower = command.lower()
        if any(w in cmd_lower for w in ["meeting", "schedule", "calendar", "call", "appointment", "tomorrow", "friday"]):
            target = "CALENDAR"
        elif any(w in cmd_lower for w in ["presentation", "slide", "pitch deck", "deck"]):
            target = "SLIDES"
        elif any(w in cmd_lower for w in ["sheet", "spreadsheet", "tracker", "excel", "table"]):
            target = "SHEETS"
        elif any(w in cmd_lower for w in ["email", "mail", "gmail", "inbox"]):
            target = "GMAIL"
        elif any(w in cmd_lower for w in ["folder", "file", "drive"]):
            target = "DRIVE"
        elif any(w in cmd_lower for w in ["doc", "document", "proposal", "contract", "report"]):
            target = "DOCS"

        # Execute on target service
        try:
            if target == "CALENDAR":
                if not client.google_calendar_enabled:
                    return Response({
                        "success": False,
                        "target": "CALENDAR",
                        "requires_connection": True,
                        "message": "Google Calendar is not connected. Please connect Google Calendar first.",
                        "connect_url": "/api/google-calendar/connect",
                    })
                cal_res = ai_calendar_assistant(client, command)
                return Response({
                    "success": cal_res.get("success", True),
                    "target": "CALENDAR",
                    "action": "EVENT_CREATED",
                    "title": cal_res.get("event", {}).get("summary") or "Calendar Event",
                    "meet_link": cal_res.get("event", {}).get("meetLink"),
                    "url": cal_res.get("event", {}).get("htmlLink"),
                    "details": cal_res.get("message"),
                })

            elif target == "SLIDES":
                if not client.google_slides_enabled:
                    return Response({
                        "success": False,
                        "target": "SLIDES",
                        "requires_connection": True,
                        "message": "Google Slides is not connected. Please connect Google Slides first.",
                        "connect_url": "/api/google-slides/connect",
                    })
                slides_res = ai_generate_google_presentation(client, command, slide_count=5)
                return Response({
                    "success": True,
                    "target": "SLIDES",
                    "action": "PRESENTATION_CREATED",
                    "title": slides_res.get("title"),
                    "url": slides_res.get("presentation_url"),
                    "resource_id": slides_res.get("presentation_id"),
                    "details": f"Created presentation '{slides_res.get('title')}' with {slides_res.get('slides_count')} slides.",
                })

            elif target == "SHEETS":
                if not client.google_sheets_enabled:
                    return Response({
                        "success": False,
                        "target": "SHEETS",
                        "requires_connection": True,
                        "message": "Google Sheets is not connected. Please connect Google Sheets first.",
                        "connect_url": "/api/google-sheets/connect",
                    })
                sheets_res = ai_generate_google_spreadsheet(client, command)
                return Response({
                    "success": True,
                    "target": "SHEETS",
                    "action": "SPREADSHEET_CREATED",
                    "title": sheets_res.get("title"),
                    "url": sheets_res.get("spreadsheet_url"),
                    "resource_id": sheets_res.get("spreadsheet_id"),
                    "details": f"Created spreadsheet '{sheets_res.get('title')}' with columns: {', '.join(sheets_res.get('headers', []))}.",
                })

            elif target == "DOCS":
                if not client.google_docs_enabled:
                    return Response({
                        "success": False,
                        "target": "DOCS",
                        "requires_connection": True,
                        "message": "Google Docs is not connected. Please connect Google Docs first.",
                        "connect_url": "/api/google-docs/connect",
                    })
                doc_res = ai_generate_google_doc(client, command)
                return Response({
                    "success": True,
                    "target": "DOCS",
                    "action": "DOCUMENT_CREATED",
                    "title": doc_res.get("title"),
                    "url": doc_res.get("doc_url"),
                    "resource_id": doc_res.get("doc_id"),
                    "details": f"Created document '{doc_res.get('title')}' in Google Docs.",
                })

            elif target == "GMAIL":
                if not client.gmail_enabled:
                    return Response({
                        "success": False,
                        "target": "GMAIL",
                        "requires_connection": True,
                        "message": "Gmail is not connected. Please connect Gmail first.",
                        "connect_url": "/api/auth/gmail/connect",
                    })
                # Draft email response
                return Response({
                    "success": True,
                    "target": "GMAIL",
                    "action": "COMPOSE_PREPARED",
                    "title": f"Draft email for: {command[:40]}",
                    "details": "Ready to compose. Opening Gmail composer workspace.",
                    "redirect_url": "/client/gmail",
                })

            elif target == "DRIVE":
                return Response({
                    "success": True,
                    "target": "DRIVE",
                    "action": "NAVIGATE_DRIVE",
                    "title": "Google Drive",
                    "details": "Navigating to Google Drive workspace.",
                    "redirect_url": "/client/drive",
                })

        except Exception as e:
            logger.error("Error executing AI command: %s", e)
            return Response({"error": str(e)}, status=500)
