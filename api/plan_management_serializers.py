from rest_framework import serializers
from .serializers import ObjectIdField
from .models import Feature, Plan, PlanFeature, ClientFeatureOverride, PlanAuditLog

# ── PLAN MANAGEMENT SERIALIZERS ─────────────────────────────────────

class FeatureSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = Feature
        fields = '__all__'

class PlanSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)
    feature_keys = serializers.SerializerMethodField()
    channel_count = serializers.SerializerMethodField()
    connector_count = serializers.SerializerMethodField()

    class Meta:
        model = Plan
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

    def get_feature_keys(self, obj):
        if obj.metadata and isinstance(obj.metadata, dict):
            return obj.metadata.get('feature_keys', [])
        return []

    def get_channel_count(self, obj):
        keys = self.get_feature_keys(obj)
        return len([k for k in keys if k.startswith('channel_')])

    def get_connector_count(self, obj):
        keys = self.get_feature_keys(obj)
        return len([k for k in keys if k.startswith('connector_')])

    def to_representation(self, instance):
        ret = super().to_representation(instance)
        # Ensure metadata values are exposed nicely if set
        meta = instance.metadata or {}
        if isinstance(meta, dict):
            for key in [
                'monthly_price', 'quarterly_price', 'yearly_price', 'yearly_discount_percent', 'tax_info',
                'cta_text', 'cta_action', 'badge_text', 'accent_color', 'is_recommended',
                'agent_role_type', 'limits', 'channels', 'allowed_channels', 'max_channels',
                'allowed_connectors', 'allowed_features', 'feature_keys', 'feature_groups',
                'message_costs', 'additional_benefits', 'channel_details'
            ]:
                if key in meta and key not in ret:
                    ret[key] = meta[key]
        return ret

    def create(self, validated_data):
        initial = self.initial_data
        metadata = validated_data.get('metadata', {}) or {}
        # Merge top-level custom attributes into metadata if passed
        for key in [
            'feature_keys', 'monthly_price', 'quarterly_price', 'yearly_price', 'yearly_discount_percent', 'tax_info',
            'cta_text', 'cta_action', 'badge_text', 'accent_color', 'is_recommended',
            'agent_role_type', 'limits', 'channels', 'allowed_channels', 'max_channels',
            'allowed_connectors', 'allowed_features', 'feature_groups', 'message_costs', 'additional_benefits', 'channel_details'
        ]:
            if key in initial and initial[key] is not None:
                metadata[key] = initial[key]
        validated_data['metadata'] = metadata
        return super().create(validated_data)

    def update(self, instance, validated_data):
        initial = self.initial_data
        metadata = instance.metadata or {}
        for key in [
            'feature_keys', 'monthly_price', 'quarterly_price', 'yearly_price', 'yearly_discount_percent', 'tax_info',
            'cta_text', 'cta_action', 'badge_text', 'accent_color', 'is_recommended',
            'agent_role_type', 'limits', 'channels', 'allowed_channels', 'max_channels',
            'allowed_connectors', 'allowed_features', 'feature_groups', 'message_costs', 'additional_benefits', 'channel_details'
        ]:
            if key in initial and initial[key] is not None:
                metadata[key] = initial[key]
        validated_data['metadata'] = metadata
        return super().update(instance, validated_data)

class PlanFeatureSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = PlanFeature
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

class ClientFeatureOverrideSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = ClientFeatureOverride
        fields = '__all__'
        read_only_fields = ('created_at', 'updated_at')

class PlanAuditLogSerializer(serializers.ModelSerializer):
    id = ObjectIdField(read_only=True)

    class Meta:
        model = PlanAuditLog
        fields = '__all__'
        read_only_fields = ('timestamp',)
