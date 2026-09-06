from rest_framework import serializers
from .models import GradeFieldSetting, GradePassingSetting, StudentGrade, FIELD_KEYS


class GradeFieldSettingSerializer(serializers.ModelSerializer):
    age_group_display = serializers.CharField(source='get_age_group_display', read_only=True)
    field_key_display = serializers.CharField(source='get_field_key_display', read_only=True)

    class Meta:
        model = GradeFieldSetting
        fields = [
            'id', 'age_group', 'age_group_display', 'field_key', 'field_key_display',
            'title', 'is_active', 'max_score', 'order', 'updated_at',
        ]
        read_only_fields = ['id', 'age_group', 'field_key', 'updated_at']


class GradePassingSettingSerializer(serializers.ModelSerializer):
    age_group_display = serializers.CharField(source='get_age_group_display', read_only=True)

    class Meta:
        model = GradePassingSetting
        fields = ['id', 'age_group', 'age_group_display', 'passing_score', 'updated_at']
        read_only_fields = ['id', 'age_group', 'updated_at']


class StudentGradeSerializer(serializers.ModelSerializer):
    student_id = serializers.IntegerField(source='student.id', read_only=True)
    student_name = serializers.SerializerMethodField()
    national_code = serializers.CharField(source='student.national_code', read_only=True)
    age_group_display = serializers.SerializerMethodField()
    class_number = serializers.IntegerField(source='class_slot.number', read_only=True)
    term_title = serializers.CharField(source='term.title', read_only=True)
    is_editable = serializers.ReadOnlyField()
    finalized_at_jalali = serializers.ReadOnlyField()
    updated_at_jalali = serializers.ReadOnlyField()

    class Meta:
        model = StudentGrade
        fields = [
            'id', 'class_slot', 'class_number', 'student_id', 'student_name', 'national_code',
            'term', 'term_title', 'level', 'age_group', 'age_group_display',
            'cp_score', 'midterm_score', 'writing1_score', 'writing2_score', 'final_score',
            'total_score', 'is_finalized', 'is_fail', 'is_editable',
            'finalized_at_jalali', 'updated_at_jalali',
        ]
        read_only_fields = [
            'id', 'class_slot', 'term', 'level', 'age_group', 'total_score',
            'is_finalized', 'is_fail', 'is_editable', 'finalized_at_jalali', 'updated_at_jalali',
        ]

    def get_student_name(self, obj):
        return obj.student.get_full_name()

    def get_age_group_display(self, obj):
        mapping = {'kids': 'کودک', 'teen': 'نوجوان', 'adult': 'بزرگسال'}
        return mapping.get(obj.age_group, '')


class StudentGradeUpsertItemSerializer(serializers.Serializer):
    """یک ردیف از درخواست ذخیره‌ی گروهی نمرات یک کلاس."""
    student_id = serializers.IntegerField()
    cp_score = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    midterm_score = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    writing1_score = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    writing2_score = serializers.IntegerField(required=False, allow_null=True, min_value=0)
    final_score = serializers.IntegerField(required=False, allow_null=True, min_value=0)
