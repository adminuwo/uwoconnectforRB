from rest_framework import serializers
from api.models import (
    DynamicContentItem,
    DynamicBanner,
    AppMaintenanceConfig,
    AppFeatureFlag,
    DynamicContentVersionSnapshot
)
from api.serializers import ObjectIdField


class DynamicContentItemSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = DynamicContentItem
        fields = [
            'id', 'section', 'key', 'language', 'content_type',
            'label', 'description', 'draft_value', 'published_value',
            'is_active', 'version', 'updated_by_name',
            'published_at', 'created_at', 'updated_at'
        ]

    def get_updated_by_name(self, obj):
        if obj.updated_by:
            return obj.updated_by.get_full_name() or obj.updated_by.username
        return 'System Admin'


class DynamicBannerSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    image_url_display = serializers.SerializerMethodField()

    class Meta:
        model = DynamicBanner
        fields = [
            'id', 'title', 'description', 'image', 'image_url',
            'image_url_display', 'action_type', 'action_url',
            'placement', 'display_order', 'is_active', 'draft_mode',
            'created_at', 'updated_at'
        ]

    def get_image_url_display(self, obj):
        if obj.image:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.image.url)
            return obj.image.url
        return obj.image_url or ''


class AppMaintenanceConfigSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    updated_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AppMaintenanceConfig
        fields = [
            'id', 'is_enabled', 'title', 'message',
            'estimated_completion', 'allowed_roles',
            'updated_at', 'updated_by_name'
        ]

    def get_updated_by_name(self, obj):
        if obj.updated_by:
            return obj.updated_by.get_full_name() or obj.updated_by.username
        return 'System Admin'


class AppFeatureFlagSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = AppFeatureFlag
        fields = ['id', 'feature_key', 'name', 'description', 'is_enabled', 'updated_at']


class DynamicContentVersionSnapshotSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    published_by_name = serializers.SerializerMethodField()
    items_count = serializers.SerializerMethodField()

    class Meta:
        model = DynamicContentVersionSnapshot
        fields = [
            'id', 'version_number', 'changelog',
            'published_by_name', 'published_at',
            'items_count'
        ]

    def get_published_by_name(self, obj):
        if obj.published_by:
            return obj.published_by.get_full_name() or obj.published_by.username
        return 'System Admin'

    def get_items_count(self, obj):
        data = obj.snapshot_data or {}
        content_items = data.get('content', {})
        return len(content_items)
