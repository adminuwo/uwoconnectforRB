# Google Cloud Console — OAuth Verification Checklist

**Application Name:** UWOConnect  
**Auditor / Verification Engineer:** Senior Full-Stack Security Engineer  
**Target Review:** Google Third-Party Data Safety & Trust Review  

---

> [!IMPORTANT]
> **Manual Action Required:** Google Cloud Console settings cannot be modified via codebase files. An authorized project owner must perform the manual steps outlined in this checklist in the [Google Cloud Console](https://console.cloud.google.com/apis/credentials/consent).

---

## 1. OAuth Consent Screen Configuration

### A. Publishing Status
- [ ] Confirm the app is in **In Production** (or **Testing** if adding test accounts before re-verification).
- [ ] Ensure the **App Name** matches `UWOConnect` consistently with the domain and branding.
- [ ] Ensure **User Support Email** and **Developer Contact Information** are monitored inbox addresses.
- [ ] Verify Authorized Domains list contains:
  - `uwoconnect.aisa24.com`
  - `aisa24.com`
  - `run.app` (if using Cloud Run staging domain)

---

## 2. Data Access (Scopes) Configuration

Navigate to: **APIs & Services > OAuth consent screen > Edit App > Step 2: Scopes (Data Access)**.

### A. Scopes to RETAIN and Ensure are Checked
Ensure the following **9 active scopes** are explicitly added and saved in the Data Access list:

1. **Google Sheets API:**
   - `https://www.googleapis.com/auth/spreadsheets` (Sensitive)
2. **Gmail API:**
   - `https://www.googleapis.com/auth/gmail.modify` (Restricted)
3. **Google Slides API:**
   - `https://www.googleapis.com/auth/presentations` (Sensitive)
4. **Google Docs API:**
   - `https://www.googleapis.com/auth/documents` (Sensitive)
5. **Google Calendar API:**
   - `https://www.googleapis.com/auth/calendar` (Sensitive)
   - `https://www.googleapis.com/auth/calendar.events` (Sensitive)
6. **YouTube Data API v3:**
   - `https://www.googleapis.com/auth/youtube.readonly` (Non-Sensitive)
   - `https://www.googleapis.com/auth/youtube.upload` (Sensitive)
   - `https://www.googleapis.com/auth/youtube.force-ssl` (Sensitive)
7. **Identity Scopes (Non-Sensitive):**
   - `openid`
   - `.../auth/userinfo.email`
   - `.../auth/userinfo.profile`

---

### B. Scopes to REMOVE from Google Cloud Console (Least Privilege)
- [ ] **REMOVE:** `https://www.googleapis.com/auth/calendar.calendars`
  - *Rationale:* UWOConnect only schedules and modifies calendar events; it never creates or deletes secondary calendars. Removing this scope aligns with Google's least-privilege mandate.
- [ ] **REMOVE / UNCHECK (if present):** `https://www.googleapis.com/auth/youtube` (Full Access)
  - *Rationale:* Replaced with granular scopes (`youtube.readonly`, `youtube.upload`, `youtube.force-ssl`). Retaining full `youtube` triggers automatic verification rejection for excessive access.

---

## 3. OAuth 2.0 Client IDs & Authorized Redirect URIs

Navigate to: **APIs & Services > Credentials > OAuth 2.0 Client IDs**.

Select the Web Client used by UWOConnect and verify that the Authorized Redirect URIs list contains all of the following exact endpoints:

### Production Redirect URIs:
- [ ] `https://uwoconnect.aisa24.com/api/auth/gmail/callback`
- [ ] `https://uwoconnect.aisa24.com/api/auth/google-calendar/callback`
- [ ] `https://uwoconnect.aisa24.com/api/google-sheets/callback/`
- [ ] `https://uwoconnect.aisa24.com/api/google-sheets/callback`
- [ ] `https://uwoconnect.aisa24.com/api/google-docs/callback/`
- [ ] `https://uwoconnect.aisa24.com/api/google-docs/callback`
- [ ] `https://uwoconnect.aisa24.com/api/google-slides/callback/`
- [ ] `https://uwoconnect.aisa24.com/api/google-slides/callback`
- [ ] `https://uwoconnect.aisa24.com/api/auth/youtube/callback`
- [ ] `https://uwoconnect.aisa24.com/api/auth/youtube/callback/`
- [ ] `https://uwoconnect.aisa24.com/api/auth/google/callback/`

### Staging / Cloud Run Redirect URIs:
- [ ] `https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/gmail/callback`
- [ ] `https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/google-calendar/callback`
- [ ] `https://uwoconnectforrb-743928421487.asia-south1.run.app/api/google-sheets/callback/`
- [ ] `https://uwoconnectforrb-743928421487.asia-south1.run.app/api/google-docs/callback/`
- [ ] `https://uwoconnectforrb-743928421487.asia-south1.run.app/api/google-slides/callback/`
- [ ] `https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/youtube/callback`
- [ ] `https://uwoconnectforrb-743928421487.asia-south1.run.app/api/auth/google/callback/`

### Local Development URIs (for testing):
- [ ] `http://localhost:8000/api/auth/gmail/callback`
- [ ] `http://localhost:8000/api/auth/google-calendar/callback`
- [ ] `http://localhost:8000/api/google-sheets/callback/`
- [ ] `http://localhost:8000/api/google-docs/callback/`
- [ ] `http://localhost:8000/api/google-slides/callback/`
- [ ] `http://localhost:8000/api/auth/youtube/callback`

---

## 4. Test Users Configuration (If App in Testing State)

If the app is temporarily returned to "Testing" state for recording the verification demo video:
- [ ] Add the designated demo Google account to the **Test Users** list.
- [ ] Add the Google Reviewer account email address (`google-safety-review@...` or reviewer Gmail).

---

## 5. Verification Submission Packet Preparation

Before submitting the form in Google Cloud Console:
- [ ] Privacy Policy URL accessible: `https://uwoconnect.aisa24.com/privacy-policy`
- [ ] Terms of Service URL accessible: `https://uwoconnect.aisa24.com/terms`
- [ ] YouTube demo video recorded and set to **Unlisted** (see `google-verification-demo-script.md`).
- [ ] Reviewer test credentials provided (see `google-reviewer-test-guide.md`).
- [ ] Justification statement submitted for each retained scope (see `google-scope-feature-mapping.md`).
