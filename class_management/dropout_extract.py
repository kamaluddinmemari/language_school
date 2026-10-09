"""
استخراج ریزشی از مقایسه‌ی اکسلِ دو ترم متوالی.

  ۱) parse   : یک اکسل (با همان بازه‌ی ستون/سطرِ «ورود دانش‌آموزان از Excel» کلاس) خوانده و نرمال می‌شود.
  ۲) compute : لیست ترم اول − لیست ترم دوم = ریزشی‌ها (بر پایه‌ی کد ملی؛ در نبود کد ملی معتبر: موبایل، بعد نام کامل).
  ۳) commit  : اگر دو ترم «ترم اخیر و ترم قبلش» باشند، ریزشی‌ها مستقیم وارد «ثبت‌نام‌نشده‌ها» (با برچسب) می‌شوند؛
               در غیر این صورت به بخش «ریزشی‌ها» می‌روند.
"""
import json
import re

from django.db import IntegrityError, transaction
from django.db.models import Q
from rest_framework import status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.menu_permissions import can_edit_menu
from .models import ClassSlotEnrollment, Term
from .views import ClassSlotExcelImportView

_COLUMN_RE = re.compile(r'^[A-Z]{1,2}$')
_DEFAULT_COLUMNS = {
    'first_name_start_column': 'N', 'first_name_end_column': 'U',
    'last_name_start_column': 'N', 'last_name_end_column': 'U',
    'national_code_start_column': 'K', 'national_code_end_column': 'M',
    'phone_start_column': 'A', 'phone_end_column': 'D',
}


def _digits(value):
    return ClassSlotExcelImportView._national_code_key(value)


def _ordered_terms():
    return list(Term.objects.order_by('year', 'term_number', 'id'))


def _term_pair(term1_id, term2_id):
    """(term1, term2, error, is_recent_pair). term1 باید ترمِ قبل و بلافاصله‌ی ترم2 باشد."""
    terms = _ordered_terms()
    position = {term.id: index for index, term in enumerate(terms)}
    try:
        term1_id, term2_id = int(term1_id), int(term2_id)
    except (TypeError, ValueError):
        return None, None, 'ترم اول و ترم دوم را انتخاب کنید', False
    if term1_id not in position or term2_id not in position:
        return None, None, 'ترم انتخاب‌شده پیدا نشد', False
    if term1_id == term2_id:
        return None, None, 'ترم اول و دوم باید متفاوت باشند', False
    if position[term2_id] - position[term1_id] != 1:
        return None, None, 'دو ترم باید متوالی باشند؛ ترم اول همان ترمِ بلافاصله قبل از ترم دوم است', False
    is_recent = position[term2_id] == len(terms) - 1
    return terms[position[term1_id]], terms[position[term2_id]], '', is_recent


def _person_keys(row):
    keys = []
    code = _digits(row.get('national_code'))
    if len(code) == 10:
        keys.append(f'nc:{code}')
    phone = _digits(row.get('phone'))
    if len(phone) == 10 and phone.startswith('9'):
        phone = '0' + phone
    if len(phone) == 11:
        keys.append(f'ph:{phone}')
    name = ' '.join(f"{row.get('first_name', '')} {row.get('last_name', '')}".split()).casefold()
    if name:
        keys.append(f'nm:{name}')
    return keys


def _single_term(term_id):
    """(term, error, is_latest) برای حالت «همه‌ی دانش‌آموزان ثبت‌شده در برابر یک ترم»."""
    terms = _ordered_terms()
    try:
        term = next(t for t in terms if t.id == int(term_id))
    except (StopIteration, TypeError, ValueError):
        return None, 'ترم انتخاب‌شده پیدا نشد', False
    return term, '', terms[-1].id == term.id


def _valid_code(value):
    code = _digits(value)
    return code if len(code) == 10 else ''


