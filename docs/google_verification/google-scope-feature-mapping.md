# Google OAuth Scope-to-Feature Mapping & Justification

**Application:** UWOConnect  
**Document Purpose:** Detailed technical justification for each retained Google OAuth scope, demonstrating why the scope is essential to user-facing features and why narrower permissions are technically insufficient.

---

## 1. Scope-to-Feature Technical Matrix

### Scope 1: `https://www.googleapis.com/auth/spreadsheets`
- **Google API:** Google Sheets API v4
- **Risk Category:** Sensitive
- **User-Facing Feature:** **Real-Time CRM Leads & E-Commerce Orders Sync to Spreadsheets**
- **Specific API Endpoints Used:**
  - `GET https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}`
  - `POST https://sheets.googleapis.com/v4/spreadsheets`
  - `GET https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values/{range}`
  - `POST https://sheets.googleapis.com/v4/spreadsheets/{spreadsheetId}/values/{range}:append`
- **Technical Justification:**
  UWOConnect allows business users to designate Google Spreadsheets as target data repositories for incoming customer leads, live chat inquiries, and product order transactions. When a lead or order occurs, UWOConnect queries existing sheet headers (`values.get`) to map column names and appends the new record row (`values.append`).
- **Why Narrower Scopes Cannot Satisfy Requirement:**
  - `spreadsheets.readonly`: Insufficient because the application writes new lead and order rows.
  - `drive.file`: Alone is insufficient because it only allows access to files created by the application; business users connect existing spreadsheets from their Google Drive. Therefore, `https://www.googleapis.com/auth/spreadsheets` is strictly necessary.

---

### Scope 2: `https://www.googleapis.com/auth/gmail.modify`
- **Google API:** Gmail API v1
- **Risk Category:** Restricted
- **User-Facing Feature:** **Omnichannel Support Inbox, Customer Triage & AI Auto-Reply**
- **Specific API Endpoints Used:**
  - `GET https://gmail.googleapis.com/gmail/v1/users/me/messages`
  - `GET https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}`
  - `POST https://gmail.googleapis.com/gmail/v1/users/me/messages/send`
  - `POST https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}/modify`
  - `GET https://gmail.googleapis.com/gmail/v1/users/me/labels`
- **Technical Justification:**
  UWOConnect consolidates customer communications across WhatsApp, Instagram, Facebook, and Gmail into a single unified business inbox. Agents and automated AI copilot bots read incoming customer inquiries, send threaded responses, and update message labels (e.g., "Handled", "Needs Attention", "In Review") and read/unread status.
- **Why Narrower Scopes Cannot Satisfy Requirement:**
  - `gmail.send`: Can only dispatch emails; cannot read incoming customer questions or manage conversation threads.
  - `gmail.readonly`: Can only read emails; cannot dispatch customer responses or update triage labels.
  - `mail.google.com` (Full Mailbox Access): Excessive and violates least privilege because it allows permanent deletion of messages. `gmail.modify` is the exact scope approved by Google for customer service inbox management without granting destructive deletion rights.

---

### Scope 3: `https://www.googleapis.com/auth/presentations`
- **Google API:** Google Slides API v1
- **Risk Category:** Sensitive
- **User-Facing Feature:** **Automated Sales Pitch Deck & Proposal Generator**
- **Specific API Endpoints Used:**
  - `POST https://slides.googleapis.com/v1/presentations`
  - `GET https://slides.googleapis.com/v1/presentations/{presentationId}`
  - `POST https://slides.googleapis.com/v1/presentations/{presentationId}:batchUpdate`
- **Technical Justification:**
  Sales teams using UWOConnect generate tailored client proposals and sales pitch decks directly from deal information in CRM. The platform clones master slide templates, substitutes client placeholders with personalized data, inserts dynamic product screenshots, and saves the presentation into the user's Google Drive.
- **Why Narrower Scopes Cannot Satisfy Requirement:**
  - `presentations.readonly`: Insufficient because presentations must be created and modified with new slide elements and text runs.

---

### Scope 4: `https://www.googleapis.com/auth/documents`
- **Google API:** Google Docs API v1
- **Risk Category:** Sensitive
- **User-Facing Feature:** **Automated Client Contracts, Proposals & Service Agreements**
- **Specific API Endpoints Used:**
  - `POST https://docs.googleapis.com/v1/documents`
  - `GET https://docs.googleapis.com/v1/documents/{documentId}`
  - `POST https://docs.googleapis.com/v1/documents/{documentId}:batchUpdate`
