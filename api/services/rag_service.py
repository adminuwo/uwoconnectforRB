"""
HybridRAGService
Implements production-grade hybrid retrieval (Dense Semantic + Lexical Keyword BM25/RRF)
for the UWO Connect RAG pipeline:
- Dense Vector Search using cosine similarity on 1536-dim embeddings
- Lexical Keyword Search with exact phrase matching & title/heading boosts
- Reciprocal Rank Fusion (RRF) combining semantic & keyword signals
- Strict tenant/client data isolation
- Source citation attribution (page title, source URL, heading hierarchy)
- Multilingual and mirror-language answer generation
"""

import math
import re
from typing import List, Dict, Any, Optional
import numpy as np

from ..models import Client, KnowledgeChunk, KnowledgeDocument
from ..repositories.knowledge_repository import KnowledgeRepository
from .ai_service import get_embedding, cosine_similarity, _get_client


class HybridRAGService:
    @staticmethod
    def retrieve_relevant_chunks(
        client: Client,
        query: str,
        top_k: int = 5,
        dense_weight: float = 0.6,
        lexical_weight: float = 0.4
    ) -> List[Dict[str, Any]]:
        """
        Retrieves top_k most relevant chunks using Hybrid Search:
        1. Dense semantic search via OpenAI embeddings
        2. Lexical keyword search with phrase matching
        3. Reciprocal Rank Fusion (RRF)
        Strictly isolated to chunks belonging to `client`.
        """
        if not client or not query or not query.strip():
            return []

        # 1. Fetch all candidate chunks for this specific client
        chunk_qs = KnowledgeChunk.objects.filter(client=client).select_related('document')
        chunks_list = list(chunk_qs)

        if not chunks_list:
            return []

        # 2. Dense Semantic Search
        dense_ranks: Dict[str, int] = {}
        dense_scores: Dict[str, float] = {}

        query_emb = get_embedding(query.strip())
        if query_emb:
            scored_dense = []
            for c in chunks_list:
                cid = str(c.id)
                emb = c.embedding
                if emb and len(emb) == 1536:
                    sim = cosine_similarity(query_emb, emb)
                    scored_dense.append((cid, sim))
                else:
                    scored_dense.append((cid, 0.0))

            scored_dense.sort(key=lambda x: x[1], reverse=True)
            for rank, (cid, sim) in enumerate(scored_dense):
                dense_ranks[cid] = rank + 1
                dense_scores[cid] = sim

        # 3. Lexical Keyword Search
        lexical_ranks: Dict[str, int] = {}
        lexical_scores: Dict[str, float] = {}

        query_tokens = [w.lower() for w in re.findall(r'\w+', query.strip()) if len(w) > 1]
        query_phrase = query.strip().lower()

        scored_lexical = []
        for c in chunks_list:
            cid = str(c.id)
            text_lower = (c.chunk_text or '').lower()
            title_lower = (getattr(c, 'page_title', '') or getattr(c.document, 'title', '') or '').lower()
            heading_lower = (getattr(c, 'heading_path', '') or '').lower()

            score = 0.0

            # Exact phrase match boost
            if query_phrase and query_phrase in text_lower:
                score += 5.0
            if query_phrase and (query_phrase in title_lower or query_phrase in heading_lower):
                score += 8.0

            # Individual token matches
            for token in query_tokens:
                # Count occurrences in body
                matches = text_lower.count(token)
                if matches > 0:
                    score += 1.0 + math.log(1 + matches)

                # Heading / title match boost
                if token in title_lower:
                    score += 3.0
                if token in heading_lower:
                    score += 2.0

            scored_lexical.append((cid, score))

        scored_lexical.sort(key=lambda x: x[1], reverse=True)
        for rank, (cid, score) in enumerate(scored_lexical):
            lexical_ranks[cid] = rank + 1
            lexical_scores[cid] = score

        # 4. Reciprocal Rank Fusion (RRF)
        # RRF Score = dense_weight / (60 + rank_dense) + lexical_weight / (60 + rank_lexical)
        fused_scores = []
        chunk_map = {str(c.id): c for c in chunks_list}

        for cid, chunk in chunk_map.items():
            r_dense = dense_ranks.get(cid, 9999)
            r_lex = lexical_ranks.get(cid, 9999)

            rrf = (dense_weight / (60.0 + r_dense)) + (lexical_weight / (60.0 + r_lex))
            fused_scores.append((cid, rrf))

        fused_scores.sort(key=lambda x: x[1], reverse=True)
        top_candidates = fused_scores[:top_k]

        results = []
        for cid, rrf_score in top_candidates:
            c = chunk_map[cid]
            doc = c.document
            source_url = getattr(c, 'source_url', None) or getattr(doc, 'source_url', None) or ''
            page_title = getattr(c, 'page_title', '') or getattr(doc, 'title', 'Document')
            heading_path = getattr(c, 'heading_path', '') or ''

            results.append({
                "chunk_id": cid,
                "text": c.chunk_text,
                "score": rrf_score,
                "dense_score": dense_scores.get(cid, 0.0),
                "lexical_score": lexical_scores.get(cid, 0.0),
                "doc_title": page_title,
                "source_url": source_url,
                "heading_path": heading_path,
            })

        return results

    @staticmethod
    def generate_rag_answer(
        query: str,
        relevant_chunks: List[Dict[str, Any]],
        client_model: Optional[Client] = None
    ) -> str:
        """
        Generates final answer using retrieved chunks with source citations
        and mirror-language matching.
        """
        ai_client = _get_client()
        if not ai_client:
            return "AI service is not configured. Please add an OPENAI_API_KEY."

        # Assemble rich context
        context_parts = []
        for i, chunk in enumerate(relevant_chunks, 1):
            src_url = chunk.get('source_url', '')
            url_str = f" | URL: {src_url}" if src_url else ""
            heading_str = f" | Section: {chunk['heading_path']}" if chunk.get('heading_path') else ""
            header = f"[Document Section {i} | Source: {chunk.get('doc_title', 'Knowledge')}{heading_str}{url_str}]"
            context_parts.append(f"{header}\n{chunk['text']}")

        knowledge_context = "\n\n".join(context_parts) if context_parts else "No relevant documents found."
        biz_name = getattr(client_model, 'business_name', None) or 'our business'

        system_prompt = f"""You are a helpful, professional, and knowledgeable AI assistant for {biz_name}.
You answer questions accurately based on the business documents provided below.

SOURCE CITATION RULES:
1. When answering factual questions from website documents, cite the exact source page title and page URL (if available in the section header) so the user can verify or read more. Example: "You can find more details here: [Page Title](https://example.com/page)".
2. Do not invent facts, features, prices, or contact details not present in the documents.

CRITICAL MULTILINGUAL & MIRROR-LANGUAGE RULES:
1. STRICT LANGUAGE MATCHING: You MUST detect the exact language and script used by the user in their message, and reply in the EXACT SAME LANGUAGE and tone:
   - Romanized Hindi / Hinglish (e.g. 'kya price hai', 'kese kaam krta hai', 'order kaise karein') -> Reply in natural Romanized Hindi / Hinglish.
   - Devanagari Hindi (e.g. 'नमस्ते, जानकारी चाहिए') -> Reply in pure Devanagari Hindi.
   - Regional Indian languages (Punjabi, Gujarati, Marathi, Bengali, Tamil, Telugu, etc.) -> Reply in that exact language.
   - English -> Reply in English.
   - NEVER reply in English if the user wrote in Hindi, Hinglish, or any regional language!

2. If a factual question's answer is NOT found in the documents, apologize politely in the CUSTOMER'S SAME LANGUAGE:
   - Hinglish: "Maaf kijiye, hamare paas iski jaankari knowledge base me nahi hai. Kripya humse directly contact karein."
   - Hindi: "क्षमा करें, हमारे पास अभी इसकी जानकारी उपलब्ध नहीं है। कृपया हमसे सीधे संपर्क करें।"
   - English: "I'm sorry, I don't have information about that in our knowledge base. Please contact us directly for assistance."

--- RELEVANT BUSINESS KNOWLEDGE ---
{knowledge_context}
--- END OF KNOWLEDGE ---"""

        try:
            response = ai_client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": query}
                ],
                max_tokens=600,
                temperature=0.3
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"[HybridRAGService] Error generating answer: {e}")
            return "I'm sorry, I'm unable to process your request right now. Please try again later."
