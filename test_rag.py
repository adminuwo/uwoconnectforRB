import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import KnowledgeChunk
from api.services.ai_service import get_embedding, cosine_similarity
from api.repositories.knowledge_repository import KnowledgeRepository

chunks = KnowledgeChunk.objects.all()
print(f"Total chunks: {chunks.count()}")
valid_chunks = chunks.exclude(embedding=[])
print(f"Chunks with embeddings via exclude: {valid_chunks.count()}")

# Test with first chunk if exists
c = chunks.first()
if c:
    emb = c.embedding
    print(f"First chunk embedding length: {len(emb) if emb else 'None or empty'}")
    if isinstance(emb, list) and not emb:
        print("First chunk has empty list embedding.")

