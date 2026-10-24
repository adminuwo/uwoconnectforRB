"""
SemanticChunker
Implements heading-aware, structure-preserving chunking for RAG pipelines:
- Preserves relationship between headings, paragraphs, lists, and tables
- Prefixes contextual breadcrumbs (Source URL, Page Title, Heading Hierarchy)
- Target chunk size: ~500-800 tokens (~400-600 words) with controlled overlap
- Generates SHA-256 content hashes for deduplication and incremental updates
- Preserves full metadata for vector search and citation attribution
"""

import hashlib
import re
from typing import List, Dict, Any


class SemanticChunker:
    def __init__(self, target_chunk_words: int = 500, overlap_words: int = 80):
        self.target_chunk_words = target_chunk_words
        self.overlap_words = overlap_words

    def chunk_extracted_page(self, page_data: Dict[str, Any], global_chunk_start_idx: int = 0) -> List[Dict[str, Any]]:
        """
        Chunks an extracted page dictionary produced by WebpageContentExtractor.
        Returns a list of chunk dictionaries with complete metadata.
        """
        url = page_data.get("url") or page_data.get("canonical_url", "")
        title = page_data.get("title", "")
        sections = page_data.get("sections", [])
        structured_text = page_data.get("structured_text", "")

        # Fallback if no sections were explicitly parsed
        if not sections and structured_text:
            sections = [{
                "heading_path": title or "Main Content",
                "content": structured_text
            }]

        chunks = []
        current_idx = global_chunk_start_idx

        # Group sections into sized chunks
        current_chunk_paragraphs = []
        current_word_count = 0
        current_path = title

        def create_chunk_dict(paragraphs: List[str], path: str, idx: int) -> Dict[str, Any]:
            body = "\n\n".join(paragraphs).strip()
            # Header breadcrumb prepended to the chunk text for dense & lexical search context
            breadcrumb_header = (
                f"[Source: {url}]\n"
                f"[Page Title: {title}]\n"
                f"[Section: {path}]\n"
                f"---\n"
            )
            full_chunk_text = breadcrumb_header + body
            content_hash = hashlib.sha256(body.encode('utf-8')).hexdigest()

            return {
                "chunk_index": idx,
                "chunk_text": full_chunk_text,
                "text": full_chunk_text,
                "clean_body": body,
                "source_url": url,
                "page_title": title,
                "doc_title": title,
                "heading_path": path,
                "content_hash": content_hash,
                "word_count": len(full_chunk_text.split()),
                "char_count": len(full_chunk_text),
            }

        for sec in sections:
            sec_path = sec.get("heading_path") or title or "General"
            sec_content = sec.get("content", "").strip()
            if not sec_content:
                continue

            sec_paragraphs = [p.strip() for p in sec_content.split("\n\n") if p.strip()]

            for para in sec_paragraphs:
                para_words = len(para.split())

                # If single paragraph is exceptionally large, split it cleanly
                if para_words > self.target_chunk_words:
                    if current_chunk_paragraphs:
                        chunks.append(create_chunk_dict(current_chunk_paragraphs, current_path, current_idx))
                        current_idx += 1
                        current_chunk_paragraphs = []
                        current_word_count = 0

                    sub_chunks = self._split_large_text(para, self.target_chunk_words, self.overlap_words)
                    for sc in sub_chunks:
                        chunks.append(create_chunk_dict([sc], sec_path, current_idx))
                        current_idx += 1
                    current_path = sec_path
                    continue

                if current_word_count + para_words > self.target_chunk_words and current_chunk_paragraphs:
                    # Flush current chunk
                    chunks.append(create_chunk_dict(current_chunk_paragraphs, current_path, current_idx))
                    current_idx += 1

                    # Compute overlap from end of previous paragraphs
                    overlap_paras = []
                    overlap_words_acc = 0
                    for p in reversed(current_chunk_paragraphs):
                        w = len(p.split())
                        if overlap_words_acc + w <= self.overlap_words:
                            overlap_paras.insert(0, p)
                            overlap_words_acc += w
                        else:
                            break

                    current_chunk_paragraphs = overlap_paras + [para]
                    current_word_count = overlap_words_acc + para_words
                    current_path = sec_path
                else:
                    current_chunk_paragraphs.append(para)
                    current_word_count += para_words
                    current_path = sec_path

        # Flush final chunk if any
        if current_chunk_paragraphs:
            chunks.append(create_chunk_dict(current_chunk_paragraphs, current_path, current_idx))

        return chunks

    def _split_large_text(self, text: str, chunk_words: int, overlap_words: int) -> List[str]:
        """Splits a single huge block of text (e.g. huge table or long text) into overlapping slices."""
        words = text.split()
        if len(words) <= chunk_words:
            return [text]

        slices = []
        start = 0
        while start < len(words):
            end = start + chunk_words
            slices.append(" ".join(words[start:end]))
            start = end - overlap_words
        return slices
