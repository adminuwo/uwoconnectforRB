#!/usr/bin/env python3
"""
Setup and Provision Google OAuth Verification Reviewer Test Account.
Creates or upgrades a dedicated test account with pre-configured verification privileges,
bypassing subscription paywalls strictly for the reviewer account without modifying production billing logic.
"""

import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import User, Client
from api.services.google_oauth_service import is_google_verification_account


def setup_reviewer_account(
    email="google-reviewer@uwoconnect.aisa24.com",
    password="UwoReviewer@2026!",
    business_name="Google OAuth Verification Test Lab"
):
    print("=" * 65)
    print("UWOConnect — Google Reviewer Test Account Provisioning")
    print("=" * 65)

    # 1. Ensure Client exists
    client_obj, client_created = Client.objects.get_or_create(
        business_name=business_name,
        defaults={
            "plan": "ENTERPRISE",
            "status": "ACTIVE",
            "automation_enabled": True,
            "whatsapp_enabled": True,
            "gmail_enabled": True,
            "google_calendar_enabled": True,
            "google_sheets_enabled": True,
            "google_docs_enabled": True,
            "google_slides_enabled": True,
            "youtube_enabled": True,
            "settings": {
                "is_verification_account": True,
                "notes": "Designated for Google OAuth 2.0 verification reviewer testing"
            }
        }
    )

    # Ensure verification flag is enabled in client.settings
    if not client_created:
        settings_dict = client_obj.settings or {}
        settings_dict["is_verification_account"] = True
        client_obj.settings = settings_dict
        client_obj.plan = "ENTERPRISE"
        client_obj.status = "ACTIVE"
        client_obj.gmail_enabled = True
        client_obj.google_calendar_enabled = True
        client_obj.google_sheets_enabled = True
        client_obj.google_docs_enabled = True
        client_obj.google_slides_enabled = True
        client_obj.youtube_enabled = True
        client_obj.save()

    print(f"[*] Client Workspace: {client_obj.business_name} (ID: {client_obj.id})")

    # 2. Ensure User exists
    user = User.objects.filter(email__iexact=email).first()
    if not user:
        user = User.objects.create_user(
            username=email.lower().strip(),
            email=email.lower().strip(),
            password=password,
            first_name="Google",
            last_name="Reviewer",
            role="CLIENT",
            status="ACTIVE",
            client=client_obj
        )
        print(f"[+] Created new reviewer user: {email}")
    else:
        user.client = client_obj
        user.role = "CLIENT"
        user.status = "ACTIVE"
        user.set_password(password)
        user.save()
        print(f"[*] Updated existing reviewer user: {email}")

    # 3. Verify entitlement check
    is_verified = is_google_verification_account(client_obj, user)
    print(f"[✓] Verification Account Flag Active: {is_verified}")

    print("\n" + "=" * 65)
    print("REVIEWER TEST CREDENTIALS READY FOR GOOGLE:")
    print(f"Email:    {email}")
    print(f"Password: {password}")
    print(f"Role:     CLIENT")
    print(f"Workspace Plan: Verification Partner (All Google Integrations Unlocked)")
    print("=" * 65)

    return user, client_obj


if __name__ == "__main__":
    reviewer_email = sys.argv[1] if len(sys.argv) > 1 else "google-reviewer@uwoconnect.aisa24.com"
    reviewer_pwd = sys.argv[2] if len(sys.argv) > 2 else "UwoReviewer@2026!"
    setup_reviewer_account(reviewer_email, reviewer_pwd)
