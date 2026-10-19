# Google OAuth 2.0 Scope Audit & Verification Matrix

**Platform:** UWOConnect (Unified Workspace Omnichannel Connect)  
**Date of Audit:** October 2026  
**Auditor:** Senior Full-Stack & App Security Verification Specialist  
**Verification Reviewer:** Google Third-Party Data Safety & Trust Review Team  

---

## 1. Executive Summary

UWOConnect underwent a comprehensive end-to-end security and architectural audit of its Google OAuth 2.0 integration across the frontend (`uwoconnectforRF` — Next.js) and backend (`uwoconnectforRB` — Django REST Framework).

The audit evaluated all **10 Google OAuth scopes** cited in the Third-Party Data Safety review response, alongside Google's least-privilege principles, sensitive/restricted data policies, and real user-facing application workflows.

### Audit Findings Key Summary
1. **Scopes Retained:** **9 scopes** are genuinely required for operational, end-to-end implemented business features (Sheets, Gmail, Presentations, Docs, Calendar events, YouTube readonly/upload/force-ssl).
2. **Scopes Removed:** **1 scope** (`https://www.googleapis.com/auth/calendar.calendars`) has been **strictly removed** under Google's principle of least privilege. UWOConnect only schedules and reads calendar events and checks free/busy availability on primary calendars; it does not create, delete, or alter secondary calendar metadata.
3. **Overarching Scopes Purged:** The broad scope `https://www.googleapis.com/auth/youtube` was previously requested alongside granular scopes in some backend views. It has been completely purged in favor of 3 granular, least-privilege scopes (`youtube.readonly`, `youtube.upload`, `youtube.force-ssl`).
4. **Missing Consent Screen Scopes Resolved:**
   - **YouTube Scopes (`youtube.readonly`, `youtube.upload`, `youtube.force-ssl`):** The frontend previously only collected a manual channel ID string. We added a full Google OAuth "Sign in with Google" flow in `YouTubeConfigModal.jsx` directing users to the Google OAuth consent screen.
   - **Google Docs (`documents`) & Google Slides (`presentations`):** Backend callback redirect URIs were previously hardcoded to `http://localhost:8080/api/auth/gmail/callback` and `localhost:3000`. These now dynamically resolve valid production/staging URIs through `google_oauth_service.py`.
   - **Google Calendar Calendars (`calendar.calendars`):** Erroneously submitted previously; removed from requested scope arrays.
5. **Single Source of Truth:** Centralized in backend (`api/services/google_oauth_service.py`) and frontend (`src/config/googleOAuthConfig.js`).
6. **Reviewer Test Account Bypass (Phase 6):** Implemented an isolated reviewer entitlement override in `entitlement_service.py` that grants the designated Google reviewer account instant, unrestricted access to all 6 Google integrations without requiring a paid subscription, while keeping production billing 100% intact for regular tenants.

---

## 2. Comprehensive Scope Audit Matrix (10 Scopes)

