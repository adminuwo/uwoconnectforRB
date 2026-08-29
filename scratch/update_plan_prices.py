import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
# In uwo_connect_B, setting module is uwo_connect_B.settings or uwo_connect.settings
try:
    import uwo_connect_B.settings
    os.environ['DJANGO_SETTINGS_MODULE'] = 'uwo_connect_B.settings'
except ImportError:
    pass

django.setup()

from api.models import Plan
from api.services.entitlement_service import DEFAULT_PLANS_CONFIG

NEW_PRICES = {
    'starter': {'monthly': 499, 'yearly': 999},
    'growth': {'monthly': 1599, 'yearly': 2799},
    'advanced': {'monthly': 2499, 'yearly': 25489}
}

for slug, prices in NEW_PRICES.items():
    plans = Plan.objects.filter(slug=slug)
    for p in plans:
        p.price = str(prices['monthly'])
        meta = p.metadata or {}
        meta['monthly_price'] = prices['monthly']
        meta['yearly_price'] = prices['yearly']
        p.metadata = meta
        p.save()
        print(f"Updated plan '{p.name}' -> Monthly: ₹{prices['monthly']}, Yearly: ₹{prices['yearly']}")

print("Database plan prices updated successfully.")
