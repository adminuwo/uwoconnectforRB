# Google Reviewer Test & Access Guide

**Application:** UWOConnect  
**Target Audience:** Google Trust & Safety Team Reviewers  
**Purpose:** Instructions for Google reviewers to access, test, and evaluate UWOConnect's Google OAuth integrations without requiring a paid subscription or payment credentials.

---

> [!NOTE]
> **Resolution of Previous Review Blocker:**  
> In the prior review, testing was halted because features appeared to require a paid/premium subscription.  
> We have implemented a dedicated, zero-regression reviewer bypass mechanism: accounts flagged as `is_verification_account` or matching authorized reviewer emails automatically receive the **Google Verification Reviewer Plan**. This plan provides 100% unlocked access to all Google connectors (Gmail, Sheets, Docs, Slides, Calendar, YouTube) without requiring credit card details or paid upgrades.

---

## 1. Test Environment URLs & Reviewer Credentials

| Parameter | Production Environment | Staging Environment |
|---|---|---|
| **Web Application URL** | `https://uwoconnect.aisa24.com` | `https://uwoconnectforrf-...` |
| **Login Page** | `https://uwoconnect.aisa24.com/login` | Staging login URL |
| **Reviewer Username / Email** | `google-reviewer@uwoconnect.aisa24.com` *(or reviewer's `@google.com` email)* | `google-reviewer@uwoconnect.aisa24.com` |
| **Password** | Provided securely via Google Cloud Console developer response | Provided securely via Console |
| **Assigned Plan** | **Google Verification Reviewer Plan** (Free / Unrestricted) | **Google Verification Reviewer Plan** |

---

## 2. Reviewer Account Provisioning via CLI

If the reviewer wishes to test with their own `@google.com` account or create a fresh isolated tenant, an administrator can provision or promote an account immediately:

```bash
# Provision new reviewer account:
python manage.py shell -c "
from api.models import Client, User
c, _ = Client.objects.get_or_create(business_name='Google Reviewer Workspace', defaults={'status': 'ACTIVE'})
c.is_verification_account = True
c.save()
u, _ = User.objects.get_or_create(username='google_reviewer', email='google-reviewer@uwoconnect.aisa24.com', client=c)
u.set_password('ReviewerSecurePass2026!')
u.save()
print('Provisioned reviewer account successfully!')
"
```

Or run the pre-built management script:
```bash
python setup_google_reviewer.py --email reviewer@google.com --password SecurePassword123!
```

---

## 3. Step-by-Step Testing Walkthrough for Reviewers

### Step 1: Login
1. Navigate to the login page: `https://uwoconnect.aisa24.com/login`.
2. Enter the reviewer credentials and click **Sign In**.
3. You will arrive at the **Client Dashboard**. Notice the badge indicating active enterprise integration capabilities.

### Step 2: Accessing Google Connectors
1. In the left navigation menu, click **Channels & Integrations** (or visit `/client/channels`).
2. Scroll to the **Google Workspace & Media Integrations** section:
   - **Gmail**
   - **Google Calendar**
   - **Google Sheets**
   - **Google Docs**
   - **Google Slides**
   - **YouTube**

### Step 3: Authorizing Integrations
1. Click **Connect** on any Google integration card.
2. An informative modal appears detailing the exact least-privilege scopes requested.
3. Click **Connect with Google**.
4. You will be redirected to Google's standard OAuth 2.0 consent screen displaying `UWOConnect`.
5. Grant the permissions. You will be redirected back to UWOConnect with an "Active & Synced" confirmation.

### Step 4: Testing Each Integration
- **Google Sheets:** Open the Sheets modal. Select or link a test spreadsheet. Click "Sync Test Data" to verify real-time append.
- **Gmail:** Open `/client/gmail`. View synced inbox messages. Dispatch an automated AI reply or compose a test message.
- **Google Calendar:** Open `/client/calendar`. Schedule a test appointment. Verify event creation on calendar.google.com.
- **Google Docs:** Navigate to Sales Documents. Click "Generate Document" to verify automated document generation.
- **Google Slides:** Navigate to Sales Proposals. Click "Generate Slides Deck" to verify automated slide deck creation.
- **YouTube:** Open the YouTube Channel modal. View channel statistics, test uploading a test video, or reply to video comments.

---

## 4. Security & Isolation Controls
- Reviewer test accounts operate in a secure, isolated workspace tenant.
- Reviewer actions do not affect real customer data or production tenants.
- All tokens are stored encrypted and can be revoked at any time via the "Disconnect" button in the modal or via Google Account Security permissions (`myaccount.google.com/permissions`).
