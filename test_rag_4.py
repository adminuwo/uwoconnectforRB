import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import KnowledgeChunk
c = KnowledgeChunk.objects.exclude(embedding=[]).first()
if c:
    print(type(c.embedding))
    if isinstance(c.embedding, str):
        print(c.embedding[:50])