- **Technical Justification:**
  UWOConnect generates legal agreements, statements of work (SOW), and custom client proposals. The backend creates a Google Doc and executes `batchUpdate` requests (such as `insertText`, `updateTextStyle`, `insertTable`) to render customized agreements for client signing.
- **Why Narrower Scopes Cannot Satisfy Requirement:**
  - `documents.readonly`: Insufficient because documents are dynamically created and populated.

---

### Scope 5: `https://www.googleapis.com/auth/calendar` & `https://www.googleapis.com/auth/calendar.events`
- **Google API:** Google Calendar API v3
- **Risk Category:** Sensitive
- **User-Facing Feature:** **Two-Way Appointment Booking & Availability Synchronization**
- **Specific API Endpoints Used:**
  - `POST https://www.googleapis.com/calendar/v3/freeBusy`
  - `GET https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events`
  - `POST https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events`
  - `PATCH https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events/{eventId}`
  - `DELETE https://www.googleapis.com/calendar/v3/calendars/{calendarId}/events/{eventId}`
- **Technical Justification:**
  UWOConnect powers real-time appointment booking widgets. To prevent double-booking, the system queries real-time availability on the user's primary calendar (`freeBusy.query`). When a client books a slot, UWOConnect schedules the event, creates an automated Google Meet conference link, and sends calendar invites. Rescheduled or cancelled appointments update or remove the corresponding event.
- **Least-Privilege Note:**
  - `calendar.calendars` was **REMOVED** because UWOConnect does not alter calendar container metadata or secondary calendar lists.
  - `calendar` is retained for `freeBusy` schedule queries, and `calendar.events` handles the event lifecycle.

---

### Scope 6: `https://www.googleapis.com/auth/youtube.readonly`
- **Google API:** YouTube Data API v3
- **Risk Category:** Non-Sensitive
- **User-Facing Feature:** **YouTube Channel Analytics Dashboard & Audience Monitoring**
- **Specific API Endpoints Used:**
  - `GET https://www.googleapis.com/youtube/v3/channels?mine=true`
  - `GET https://www.googleapis.com/youtube/v3/videos`
  - `GET https://www.googleapis.com/youtube/v3/commentThreads`
- **Technical Justification:**
  Allows channel owners to monitor viewer engagement, track subscriber growth, and view incoming comments across their published videos directly from the UWOConnect multichannel dashboard.
- **Least-Privilege Note:**
  Read-only access strictly adheres to least-privilege principles.

---

### Scope 7: `https://www.googleapis.com/auth/youtube.upload`
- **Google API:** YouTube Data API v3
- **Risk Category:** Sensitive
- **User-Facing Feature:** **Direct Product Demo & Marketing Video Publishing**
- **Specific API Endpoints Used:**
  - `POST https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable`
- **Technical Justification:**
  Content creators and sales teams using UWOConnect can publish recorded product tutorials, demo walkthroughs, and onboarding videos directly to their YouTube channel from the media asset manager.
- **Why Narrower Scopes Cannot Satisfy Requirement:**
  No narrower scope exists in the YouTube Data API to upload video assets. This granular scope is strictly narrower than the full `https://www.googleapis.com/auth/youtube` scope.

---

### Scope 8: `https://www.googleapis.com/auth/youtube.force-ssl`
- **Google API:** YouTube Data API v3
- **Risk Category:** Sensitive
- **User-Facing Feature:** **AI Community Comment Moderation & Customer Inquiry Replies**
- **Specific API Endpoints Used:**
  - `POST https://www.googleapis.com/youtube/v3/comments?part=snippet`
  - `POST https://www.googleapis.com/youtube/v3/comments/setModerationStatus`
- **Technical Justification:**
  Allows businesses to automatically or manually reply to customer inquiries under YouTube videos (e.g., pricing questions, support links) and moderate spam or abusive comments.
- **Why Narrower Scopes Cannot Satisfy Requirement:**
  Google's YouTube Data API v3 explicitly mandates `https://www.googleapis.com/auth/youtube.force-ssl` to execute `comments.insert`. No read-only or narrower scope permits posting comment replies.

---

## 2. Removed Scopes Summary

| Removed Scope | Reason for Removal | Replacement Action |
|---|---|---|
| `https://www.googleapis.com/auth/calendar.calendars` | Least-privilege violation; application only manages events on primary calendar. | **Permanently removed.** Use `calendar.events` and `calendar` only. |
| `https://www.googleapis.com/auth/youtube` (Full) | Overly broad scope that was previously requested alongside granular scopes. | **Permanently removed.** Replaced by granular `youtube.readonly`, `youtube.upload`, and `youtube.force-ssl`. |
