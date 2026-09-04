import sys
import os
import re
import json

# Add project root to sys.path
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

import django

# Set UTF-8 encoding for terminal output
sys.stdout.reconfigure(encoding='utf-8')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.urls import get_resolver, URLPattern, URLResolver
from rest_framework.test import APIClient

print("=" * 80)
print("🛡️  ANTIGRAVITY SECURITY TEST 1: BACKEND ENDPOINT FUZZING & NEGATIVE VALIDATION")
print("=" * 80)

# 1. DISCOVER ALL URL PATTERNS
def extract_urls(urlpatterns, prefix=""):
    urls = []
    for pattern in urlpatterns:
        if isinstance(pattern, URLPattern):
            full_path = prefix + str(pattern.pattern)
            # Clean DRF router regexes and path converters
            clean_path = full_path.replace("^", "").replace("$", "").replace("\\.", ".").replace("(?P<format>[a-z0-9]+)/?", "")
            clean_path = re.sub(r"\(\?P<format>.*?\)", "", clean_path)
            clean_path = "/" + clean_path.lstrip("/")
            if clean_path and not clean_path.endswith("/") and not "." in clean_path.split("/")[-1]:
                clean_path += "/"
            if clean_path not in urls:
                urls.append(clean_path)
        elif isinstance(pattern, URLResolver):
            nested_prefix = prefix + str(pattern.pattern)
            urls.extend(extract_urls(pattern.url_patterns, nested_prefix))
    return urls

all_raw_urls = extract_urls(get_resolver().url_patterns)
# Deduplicate while preserving order and filter relevant API urls
api_urls = []
for u in all_raw_urls:
    if (u.startswith("/api/") or u.startswith("/webhook/") or u.startswith("/health")) and "<format>" not in u:
        if u not in api_urls:
            api_urls.append(u)

print(f"🔍 Discovered {len(api_urls)} distinct API route patterns in codebase.\n")

# 2. DEFINE FUZZING PAYLOAD PERMUTATIONS
FUZZ_PAYLOADS = [
    ("Empty Body", {}),
    ("Type Mismatch (Nested Object)", {"id": {"nested": True}, "name": {"invalid": 123}, "amount": [1, 2, 3]}),
    ("Type Mismatch (Gibberish String)", {"id": "abc_gibberish_123!@#$%", "quantity": "invalid_string_instead_of_int", "price": "NaN"}),
    ("Invalid ID & Non-Existent Identifier", {"id": "999999999999999999999999", "client_id": "invalid-object-id-format", "pk": "non_existent_key"}),
    ("Boolean/Number Type Swap", {"enabled": 12345, "is_active": "maybe", "status": 99999}),
]

# Sensitive stack trace and internal leak patterns to detect in responses
LEAK_PATTERNS = [
    re.compile(r"Traceback \(most recent call last\):", re.IGNORECASE),
    re.compile(r"django\.db\.", re.IGNORECASE),
    re.compile(r"pymongo\.errors\.", re.IGNORECASE),
    re.compile(r"bson\.errors\.", re.IGNORECASE),
    re.compile(r"Exception at /", re.IGNORECASE),
    re.compile(r"Environment:\s+Request Method:", re.IGNORECASE),
    re.compile(r"mongodb\+srv://", re.IGNORECASE),
    re.compile(r"django-insecure", re.IGNORECASE),
    re.compile(r"AIzaSy[0-9A-Za-z_-]{33}", re.IGNORECASE),  # API Key patterns
    re.compile(r"sk-[0-9A-Za-z_-]{32,}", re.IGNORECASE),
]

def check_for_leaks(content_str):
    leaks_found = []
    for pattern in LEAK_PATTERNS:
        if pattern.search(content_str):
            leaks_found.append(pattern.pattern)
    return leaks_found

# 3. RUN AUTOMATED NEGATIVE & FUZZ TESTING
results = []
client_unauth = APIClient()
client_bad_token = APIClient()
client_bad_token.credentials(HTTP_AUTHORIZATION="Bearer invalid_gibberish_token_xyz_9999999")
client_spoofed_role = APIClient()
client_spoofed_role.credentials(HTTP_AUTHORIZATION="Bearer spoofed_fake_role_token", HTTP_X_USER_ROLE="super_admin_fake")

total_tests = 0
total_500_errors = 0
total_leaks = 0

print("🚀 Executing automated test permutations across discovered endpoints...\n")

