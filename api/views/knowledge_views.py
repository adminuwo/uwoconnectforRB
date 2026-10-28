from ..repositories.knowledge_repository import KnowledgeRepository
from ..repositories.client_repository import ClientRepository
from ..permissions.custom_permissions import IsApprovedUser
from rest_framework import status, views, viewsets
from rest_framework.response import Response
from firebase_admin import auth as firebase_auth
from django.contrib.auth import authenticate
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.decorators import action
from rest_framework.views import APIView
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils.decorators import method_decorator
from ..serializers import RegisterSerializer, UserSerializer, ClientSerializer, AutomationSerializer, WorkflowSerializer, ContactSerializer, TemplateSerializer, CampaignSerializer, SupportMessageSerializer, AuditLogSerializer, TeamInviteSerializer, ProductSerializer, OrderSerializer
from ..models import User, Client, Automation, Message, Workflow, KnowledgeDocument, KnowledgeChunk, Contact, Template, Campaign, SupportMessage, AuditLog, TeamInvite, Product, Order
import requests
import os
import json
from ..services.ai_service import get_ai_response, get_platform_assistance, get_rag_response, get_embedding, chunk_text, find_relevant_chunks
from rest_framework.permissions import BasePermission
from ..utils.channel_permissions import safe_get_client

def get_tenant_client(request):
    if not request.user or not request.user.is_authenticated:
        return None
    if getattr(request.user, 'role', '') == 'ADMIN':
        client_id = request.query_params.get('client_id') if hasattr(request, 'query_params') else None
        if not client_id and isinstance(getattr(request, 'data', None), dict):
            client_id = request.data.get('client_id')
        if client_id:
            try:
                return ClientRepository.get_client(id=client_id)
            except Exception:
                pass
        return safe_get_client(request.user)
    return safe_get_client(request.user)

class PlatformAssistantView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        query = request.data.get('query')
        if not query:
            return Response({"message": "Query is required"}, status=400)
        
        response = get_platform_assistance(query)
        return Response({"response": response})


from ..services.crawler_service import WebsiteCrawlerService
from ..services.semantic_chunker import SemanticChunker
from ..services.rag_service import HybridRAGService


