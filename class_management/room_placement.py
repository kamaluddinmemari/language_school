"""تنظیم تعداد صندلی کلاس‌های فیزیکی و «جایگذاری خودکار محل کلاس‌ها».

- PhysicalRoomsView: خواندن/ذخیرهٔ فهرست اتاق‌ها (شماره، تعداد صندلی، فعال بودن).
- AutoPlaceRoomsView: با فیلتر ترم/روز/ساعت، کلاس‌های هم‌روز و هم‌ساعت را بر اساس «تعداد افراد هر کلاس
  (ثبت‌نام قطعی‌شده + منتظر ثبت‌نام)» و تعداد صندلی اتاق‌ها در اتاق‌ها پخش می‌کند و گزارش می‌دهد.
"""
from collections import defaultdict

from django.db import transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.menu_permissions import can_edit_menu

from .models import ClassSlot, PhysicalRoom

DEFAULT_ROOM_COUNT = 11
DEFAULT_SEATS = 15
MAX_ROOM_NUMBER = 60
TEMP_OFFSET = 1000000


def _rooms_list():
    rooms = list(PhysicalRoom.objects.order_by('number'))
    if not rooms:
        return [{'number': n, 'seats': DEFAULT_SEATS, 'is_active': True, 'saved': False} for n in range(1, DEFAULT_ROOM_COUNT + 1)]
    return [{'number': r.number, 'seats': r.seats, 'is_active': r.is_active, 'saved': True} for r in rooms]


class PhysicalRoomsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return Response({'rooms': _rooms_list()})

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        rows = request.data.get('rooms')
        if not isinstance(rows, list) or not rows:
            return Response({'error': 'فهرست اتاق‌ها خالی است'}, status=status.HTTP_400_BAD_REQUEST)
        cleaned, seen = [], set()
        for row in rows:
            try:
                number = int(row.get('number'))
                seats = int(row.get('seats'))
            except (TypeError, ValueError, AttributeError):
                return Response({'error': 'شمارهٔ اتاق و تعداد صندلی باید عدد باشد'}, status=status.HTTP_400_BAD_REQUEST)
            if number < 1 or number > MAX_ROOM_NUMBER:
                return Response({'error': f'شمارهٔ اتاق باید بین ۱ تا {MAX_ROOM_NUMBER} باشد'}, status=status.HTTP_400_BAD_REQUEST)
            if seats < 0 or seats > 500:
                return Response({'error': f'تعداد صندلی اتاق {number} معتبر نیست'}, status=status.HTTP_400_BAD_REQUEST)
            if number in seen:
                return Response({'error': f'شمارهٔ اتاق {number} تکراری است'}, status=status.HTTP_400_BAD_REQUEST)
            seen.add(number)
            cleaned.append((number, seats, bool(row.get('is_active', True))))
        with transaction.atomic():
            PhysicalRoom.objects.exclude(number__in=seen).delete()
            for number, seats, active in cleaned:
                PhysicalRoom.objects.update_or_create(number=number, defaults={'seats': seats, 'is_active': active})
        return Response({'message': 'تعداد صندلی اتاق‌ها ذخیره شد', 'rooms': _rooms_list()})


