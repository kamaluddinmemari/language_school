from django.db.models import Sum, F, IntegerField
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
import jdatetime
from .models import Book, BookSale, BookStockAddition
from .serializers import BookSerializer, BookSaleSerializer, SellBookSerializer, AddBookStockSerializer, BookStockAdditionSerializer
from accounts.menu_permissions import can_edit_menu

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
        total_titles = books.count()
        total_stock = sum(b.current_stock for b in books)
        total_stock_value = sum(b.stock_value for b in books)
        total_predicted_need = sum(b.predicted_need for b in books)

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

            data = BookSerializer(b).data
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
