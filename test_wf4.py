import os
import django
import json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Workflow
wf = Workflow.objects.get(name="Untitled Workflow")
nodes = wf.steps.get('nodes', [])
edges = wf.steps.get('edges', [])

start_node = next((n for n in nodes if n.get('id') == 'start'), None)
print(f"Start Node: {start_node.get('type')}")
edge1 = next((e for e in edges if e.get('source') == 'start'), None)
if edge1:
    node1 = next((n for n in nodes if n.get('id') == edge1.get('target')), None)
    print(f"Node 1: {node1.get('type')}")
    print(node1)