def _start_minutes(time_slot):
    import re
    m = re.match(r'^\s*(\d{1,2}):(\d{2})', str(time_slot or ''))
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def _chair_suggestions(all_slots, people, rooms, planned_room, groups_report, first_floor_max=3):
    """برای کلاس‌هایی که بعد از جایگذاری صندلی کم دارند، پیشنهاد می‌دهد از کدام اتاق‌ها صندلی برداشته شود.
    اتاقِ اهداکننده فقط وقتی صندلی می‌دهد که بعد از برداشتن، جمعیت کلاس‌های خودش هم در همین ساعت و هم در
    ساعات بعدیِ همان روزها همچنان جا شود (بیشینهٔ جمعیتِ این ساعت‌ها ملاک است)."""
    from .views import _slot_weekdays, _time_ranges_overlap

    work_seats = {r['number']: int(r['seats']) for r in rooms}
    floor_of = lambda n: 1 if n <= first_floor_max else 2  # noqa: E731
    room_of = lambda c: planned_room.get(c.pk, c.number)  # noqa: E731

    def key(row_group):
        start = _start_minutes(row_group['time_slot'])
        return (start if start is not None else 10 ** 6, row_group['day_type'])

    suggestions_total = 0
    for group in sorted(groups_report, key=key):
        short_rows = [r for r in group['rows'] if r['state'] == 'overflow']
        short_rows.sort(key=lambda r: -(r['people'] - r['seats']))
        for row in short_rows:
            slot = row['_slot']
            room_no = row['new_number']
            deficit = row['people'] - work_seats.get(room_no, row['seats'])
            row['shortage'] = max(0, row['people'] - row['seats'])
            if deficit <= 0:
                row['suggestion'] = {'resolved': True, 'remaining': 0, 'donors': [], 'note': 'با صندلی‌هایی که برای کلاس‌های قبلی منتقل می‌شود کمبود این کلاس هم جبران می‌شود'}
                continue
            mine = _slot_weekdays(slot.day_type, slot.schedule_days)
            start = _start_minutes(slot.time_slot)
            donors = []
            for room in rooms:
                number = room['number']
                if number == room_no:
                    continue
                occupants = []
                for c in all_slots:
                    if room_of(c) != number or c.is_online != slot.is_online:
                        continue
                    theirs = _slot_weekdays(c.day_type, c.schedule_days)
                    same_days = (c.day_type == slot.day_type) if (mine is None or theirs is None) else bool(set(mine) & set(theirs))
                    if not same_days:
                        continue
                    c_start = _start_minutes(c.time_slot)
                    later = (start is not None and c_start is not None and c_start >= start)
                    if later or _time_ranges_overlap(c.time_slot, slot.time_slot):
                        occupants.append(c)
                peak = max([people[c.pk] for c in occupants], default=0)
                surplus = work_seats[number] - peak
                if surplus > 0:
                    donors.append({'room': number, 'surplus': surplus, 'peak': peak, 'occupants': occupants, 'empty': peak == 0})
            # اولویت: کلاس‌های خالی؛ در هر دسته اول اتاق‌های هم‌طبقهٔ کلاس دارای کمبود، بعد بیشترین صندلی اضافه
            my_floor = floor_of(room_no)
            donors.sort(key=lambda d: (0 if d['empty'] else 1, 0 if floor_of(d['room']) == my_floor else 1, -d['surplus'], d['room']))
            remaining, chosen = deficit, []
            for donor in donors:
                if remaining <= 0:
                    break
                take = min(donor['surplus'], remaining)
                work_seats[donor['room']] -= take
                work_seats[room_no] += take
                remaining -= take
                chosen.append({
                    'room': donor['room'], 'empty': donor['empty'], 'take': take, 'seats_after': work_seats[donor['room']], 'peak_people': donor['peak'],
                    'classes': [{'level': c.assigned_level or 'بدون سطح', 'time_slot': c.time_slot, 'day_type_display': c.day_type_display, 'people': people[c.pk]}
                                for c in sorted(donor['occupants'], key=lambda c: (_start_minutes(c.time_slot) or 0, c.pk))],
                })
            row['suggestion'] = {'resolved': remaining <= 0, 'remaining': max(0, remaining), 'donors': chosen, 'note': ''}
            suggestions_total += 1
    return suggestions_total


def _demand(slot):
    """تعداد افراد کلاس: ثبت‌نام قطعی‌شده + منتظر ثبت‌نام (تمدیدشدگان ترم قبل)؛ هر دو ردیف ثبت‌نام همین کلاس‌اند."""
    return int(slot.real_enrolled_count or 0)


