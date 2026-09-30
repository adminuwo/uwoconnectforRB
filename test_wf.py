import os
import django
import json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Workflow
for wf in Workflow.objects.all():
    print(f"ID: {wf.id} | Name: {wf.name} | Enabled: {wf.enabled} | Channels: {wf.channels} | Trigger: {wf.trigger_type} -> {wf.trigger_value}")
    print(f"Steps count: {len(wf.steps) if isinstance(wf.steps, list) else 'Not list'}")
