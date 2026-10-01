import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from api.models import KnowledgeChunk
from api.services.ai_service import get_embedding, cosine_similarity, find_relevant_chunks

chunks = KnowledgeChunk.objects.all().exclude(embedding=[])

if chunks.exists():
    chunks_data = [{
        'text': c.chunk_text,
        'embedding': c.embedding,
        'doc_title': c.document.title
    } for c in chunks.select_related('document')]

    query = "hi"
    q_emb = get_embedding(query)
    
    if q_emb:
        relevant = find_relevant_chunks(q_emb, chunks_data, top_k=5)
        print("Query:", query)
        for i, r in enumerate(relevant):
            print(f"[{i}] Score: {r['score']} | Doc: {r['doc_title']} | Text snippet: {r['text'][:50]}")
    else:
        print("Failed to get query embedding")
else:
    print("No chunks with embeddings found.")