def _db_rows(term_ids):
    """لیست دانش‌آموزان با ثبت‌نام قطعی در ترم(های) داده‌شده، از خود سامانه."""
    rows = {}
    qs = ClassSlotEnrollment.objects.filter(
        class_slot__term_id__in=term_ids, student__role='student', payment_verified=True,
    ).exclude(is_carryover=True, carryover_confirmed=False).select_related('student')
    for enrollment in qs:
        student = enrollment.student
        rows[student.id] = {'first_name': student.first_name, 'last_name': student.last_name,
                            'national_code': student.national_code or '', 'phone': student.phone or ''}
    return list(rows.values())


def _all_student_rows():
    """کل دانش‌آموزان ثبت‌شده در بخش «اطلاعات دانش‌آموزان» (بدون نیاز به ثبت‌نام ترمی)."""
    from django.contrib.auth import get_user_model
    User = get_user_model()
    return [{
        'first_name': u.first_name, 'last_name': u.last_name, 'national_code': u.national_code or '',
        'phone': u.phone or '', 'level_fallback': u.language_level or '',
    } for u in User.objects.filter(role='student')]


def _enrollment_info(codes, term_ids):
    """برای هر کد ملی، آخرین ثبت‌نام قطعی در `term_ids`: سطح، روز، ساعت، استاد، شماره کلاس و ترم."""
    if not codes:
        return {}
    position = {t.id: i for i, t in enumerate(_ordered_terms())}
    best = {}
    qs = ClassSlotEnrollment.objects.filter(
        class_slot__term_id__in=term_ids, student__national_code__in=list(codes), payment_verified=True,
    ).exclude(is_carryover=True, carryover_confirmed=False).select_related('student', 'class_slot', 'class_slot__term')
    for enrollment in qs:
        code = _valid_code(enrollment.student.national_code)
        current = best.get(code)
        if not current or position.get(enrollment.class_slot.term_id, 0) > position.get(current.class_slot.term_id, 0):
            best[code] = enrollment
    info = {}
    for code, enrollment in best.items():
        slot = enrollment.class_slot
        info[code] = {
            'level': slot.assigned_level or '', 'day': slot.day_type_display or '', 'time_slot': slot.time_slot or '',
            'teacher': slot.teacher_name or '', 'class_number': slot.number,
            'last_term_id': slot.term_id, 'last_term_title': slot.term.title,
        }
    return info


def _difference(a_rows, b_rows, info_term_ids):
    """
    ریزشی = کدهای ملیِ (غیرتکراری) لیست الف که در لیست ب نیستند.
    خروجی: (dropouts, skipped_no_code) — ردیف‌های بدون کد ملی معتبر قابل مقایسه نیستند و شمرده می‌شوند.
    """
    b_codes = {_valid_code(row.get('national_code')) for row in b_rows}
    b_codes.discard('')
    seen, skipped, candidates = set(), 0, []
    for row in a_rows:
        code = _valid_code(row.get('national_code'))
        if not code:
            skipped += 1
            continue
        if code in seen or code in b_codes:
            continue
        seen.add(code)
        candidates.append((code, row))
    info = _enrollment_info({c for c, _ in candidates}, info_term_ids)
    dropouts = []
    for code, row in candidates:
        extra = info.get(code, {})
        phone = _digits(row.get('phone'))
        if len(phone) == 10 and phone.startswith('9'):
            phone = '0' + phone
        dropouts.append({
            'key': code, 'row_number': code,
            'first_name': str(row.get('first_name') or '').strip(), 'last_name': str(row.get('last_name') or '').strip(),
            'national_code': code, 'phone': phone,
            'level': extra.get('level', '') or str(row.get('level_fallback') or ''), 'day': extra.get('day', ''), 'time_slot': extra.get('time_slot', ''),
            'teacher': extra.get('teacher', ''), 'class_number': extra.get('class_number'),
            'last_term_id': extra.get('last_term_id'), 'last_term_title': extra.get('last_term_title', ''),
        })
    dropouts.sort(key=lambda r: (r['level'], r['last_name'], r['first_name']))
    return dropouts, skipped


