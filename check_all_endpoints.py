"""
Comprehensive Endpoint Audit Script
Enumerates and tests every registered URL pattern in the Django application.
Identifies any 500 crashes, broken view callables, or unhandled exceptions.
"""

import os
import sys
import django
import json

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.urls import get_resolver, URLPattern, URLResolver
from rest_framework.test import APIClient
from api.models import User, Client

def extract_patterns(url_patterns, prefix=''):
    """Recursively extract all URL patterns and their views."""
    endpoints = []
    for pattern in url_patterns:
        if isinstance(pattern, URLResolver):
            nested_prefix = prefix + str(pattern.pattern)
            endpoints.extend(extract_patterns(pattern.url_patterns, nested_prefix))
        elif isinstance(pattern, URLPattern):
            full_path = prefix + str(pattern.pattern)
            # Remove regex artifacts if any for clean presentation
            clean_path = full_path.replace('^', '').replace('$', '')
            endpoints.append({
                'path': clean_path,
                'name': pattern.name,
                'callback': pattern.callback,
                'pattern_obj': pattern
            })
    return endpoints

def run_endpoint_audit():
    resolver = get_resolver()
    all_endpoints = extract_patterns(resolver.url_patterns)
    print(f"Total Registered Endpoints Discovered: {len(all_endpoints)}")

    client = APIClient()

    # Create / get a test user and client for authenticated checks
    test_user = User.objects.filter(email='endpoint_audit_test@uwo.ai').first()
    if not test_user:
        try:
            test_user = User.objects.create_user(
                email='endpoint_audit_test@uwo.ai',
                username='endpoint_audit_test',
                password='TestPassword123!',
                role='CLIENT'
            )
        except Exception as e:
            # Fallback to existing user if any
            test_user = User.objects.first()

    test_client_profile = None
    if test_user:
        if not test_user.client:
            test_client_profile = Client.objects.first()
            if not test_client_profile:
                test_client_profile = Client.objects.create(
                    business_name="Test Audit Client",
                    phone_number="+1234567890"
                )
            test_user.client = test_client_profile
            test_user.role = 'ADMIN'  # Give admin rights to test all client & admin endpoints
            test_user.save()
        else:
            test_client_profile = test_user.client

    results = {
        'total': len(all_endpoints),
        'passed_2xx': [],
        'auth_guarded_401_403': [],
        'client_error_400_405': [],
        'not_found_404': [],
        'server_error_500': [],
        'skipped_parameterized': []
    }

    # Authenticate client
    if test_user:
        client.force_authenticate(user=test_user)

    for ep in all_endpoints:
        path = ep['path']
        # If path has url parameters like <pk> or (?P<path>.*), handle or skip
        if '<' in path or '(?P<' in path or ':path' in path:
            # Try to substitute dummy id if it's a simple <id> or <pk>
            dummy_path = path
            for param in ['<int:pk>', '<pk>', '<int:id>', '<id>', '<str:id>', '<uuid:id>']:
                if param in dummy_path:
                    dummy_path = dummy_path.replace(param, '1')
            if '<' in dummy_path or '(?P<' in dummy_path:
                results['skipped_parameterized'].append(path)
                continue
            path_to_test = '/' + dummy_path.lstrip('/')
        else:
            path_to_test = '/' + path.lstrip('/')

        try:
            # Test GET first
            resp = client.get(path_to_test)
            code = resp.status_code

            # If 405 Method Not Allowed, try POST or OPTIONS to verify endpoint handler is alive
            if code == 405:
                # Try OPTIONS to check valid methods
                opt_resp = client.options(path_to_test)
                if opt_resp.status_code in [200, 204]:
                    results['client_error_400_405'].append({
                        'path': path_to_test,
                        'status': 405,
                        'name': ep['name'],
                        'info': 'Method 405 on GET (Endpoint alive; expects POST/PUT/DELETE)'
                    })
                    continue

            if 200 <= code < 300 or code == 301 or code == 302:
                results['passed_2xx'].append({'path': path_to_test, 'status': code, 'name': ep['name']})
            elif code in (401, 403):
                results['auth_guarded_401_403'].append({'path': path_to_test, 'status': code, 'name': ep['name']})
            elif code in (400, 405):
                results['client_error_400_405'].append({'path': path_to_test, 'status': code, 'name': ep['name']})
            elif code == 404:
                results['not_found_404'].append({'path': path_to_test, 'status': code, 'name': ep['name']})
            elif code >= 500:
                results['server_error_500'].append({
                    'path': path_to_test,
                    'status': code,
                    'name': ep['name'],
                    'error': str(resp.content[:300])
                })
        except Exception as e:
            results['server_error_500'].append({
                'path': path_to_test,
                'status': 'EXCEPTION',
                'name': ep['name'],
                'error': str(e)
            })

    print("\n" + "="*60)
    print("ENDPOINT AUDIT SUMMARY:")
    print(f"Total Endpoints Checked: {results['total']}")
    print(f"2xx / 3xx Success: {len(results['passed_2xx'])}")
    print(f"401 / 403 Auth Guarded: {len(results['auth_guarded_401_403'])}")
    print(f"400 / 405 Client Validated / Action Required: {len(results['client_error_400_405'])}")
    print(f"Parameterized Endpoints (require specific resource ID): {len(results['skipped_parameterized'])}")
    print(f"404 Not Found: {len(results['not_found_404'])}")
    print(f"500 Internal Server Errors: {len(results['server_error_500'])}")
    print("="*60)

    if results['server_error_500']:
        print("\nCRITICAL: 500 SERVER ERRORS FOUND:")
        for err in results['server_error_500']:
            print(f"  {err['path']} ({err.get('name')}): {err.get('error')}")
    else:
        print("\n ZERO 500 SERVER ERRORS! All tested endpoints are stable.")

    # Save detailed JSON log
    out_file = '/Users/gurumukhpahuja/Desktop/forrb/uwoconnectforRB/endpoint_audit_results.json'
    with open(out_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nDetailed audit results saved to {out_file}")

if __name__ == '__main__':
    run_endpoint_audit()
