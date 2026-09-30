import os
import django
import json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import Workflow
wf = Workflow.objects.get(name="Untitled Workflow")
nodes = wf.steps.get('nodes', [])
edges = wf.steps.get('edges', [])
print(f"Nodes: {len(nodes)}")
print(f"Edges: {len(edges)}")
start_node = next((n for n in nodes if n.get('type') == 'trigger'), None)
if start_node:
    print(f"Start Node ID: {start_node.get('id')}")
    out_edges = [e for e in edges if e.get('source') == start_node.get('id')]
    print(f"Out edges from start node: {len(out_edges)}")
else:
    print("No start node found!")
