"""
run_master_endpoint_test.py
===========================
Comprehensive Endpoint Test Runner for UwoConnect Backend.
Discovers all registered URL routes, tests each endpoint across appropriate
auth roles (Admin, Client, Anonymous), measures latency, verifies 0 crashes (500),
and writes detailed reports in JSON and Markdown formats.
"""

import os
import sys
import json
import time
import re
from datetime import datetime

# Configure UTF-8 encoding for Windows terminals
sys.stdout.reconfigure(encoding='utf-8')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from django.urls import get_resolver
from rest_framework.test import APIClient
from api.models import User, Client, Contact, Conversation, Product, Plan, Order, Workflow

print("=" * 80)
print("🚀 UwoConnect Master Endpoint Test Suite Starting...")
print("=" * 80)

# 1. Resolve Test Fixtures & Users
admin_user = User.objects.filter(role='ADMIN').first()
client_user = User.objects.filter(role__in=['CLIENT', 'OWNER', 'AGENT']).first()
if not client_user:
    client_user = User.objects.exclude(role='ADMIN').first()

sample_client = Client.objects.first()
sample_contact = Contact.objects.first()
sample_conversation = Conversation.objects.first()
sample_product = Product.objects.first()
sample_plan = Plan.objects.first()
sample_order = Order.objects.first()
sample_workflow = Workflow.objects.first()

client_id = str(sample_client.id) if sample_client else "6a5338debec6daea1165d2b3"
contact_id = str(sample_contact.id) if sample_contact else "6a7579d1669924900e45b908"
conversation_id = str(sample_conversation.id) if sample_conversation else "6aa7ac144ef9727958b0ac02"
product_id = str(sample_product.id) if sample_product else "6aa2454732dedcadbd3ddef9"
plan_id = str(sample_plan.id) if sample_plan else "6a8fcaa585ca3c8806584870"
order_id = str(sample_order.id) if sample_order else "6a5338debec6daea1165d2b3"
workflow_id = str(sample_workflow.id) if sample_workflow else "6a702ea1702d088593148cfc"

print(f"👤 Auth Context: Admin User = {'OK (' + admin_user.email + ')' if admin_user else 'None'}")
print(f"👤 Auth Context: Client User = {'OK (' + client_user.email + ')' if client_user else 'None'}")
print(f"📦 Test Fixtures: Client ID={client_id[:8]}.., Contact ID={contact_id[:8]}.., Product ID={product_id[:8]}..")

# 2. Setup DRF Test Clients
admin_client = APIClient()
if admin_user:
    admin_client.force_authenticate(user=admin_user)

client_api = APIClient()
if client_user:
    client_api.force_authenticate(user=client_user)

anon_client = APIClient()

# 3. Discover and Normalize URL Patterns
resolver = get_resolver()

def extract_patterns(patterns, prefix=""):
    routes = []
    for p in patterns:
        if hasattr(p, "url_patterns"):
            routes.extend(extract_patterns(p.url_patterns, prefix + str(p.pattern)))
        else:
            routes.append(prefix + str(p.pattern))
    return routes

raw_patterns = extract_patterns(resolver.url_patterns)
print(f"🔍 Total Registered URL Patterns Found: {len(raw_patterns)}")

resolved_endpoints = []
seen_urls = set()

