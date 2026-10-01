import os
import django
import json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Workflow
wf = Workflow.objects.get(name="Untitled Workflow")
print(type(wf.steps))
print(repr(wf.steps)[:500])
