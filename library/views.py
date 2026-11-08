from django.db.models import Sum, F, IntegerField, Max, Count
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
import jdatetime
from .models import Book, BookSale, BookStockAddition, BookShortcut, LevelShortcut
from .serializers import BookShortcutSerializer, BookSerializer, BookSaleSerializer, SellBookSerializer, AddBookStockSerializer, BookStockAdditionSerializer, LevelShortcutSerializer
from accounts.menu_permissions import can_edit_menu, can_view_menu
from . import forecast as fc

# منسوخ — از تنظیمات دسترسی (accounts.menu_permissions.can_edit_menu) جایگزین شد.
MANAGE_ROLES = ('admin', 'evaluator', 'office')


class BookListView(generics.ListCreateAPIView):
    """مدیریت کتابخانه — برای مدیر و مسئول آموزش هر دو باز است"""
    permission_classes = [IsAuthenticated]
    serializer_class = BookSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'library'):
            return Book.objects.none()
        return Book.objects.all()

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'library'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class BookDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BookSerializer
    queryset = Book.objects.all()

    def check_permission(self, request):
        return can_edit_menu(request.user, 'library')

    def retrieve(self, request, *args, **kwargs):
        if not self.check_permission(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().retrieve(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not self.check_permission(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not self.check_permission(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class BookReorderView(APIView):
    """POST {ids:[...]}: ترتیب دلخواه کتاب‌ها (ترتیب همین فهرست ذخیره می‌شود)."""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not can_edit_menu(request.user, 'library'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        ids = request.data.get('ids')
        if not isinstance(ids, list):
            return Response({'error': 'ids الزامی است'}, status=status.HTTP_400_BAD_REQUEST)
        for position, book_id in enumerate(ids, start=1):
            Book.objects.filter(pk=book_id).update(sort_order=position)
        return Response({'ok': True})


class BookSalesPriceListView(APIView):
    """GET: داده‌ی فشرده‌ی جدول «قیمت فروش کتاب‌ها» برای نمایش سریع در پنل."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'library'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        books = Book.objects.order_by('title', 'id')
        return Response([
            {
                'id': book.id,
                'title': book.title,
                'unit_price': book.unit_price,
                'current_stock': book.current_stock,
            }
            for book in books
        ])


class SellBookView(APIView):
    """POST: ثبت فروش — بدنه: {quantity} — از موجودی کم می‌کند و تراکنش فروش می‌سازد"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'library'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            book = Book.objects.get(pk=pk)
        except Book.DoesNotExist:
            return Response({'error': 'کتاب پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = SellBookSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quantity = serializer.validated_data['quantity']

        if quantity > book.current_stock:
            return Response({'error': f'موجودی کافی نیست (موجودی فعلی: {book.current_stock})'}, status=status.HTTP_400_BAD_REQUEST)

        sale = BookSale.objects.create(
            book=book, quantity=quantity, unit_price_at_sale=book.unit_price, sold_by=request.user
        )
        book.current_stock -= quantity
        book.save()

        return Response({
            'sale': BookSaleSerializer(sale).data,
            'book': BookSerializer(book).data,
        }, status=status.HTTP_201_CREATED)


class AddBookStockView(APIView):
    """POST: افزایش موجودی یک کتاب — بدنه: {quantity} — برای دکمه‌ی «+ افزودن» جلوی هر ردیف"""
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if not can_edit_menu(request.user, 'library'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        try:
            book = Book.objects.get(pk=pk)
        except Book.DoesNotExist:
            return Response({'error': 'کتاب پیدا نشد'}, status=status.HTTP_404_NOT_FOUND)

        serializer = AddBookStockSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quantity = serializer.validated_data['quantity']

        addition = BookStockAddition.objects.create(book=book, quantity=quantity, added_by=request.user)
        book.current_stock += quantity
        book.save()

        return Response({
            'addition': BookStockAdditionSerializer(addition).data,
            'book': BookSerializer(book).data,
        }, status=status.HTTP_201_CREATED)


class BookSalesHistoryView(generics.ListAPIView):
    """GET: تاریخچه‌ی فروش یک کتاب"""
    permission_classes = [IsAuthenticated]
    serializer_class = BookSaleSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'library'):
            return BookSale.objects.none()
        return BookSale.objects.filter(book_id=self.kwargs['pk'])


class LibraryStatsView(APIView):
    """
    GET: آمار تجمیعی کتابخانه — با پارامترهای اختیاری ?date_from=YYYY-MM-DD و ?date_to=YYYY-MM-DD
    همه‌ی آمارهای فروش/تأمین موجودی/سود را فقط در همان بازه محاسبه می‌کند (هم در سطح کل کتابخانه
    هم در سطح هر کتاب، از طریق فیلدهای period_*). موجودی فعلی (current_stock) همیشه لحظه‌ای و
    مستقل از فیلتر تاریخ است، چون سابقه‌ی روزانه‌ای از موجودی نگه‌داری نمی‌شود.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'library'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)

        date_from = request.query_params.get('date_from') or None
        date_to = request.query_params.get('date_to') or None

        sales_qs = BookSale.objects.all()
        additions_qs = BookStockAddition.objects.all()
        if date_from:
            sales_qs = sales_qs.filter(sold_at__date__gte=date_from)
            additions_qs = additions_qs.filter(added_at__date__gte=date_from)
        if date_to:
            sales_qs = sales_qs.filter(sold_at__date__lte=date_to)
            additions_qs = additions_qs.filter(added_at__date__lte=date_to)

        books = Book.objects.all()
        forecast_ctx = fc.build_context(request.query_params.get('forecast_term'))
        ser_ctx = {'request': request, 'forecast': forecast_ctx}
        total_titles = books.count()
        total_stock = sum(b.current_stock for b in books)
        total_stock_value = sum(b.stock_value for b in books)
        total_predicted_need = 0

        books_data = []
        period_sales_quantity = 0
        period_sales_revenue = 0
        period_stock_added = 0
        period_stock_added_cost = 0
        period_cost_of_goods_sold = 0
        period_profit = 0

        for b in books:
            b_sales = list(sales_qs.filter(book=b))
            b_additions = list(additions_qs.filter(book=b))
            b_sales_qty = sum(s.quantity for s in b_sales)
            b_sales_rev = sum(s.total_price for s in b_sales)
            b_added_qty = sum(a.quantity for a in b_additions)
            b_added_cost = b.purchase_price * b_added_qty
            b_cogs = b.purchase_price * b_sales_qty
            b_profit = b_sales_rev - b_cogs

            period_sales_quantity += b_sales_qty
            period_sales_revenue += b_sales_rev
            period_stock_added += b_added_qty
            period_stock_added_cost += b_added_cost
            period_cost_of_goods_sold += b_cogs
            period_profit += b_profit

            data = BookSerializer(b, context=ser_ctx).data
            total_predicted_need += data['order_needed']
            data['period_sales_quantity'] = b_sales_qty
            data['period_sales_revenue'] = b_sales_rev
            data['period_stock_added'] = b_added_qty
            data['period_stock_added_cost'] = b_added_cost
            data['period_cost_of_goods_sold'] = b_cogs
            data['period_profit'] = b_profit
            books_data.append(data)

        now_local = timezone.localtime(timezone.now())
        generated_at_jalali = jdatetime.datetime.fromgregorian(datetime=now_local).strftime('%Y/%m/%d - %H:%M:%S')

        return Response({
            'date_from': date_from,
            'date_to': date_to,
            'total_titles': total_titles,
            'total_stock': total_stock,
            'total_stock_value': total_stock_value,
            'total_predicted_need': total_predicted_need,
            'forecast_mode': forecast_ctx.get('mode'),
            'available_levels': fc.available_levels(forecast_ctx['term']),
            'forecast_term': {'id': forecast_ctx['term'].id, 'title': forecast_ctx['term'].title} if forecast_ctx['term'] else None,
            'terms': [{'id': t.id, 'title': t.title, 'is_latest': bool(forecast_ctx['term'] and t.id == forecast_ctx['term'].id)} for t in reversed(forecast_ctx['terms'])],
            # آمار درون‌بازه‌ای (اگه تاریخ داده نشه، یعنی از ابتدا تا الان = همون آمار کلی سابق)
            'period_sales_quantity': period_sales_quantity,
            'period_sales_revenue': period_sales_revenue,
            'period_stock_added': period_stock_added,
            'period_stock_added_cost': period_stock_added_cost,
            'period_cost_of_goods_sold': period_cost_of_goods_sold,
            'period_profit': period_profit,
            # نگه‌داشته‌شده برای سازگاری با هر کد قبلی‌ای که به این اسم‌ها متکی بود (همیشه کل‌عمر، فیلترنشده)
            'total_sales_revenue': sum(b.total_sales_revenue for b in books),
            'total_sales_quantity': sum(b.total_sales_quantity for b in books),
            'total_cost': sum(b.total_cost for b in books),
            'total_cost_of_goods_sold': sum(b.cost_of_goods_sold for b in books),
            'total_profit': sum(b.total_profit for b in books),
            'generated_at': now_local.isoformat(),
            'generated_at_jalali': generated_at_jalali,
            'books': books_data,
        })


class LibraryStockPulseView(APIView):
    """GET: نبض سبک کسر/افزودن موجودی برای اعلان صوتی سراسری پنل."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not (can_view_menu(request.user, 'library') or can_edit_menu(request.user, 'library')):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        sales = BookSale.objects.aggregate(max_id=Max('id'), count=Count('id'))
        additions = BookStockAddition.objects.aggregate(max_id=Max('id'), count=Count('id'))
        return Response({
            'sell': {'max_id': sales['max_id'] or 0, 'count': sales['count'] or 0},
            'add': {'max_id': additions['max_id'] or 0, 'count': additions['count'] or 0},
        })


class BookShortcutListView(generics.ListCreateAPIView):
    """میانبرهای فروش کتاب — برای همه‌ی کاربرانی که به منوی کتابخانه دسترسی دارند مشترک است"""
    permission_classes = [IsAuthenticated]
    serializer_class = BookShortcutSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'library'):
            return BookShortcut.objects.none()
        return BookShortcut.objects.select_related('book').all()

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'library'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        last = BookShortcut.objects.order_by('-order').first()
        serializer.save(order=(last.order + 1) if last else 0)


class BookShortcutDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BookShortcutSerializer
    queryset = BookShortcut.objects.select_related('book').all()

    def _denied(self, request):
        return not can_edit_menu(request.user, 'library')

    def update(self, request, *args, **kwargs):
        if self._denied(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if self._denied(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class LevelShortcutListView(generics.ListCreateAPIView):
    """میانبرهای فروش بر اساس سطح؛ سطح و کتاب در یک رکورد قابل تغییرند."""
    permission_classes = [IsAuthenticated]
    serializer_class = LevelShortcutSerializer

    def get_queryset(self):
        if not can_edit_menu(self.request.user, 'library'):
            return LevelShortcut.objects.none()
        return LevelShortcut.objects.select_related('book').all()

    def create(self, request, *args, **kwargs):
        if not can_edit_menu(request.user, 'library'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        last = LevelShortcut.objects.order_by('-order').first()
        serializer.save(order=(last.order + 1) if last else 0)


class LevelShortcutDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = LevelShortcutSerializer
    queryset = LevelShortcut.objects.select_related('book').all()

    def _denied(self, request):
        return not can_edit_menu(request.user, 'library')

    def update(self, request, *args, **kwargs):
        if self._denied(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if self._denied(request):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().destroy(request, *args, **kwargs)


class BookOrderNeedsView(APIView):
    """GET: جدول زندهٔ «کتاب‌های مورد نیاز برای سفارش» بر حسب سطوح استاندارد و کتاب‌های هر سطح.

    هر ردیف = یک کتاب (یا یک سطحِ بدون کتاب): تعداد زبان‌آموزان ثبت‌نام‌شدهٔ همان سطح(ها) در ترم ملاک کتابخانه،
    موجودی فعلی کتاب و کسری = max(0, نیاز − موجودی). چیزی ذخیره نمی‌شود؛ هر بار از ثبت‌نام‌ها و موجودی لحظه‌ای محاسبه می‌شود.
    پارامتر اختیاری ?forecast_term=<id> همان ترم ملاک سایر بخش‌های کتابخانه است.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not can_edit_menu(request.user, 'library'):
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        from level_tests.models import StandardLevel
        # ترم جاریِ واقعی (تا شروع تاریخیِ ترم جدید، ترم قبلی)؛ همهٔ ثبت‌نام‌شده‌ها در همهٔ نوع کلاس‌ها
        # (دخترانه، پسرانه و مختلط) شمرده می‌شوند، نه فقط بیعانه‌دارها یا فقط کلاس‌های زوج/فرد.
        terms = fc.ordered_terms()
        wanted = request.query_params.get('forecast_term')
        term = next((t for t in terms if str(t.id) == str(wanted)), None) if wanted else None
        term = term or fc.current_started_term(terms)
        ctx = fc.build_context(term=term, mode='registered', all_day_types=True)
        index = ctx['index']
        gender_index = ctx['gender_index']
        group_labels = dict(StandardLevel.AgeGroup.choices)
        levels = list(StandardLevel.objects.all().order_by('age_group', 'order', 'code'))
        position = {fc.normalize_level(lv.code): i for i, lv in enumerate(levels)}
        info = {fc.normalize_level(lv.code): lv for lv in levels}

        # منطق سفارش: کسی که الان در «آخرین سطحِ» یک گروه است ترم بعد وارد گروه بعدی می‌شود و کتاب آن گروه را لازم دارد.
        # پس برای هر کتاب فقط افرادِ سطح مرزی (یک سطح قبل از شروع کتاب) شمرده می‌شوند، نه همهٔ سطوح گروه؛
        # مثلاً Evolve 2 (سطوح 201–206) ← زبان‌آموزان 106. ستون «سطح» همان سطوح پوشش‌داده‌شدهٔ کتاب را نشان می‌دهد.
        def group_of(key):
            return fc.level_group(key) or ('single', key)

        members = {}
        for key in position:
            members.setdefault(group_of(key), []).append(key)
        group_order = sorted(members, key=lambda g: position[members[g][0]])

        def next_group(group):
            at = group_order.index(group)
            if at + 1 < len(group_order) and group_order[at + 1][0] == group[0]:
                return group_order[at + 1]
            return None

        def covered_keys(book, count_keys):
            """سطوحی که کتاب پوشش می‌دهد (فقط برای نمایش)."""
            if book.category == Book.Category.STORY:
                return list(count_keys)
            is_oxford = 'oxford' in str(book.title).lower()
            covered = []
            for key in count_keys:
                group = group_of(key)
                start = group
                if key == members[group][-1] and next_group(group):
                    start = next_group(group)
                chosen = [start]
                if is_oxford and next_group(start):
                    chosen.append(next_group(start))
                for g in chosen:
                    if g not in covered:
                        covered.append(g)
            return [k for g in sorted(covered, key=lambda g: position[members[g][0]]) for k in members[g]]

        def range_labels(keys):
            """کلیدهای پشت‌سرهم یک بازه می‌شوند: ['201','202',…,'206'] → '201–206'"""
            keys = sorted(set(keys), key=position.get)
            runs, run = [], []
            for key in keys:
                if run and position[key] != position[run[-1]] + 1:
                    runs.append(run)
                    run = []
                run.append(key)
            if run:
                runs.append(run)
            return [info[r[0]].code if len(r) == 1 else f'{info[r[0]].code}–{info[r[-1]].code}' for r in runs]

        def gender_counts(keys):
            out = {}
            for gender in ('girls', 'boys', 'mixed'):
                people = set()
                for key in keys:
                    people |= gender_index.get(key, {}).get(gender, set())
                out[gender] = len(people)
            return out

        rows, used_keys = [], set()
        for book in Book.objects.all():
            count_keys = sorted({k for k in fc.levels_for_book(book) if k in position}, key=position.get)
            if not count_keys:
                continue
            students = set()
            for key in count_keys:
                students |= index.get(key, set())
            used_keys.update(count_keys)
            need = len(students)
            stock = book.current_stock
            shown = covered_keys(book, count_keys) or count_keys
            first = info[shown[0]]
            rows.append({
                'sort': (position[shown[0]], book.sort_order, book.title),
                'levels': range_labels(shown), 'count_levels': [info[k].code for k in count_keys],
                'group': first.age_group, 'group_label': group_labels.get(first.age_group, first.age_group),
                'students': need, 'book_id': book.id, 'book_title': book.title, 'stock': stock,
                'shortage': max(0, need - max(stock, 0)), **gender_counts(count_keys),
            })
        rows.sort(key=lambda r: r['sort'])
        for row in rows:
            row.pop('sort')
        all_students = set()
        for key in used_keys:
            all_students |= index.get(key, set())
        return Response({
            'term': {'id': term.id, 'title': term.title} if term else None,
            'mode': ctx['mode'],
            'rows': rows,
            'total_students': len(all_students),
            'total_shortage': sum(r['shortage'] for r in rows),
            'generated_at': timezone.now().isoformat(),
        })