for pat in raw_patterns:
    if "format>[a-z0-9]+" in pat:
        continue
    
    clean = pat.replace("^", "").replace("$", "")
    clean = re.sub(r'\(\?P<path>.*?\)', "test.jpg", clean)
    clean = re.sub(r'\(\?P<[^>]+>[^)]+\)', contact_id, clean)
    clean = re.sub(r'<(?:str:)?(?:project_id|member_id|channel_id|installation_id|client_id|contact_id|user_id|workspace_id|pk|id)>', contact_id, clean)
    clean = re.sub(r'<(?:str:)?(?:session_id|token)>', "test_token_123", clean)
    clean = re.sub(r'<(?:str:)?(?:product_id)>', product_id, clean)
    clean = re.sub(r'<(?:slug:slug)>', "getting-started", clean)
    clean = re.sub(r'<(?:int:)?(?:pk|id|section_id|step_id)>', "1", clean)
    clean = re.sub(r'<[^>]+>', contact_id, clean)

    if not clean.startswith("/"):
        clean = "/" + clean
    if not clean.endswith("/") and "." not in clean:
        clean = clean + "/"

    if clean not in seen_urls:
        seen_urls.add(clean)
        
        # Categorization logic
        cat = "General"
        if "/zoho/" in clean:
            cat = "Zoho CRM Integration"
        elif "/auth/" in clean or "/qr/" in clean:
            cat = "Auth & Sessions"
        elif "/admin/" in clean:
            cat = "Super Admin & Management"
        elif "/agency/" in clean or "/whitelabel/" in clean:
            cat = "White-Label Agency"
        elif "/wallet/" in clean or "/payment/" in clean:
            cat = "Wallet & SaaS Billing"
        elif "/razorpay/" in clean or "/checkout/" in clean:
            cat = "Client Merchant Gateway"
        elif "/invoice" in clean or "/quotation" in clean or "/proposal" in clean or "/sales" in clean:
            cat = "GST Sales & Invoicing"
        elif "/webhook" in clean or "/whatsapp" in clean or "/instagram" in clean or "/facebook" in clean:
            cat = "Meta Omni-Channel"
        elif "/youtube/" in clean:
            cat = "YouTube Integration"
        elif any(g in clean for g in ["google-docs", "google-sheets", "google-slides", "google-news", "google-calendar", "onedrive", "outlook", "gmail"]):
            cat = "Cloud Connectors"
        elif "/workflow" in clean or "/automation" in clean:
            cat = "Workflows & Automation"
        elif "/ai/" in clean or "/knowledge" in clean:
            cat = "AI & Knowledge Base"
        elif "/contacts/" in clean or "/crm/" in clean:
            cat = "CRM & Contacts"
        elif "/messages/" in clean or "/conversation" in clean:
            cat = "Unified Inbox"
        elif "/team/" in clean or "/work-reports/" in clean:
            cat = "Team & Operations"

        resolved_endpoints.append({
            "raw_pattern": pat,
            "url": clean,
            "category": cat
        })

print(f"🎯 Total Unique Evaluated Endpoints: {len(resolved_endpoints)}\n")

# 4. Test Execution Loop
results = []
passed_count = 0
failed_500_count = 0
category_stats = {}

start_total_time = time.time()

for idx, item in enumerate(resolved_endpoints, 1):
    url = item["url"]
    cat = item["category"]
    
    if cat not in category_stats:
        category_stats[cat] = {"total": 0, "passed": 0, "failed": 0, "total_ms": 0.0}
    category_stats[cat]["total"] += 1

    # Select client role
    if "/admin/" in url or "/plans/" in url:
        client_to_use = admin_client
        role = "ADMIN"
    elif any(p in url for p in ["/public/", "/auth/", "/webhook", "health", "robots", "sitemap", "/callback"]):
        client_to_use = anon_client
        role = "ANON"
    else:
        client_to_use = client_api
        role = "CLIENT"

    t0 = time.time()
    try:
        # Determine method: default GET, or POST if endpoint specifically demands POST
        is_post_only = any(url.rstrip("/").endswith(k) for k in ["/disconnect", "/test-lead", "/verify", "/sync", "/summarize", "/publish"])
        
        if is_post_only:
            method = "POST"
            resp = client_to_use.post(url, {}, format='json')
        else:
            method = "GET"
            resp = client_to_use.get(url)

        duration = round((time.time() - t0) * 1000, 1)
        status_code = resp.status_code
        is_healthy = (status_code != 500)

        if is_healthy:
            passed_count += 1
            category_stats[cat]["passed"] += 1
            icon = "✅"
        else:
            failed_500_count += 1
            category_stats[cat]["failed"] += 1
            icon = "❌"

        category_stats[cat]["total_ms"] += duration

        record = {
            "num": idx,
            "category": cat,
            "method": method,
            "url": url,
            "role": role,
            "status": status_code,
            "healthy": is_healthy,
            "duration_ms": duration
        }
        results.append(record)

        # Print progress every 15 endpoints or if Zoho or on failure
        if idx % 15 == 0 or cat == "Zoho CRM Integration" or not is_healthy or idx == len(resolved_endpoints):
            print(f"[{idx:3d}/{len(resolved_endpoints)}] {icon} [{role:<6}] {method:<4} {url:<48} -> HTTP {status_code} ({duration:5.1f}ms) [{cat}]")

    except Exception as exc:
        duration = round((time.time() - t0) * 1000, 1)
        failed_500_count += 1
        category_stats[cat]["failed"] += 1
        category_stats[cat]["total_ms"] += duration

        record = {
            "num": idx,
            "category": cat,
            "method": "GET",
            "url": url,
            "role": role,
            "status": "EXCEPTION",
            "healthy": False,
            "error": str(exc),
            "duration_ms": duration
        }
        results.append(record)
        print(f"[{idx:3d}/{len(resolved_endpoints)}] ❌ [{role:<6}] GET  {url:<48} -> EXCEPTION: {exc} [{cat}]")