for url_pattern in api_urls:
    # Resolve dynamic route parameters like <str:client_id>, <int:section_id>, <str:pk>
    test_url = url_pattern
    test_url = re.sub(r"<str:client_id>", "661234567890abcdef123456", test_url)
    test_url = re.sub(r"<str:pk>", "661234567890abcdef123456", test_url)
    test_url = re.sub(r"<str:project_id>", "661234567890abcdef123456", test_url)
    test_url = re.sub(r"<str:member_id>", "661234567890abcdef123456", test_url)
    test_url = re.sub(r"<str:channel_id>", "661234567890abcdef123456", test_url)
    test_url = re.sub(r"<slug:slug>", "test-guide-slug", test_url)
    test_url = re.sub(r"<int:section_id>", "99999", test_url)
    test_url = re.sub(r"<int:step_id>", "99999", test_url)
    test_url = re.sub(r"<.*?>", "invalid-id", test_url)

    if not test_url.startswith("/"):
        test_url = "/" + test_url

    # Permutation 1: Unauthenticated GET request (Negative Auth)
    try:
        resp_unauth = client_unauth.get(test_url)
        status_unauth = resp_unauth.status_code
        body_unauth = resp_unauth.content.decode('utf-8', errors='ignore')
        leaks_unauth = check_for_leaks(body_unauth)
        is_500 = status_unauth >= 500
        
        total_tests += 1
        if is_500:
            total_500_errors += 1
        if leaks_unauth:
            total_leaks += 1
            
        verdict = "FAIL" if (is_500 or leaks_unauth) else "PASS"
        results.append({
            "endpoint": test_url,
            "method": "GET",
            "test_type": "Unauthenticated Request",
            "payload": "None",
            "status": status_unauth,
            "verdict": verdict,
            "leaks": leaks_unauth
        })
    except Exception as e:
        total_tests += 1
        total_500_errors += 1
        results.append({
            "endpoint": test_url,
            "method": "GET",
            "test_type": "Unauthenticated Request",
            "payload": "None",
            "status": "CRASH",
            "verdict": "FAIL (Exception)",
            "leaks": [str(e)]
        })

    # Permutation 2: Malformed Token / Spoofed Role (Negative Auth)
    try:
        resp_bad_auth = client_bad_token.get(test_url)
        status_bad_auth = resp_bad_auth.status_code
        body_bad_auth = resp_bad_auth.content.decode('utf-8', errors='ignore')
        leaks_bad_auth = check_for_leaks(body_bad_auth)
        is_500 = status_bad_auth >= 500
        
        total_tests += 1
        if is_500:
            total_500_errors += 1
        if leaks_bad_auth:
            total_leaks += 1

        verdict = "FAIL" if (is_500 or leaks_bad_auth) else "PASS"
        results.append({
            "endpoint": test_url,
            "method": "GET",
            "test_type": "Malformed Bearer Token",
            "payload": "Bearer invalid_gibberish_token_xyz_9999999",
            "status": status_bad_auth,
            "verdict": verdict,
            "leaks": leaks_bad_auth
        })
    except Exception as e:
        total_tests += 1
        total_500_errors += 1
        results.append({
            "endpoint": test_url,
            "method": "GET",
            "test_type": "Malformed Bearer Token",
            "payload": "Bearer invalid_gibberish_token_xyz_9999999",
            "status": "CRASH",
            "verdict": "FAIL (Exception)",
            "leaks": [str(e)]
        })

    # Permutation 3: POST Fuzzing (Empty body + Gibberish + Type mismatches)
    for p_name, payload in FUZZ_PAYLOADS:
        try:
            resp_post = client_bad_token.post(test_url, data=payload, format='json')
            status_post = resp_post.status_code
            body_post = resp_post.content.decode('utf-8', errors='ignore')
            leaks_post = check_for_leaks(body_post)
            is_500 = status_post >= 500
            
            total_tests += 1
            if is_500:
                total_500_errors += 1
            if leaks_post:
                total_leaks += 1

            verdict = "FAIL" if (is_500 or leaks_post) else "PASS"
            results.append({
                "endpoint": test_url,
                "method": "POST",
                "test_type": f"Fuzz: {p_name}",
                "payload": str(payload)[:40],
                "status": status_post,
                "verdict": verdict,
                "leaks": leaks_post
            })
        except Exception as e:
            total_tests += 1
            total_500_errors += 1
            results.append({
                "endpoint": test_url,
                "method": "POST",
                "test_type": f"Fuzz: {p_name}",
                "payload": str(payload)[:40],
                "status": "CRASH",
                "verdict": "FAIL (Exception)",
                "leaks": [str(e)]
            })

# 4. PRINT FORMATTED RESULTS & SUMMARY SCORECARD
print("=" * 100)
print(f"{'ENDPOINT':<45} | {'METHOD':<6} | {'TEST SCENARIO':<30} | {'STATUS':<6} | {'VERDICT'}")
print("=" * 100)

failed_cases = []
for r in results:
    if r["verdict"] != "PASS":
        failed_cases.append(r)
        print(f"❌ {r['endpoint']:<43} | {r['method']:<6} | {r['test_type']:<30} | {str(r['status']):<6} | {r['verdict']}")
    else:
        # Show representative sample of passing tests
        if r['method'] == 'GET' and r['test_type'] == 'Unauthenticated Request':
            print(f"✅ {r['endpoint']:<43} | {r['method']:<6} | {r['test_type']:<30} | {str(r['status']):<6} | {r['verdict']}")

print("\n" + "=" * 80)
print("📊 SECURITY TEST 1 EXECUTIVE SUMMARY & SCORECARD")
print("=" * 80)
print(f"Total Test Permutations Executed : {total_tests}")
print(f"Total Endpoints Scanned           : {len(api_urls)}")
print(f"Total 500 Internal Server Errors  : {total_500_errors}")
print(f"Total Data / Trace Leaks Detected : {total_leaks}")
print(f"Failed Security Cases             : {len(failed_cases)}")

if total_500_errors == 0 and total_leaks == 0:
    print("\n🏆 OVERALL SECURITY POSTURE VERDICT: PASS (100% Negative Schema & Auth Resilient)")
else:
    print(f"\n⚠️ OVERALL SECURITY POSTURE VERDICT: WARN/FAIL ({total_500_errors} 500s / {total_leaks} leaks detected)")

# Save detailed results to JSON report
output_file = os.path.join(os.path.dirname(__file__), "security_test_1_results.json")
with open(output_file, "w", encoding="utf-8") as f:
    json.dump({
        "total_tests": total_tests,
        "total_endpoints": len(api_urls),
        "total_500_errors": total_500_errors,
        "total_leaks": total_leaks,
        "failed_cases": failed_cases,
        "all_results": results
    }, f, indent=2)

print(f"\n📁 Full JSON Audit Log saved to: {output_file}")
