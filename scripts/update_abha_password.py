import os, sys

# Ensure project root is on PYTHONPATH
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
sys.path.append(PROJECT_ROOT)

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from api.models import User

email = 'abha@uwo24.com'
new_password = 'admin123'

try:
    user = User.objects.get(email=email)
    user.set_password(new_password)
    user.save(update_fields=['password'])
    print(f'Success: Password for {email} updated.')
except User.DoesNotExist:
    print(f'Error: User with email {email} not found.')
except Exception as e:
    print(f'Error: {e}')
