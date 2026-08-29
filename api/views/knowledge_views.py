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

def get_tenant_client(request):
    if not request.user or not request.user.is_authenticated:
        return None
    if request.user.role == 'ADMIN':
        client_id = request.query_params.get('client_id') or request.data.get('client_id')
        if client_id:
            try:
                return ClientRepository.get_client(id=client_id)
            except (Client.DoesNotExist, ValueError):
                pass
        return None
    return request.user.client

class PlatformAssistantView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        query = request.data.get('query')
        if not query:
            return Response({"message": "Query is required"}, status=400)
        
        response = get_platform_assistance(query)
        return Response({"response": response})


class KnowledgeBaseView(APIView):
    """
    RAG Knowledge Base API with Embeddings
    GET  /api/knowledge/       → Client ke saare documents list karo
    POST /api/knowledge/       → Document upload → Extract text → Chunk → Embed → Store
    DELETE /api/knowledge/<pk>/ → Document + chunks delete karo
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        client = get_tenant_client(request)
        if not client:
            return Response([], status=200)
        
        if pk:
            doc = KnowledgeRepository.filter_documents(client=client).filter(id=pk).first()
            if not doc:
                return Response({"error": "Document not found"}, status=404)
            chunk_count = doc.chunks.count()
            embedded_count = doc.chunks.exclude(embedding=[]).count()
            return Response({
                "id": str(doc.id),
                "title": doc.title,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "has_text": bool(doc.extracted_text),
                "text_preview": doc.extracted_text[:200] + "..." if len(doc.extracted_text) > 200 else doc.extracted_text,
                "chunks": chunk_count,
                "embedded": embedded_count,
                "fully_embedded": chunk_count > 0 and chunk_count == embedded_count,
                "created_at": doc.created_at,
            })

        docs = KnowledgeRepository.filter_documents(client=client).order_by('-created_at')
        data = []
        for doc in docs:
            chunk_count = doc.chunks.count()
            embedded_count = doc.chunks.exclude(embedding=[]).count()
            data.append({
                "id": str(doc.id),
                "title": doc.title,
                "file_type": doc.file_type,
                "file_size": doc.file_size,
                "has_text": bool(doc.extracted_text),
                "text_preview": doc.extracted_text[:200] + "..." if len(doc.extracted_text) > 200 else doc.extracted_text,
                "chunks": chunk_count,
                "embedded": embedded_count,
                "fully_embedded": chunk_count > 0 and chunk_count == embedded_count,
                "created_at": doc.created_at,
            })
        return Response(data)

    def post(self, request):
        client = get_tenant_client(request)
        if not client:
            return Response({"message": "No client associated"}, status=400)

        file = request.FILES.get('file')
        title = request.data.get('title', '')

        if not file:
            return Response({"message": "File is required"}, status=400)

        # File size check — max 5MB
        if file.size > 5 * 1024 * 1024:
            return Response({"message": "File too large. Maximum size is 5MB."}, status=400)

        ext = os.path.splitext(file.name)[1].lower().lstrip('.')
        if ext not in ['pdf', 'docx', 'txt']:
            return Response({"message": "Only PDF, DOCX, and TXT files are supported."}, status=400)

        if not title:
            title = os.path.splitext(file.name)[0]

        # === STEP 1: Extract text from file ===
        extracted_text = ""
        try:
            if ext == 'pdf':
                # pyrefly: ignore [missing-import]
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
            print(f"Text extraction error: {str(e)}")
            return Response({"message": f"Could not extract text from file: {str(e)}"}, status=400)

        if not extracted_text.strip():
            return Response({"message": "No readable text found in the file. Please check the file content."}, status=400)

        knowledge_doc = KnowledgeRepository.create_knowledgedocument(
            client=client,
            title=title,
            extracted_text=extracted_text.strip(),
            file_type=ext,
            file_size=file.size,
        )
        knowledge_doc.file = file
        knowledge_doc.save()

        # === STEP 3: Chunk the text ===
        chunks = chunk_text(extracted_text.strip(), chunk_size=800, overlap=100)
        print(f"Document '{title}' split into {len(chunks)} chunks")

        # === STEP 4: Generate embeddings for each chunk & save ===
        embedded_count = 0
        for i, chunk_content in enumerate(chunks):
            embedding = get_embedding(chunk_content)
            KnowledgeRepository.create_knowledgechunk(
                document=knowledge_doc,
                client=client,
                chunk_text=chunk_content,
                chunk_index=i,
                embedding=embedding if embedding else [],
            )
            if embedding:
                embedded_count += 1

        print(f"Successfully embedded {embedded_count}/{len(chunks)} chunks for '{title}'")

        return Response({
            "id": str(knowledge_doc.id),
            "title": knowledge_doc.title,
            "file_type": knowledge_doc.file_type,
            "file_size": knowledge_doc.file_size,
            "has_text": True,
            "text_preview": extracted_text[:200] + "..." if len(extracted_text) > 200 else extracted_text,
            "chunks": len(chunks),
            "embedded": embedded_count,
            "fully_embedded": embedded_count == len(chunks),
            "created_at": knowledge_doc.created_at,
            "message": f"Document uploaded! {len(chunks)} chunks created, {embedded_count} embedded."
        }, status=201)

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


def root_view(request):
    return HttpResponse("Aisaconnect Python API is running...")


from rest_framework.decorators import action
import threading