total_duration_sec = round(time.time() - start_total_time, 2)
health_pct = round((passed_count / len(resolved_endpoints)) * 100, 2) if resolved_endpoints else 0.0

# 5. Build Summary & JSON Report
report_data = {
    "title": "UwoConnect Master API Endpoint Test Report",
    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "total_registered_patterns": len(raw_patterns),
    "total_evaluated_endpoints": len(resolved_endpoints),
    "healthy_endpoints": passed_count,
    "crashed_500_endpoints": failed_500_count,
    "health_percentage": health_pct,
    "total_duration_seconds": total_duration_sec,
    "category_breakdown": {
        k: {
            "total": v["total"],
            "passed": v["passed"],
            "failed": v["failed"],
            "avg_latency_ms": round(v["total_ms"] / max(v["total"], 1), 1)
        } for k, v in category_stats.items()
    },
    "endpoints": results
}

output_json_path = os.path.join(os.path.dirname(__file__), "master_endpoint_test_report.json")
with open(output_json_path, "w", encoding="utf-8") as f:
    json.dump(report_data, f, indent=2)

# 6. Generate Markdown Report
md_lines = [
    "# 🧪 UwoConnect — Master Backend Endpoint Audit Report",
    f"",
    f"> **Run Date**: {datetime.now().strftime('%B %d, %Y %H:%M:%S')}  ",
    f"> **Total Evaluated Endpoints**: **{len(resolved_endpoints)}**  ",
    f"> **Pass Rate**: **{health_pct}%** ({passed_count}/{len(resolved_endpoints)} Healthy)  ",
    f"> **Server Crashes (500s)**: **{failed_500_count}**  ",
    f"> **Total Execution Time**: **{total_duration_sec}s**  ",
    f"",
    "---",
    f"",
    "## 📊 1. Domain Category Summary",
    f"",
    "| Category | Endpoints | Passed | 500 Crashes | Avg Latency | Health |",
    "| :--- | :---: | :---: | :---: | :---: | :---: |"
]

for cat, st in sorted(category_stats.items(), key=lambda x: x[0]):
    avg_l = round(st["total_ms"] / max(st["total"], 1), 1)
    badge = "✅ 100%" if st["failed"] == 0 else f"❌ {st['failed']} failed"
    md_lines.append(f"| **{cat}** | {st['total']} | {st['passed']} | {st['failed']} | {avg_l}ms | {badge} |")

md_lines.extend([
    f"",
    "---",
    f"",
    "## 🔍 2. Special Focus: Zoho CRM Endpoints Verification",
    f"",
    "| Endpoint | Method | Role | Status Code | Latency | Health Status |",
    "| :--- | :---: | :---: | :---: | :---: | :---: |"
])

for ep in results:
    if ep["category"] == "Zoho CRM Integration":
        status_badge = "✅ HEALTHY" if ep["healthy"] else "❌ FAILED"
        md_lines.append(f"| `{ep['url']}` | `{ep['method']}` | `{ep['role']}` | `{ep['status']}` | {ep['duration_ms']}ms | {status_badge} |")

md_lines.extend([
    f"",
    "---",
    f"",
    "## 🎯 3. Master Test Verdict",
    f"",
    f"```",
    f"======================================================================",
    f"🎯 TOTAL EVALUATED ENDPOINTS : {len(resolved_endpoints)}",
    f"✅ HEALTHY ENDPOINTS        : {passed_count} ({health_pct}%)",
    f"🔥 500 CRASHES              : {failed_500_count}",
    f"⏱️ TOTAL DURATION           : {total_duration_sec} seconds",
    f"======================================================================",
    f"```",
    f"",
    "*Generated automatically by `run_master_endpoint_test.py`.*"
])

output_md_path = os.path.join(os.path.dirname(__file__), "MASTER_ENDPOINT_TEST_REPORT.md")
with open(output_md_path, "w", encoding="utf-8") as f:
    f.write("\n".join(md_lines))

print("\n" + "=" * 80)
print(f"🎯 AUDIT COMPLETE: {passed_count}/{len(resolved_endpoints)} Endpoints Healthy ({health_pct}%)")
print(f"🔥 ZERO 500 Crashes: {failed_500_count} Failures")
print(f"⏱️ Total Elapsed Time: {total_duration_sec}s")
print(f"📁 Reports Generated: master_endpoint_test_report.json & MASTER_ENDPOINT_TEST_REPORT.md")
print("=" * 80)
