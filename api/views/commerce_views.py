from ..services.admin_service import AdminService
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
    if getattr(request.user, 'role', '') == 'ADMIN':
        client_id = request.query_params.get('client_id') if hasattr(request, 'query_params') else None
        if not client_id and isinstance(getattr(request, 'data', None), dict):
            client_id = request.data.get('client_id')
        if client_id:
            try:
                return ClientRepository.get_client(id=client_id)
            except Exception:
                pass
        return getattr(request.user, 'client', None)
    return getattr(request.user, 'client', None)


from ..repositories.product_repository import ProductRepository
from ..repositories.order_repository import OrderRepository

class ProductViewSet(viewsets.ModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [IsAuthenticated, IsApprovedUser]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if client:
            return ProductRepository.filter_products(client=client)
        return ProductRepository.get_all()

    def perform_create(self, serializer):
        client = get_tenant_client(self.request)
        instance = serializer.save(client=client)
        AdminService.log_admin_action(self.request, instance, 'Products', 'CREATE', after_value=str(serializer.data))

    @action(detail=True, methods=['post'])
    def track_click(self, request, pk=None):
        product = self.get_object()
        click_type = request.data.get('type', 'link')  # 'link' or 'button'
        if click_type == 'button':
            product.button_clicks_count = (product.button_clicks_count or 0) + 1
        else:
            product.link_clicks_count = (product.link_clicks_count or 0) + 1
        product.views_count = (product.views_count or 0) + 1
        product.save()
        return Response({'status': 'success', 'link_clicks': product.link_clicks_count, 'button_clicks': product.button_clicks_count})

    @action(detail=True, methods=['get', 'post'], permission_classes=[])
    def redirect_link(self, request, pk=None):
        from django.http import HttpResponseRedirect
        from bson import ObjectId
        product = None
        try:
            product = Product.objects.get(pk=pk)
        except Exception:
            try:
                product = Product.objects.get(pk=ObjectId(pk))
            except Exception:
                pass

        if not product:
            return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

        product.link_clicks_count = (product.link_clicks_count or 0) + 1
        product.views_count = (product.views_count or 0) + 1
        product.save()

        target_url = product.product_url or '/'
        if target_url and not target_url.startswith('http://') and not target_url.startswith('https://'):
            target_url = 'https://' + target_url

        return HttpResponseRedirect(target_url)

    @action(detail=False, methods=['post'])
    def bulk_action(self, request):
        client = get_tenant_client(self.request)
        product_ids = request.data.get('ids', [])
        action_type = request.data.get('action')
        payload = request.data.get('payload', {})

        if not product_ids or not action_type:
            return Response({'error': 'Missing ids or action'}, status=status.HTTP_400_BAD_REQUEST)

        queryset = Product.objects.filter(id__in=product_ids)
        if client:
            queryset = queryset.filter(client=client)

        updated_count = 0
        if action_type == 'delete':
            updated_count, _ = queryset.delete()
            return Response({'status': 'success', 'message': f'Deleted {updated_count} products.'})
        elif action_type == 'update_price':
            price = payload.get('price')
            discount_price = payload.get('discount_price')
            if price is not None:
                queryset.update(price=price)
            if discount_price is not None:
                queryset.update(discount_price=discount_price)
            return Response({'status': 'success', 'message': 'Price updated for selected products.'})
        elif action_type == 'update_category':
            category = payload.get('category')
            if category:
                queryset.update(category=category)
            return Response({'status': 'success', 'message': 'Category updated for selected products.'})
        elif action_type == 'update_link':
            product_url = payload.get('product_url')
            link_type = payload.get('link_type')
            cta_text = payload.get('cta_text')
            button_color = payload.get('button_color')
            update_data = {}
            if product_url: update_data['product_url'] = product_url
            if link_type: update_data['link_type'] = link_type
            if cta_text: update_data['cta_text'] = cta_text
            if button_color: update_data['button_color'] = button_color
            if update_data:
                queryset.update(**update_data)
            return Response({'status': 'success', 'message': 'Product links updated.'})

        return Response({'error': 'Invalid action type'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['post'])
    def import_csv(self, request):
        client = get_tenant_client(self.request)
        if not client:
            return Response({'error': 'Unauthorized tenant'}, status=status.HTTP_400_BAD_REQUEST)

        file = request.FILES.get('file')
        if not file:
            return Response({'error': 'No file uploaded'}, status=status.HTTP_400_BAD_REQUEST)

        import csv
        import io
        try:
            decoded_file = file.read().decode('utf-8')
            reader = csv.DictReader(io.StringIO(decoded_file))
            created_count = 0
            for row in reader:
                name = row.get('Name') or row.get('name')
                price = row.get('Price') or row.get('price') or 0.00
                if name:
                    Product.objects.create(
                        client=client,
                        name=name.strip(),
                        price=float(price),
                        category=row.get('Category', 'PHYSICAL').upper().strip(),
                        description=row.get('Description', '').strip(),
                        image_url=row.get('ImageURL', '').strip(),
                        product_url=row.get('ProductURL', '').strip(),
                        cta_text=row.get('CTAText', 'View Product').strip(),
                        link_type=row.get('LinkType', 'WEBSITE').upper().strip(),
                        sku=row.get('SKU', '').strip(),
                        brand=row.get('Brand', '').strip()
                    )
                    created_count += 1
            return Response({'status': 'success', 'message': f'Successfully imported {created_count} products.'})
        except Exception as e:
            return Response({'error': f'Failed to parse CSV: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def analytics(self, request):
        client = get_tenant_client(self.request)
        products = Product.objects.filter(client=client) if client else Product.objects.all()

        total_views = sum(p.views_count or 0 for p in products)
        total_link_clicks = sum(p.link_clicks_count or 0 for p in products)
        total_button_clicks = sum(p.button_clicks_count or 0 for p in products)
        total_whatsapp_sends = sum(p.whatsapp_sends_count or 0 for p in products)
        total_conversions = sum(p.conversions_count or 0 for p in products)
        total_revenue = sum(float(p.revenue_generated or 0) for p in products)

        ctr = round((total_button_clicks + total_link_clicks) / max(total_views, 1) * 100, 2)

        top_products = sorted(products, key=lambda p: (p.link_clicks_count or 0) + (p.button_clicks_count or 0), reverse=True)[:5]
        top_list = [{
            'id': str(p.id),
            'name': p.name,
            'price': float(p.price),
            'views': p.views_count,
            'clicks': (p.link_clicks_count or 0) + (p.button_clicks_count or 0),
            'product_url': p.product_url,
            'cta_text': p.cta_text
        } for p in top_products]

        return Response({
            'total_products': len(products),
            'total_views': total_views,
            'total_link_clicks': total_link_clicks,
            'total_button_clicks': total_button_clicks,
            'total_whatsapp_sends': total_whatsapp_sends,
            'total_conversions': total_conversions,
            'total_revenue': total_revenue,
            'ctr': ctr,
            'top_products': top_list
        })

class OrderViewSet(viewsets.ModelViewSet):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated, IsApprovedUser]

    def get_queryset(self):
        client = get_tenant_client(self.request)
        if client:
            return OrderRepository.filter_orders(client=client)
        return OrderRepository.get_all()

    def perform_create(self, serializer):
        client = get_tenant_client(self.request)
        instance = serializer.save(client=client)
        AdminService.log_admin_action(self.request, instance, 'Orders', 'CREATE', after_value=str(serializer.data))
