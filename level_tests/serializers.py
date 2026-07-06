from rest_framework import serializers
from .models import LevelTest, LevelTestPriceSetting
from .levels import LEVELS_BY_AGE_GROUP


class LevelTestPriceSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = LevelTestPriceSetting
        fields = ['id', 'price', 'updated_at']
        read_only_fields = ['updated_at']


class LevelTestIntakeSerializer(serializers.ModelSerializer):
    """برای مرحله‌ی اول — فقط مدیر/کانتر، فقط مشخصات اولیه‌ی داوطلب (بدون نتیجه)"""

    class Meta:
        model = LevelTest
        fields = ['id', 'first_name', 'last_name', 'father_name', 'birth_date', 'national_code', 'phone', 'price', 'payment_status']

    def validate(self, attrs):
        for field in ['first_name', 'last_name', 'father_name', 'birth_date', 'national_code', 'phone']:
            if not attrs.get(field) and not (self.instance and getattr(self.instance, field, None)):
                raise serializers.ValidationError({field: 'این فیلد لازم است'})
        return attrs


class LevelTestSerializer(serializers.ModelSerializer):
    """نمایش کامل + ویرایش نتیجه (برای پنل مسئول آموزش و مدیر)"""
    test_date_jalali = serializers.ReadOnlyField()
    created_at_jalali = serializers.ReadOnlyField()
    birth_date_jalali = serializers.ReadOnlyField()
    display_evaluator_name = serializers.ReadOnlyField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = LevelTest
        fields = [
            'id', 'first_name', 'last_name', 'father_name', 'birth_date', 'birth_date_jalali',
            'national_code', 'phone', 'status', 'status_display', 'price', 'payment_status',
            'age_group', 'level', 'test_date', 'test_date_jalali',
            'evaluator', 'evaluator_name', 'display_evaluator_name', 'notes', 'created_by',
            'created_at', 'created_at_jalali', 'updated_at',
        ]
        read_only_fields = ['created_by', 'created_at', 'updated_at', 'status']

    def validate(self, attrs):
        age_group = attrs.get('age_group', getattr(self.instance, 'age_group', None))
        level = attrs.get('level', getattr(self.instance, 'level', None))
        if age_group and level:
            valid_levels = LEVELS_BY_AGE_GROUP.get(age_group, [])
            if level not in valid_levels:
                raise serializers.ValidationError({'level': f'این سطح متعلق به گروه سنی «{age_group}» نیست'})
        return attrs