class KnowledgeBaseView(APIView):
    """
    RAG Knowledge Base API with Embeddings
    GET  /api/knowledge/        → Client ke saare documents list karo
    POST /api/knowledge/        → Website Crawl / Document upload → Semantic Chunk → Embed → Store
    DELETE /api/knowledge/<pk>/ → Document + chunks delete karo
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        client = get_tenant_client(request)
        if not client:
            return Response([], status=200)

        def serialize_doc(doc):
            chunk_count = doc.chunks.count()
            embedded_count = doc.chunks.exclude(embedding=[]).count()
            return {
                "id": str(doc.id),
                "title": doc.title,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "source_url": getattr(doc, 'source_url', None) or '',
                "crawl_status": getattr(doc, 'crawl_status', 'COMPLETED'),
                "crawl_metadata": getattr(doc, 'crawl_metadata', {}) or {},
                "has_text": bool(doc.extracted_text),
                "text_preview": doc.extracted_text[:200] + "..." if len(doc.extracted_text) > 200 else doc.extracted_text,
                "chunks": chunk_count,
                "embedded": embedded_count,
                "fully_embedded": chunk_count > 0 and chunk_count == embedded_count,
                "created_at": doc.created_at,
                "updated_at": getattr(doc, 'updated_at', doc.created_at),
            }

        if pk:
            try:
                doc = KnowledgeRepository.filter_documents(client=client).filter(id=pk).first()
            except Exception:
                doc = None
            if not doc:
                return Response({"error": "Document not found"}, status=404)
            return Response(serialize_doc(doc))

        docs = KnowledgeRepository.filter_documents(client=client).order_by('-created_at')
        return Response([serialize_doc(doc) for doc in docs])

    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"message": "No client associated"}, status=400)

        file = request.FILES.get('file')
        title = request.data.get('title', '').strip()
        website_url = request.data.get('website_url', '').strip()
        content_snippet = (request.data.get('content_snippet') or request.data.get('text') or '').strip()
        doc_type = (request.data.get('doc_type') or '').upper()

        chunker = SemanticChunker(target_chunk_words=500, overlap_words=80)

        # === 1. Website URL Crawl & Multi-Page Ingestion ===
        if website_url or doc_type == 'URL':
            if not website_url:
                return Response({"message": "Website URL is required"}, status=400)

            try:
                max_pages = int(request.data.get('max_pages') or 25)
            except (ValueError, TypeError):
                max_pages = 25

            try:
                max_depth = int(request.data.get('max_depth') or 3)
            except (ValueError, TypeError):
                max_depth = 3

            respect_robots = bool(request.data.get('respect_robots', True))

            crawler = WebsiteCrawlerService(
                start_url=website_url,
                max_pages=max_pages,
                max_depth=max_depth,
                respect_robots=respect_robots
            )

            # SSRF check on start URL before crawling
            if not crawler.is_safe_url(crawler.raw_start_url):
                return Response({
                    "message": "The provided URL is blocked by security policy (Private IP, Localhost, or Cloud Metadata endpoint)."
                }, status=400)

            crawl_result = crawler.crawl()

            if not crawl_result.get("success") or not crawl_result.get("crawled_pages"):
                failed_reasons = []
                for f in crawl_result.get("diagnostics", {}).get("failed_urls", []):
                    failed_reasons.append(f"{f.get('url')}: {f.get('error')}")
                for s in crawl_result.get("diagnostics", {}).get("skipped_urls", []):
                    failed_reasons.append(f"{s.get('url')}: {s.get('reason')}")
                
                err_detail = "; ".join(failed_reasons[:3]) if failed_reasons else "No accessible HTML content could be extracted."
                return Response({
                    "message": f"Could not crawl website: {err_detail}",
                    "diagnostics": crawl_result.get("diagnostics")
                }, status=400)

            crawled_pages = crawl_result["crawled_pages"]

            # Aggregate all pages into combined text with clear page section boundaries
            page_blocks = []
            for p in crawled_pages:
                page_blocks.append(f"=== PAGE: {p['title']} ({p['url']}) ===\n{p['structured_text']}")
            combined_text = "\n\n".join(page_blocks)

            doc_title = title or crawler.allowed_host

            # Check if this exact source_url was previously crawled for this client
            existing_doc = KnowledgeDocument.objects.filter(client=client, source_url=website_url).first()
            if existing_doc:
                knowledge_doc = existing_doc
                knowledge_doc.title = doc_title
                knowledge_doc.extracted_text = combined_text
                knowledge_doc.file_type = 'url'
                knowledge_doc.file_size = len(combined_text.encode('utf-8'))
                knowledge_doc.crawl_status = 'COMPLETED'
                knowledge_doc.crawl_metadata = {
                    "total_pages_discovered": crawl_result["diagnostics"]["discovered_count"],
                    "total_pages_crawled": len(crawled_pages),
                    "total_pages_skipped": crawl_result["diagnostics"]["skipped_count"],
                    "total_pages_failed": crawl_result["diagnostics"]["failed_count"],
                    "duration_seconds": crawl_result["duration_seconds"],
                    "crawled_urls": [{"url": p["url"], "title": p["title"], "chars": p["char_count"]} for p in crawled_pages],
                    "skipped_urls": crawl_result["diagnostics"]["skipped_urls"],
                    "failed_urls": crawl_result["diagnostics"]["failed_urls"],
                }
                knowledge_doc.save()
                # Clean up old chunks for this document before adding new
                KnowledgeChunk.objects.filter(document=knowledge_doc).delete()
            else:
                knowledge_doc = KnowledgeDocument.objects.create(
                    client=client,
                    title=doc_title,
                    source_url=website_url,
                    extracted_text=combined_text,
                    file_type='url',
                    file_size=len(combined_text.encode('utf-8')),
                    crawl_status='COMPLETED',
                    crawl_metadata={
                        "total_pages_discovered": crawl_result["diagnostics"]["discovered_count"],
                        "total_pages_crawled": len(crawled_pages),
                        "total_pages_skipped": crawl_result["diagnostics"]["skipped_count"],
                        "total_pages_failed": crawl_result["diagnostics"]["failed_count"],
                        "duration_seconds": crawl_result["duration_seconds"],
                        "crawled_urls": [{"url": p["url"], "title": p["title"], "chars": p["char_count"]} for p in crawled_pages],
                        "skipped_urls": crawl_result["diagnostics"]["skipped_urls"],
                        "failed_urls": crawl_result["diagnostics"]["failed_urls"],
                    }
                )

            # Generate semantic chunks for all crawled pages
            all_chunks = []
            chunk_global_idx = 0
            for page in crawled_pages:
                page_chunks = chunker.chunk_extracted_page(page, global_chunk_start_idx=chunk_global_idx)
                all_chunks.extend(page_chunks)
                chunk_global_idx += len(page_chunks)

            # Generate embeddings and store chunks
            embedded_count = 0
            for c_data in all_chunks:
                embedding = get_embedding(c_data["chunk_text"])
                KnowledgeChunk.objects.create(
                    document=knowledge_doc,
                    client=client,
                    chunk_text=c_data["chunk_text"],
                    chunk_index=c_data["chunk_index"],
                    source_url=c_data.get("source_url") or website_url,
                    page_title=c_data.get("page_title") or doc_title,
                    heading_path=c_data.get("heading_path") or "",
                    content_hash=c_data.get("content_hash") or "",
                    embedding=embedding if embedding else []
                )
                if embedding:
                    embedded_count += 1

            return Response({
                "id": str(knowledge_doc.id),
                "title": knowledge_doc.title,
                "file_type": knowledge_doc.file_type,
                "file_size": knowledge_doc.file_size,
                "source_url": knowledge_doc.source_url,
                "pages_crawled": len(crawled_pages),
                "chunks": len(all_chunks),
                "embedded": embedded_count,
                "fully_embedded": embedded_count == len(all_chunks),
                "duration_seconds": crawl_result["duration_seconds"],
                "created_at": knowledge_doc.created_at,
                "crawl_metadata": knowledge_doc.crawl_metadata,
                "message": f"Website indexed successfully! Crawled {len(crawled_pages)} pages, created {len(all_chunks)} semantic chunks ({embedded_count} embedded)."
            }, status=201)

        # === 2. File Upload (PDF, DOCX, TXT) ===
        elif file:
            if file.size > 15 * 1024 * 1024:
                return Response({"message": "File too large. Maximum size is 15MB."}, status=400)

            ext = os.path.splitext(file.name)[1].lower().lstrip('.')
            if ext not in ['pdf', 'docx', 'txt']:
                return Response({"message": "Only PDF, DOCX, and TXT files are supported."}, status=400)

            file_type = ext
            file_size = file.size
            doc_title = title or os.path.splitext(file.name)[0]
            extracted_text = ""

            try:
                if ext == 'pdf':
                    import PyPDF2
                    pdf_reader = PyPDF2.PdfReader(file)
                    for page in pdf_reader.pages:
                        page_text = page.extract_text()
                        if page_text:
                            extracted_text += page_text + "\n"
                elif ext == 'docx':
                    import docx
                    doc_file = docx.Document(file)
                    for para in doc_file.paragraphs:
                        if para.text.strip():
                            extracted_text += para.text + "\n"
                elif ext == 'txt':
                    extracted_text = file.read().decode('utf-8', errors='ignore')
            except Exception as e:
                return Response({"message": f"Could not extract text from file: {str(e)}"}, status=400)

            if not extracted_text.strip():
                return Response({"message": "No readable text content found in file."}, status=400)

            knowledge_doc = KnowledgeDocument.objects.create(
                client=client,
                title=doc_title,
                extracted_text=extracted_text.strip(),
                file_type=file_type,
                file_size=file_size,
            )
            knowledge_doc.file = file
            knowledge_doc.save()

            page_data = {
                "url": doc_title,
                "title": doc_title,
                "structured_text": extracted_text.strip()
            }
            chunks = chunker.chunk_extracted_page(page_data)

            embedded_count = 0
            for c_data in chunks:
                embedding = get_embedding(c_data["chunk_text"])
                KnowledgeChunk.objects.create(
                    document=knowledge_doc,
                    client=client,
                    chunk_text=c_data["chunk_text"],
                    chunk_index=c_data["chunk_index"],
                    page_title=doc_title,
                    heading_path=c_data.get("heading_path") or doc_title,
                    content_hash=c_data.get("content_hash") or "",
                    embedding=embedding if embedding else []
                )
                if embedding:
                    embedded_count += 1

            return Response({
                "id": str(knowledge_doc.id),
                "title": knowledge_doc.title,
                "file_type": knowledge_doc.file_type,
                "file_size": knowledge_doc.file_size,
                "chunks": len(chunks),
                "embedded": embedded_count,
                "fully_embedded": embedded_count == len(chunks),
                "created_at": knowledge_doc.created_at,
                "message": f"Document indexed! {len(chunks)} chunks created, {embedded_count} embedded."
            }, status=201)

        # === 3. Direct Text / FAQ ===
        elif content_snippet or doc_type == 'TEXT':
            extracted_text = content_snippet
            if not extracted_text.strip():
                return Response({"message": "Text content cannot be empty."}, status=400)

            doc_title = title or ((extracted_text[:40] + '...') if len(extracted_text) > 40 else 'Knowledge Note')
            knowledge_doc = KnowledgeDocument.objects.create(
                client=client,
                title=doc_title,
                extracted_text=extracted_text.strip(),
                file_type='txt',
                file_size=len(extracted_text.encode('utf-8'))
            )

            page_data = {
                "url": doc_title,
                "title": doc_title,
                "structured_text": extracted_text.strip()
            }
            chunks = chunker.chunk_extracted_page(page_data)

            embedded_count = 0
            for c_data in chunks:
                embedding = get_embedding(c_data["chunk_text"])
                KnowledgeChunk.objects.create(
                    document=knowledge_doc,
                    client=client,
                    chunk_text=c_data["chunk_text"],
                    chunk_index=c_data["chunk_index"],
                    page_title=doc_title,
                    heading_path=c_data.get("heading_path") or doc_title,
                    content_hash=c_data.get("content_hash") or "",
                    embedding=embedding if embedding else []
                )
                if embedding:
                    embedded_count += 1

            return Response({
                "id": str(knowledge_doc.id),
                "title": knowledge_doc.title,
                "file_type": knowledge_doc.file_type,
                "file_size": knowledge_doc.file_size,
                "chunks": len(chunks),
                "embedded": embedded_count,
                "fully_embedded": embedded_count == len(chunks),
                "created_at": knowledge_doc.created_at,
                "message": f"Knowledge note indexed! {len(chunks)} chunks created, {embedded_count} embedded."
            }, status=201)

        return Response({"message": "Please provide a document file, website URL, or text content to index."}, status=400)

    def delete(self, request, pk=None):
        target_id = pk or request.query_params.get('id') or request.data.get('id')
        if not target_id:
            return Response({"message": "Document ID is required"}, status=400)

        client = get_tenant_client(request)

        try:
            if client:
                doc = KnowledgeDocument.objects.filter(id=target_id, client=client).first()
            elif request.user.role == 'ADMIN' or getattr(request.user, 'is_staff', False) or getattr(request.user, 'is_superuser', False):
                doc = KnowledgeDocument.objects.filter(id=target_id).first()
            else:
                doc = None

            if not doc:
                return Response({"message": "Document not found or access denied"}, status=404)

            doc_title = doc.title

            # Clean up physical file if stored on disk
            if doc.file:
                try:
                    if os.path.isfile(doc.file.path):
                        os.remove(doc.file.path)
                except Exception as e:
                    print(f"Error removing physical file: {e}")

            # Delete chunks explicitly and document
            KnowledgeChunk.objects.filter(document=doc).delete()
            doc.delete()

            return Response({"message": f"Document '{doc_title}' and all vector chunks deleted successfully."}, status=200)
        except Exception as e:
            print(f"Delete knowledge document error: {e}")
            return Response({"message": f"Failed to delete document: {str(e)}"}, status=500)


class KnowledgeRecrawlView(APIView):
    """
    POST /api/knowledge/<pk>/recrawl/
    Performs staged re-crawl of an existing website document.
    Never deletes existing chunks if the crawl fails midway!
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        client = get_tenant_client(request)
        if not client:
            return Response({"message": "No client associated"}, status=400)

        doc = KnowledgeDocument.objects.filter(id=pk, client=client).first()
        if not doc:
            return Response({"message": "Knowledge document not found"}, status=404)

        if doc.file_type != 'url' or not doc.source_url:
            return Response({"message": "Only website URL documents can be re-crawled"}, status=400)

        max_pages = int(request.data.get('max_pages') or 25)
        max_depth = int(request.data.get('max_depth') or 3)

        crawler = WebsiteCrawlerService(
            start_url=doc.source_url,
            max_pages=max_pages,
            max_depth=max_depth
        )

        crawl_result = crawler.crawl()
        if not crawl_result.get("success") or not crawl_result.get("crawled_pages"):
            return Response({
                "message": "Re-crawl failed. The existing indexed content has been safely preserved.",
                "diagnostics": crawl_result.get("diagnostics")
            }, status=400)

        crawled_pages = crawl_result["crawled_pages"]
        chunker = SemanticChunker(target_chunk_words=500, overlap_words=80)

        all_chunks = []
        chunk_global_idx = 0
        for page in crawled_pages:
            page_chunks = chunker.chunk_extracted_page(page, global_chunk_start_idx=chunk_global_idx)
            all_chunks.extend(page_chunks)
            chunk_global_idx += len(page_chunks)

        # Staged replacement:
        # 1. Delete previous chunks only after new crawl has successfully yielded content
        KnowledgeChunk.objects.filter(document=doc).delete()

        # 2. Update document metadata
        page_blocks = [f"=== PAGE: {p['title']} ({p['url']}) ===\n{p['structured_text']}" for p in crawled_pages]
        combined_text = "\n\n".join(page_blocks)
        doc.extracted_text = combined_text
        doc.file_size = len(combined_text.encode('utf-8'))
        doc.crawl_status = 'COMPLETED'
        doc.crawl_metadata = {
            "total_pages_discovered": crawl_result["diagnostics"]["discovered_count"],
            "total_pages_crawled": len(crawled_pages),
            "total_pages_skipped": crawl_result["diagnostics"]["skipped_count"],
            "total_pages_failed": crawl_result["diagnostics"]["failed_count"],
            "duration_seconds": crawl_result["duration_seconds"],
            "crawled_urls": [{"url": p["url"], "title": p["title"], "chars": p["char_count"]} for p in crawled_pages],
            "skipped_urls": crawl_result["diagnostics"]["skipped_urls"],
            "failed_urls": crawl_result["diagnostics"]["failed_urls"],
            "last_recrawl_at": time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime()),
        }
        doc.save()

        # 3. Insert new chunks with embeddings
        embedded_count = 0
        for c_data in all_chunks:
            embedding = get_embedding(c_data["chunk_text"])
            KnowledgeChunk.objects.create(
                document=doc,
                client=client,
                chunk_text=c_data["chunk_text"],
                chunk_index=c_data["chunk_index"],
                source_url=c_data.get("source_url") or doc.source_url,
                page_title=c_data.get("page_title") or doc.title,
                heading_path=c_data.get("heading_path") or "",
                content_hash=c_data.get("content_hash") or "",
                embedding=embedding if embedding else []
            )
            if embedding:
                embedded_count += 1

        return Response({
            "message": f"Website re-crawl completed successfully! {len(crawled_pages)} pages updated, {len(all_chunks)} semantic chunks re-indexed.",
            "pages_crawled": len(crawled_pages),
            "chunks": len(all_chunks),
            "embedded": embedded_count,
            "crawl_metadata": doc.crawl_metadata
        }, status=200)


class KnowledgeQueryView(APIView):
    """
    POST /api/knowledge/query/
    RAG Search & Retrieval testing endpoint:
    Evaluates Hybrid Search (Dense + Lexical) and generates answer with source citations.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"message": "No client associated"}, status=400)

        query = request.data.get('query', '').strip()
        if not query:
            return Response({"message": "Query parameter is required"}, status=400)

        top_k = int(request.data.get('top_k') or 5)

        # Retrieve relevant chunks using hybrid search
        relevant_chunks = HybridRAGService.retrieve_relevant_chunks(client, query, top_k=top_k)

        # Generate final answer with citations
        answer = HybridRAGService.generate_rag_answer(query, relevant_chunks, client)

        return Response({
            "query": query,
            "answer": answer,
            "retrieved_count": len(relevant_chunks),
            "chunks": relevant_chunks,
            "sources": list({c.get("source_url") for c in relevant_chunks if c.get("source_url")})
        }, status=200)


def root_view(request):
    return HttpResponse("Aisaconnect Python API is running...")


from rest_framework.decorators import action
import threading


