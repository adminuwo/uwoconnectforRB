import os
import django
import json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import WorkflowSession
sessions = WorkflowSession.objects.filter(is_active=True)
count = sessions.count()
print(f"Active workflow/ai sessions found: {count}")
for s in sessions:
    s.is_active = False
    s.save()
print("Disabled active sessions to unstick the bot.")