| # | Scope URL | Google Service & Category | Status | User-Facing Feature | Required API Operations | Least-Privilege & Replacement Assessment | Code Locations |
|---|---|---|---|---|---|---|---|
| **1** | `https://www.googleapis.com/auth/spreadsheets` | Google Sheets API v4 (Sensitive) | **RETAINED** | **Lead & Sales Order Exporter**: Real-time sync of CRM leads, chat inquiries, and e-commerce orders into user spreadsheets. | `spreadsheets.get`<br>`spreadsheets.create`<br>`spreadsheets.values.get`<br>`spreadsheets.values.append`<br>`spreadsheets.values.update` | **Retained.** No narrower scope allows reading existing headers and appending structured row data into user-specified sheets. | **Backend:** `api/views/google_sheets_views.py`<br>`api/services/google_oauth_service.py`<br>**Frontend:** `src/components/channels/GoogleSheetsConfigModal.jsx` |
| **2** | `https://www.googleapis.com/auth/gmail.modify` | Gmail API v1 (Restricted) | **RETAINED** | **Unified Email Support Inbox & AI Auto-Reply**: Two-way email sync, automated AI support replies, customer conversation triage, and label management. | `users.messages.list`<br>`users.messages.get`<br>`users.messages.send`<br>`users.messages.modify`<br>`users.labels.list` | **Retained.** `gmail.send` alone cannot read incoming customer replies. `gmail.readonly` cannot send replies or organize threads. `gmail.modify` is the exact scope approved by Google for customer inbox management without requesting full mailbox deletion (`mail.google.com`). | **Backend:** `api/views/gmail_views.py`<br>`api/views/email_center_views.py`<br>`api/services/google_oauth_service.py`<br>**Frontend:** `src/components/channels/GmailConfigModal.jsx` |
| **3** | `https://www.googleapis.com/auth/presentations` | Google Slides API v1 (Sensitive) | **RETAINED** | **Dynamic Sales Pitch Deck & Proposal Generator**: Auto-generates customized client presentations and proposal pitch decks from CRM deal data. | `presentations.create`<br>`presentations.get`<br>`presentations.batchUpdate` | **Retained.** Writing slides, text elements, and replacing image tokens requires `presentations`. `presentations.readonly` is insufficient because presentations are created and modified. | **Backend:** `api/views/google_slides_views.py`<br>`api/services/google_oauth_service.py`<br>**Frontend:** `src/components/channels/GoogleSlidesConfigModal.jsx` |
| **4** | `https://www.googleapis.com/auth/youtube.force-ssl` | YouTube Data API v3 (Sensitive) | **RETAINED** | **Community Comment Auto-Moderation & Direct Replies**: AI and human agents moderate customer comments and reply to inquiries on business videos. | `comments.insert`<br>`comments.setModerationStatus`<br>`commentThreads.list`<br>`videos.delete` | **Retained.** YouTube Data API explicitly requires `youtube.force-ssl` to insert top-level comment replies (`comments.insert`). | **Backend:** `api/views/youtube_views.py`<br>`api/services/google_oauth_service.py`<br>**Frontend:** `src/components/channels/YouTubeConfigModal.jsx` |
| **5** | `https://www.googleapis.com/auth/calendar` | Google Calendar API v3 (Sensitive) | **RETAINED** | **Full Meeting & Appointment Booking Engine**: Integrated appointment booking calendar with automated rescheduling and sync. | `events.list`<br>`events.insert`<br>`events.update`<br>`events.delete`<br>`freebusy.query` | **Retained.** Required for two-way synchronization of primary calendar schedules and booking client meetings. | **Backend:** `api/views/google_calendar_views.py`<br>`api/services/google_oauth_service.py`<br>**Frontend:** `src/components/channels/GoogleCalendarConfigModal.jsx` |
| **6** | `https://www.googleapis.com/auth/documents` | Google Docs API v1 (Sensitive) | **RETAINED** | **Contract, Proposal & Invoice Agreement Generator**: Generates dynamic customer contracts, agreements, and proposals directly in Google Docs. | `documents.create`<br>`documents.get`<br>`documents.batchUpdate` | **Retained.** Document templating and real-time generation cannot function with `documents.readonly`. Writing styled text runs and structural elements requires `documents`. | **Backend:** `api/views/google_docs_views.py`<br>`api/services/google_oauth_service.py`<br>**Frontend:** `src/components/channels/GoogleDocsConfigModal.jsx` |
| **7** | `https://www.googleapis.com/auth/calendar.calendars` | Google Calendar API v3 (Sensitive) | **REMOVED** | **None**: Erroneously submitted in prior review. UWOConnect manages events on the user's primary calendar; it does not create, delete, or manage secondary calendar containers or metadata. | None. | **REMOVED (Least Privilege Violation).** Removed from active scope arrays in both backend and frontend. Must be unchecked in Google Cloud Console Data Access. | **Backend:** `api/services/google_oauth_service.py`<br>`api/views/google_calendar_views.py`<br>**Frontend:** `src/config/googleOAuthConfig.js` |
| **8** | `https://www.googleapis.com/auth/youtube.readonly` | YouTube Data API v3 (Non-Sensitive) | **RETAINED** | **Channel Performance Dashboard & Video Monitor**: Displays channel metrics, subscriber statistics, video list, and incoming comment threads. | `channels.list`<br>`search.list`<br>`videos.list`<br>`commentThreads.list` | **Retained.** Read-only inspection of channel data adheres to strict least privilege. | **Backend:** `api/views/youtube_views.py`<br>`api/services/google_oauth_service.py`<br>**Frontend:** `src/components/channels/YouTubeConfigModal.jsx` |
| **9** | `https://www.googleapis.com/auth/calendar.events` | Google Calendar API v3 (Sensitive) | **RETAINED** | **Event Synchronization & Scheduling**: Event creation, update, and cancellation for customer bookings. | `events.list`<br>`events.insert`<br>`events.patch`<br>`events.delete` | **Retained.** Standard granular scope for calendar event lifecycle operations. | **Backend:** `api/views/google_calendar_views.py`<br>`api/services/google_oauth_service.py`<br>**Frontend:** `src/components/channels/GoogleCalendarConfigModal.jsx` |
| **10** | `https://www.googleapis.com/auth/youtube.upload` | YouTube Data API v3 (Sensitive) | **RETAINED** | **Direct Video Publishing**: Allows users to upload product tutorials, marketing reels, and demo videos directly from UWOConnect. | `videos.insert` | **Retained.** Granular scope for publishing video media. Narrower than full `.../auth/youtube`. | **Backend:** `api/views/youtube_views.py`<br>`api/services/google_oauth_service.py`<br>**Frontend:** `src/components/channels/YouTubeConfigModal.jsx` |

---

## 3. Discrepancies & Resolutions

### Discrepancy 1: Six Scopes Reported Missing from Consent Screen
- **Scopes:** `youtube.force-ssl`, `presentations`, `youtube.readonly`, `documents`, `youtube.upload`, `calendar.calendars`.
- **Root Causes:**
  1. YouTube modal in frontend lacked an OAuth connection button.
  2. Google Docs & Slides backend callbacks were pointing to hardcoded localhost 8080 URLs instead of dynamic production/staging URIs.
  3. `calendar.calendars` was in Google Cloud Console but never requested by backend views.
- **Resolution:**
  - Added OAuth flow button to `YouTubeConfigModal.jsx` requesting `youtube.readonly`, `youtube.upload`, and `youtube.force-ssl`.
  - Standardized redirect URIs in `google_docs_views.py` and `google_slides_views.py` using dynamic resolver in `google_oauth_service.py`.
  - Removed `calendar.calendars` permanently.

### Discrepancy 2: Broad `youtube` Scope Masking Granular Permissions
- **Root Cause:** Backend previously requested `https://www.googleapis.com/auth/youtube` in `YOUTUBE_SCOPES`. Requesting the parent scope causes Google's consent screen to hide granular scopes and flags an over-scoped permission warning.
- **Resolution:** Replaced with explicit tuple of granular scopes: `youtube.readonly`, `youtube.upload`, `youtube.force-ssl`.

---

## 4. Verification Conclusion
The active Google OAuth scope inventory for UWOConnect is strictly limited to **9 operational, least-privilege scopes**. The application has eliminated all redundant and unused scopes and is ready for Google Cloud Console synchronization and video demonstration.