class DropoutExtractParseView(APIView):
    """POST (multipart): خواندن یک اکسل با همان پارامترهای ورود دانش‌آموزان کلاس؛ خروجی: سطرهای نرمال‌شده."""
    parser_classes = [MultiPartParser, FormParser]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        uploaded = request.FILES.get('file')
        if not uploaded:
            return Response({'error': 'فایل Excel را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
        columns = {}
        for key, default in _DEFAULT_COLUMNS.items():
            value = str(request.data.get(key) or default).strip().upper()
            if not _COLUMN_RE.match(value):
                return Response({'error': 'بازه‌های ستون را به‌درستی انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
            columns[key] = ClassSlotExcelImportView._excel_column_index(value)
        pairs = [('first_name_start_column', 'first_name_end_column'), ('last_name_start_column', 'last_name_end_column'),
                 ('national_code_start_column', 'national_code_end_column'), ('phone_start_column', 'phone_end_column')]
        if any(columns[a] > columns[b] for a, b in pairs):
            return Response({'error': 'ستون «از» باید قبل از ستون «تا» باشد'}, status=status.HTTP_400_BAD_REQUEST)
        ranges = [(columns[a], columns[b]) for a, b in pairs]
        same_full_name = ranges[0] == ranges[1]
        for i, (s1, e1) in enumerate(ranges):
            for j in range(i + 1, len(ranges)):
                s2, e2 = ranges[j]
                if s1 <= e2 and s2 <= e1 and not (i == 0 and j == 1 and same_full_name):
                    return Response({'error': 'بازه‌های نام، نام خانوادگی، کد ملی و شمارهٔ همراه نباید هم‌پوشانی داشته باشند'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            start_row = int(request.data.get('start_row') or 14)
            end_row = int(request.data.get('end_row') or 0)
        except (TypeError, ValueError):
            return Response({'error': 'شمارهٔ سطر شروع و پایان را وارد کنید'}, status=status.HTTP_400_BAD_REQUEST)
        if start_row < 1 or end_row < start_row:
            return Response({'error': 'بازهٔ سطرها معتبر نیست'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            from accounts.views import _load_excel_rows
            sheet_rows = _load_excel_rows(uploaded)
        except Exception as exc:
            return Response({'error': str(exc) or 'خواندن فایل Excel انجام نشد'}, status=status.HTTP_400_BAD_REQUEST)
        if start_row > len(sheet_rows):
            return Response({'error': f'فایل فقط {len(sheet_rows)} سطر قابل‌خواندن دارد'}, status=status.HTTP_400_BAD_REQUEST)
        actual_end = min(end_row, len(sheet_rows))

        def join_range(values, start, end):
            parts = []
            for index in range(start, end + 1):
                value = values[index] if index < len(values) else ''
                text = str(value).strip() if value is not None else ''
                if text:
                    parts.append(text)
            return ' '.join(parts)

        rows = []
        for row_number in range(start_row, actual_end + 1):
            values = sheet_rows[row_number - 1] or ()
            if same_full_name:
                parts = join_range(values, *ranges[0]).split()
                first_name, last_name = (parts[0] if parts else ''), ' '.join(parts[1:])
            else:
                first_name, last_name = join_range(values, *ranges[0]), join_range(values, *ranges[1])
            national_code = _digits(join_range(values, *ranges[2]))
            phone = _digits(join_range(values, *ranges[3]))
            if len(phone) == 10 and phone.startswith('9'):
                phone = '0' + phone
            if not (first_name or last_name or national_code or phone):
                continue
            rows.append({'row_number': row_number, 'first_name': first_name, 'last_name': last_name,
                         'national_code': national_code, 'phone': phone})
        return Response({'rows': rows, 'count': len(rows), 'selected_range': {'start': start_row, 'end': actual_end}})


class DropoutExtractComputeView(APIView):
    """
    POST (json). هر دو لیست می‌توانند «از سامانه» یا «از اکسل» باشند:
      mode = 'pair'        : term1_id, term2_id, a_source('db'|'excel'), a_rows, b_source, b_rows
      mode = 'all_vs_term' : term_id,  a_source (کل دانش‌آموزان ثبت‌شده)، a_rows, b_source, b_rows
    لیست الف منهای لیست ب بر پایه‌ی کد ملی = ریزشی‌ها.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        mode = request.data.get('mode') or 'pair'
        a_source, b_source = request.data.get('a_source') or 'db', request.data.get('b_source') or 'db'
        if a_source not in ('db', 'excel') or b_source not in ('db', 'excel'):
            return Response({'error': 'منبع داده نامعتبر است'}, status=status.HTTP_400_BAD_REQUEST)
        terms = _ordered_terms()
        position = {t.id: i for i, t in enumerate(terms)}
        if mode == 'all_vs_term':
            term2, error, is_recent = _single_term(request.data.get('term_id'))
            term1 = None
        else:
            term1, term2, error, is_recent = _term_pair(request.data.get('term1_id'), request.data.get('term2_id'))
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)

        def side_rows(source, rows, db_term_ids, label, all_students=False):
            if source == 'excel':
                if not isinstance(rows, list) or not rows:
                    return None, f'اکسل «{label}» باید خوانده شده باشد'
                return rows, ''
            if all_students:
                data = _all_student_rows()
                if not data:
                    return None, 'در بخش «اطلاعات دانش‌آموزان» دانش‌آموزی ثبت نشده است'
                return data, ''
            data = _db_rows(db_term_ids)
            if not data:
                total = ClassSlotEnrollment.objects.filter(class_slot__term_id__in=db_term_ids).count()
                hint = f' ({total} ثبت‌نام در انتظار تأیید پرداخت یا خاکستری هست که قطعی حساب نمی‌شود)' if total else ''
                return None, f'در سامانه برای «{label}» ثبت‌نام قطعی‌ای پیدا نشد{hint}. اگر لیست این ترم را دارید، گزینهٔ «ورود از Excel» را انتخاب کنید.'
            return data, ''

        if mode == 'all_vs_term':
            earlier = [t.id for t in terms if position[t.id] < position[term2.id]]
            a_rows, err = side_rows(a_source, request.data.get('a_rows'), earlier, 'کل دانش‌آموزان ثبت‌شده', all_students=True)
            info_terms = earlier
            a_label = 'کل دانش‌آموزان ثبت‌شده (اطلاعات دانش‌آموزان)'
        else:
            a_rows, err = side_rows(a_source, request.data.get('a_rows'), [term1.id], term1.title)
            info_terms = [term1.id]
            a_label = term1.title
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)
        b_rows, err = side_rows(b_source, request.data.get('b_rows'), [term2.id], term2.title)
        if err:
            return Response({'error': err}, status=status.HTTP_400_BAD_REQUEST)
        dropouts, skipped = _difference(a_rows, b_rows, info_terms)
        return Response({
            'mode': mode,
            'a': {'label': a_label, 'source': a_source, 'count': len(a_rows)},
            'b': {'label': term2.title, 'source': b_source, 'count': len(b_rows)},
            'term1': {'id': term1.id, 'title': term1.title} if term1 else None,
            'term2': {'id': term2.id, 'title': term2.title},
            'is_recent_pair': is_recent, 'dropouts': dropouts, 'dropout_count': len(dropouts),
            'skipped_no_national_code': skipped,
        })


class DropoutExtractCommitView(APIView):
    """POST (json): term1_id, term2_id, rows (ریزشی‌های انتخاب‌شده) — ثبت نهایی."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_edit_menu(request.user, 'class-management'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from accounts.services import sync_student_from_lead
        from leads.models import ExcelDropout, UnregisteredStudent, build_identity_key, build_person_key
        all_mode = request.data.get('mode') == 'all_vs_term'
        ordered = _ordered_terms()
        terms_by_id = {t.id: t for t in ordered}
        previous_term = None
        if all_mode:
            term2, error, is_recent = _single_term(request.data.get('term_id'))
            term1 = None
            if term2:
                idx = [t.id for t in ordered].index(term2.id)
                previous_term = ordered[idx - 1] if idx > 0 else None
        else:
            term1, term2, error, is_recent = _term_pair(request.data.get('term1_id'), request.data.get('term2_id'))
        if error:
            return Response({'error': error}, status=status.HTTP_400_BAD_REQUEST)
        rows = request.data.get('rows')
        if not isinstance(rows, list) or not rows:
            return Response({'error': 'حداقل یک نفر را انتخاب کنید'}, status=status.HTTP_400_BAD_REQUEST)
        if len(rows) > 3000:
            return Response({'error': 'در هر نوبت حداکثر ۳۰۰۰ نفر قابل ثبت است'}, status=status.HTTP_400_BAD_REQUEST)
        created = duplicates = failed = 0
        with transaction.atomic():
            for row in rows:
                first_name = str(row.get('first_name') or '').strip()
                last_name = str(row.get('last_name') or '').strip()
                national_code = _digits(row.get('national_code'))
                phone = _digits(row.get('phone'))
                if len(phone) == 10 and phone.startswith('9'):
                    phone = '0' + phone
                if not (first_name or last_name):
                    failed += 1
                    continue
                try:
                    student, _ = sync_student_from_lead(
                        first_name=first_name, last_name=last_name, phone=phone,
                        national_code=national_code if len(national_code) == 10 else '', language_level='',
                    )
                except Exception:
                    failed += 1
                    continue
                if not student:
                    failed += 1
                    continue
                row_term1 = (terms_by_id.get(int(row.get('last_term_id') or 0)) or previous_term) if all_mode else term1
                if not row_term1 or row_term1.id == term2.id:
                    failed += 1
                    continue
                last_enrollment = ClassSlotEnrollment.objects.filter(
                    student=student, class_slot__term=row_term1).select_related('class_slot').order_by('-created_at').first()
                level = (last_enrollment.class_slot.assigned_level if last_enrollment else '') or getattr(student, 'language_level', '') or ''
                if is_recent:
                    prefix = build_person_key(national_code, phone, first_name, last_name) + '|level:'
                    if UnregisteredStudent.objects.filter(term=term2, identity_key__startswith=prefix).exists():
                        duplicates += 1
                        continue
                    try:
                        with transaction.atomic():
                            UnregisteredStudent.objects.create(
                                first_name=first_name, last_name=last_name, class_level=level or 'نامشخص',
                                national_code=national_code, phone=phone, term=term2,
                                is_dropout=True, dropout_from_term=row_term1, submitted_by=request.user,
                            )
                        created += 1
                    except IntegrityError:
                        duplicates += 1
                else:
                    _item, was_created = ExcelDropout.objects.get_or_create(
                        student=student, from_term=row_term1, to_term=term2,
                        defaults={'level': level, 'created_by': request.user},
                    )
                    created += 1 if was_created else 0
                    duplicates += 0 if was_created else 1
        destination = 'unregistered' if is_recent else 'dropouts'
        return Response({
            'created': created, 'duplicates': duplicates, 'failed': failed, 'destination': destination,
            'message': (f'{created} نفر به «ثبت‌نام‌نشده‌ها» (با برچسب ریزشی) اضافه شد — از همان‌جا می‌توانید در کلاس ثبتشان کنید یا حذفشان کنید.'
                        if is_recent else f'{created} نفر به بخش «ریزشی‌ها» منتقل شد.'),
        })
