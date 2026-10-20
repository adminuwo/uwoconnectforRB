# Google OAuth 2.0 Verification Demo Video Script

**Application Name:** UWOConnect  
**Purpose:** Step-by-step recording guide for developers to record the official Google OAuth verification video.  
**Video Requirements:** Unlisted YouTube video, high resolution (1080p), showing full browser address bar and Google consent screen with all requested scopes clearly legible.

---

> [!IMPORTANT]
> **Recording Rules:**
> 1. Show the full browser window including the URL address bar at all times.
> 2. The client_id in the address bar during OAuth consent MUST be clearly visible and match the verified Google Cloud project client ID.
> 3. Click each permission accordion on the Google consent screen to expand it and make the explanation readable.
> 4. For every write operation, switch to the official Google application (e.g., sheets.google.com, docs.google.com, calendar.google.com, youtube.com) to visually verify the created/updated data.

---

## Pre-Recording Checklist
- [ ] Chrome profile opened with a clean Google test account (e.g., `uwoconnect.demo@gmail.com`).
- [ ] Tabs pre-opened:
  1. `https://uwoconnect.aisa24.com/login` (or staging URL)
  2. `https://mail.google.com`
  3. `https://calendar.google.com`
  4. `https://docs.google.com`
  5. `https://docs.google.com/presentation`
  6. `https://docs.google.com/spreadsheets`
  7. `https://studio.youtube.com`
- [ ] Screen recorder set to 1920x1080 at 30/60fps with clear microphone narration or captions.

---

## Scene-by-Scene Demonstration Script

### Scene 1: Introduction & Sign-in with Reviewer Account (0:00 - 0:45)
1. **Show:** UWOConnect login page (`https://uwoconnect.aisa24.com/login`).
2. **Action:** Log in using the designated verification account:
   - Email: `google-reviewer@uwoconnect.aisa24.com`
   - Password: `[DemoPassword]`
3. **Show:** Navigate to **Channels & Integrations** (`/client/channels`).
4. **Highlight:** Show that all Google connectors (Gmail, Google Sheets, Google Calendar, Google Docs, Google Slides, YouTube) are available in the reviewer workspace without any payment paywalls or subscription prompts.

---

### Scene 2: Google OAuth Authorization Consent Flow (0:45 - 2:00)
1. **Action:** Click **Connect** on any Google connector or visit the centralized authorization endpoint (`/api/auth/google/connect-all/` or individual modal).
2. **Critical Check:** Show the browser address bar navigating to `https://accounts.google.com/o/oauth2/v2/auth`.
3. **Highlight:**
   - Client ID parameter in the URL: `...apps.googleusercontent.com`
   - App Name: `UWOConnect`
   - App Logo & Privacy Policy link.
4. **Expand Scopes:** On the consent screen:
   - Click to expand each permission box so the reviewer can read each requested permission:
     - `View and modify your email (gmail.modify)`
     - `See, edit, create, and delete spreadsheets in Google Sheets (spreadsheets)`
     - `See, edit, create, and delete documents in Google Docs (documents)`
     - `See, edit, create, and delete presentations in Google Slides (presentations)`
     - `See, edit, share, and permanently delete all the calendars you can access using Google Calendar (calendar)`
     - `View, edit, and delete events on all your calendars (calendar.events)`
     - `View your YouTube account (youtube.readonly)`
     - `Manage your YouTube videos (youtube.upload)`
     - `Manage your YouTube comments (youtube.force-ssl)`
5. **Action:** Click **Allow / Continue** to complete authorization.
6. **Show:** Seamless redirection back to UWOConnect showing the "Active & Connected" status badges.

---

### Scene 3: Google Sheets Integration Demonstration (2:00 - 3:30)
1. **Scope:** `https://www.googleapis.com/auth/spreadsheets`
2. **In-App Action:**
   - In UWOConnect, open the **Google Sheets Connector Modal**.
   - Select or enter a target Google Spreadsheet (e.g., "UWOConnect Inquiries & Leads").
   - Click "Sync CRM Lead" or trigger an e-commerce order export.
3. **Source Verification:**
   - Switch to the open tab on `https://docs.google.com/spreadsheets`.
   - Show the newly appended row containing customer name, phone number, timestamp, and inquiry details appearing in real time.

---

### Scene 4: Gmail Integration Demonstration (3:30 - 5:00)
1. **Scope:** `https://www.googleapis.com/auth/gmail.modify`
2. **In-App Action:**
   - Open **UWO Email Inbox** (`/client/gmail`).
   - Show incoming customer emails synced from the connected Gmail account.
   - Reply to a support inquiry using AI Copilot or manual template: "Thank you for contacting UWOConnect. Your inquiry #104 has been received."
   - Click **Send**.
3. **Source Verification:**
   - Switch to `https://mail.google.com`.
   - Show the sent email in the "Sent" folder of the Gmail account.
   - Show the label updated or thread marked as read/handled.

---

### Scene 5: Google Calendar Integration Demonstration (5:00 - 6:30)
1. **Scopes:** `https://www.googleapis.com/auth/calendar`, `https://www.googleapis.com/auth/calendar.events`
2. **In-App Action:**
   - Open **UWO Appointments / Calendar** (`/client/calendar`).
   - Book a client consultation:
     - Title: "Product Demo & Onboarding Session"
     - Time: Tomorrow at 2:00 PM - 2:30 PM
     - Add meeting notes and attendee email.
   - Click **Confirm Booking**.
3. **Source Verification:**
   - Switch to `https://calendar.google.com`.
   - Show the new event at 2:00 PM tomorrow with Google Meet conference link and description populated.

---

### Scene 6: Google Docs & Google Slides Demonstration (6:30 - 8:00)
1. **Scopes:** `https://www.googleapis.com/auth/documents`, `https://www.googleapis.com/auth/presentations`
2. **Google Docs In-App Action:**
   - Open **Sales Documents > Agreements / Contracts**.
   - Click "Generate Google Doc Agreement" for deal "Enterprise Cloud Contract".
   - Show the generated Google Doc URL.
   - Open the URL in Google Docs (`https://docs.google.com`) and show the agreement content, client details, and pricing tables formatted.
3. **Google Slides In-App Action:**
   - Open **Sales Proposals > Pitch Decks**.
   - Click "Generate Pitch Deck in Google Slides".
   - Open the presentation on `https://docs.google.com/presentation` showing customized slides, client name token replaced, and branding applied.

---

### Scene 7: YouTube Integration Demonstration (8:00 - 9:30)
1. **Scopes:** `youtube.readonly`, `youtube.upload`, `youtube.force-ssl`
2. **In-App Action:**
   - Open the **YouTube Channel Modal** in UWOConnect.
   - Show channel statistics and video performance cards loaded via `youtube.readonly`.
   - Demonstrate comment auto-reply / manual response to a test viewer comment on a video using `youtube.force-ssl`.
   - (Optional) Demonstrate short test video upload using `youtube.upload`.
3. **Source Verification:**
   - Switch to `https://studio.youtube.com`.
   - Show the comment reply published under the video.

---

### Scene 8: Conclusion & Disconnect Handling (9:30 - 10:00)
1. **In-App Action:**
   - Click **Disconnect** on the connector modal.
   - Show that tokens are wiped from active session and connector status reverts cleanly to "Disconnected".
2. **Narration:**
   - "Thank you to the Google Trust & Safety Team for reviewing UWOConnect. All 9 requested scopes adhere strictly to least-privilege data access."
