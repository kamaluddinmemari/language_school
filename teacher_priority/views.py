from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.menu_permissions import can_view_menu

from .models import TeacherPriorityConfig
from .services import build_ranking

QUEUE_ROLES = ('admin', 'evaluator', 'office', 'employee')


def _can_view_details(user):
    return user.role == 'admin' or can_view_menu(user, 'teachers')


class TeacherPriorityRankingView(APIView):
    """GET /api/teacher-priority/ranking/ — امتیاز و اولویت همه‌ی اساتید با جزئیات هر معیار و هر ترم."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_details(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return Response(build_ranking(include_history=True))


class TeacherPriorityQueueView(APIView):
    """
    GET /api/teacher-priority/queue/ — صف ارجاع (مرحله‌ی ۱ کلاس خصوصی/جبرانی): فهرست فشرده‌ی
    اساتید به ترتیب اولویت. برای مرتب‌کردن انتخابگر استاد در داشبورد استفاده می‌شود.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in QUEUE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        data = build_ranking(include_history=False)
        return Response({
            'latest_term': data['latest_term'],
            'queue': [{
                'teacher_id': r['teacher_id'], 'teacher_name': r['teacher_name'], 'rank': r['rank'],
                'priority_score': r['priority_score'], 'term_score': r['term_score'],
                'deducted': r['usage_penalty']['points'],
            } for r in data['teachers']],
        })


class TeacherPriorityConfigView(APIView):
    """GET: خواندن تنظیمات (مدیر/دارای دسترسی منو) — PUT: ویرایش (فقط مدیر)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not _can_view_details(request.user):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return Response(TeacherPriorityConfig.get().payload())

    def put(self, request):
        if request.user.role != 'admin':
            return Response({'error': 'فقط مدیر می‌تواند تنظیمات امتیازدهی را تغییر دهد'}, status=status.HTTP_403_FORBIDDEN)
        obj = TeacherPriorityConfig.get()
        data = request.data
        try:
            for f in TeacherPriorityConfig.FIELDS:
                if f not in data:
                    continue
                if f == 'apply_to_hourly_price':
                    v = data[f]
                    setattr(obj, f, v.lower() in ('1', 'true', 'on') if isinstance(v, str) else bool(v))
                elif f in ('student_target', 'class_count_target'):
                    setattr(obj, f, int(data[f]))
                else:
                    setattr(obj, f, float(data[f]))
        except (TypeError, ValueError):
            return Response({'error': 'مقدار عددی نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)

        weights = [float(obj.w_parity), float(obj.w_students), float(obj.w_one_day), float(obj.w_class_count)]
        if any(w < 0 for w in weights) or abs(sum(weights) - 100) > 0.01:
            return Response({'error': f'مجموع وزن چهار معیار باید دقیقاً ۱۰۰ باشد (الان {sum(weights):g})'}, status=status.HTTP_400_BAD_REQUEST)
        if float(obj.parity_odd_only_ratio) > float(obj.parity_even_only_ratio) or float(obj.parity_even_only_ratio) > 1:
            return Response({'error': 'باید «فقط فرد» ≤ «فقط زوج» ≤ ۱ باشد'}, status=status.HTTP_400_BAD_REQUEST)
        if int(obj.student_target) < 1 or int(obj.class_count_target) < 1:
            return Response({'error': 'هدف دانش‌آموز و کلاس باید حداقل ۱ باشد'}, status=status.HTTP_400_BAD_REQUEST)
        if float(obj.makeup_session_penalty) > float(obj.private_session_penalty):
            return Response({'error': 'کسر جبرانی باید کمتر یا مساوی کسر خصوصی باشد'}, status=status.HTTP_400_BAD_REQUEST)
        if min(float(obj.price_coefficient), float(obj.absence_penalty_per_event), float(obj.absence_penalty_cap),
               float(obj.private_session_penalty), float(obj.makeup_session_penalty)) < 0:
            return Response({'error': 'مقادیر منفی مجاز نیست'}, status=status.HTTP_400_BAD_REQUEST)
        obj.updated_by = request.user
        obj.save()
        return Response(obj.payload())
