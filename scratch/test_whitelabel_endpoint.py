import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from rest_framework.test import APIRequestFactory
from api.views.whitelabel_views import WhiteLabelConfigView

factory = APIRequestFactory()
view = WhiteLabelConfigView.as_view()

# Test 1: Default domain
req1 = factory.get('/api/whitelabel/config?domain=localhost')
res1 = view(req1)
print("Default Test Result:", res1.status_code, res1.data)

# Test 2: Custom domain test
req2 = factory.get('/api/whitelabel/config?domain=portal.testagency.com')
res2 = view(req2)
print("Custom Domain Test Result:", res2.status_code, res2.data)
