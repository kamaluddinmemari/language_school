from rest_framework import serializers
from .models import ReportDefinition


class ReportDefinitionSerializer(serializers.ModelSerializer):
    created_at_jalali = serializers.ReadOnlyField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ReportDefinition
        fields = [
            'id', 'name', 'source_key', 'fields', 'filters', 'group_by', 'aggregations',
            'date_override', 'created_by', 'created_by_name', 'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['id', 'created_by', 'created_at', 'updated_at']

    def get_created_by_name(self, obj):
        return obj.created_by.get_full_name() if obj.created_by else '-'

    def validate_source_key(self, value):
        from .registry_custom import SOURCES
        if value not in SOURCES:
            raise serializers.ValidationError('منبع داده نامعتبر است')
        return value

    def validate(self, attrs):
        from .registry_custom import SOURCES
        source_key = attrs.get('source_key', getattr(self.instance, 'source_key', None))
        source = SOURCES.get(source_key)
        if not source:
            return attrs
        valid_keys = set(source.field_map.keys())

        for key in attrs.get('fields', []) or []:
            if key not in valid_keys:
                raise serializers.ValidationError(f'فیلد نامعتبر برای این منبع داده: {key}')
        for key in attrs.get('group_by', []) or []:
            if key not in valid_keys:
                raise serializers.ValidationError(f'فیلد گروه‌بندی نامعتبر: {key}')
        for f in attrs.get('filters', []) or []:
            if f.get('field') not in valid_keys:
                raise serializers.ValidationError(f"فیلد فیلتر نامعتبر: {f.get('field')}")
        for a in attrs.get('aggregations', []) or []:
            if a.get('field') not in valid_keys and a.get('func') != 'count':
                raise serializers.ValidationError(f"فیلد تجمیع نامعتبر: {a.get('field')}")
        return attrs