class AutoPlaceRoomsView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from .views import room_conflict, thu_odd_conflict_message

        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        term_id = data.get('term_id')
        day_types = data.get('day_types') or []
        time_slots = data.get('time_slots') or []
        dry_run = bool(data.get('dry_run'))
        # قید طبقه: اتاق‌های 1..first_floor_max طبقهٔ اول و بقیه طبقهٔ دوم‌اند؛ اساتید انتخاب‌شده فقط در طبقهٔ تعیین‌شده‌شان
        try:
            first_floor_max = int(data.get('first_floor_max') or 3)
        except (TypeError, ValueError):
            first_floor_max = 3
        # حالت تخصیص: largest = اول اتاق‌های پرصندلی؛ unit = پر کردن واحد به واحد (اتاق‌های یک مجموعه اول پر می‌شود)
        placement_mode = 'unit' if str(data.get('placement_mode') or '') == 'unit' else 'largest'
        units = []
        raw_units = data.get('units') or []
        if isinstance(raw_units, list):
            for unit in raw_units:
                numbers = []
                for value in (unit if isinstance(unit, list) else []):
                    try:
                        numbers.append(int(value))
                    except (TypeError, ValueError):
                        continue
                if numbers:
                    units.append(numbers)
        if placement_mode == 'unit' and not units:
            ordered = sorted(r['number'] for r in _rooms_list() if r['is_active'])
            units = [ordered[i:i + 3] for i in range(0, len(ordered), 3)]
        unit_index = {}
        for index, unit in enumerate(units):
            for number in unit:
                unit_index.setdefault(number, index)
        teacher_floors = {}
        raw_floors = data.get('teacher_floors') or {}
        if isinstance(raw_floors, dict):
            for name, floor in raw_floors.items():
                if str(floor) in ('1', '2') and str(name).strip():
                    teacher_floors[str(name).strip().lower()] = int(floor)
        teacher_rooms = {}
        raw_teacher_rooms = data.get('teacher_rooms') or {}
        if isinstance(raw_teacher_rooms, dict):
            for name, room in raw_teacher_rooms.items():
                try:
                    room_number = int(room)
                except (TypeError, ValueError):
                    continue
                if str(name).strip() and room_number > 0:
                    teacher_rooms[str(name).strip().lower()] = room_number
        if not term_id:
            return Response({'error': 'ترم را انتخاب کنید (جایگذاری خودکار فقط روی یک ترم انجام می‌شود)'}, status=status.HTTP_400_BAD_REQUEST)
        if not day_types:
            return Response({'error': 'حداقل یک روز را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)

        rooms = [r for r in _rooms_list() if r['is_active']]
        if not rooms:
            return Response({'error': 'هیچ اتاق فعالی تعریف نشده؛ ابتدا «تنظیم تعداد صندلی» را انجام دهید'}, status=status.HTTP_400_BAD_REQUEST)

        qs = ClassSlot.objects.filter(term_id=term_id, day_type__in=day_types)
        if time_slots:
            qs = qs.filter(time_slot__in=time_slots)
        if data.get('is_online') is not None:
            qs = qs.filter(is_online=bool(data.get('is_online')))
        slots = list(qs.order_by('number', 'id'))
        if not slots:
            return Response({'error': 'کلاسی با این فیلتر پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        groups = defaultdict(list)
        for slot in slots:
            groups[(slot.day_type, slot.time_slot, slot.is_online)].append(slot)

        report_groups, summary = [], {'classes': 0, 'moved': 0, 'unchanged': 0, 'overflow': 0, 'unplaced': 0}
        plans = []
        for (day_type, time_slot, is_online), members in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1])):
            member_ids = [m.pk for m in members]
            demand = {m.pk: _demand(m) for m in members}
            def room_rule(slot):
                return teacher_rooms.get(str(slot.teacher_name or '').strip().lower())
            def floor_rule(slot):
                # اتاق اجباری، اگر تعریف شده باشد، بر قید طبقهٔ همان استاد اولویت دارد.
                if room_rule(slot) is not None:
                    return None
                return teacher_floors.get(str(slot.teacher_name or '').strip().lower())
            # ابتدا قید اتاق مشخص، سپس قید طبقه و بعد کلاس‌های دیگر؛ هر دسته از پرجمعیت به کم‌جمعیت
            order = sorted(members, key=lambda m: (0 if room_rule(m) is not None else (1 if floor_rule(m) else 2), -demand[m.pk], -(m.capacity or 0), m.number, m.pk))
            used, assignment, notes = set(), {}, {}
            for slot in order:
                need = demand[slot.pk]
                candidates = []
                exact_room = room_rule(slot)
                active_numbers = {r['number'] for r in rooms}
                if exact_room is not None and exact_room not in active_numbers:
                    notes.setdefault(slot.pk, []).append(f'کلاس/اتاق اجباری {exact_room} فعال نیست')
                elif exact_room is not None and exact_room in used:
                    notes.setdefault(slot.pk, []).append(f'کلاس/اتاق اجباری {exact_room} در همین ساعت به کلاس دیگری داده شده است')
                for room in rooms:
                    if room['number'] in used:
                        continue
                    if exact_room is not None and room['number'] != exact_room:
                        continue
                    rule = floor_rule(slot)
                    if rule == 1 and room['number'] > first_floor_max:
                        continue
                    if rule == 2 and room['number'] <= first_floor_max:
                        continue
                    clash = room_conflict(slot.term_id, is_online, day_type, slot.schedule_days, time_slot, room['number'], member_ids)
                    if clash:
                        notes.setdefault(slot.pk, []).append(f"اتاق {room['number']}: " + thu_odd_conflict_message(clash, room['number']))
                        continue
                    candidates.append(room)
                fitting = [r for r in candidates if r['seats'] >= need]
                if fitting:
                    # بین گزینه‌های مناسب، اول اتاق با صندلی بیشتر (قیدهای طبقهٔ استاد پیش‌تر در فهرست گزینه‌ها اعمال شده‌اند)
                    if placement_mode == 'unit':
                        # واحدی که قبلاً در همین ساعت شروع به پر شدن کرده، اول؛ بعد کمترین شمارهٔ واحد؛ در واحد، اتاق با صندلی بیشتر
                        started = {unit_index.get(n) for n in used if unit_index.get(n) is not None}
                        def unit_key(r):
                            ui = unit_index.get(r['number'])
                            if ui is None:
                                return (2, 10 ** 6 + r['number'], -r['seats'], r['number'])
                            return (0 if ui in started else 1, ui, -r['seats'], r['number'])
                        room = min(fitting, key=unit_key)
                    else:
                        room = max(fitting, key=lambda r: (r['seats'], -r['number']))
                    assignment[slot.pk] = (room['number'], room['seats'], 'fit')
                elif candidates:
                    room = max(candidates, key=lambda r: (r['seats'], -r['number']))
                    assignment[slot.pk] = (room['number'], room['seats'], 'overflow')
                else:
                    if floor_rule(slot):
                        notes.setdefault(slot.pk, []).append(f"در طبقهٔ {'اول' if floor_rule(slot) == 1 else 'دوم'} اتاق آزادی برای استاد {slot.teacher_name} نبود")
                    assignment[slot.pk] = (None, 0, 'unplaced')
                if assignment[slot.pk][0] is not None:
                    used.add(assignment[slot.pk][0])
            # قاعدهٔ همیشگی (در هر دو روش): کلاسی که جمعیتش بیشتر است باید اتاقی با صندلی بیشتر (یا برابر) داشته باشد.
            # بعد از چیدن اولیه، هر جفت کلاسِ مخالف این قاعده را — اگر قیدهای طبقه و تداخل محل اجازه دهد — جای هم می‌گذاریم.
            seats_by_number = {r['number']: int(r['seats']) for r in rooms}

            def room_allowed(slot, number):
                exact_room = room_rule(slot)
                if exact_room is not None and number != exact_room:
                    return False
                rule = floor_rule(slot)
                if rule == 1 and number > first_floor_max:
                    return False
                if rule == 2 and number <= first_floor_max:
                    return False
                return not room_conflict(slot.term_id, is_online, day_type, slot.schedule_days, time_slot, number, member_ids)

            placed = [m for m in members if assignment[m.pk][0] is not None]
            for _round in range(len(placed) * len(placed) + 1):
                swapped = False
                for big in placed:
                    for small in placed:
                        if demand[big.pk] <= demand[small.pk]:
                            continue
                        big_room, small_room = assignment[big.pk][0], assignment[small.pk][0]
                        if seats_by_number.get(big_room, 0) >= seats_by_number.get(small_room, 0):
                            continue
                        if not (room_allowed(big, small_room) and room_allowed(small, big_room)):
                            continue
                        for slot, number in ((big, small_room), (small, big_room)):
                            seats = seats_by_number.get(number, 0)
                            assignment[slot.pk] = (number, seats, 'fit' if seats >= demand[slot.pk] else 'overflow')
                        swapped = True
                if not swapped:
                    break
            # کلاس‌های بدون اتاق: اگر شمارهٔ فعلی‌شان با اتاقِ تخصیص‌یافتهٔ دیگری برخورد دارد، شمارهٔ آزادی می‌گیرند
            taken = set(used)
            for slot in members:
                if assignment[slot.pk][0] is None:
                    if slot.number in taken:
                        free = next(n for n in range(1, MAX_ROOM_NUMBER + len(members) + 2) if n not in taken)
                        assignment[slot.pk] = (free, 0, 'unplaced')
                        taken.add(free)
                    else:
                        assignment[slot.pk] = (slot.number, 0, 'unplaced')
                        taken.add(slot.number)
            rows = []
            for slot in sorted(members, key=lambda m: (assignment[m.pk][0] or 0, m.pk)):
                new_number, seats, state = assignment[slot.pk]
                rows.append({
                    '_slot': slot, 'shortage': 0, 'suggestion': None,
                    'class_id': slot.pk, 'level': slot.assigned_level or 'بدون سطح', 'teacher_name': slot.teacher_name or '',
                    'people': demand[slot.pk], 'old_number': slot.number, 'new_number': new_number, 'seats': seats,
                    'state': state, 'changed': new_number != slot.number,
                    'floor': (1 if new_number <= first_floor_max else 2) if new_number else None,
                    'floor_rule': floor_rule(slot), 'room_rule': room_rule(slot),
                    'note': ' | '.join(notes.get(slot.pk, [])[:2]) if state != 'fit' else ' | '.join(notes.get(slot.pk, [])[:2]),
                })
                summary['classes'] += 1
                summary['moved'] += 1 if new_number != slot.number else 0
                summary['unchanged'] += 0 if new_number != slot.number else 1
                summary['overflow'] += 1 if state == 'overflow' else 0
                summary['unplaced'] += 1 if state == 'unplaced' else 0
            warnings = []
            if len(members) > len(rooms):
                warnings.append(f'تعداد کلاس‌ها ({len(members)}) از اتاق‌های فعال ({len(rooms)}) بیشتر است؛ اتاق بیشتری اضافه کنید.')
            report_groups.append({
                'day_type': day_type, 'day_type_display': members[0].day_type_display, 'time_slot': time_slot,
                'is_online': is_online, 'rows': rows, 'warnings': warnings,
            })
            plans.append(([(slot, assignment[slot.pk][0]) for slot in members]))

        planned_room = {slot.pk: new for plan in plans for slot, new in plan if new is not None}
        all_slots = list(ClassSlot.objects.filter(term_id=term_id))
        people_all = {c.pk: _demand(c) for c in all_slots}
        _chair_suggestions(all_slots, people_all, rooms, planned_room, report_groups, first_floor_max)
        summary['shortage_total'] = 0
        for group in report_groups:
            for row in group['rows']:
                summary['shortage_total'] += row['shortage']
                row.pop('_slot', None)

        if not dry_run:
            with transaction.atomic():
                for plan in plans:
                    changing = [(slot, new) for slot, new in plan if new is not None and new != slot.number]
                    for index, (slot, _new) in enumerate(changing):
                        slot.number = TEMP_OFFSET + slot.pk
                        slot.save(update_fields=['number', 'updated_at'])
                    for slot, new in changing:
                        slot.number = new
                        slot.save(update_fields=['number', 'updated_at'])

        message = (f"{summary['moved']} کلاس جابه‌جا شد، {summary['unchanged']} کلاس در محل قبلی ماند"
                   if not dry_run else f"پیش‌نمایش: {summary['moved']} کلاس جابه‌جا می‌شود، {summary['unchanged']} کلاس در محل قبلی می‌ماند")
        if summary['overflow']:
            message += f" — {summary['overflow']} کلاس در اتاقی با صندلی کمتر از تعداد افرادش قرار گرفت"
        if summary['shortage_total']:
            message += f" — مجموع کمبود صندلی: {summary['shortage_total']}"
        if summary['unplaced']:
            message += f" — {summary['unplaced']} کلاس اتاق مناسب پیدا نکرد"
        return Response({'dry_run': dry_run, 'first_floor_max': first_floor_max, 'message': message, 'summary': summary, 'groups': report_groups})



class SeatShortageView(APIView):
    """کمبود صندلی هر کلاس بر اساس «محل فعلی» کلاس‌ها (بدون جابه‌جایی) و اتاق‌های برداشت پیشنهادی؛ برای خروجی چاپی/اکسل شبکه‌ای."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        term_id = request.data.get('term_id')
        try:
            first_floor_max = int(request.data.get('first_floor_max') or 3)
        except (TypeError, ValueError):
            first_floor_max = 3
        rooms = [r for r in _rooms_list() if r['is_active']]
        seats_of = {r['number']: int(r['seats']) for r in rooms}
        qs = ClassSlot.objects.all()
        if term_id not in (None, '', 'all'):
            if str(term_id) == 'legacy':
                qs = qs.filter(term__isnull=True)
            else:
                qs = qs.filter(term_id=term_id)
        by_term = defaultdict(list)
        for slot in qs:
            by_term[slot.term_id].append(slot)
        items = {}
        for _term, term_slots in by_term.items():
            people = {c.pk: _demand(c) for c in term_slots}
            groups = defaultdict(list)
            for c in term_slots:
                groups[(c.day_type, c.time_slot, c.is_online)].append(c)
            report_groups = []
            for (day_type, time_slot, _online), members in groups.items():
                rows = []
                for c in members:
                    if c.number not in seats_of:
                        continue
                    seats = seats_of[c.number]
                    over = people[c.pk] > seats
                    rows.append({'_slot': c, 'class_id': c.pk, 'people': people[c.pk], 'seats': seats, 'new_number': c.number,
                                 'state': 'overflow' if over else 'fit', 'shortage': 0, 'suggestion': None})
                report_groups.append({'day_type': day_type, 'time_slot': time_slot, 'rows': rows})
            _chair_suggestions(term_slots, people, rooms, {}, report_groups, first_floor_max)
            for group in report_groups:
                for row in group['rows']:
                    if row['shortage'] > 0:
                        sg = row.get('suggestion') or {}
                        items[row['class_id']] = {
                            'shortage': row['shortage'],
                            'donor_rooms': [d['room'] for d in sg.get('donors', [])],
                            'donors': [{'room': d['room'], 'empty': bool(d.get('empty'))} for d in sg.get('donors', [])],
                            'resolved': bool(sg.get('resolved')),
                            'remaining': int(sg.get('remaining') or 0),
                        }
        return Response({'items': items})
