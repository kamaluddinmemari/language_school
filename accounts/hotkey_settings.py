from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import UserHotkeySetting

MAX_HOTKEYS = 200


def _clean_hotkeys(raw):
    """فقط فیلدهای مجاز و طول‌های معقول نگه داشته می‌شود."""
    cleaned = []
    for item in (raw if isinstance(raw, list) else [])[:MAX_HOTKEYS]:
        if not isinstance(item, dict):
            continue
        cleaned.append({
            'id': str(item.get('id') or '')[:40],
            'combo': str(item.get('combo') or '')[:60],
            'target': str(item.get('target') or '')[:80],
            'path': str(item.get('path') or '')[:300],
            'label': str(item.get('label') or '')[:80],
        })
    return cleaned


class HotkeySettingView(APIView):
    """GET/PUT: کلیدهای میانبر و تنظیم هشدار کوتاه کاربر جاری (ذخیرهٔ دائمی روی سرور، مشترک بین همهٔ سیستم‌های او).
    `initialized=false` یعنی کاربر هنوز چیزی روی سرور ذخیره نکرده (فرانت می‌تواند فهرست قدیمی مرورگر را بالا بفرستد)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        obj = UserHotkeySetting.objects.filter(user=request.user).first()
        if not obj:
            return Response({'hotkeys': [], 'toast_enabled': True, 'sound_enabled': True, 'initialized': False})
        return Response({'hotkeys': obj.hotkeys, 'toast_enabled': obj.toast_enabled, 'sound_enabled': obj.sound_enabled, 'initialized': True})

    def put(self, request):
        obj, _created = UserHotkeySetting.objects.get_or_create(user=request.user)
        if 'hotkeys' in request.data:
            obj.hotkeys = _clean_hotkeys(request.data.get('hotkeys'))
        if 'toast_enabled' in request.data:
            obj.toast_enabled = bool(request.data.get('toast_enabled'))
        if 'sound_enabled' in request.data:
            obj.sound_enabled = bool(request.data.get('sound_enabled'))
        obj.save()
        return Response({'hotkeys': obj.hotkeys, 'toast_enabled': obj.toast_enabled, 'sound_enabled': obj.sound_enabled, 'initialized': True}, status=status.HTTP_200_OK)
