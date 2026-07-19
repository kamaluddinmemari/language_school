from django.db.models import Sum, F, IntegerField
from django.db.models.functions import Coalesce
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
import jdatetime
from .models import Book, BookSale
from .serializers import BookSerializer, BookSaleSerializer, SellBookSerializer

MANAGE_ROLES = ('admin', 'evaluator', 'office')


class BookListView(generics.ListCreateAPIView):
    """مدیریت کتابخانه — برای مدیر و مسئول آموزش هر دو باز است"""
    permission_classes = [IsAuthenticated]
    serializer_class = BookSerializer

    def get_queryset(self):
        if self.request.user.role not in MANAGE_ROLES:
            return Book.objects.none()
        return Book.objects.all()

    def create(self, request, *args, **kwargs):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        return super().create(request, *args, **kwargs)


class BookDetailView(generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = BookSerializer
    queryset = Book.objects.all()

    def check_permission(self, request):
        return request.user.role in MANAGE_ROLES

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
        if request.user.role not in MANAGE_ROLES:
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


class BookSalesHistoryView(generics.ListAPIView):
    """GET: تاریخچه‌ی فروش یک کتاب"""
    permission_classes = [IsAuthenticated]
    serializer_class = BookSaleSerializer

    def get_queryset(self):
        if self.request.user.role not in MANAGE_ROLES:
            return BookSale.objects.none()
        return BookSale.objects.filter(book_id=self.kwargs['pk'])


class LibraryStatsView(APIView):
    """GET: آمار تجمیعی لحظه‌ای کل کتابخانه"""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role not in MANAGE_ROLES:
            return Response({'error': 'دسترسی ندارید'}, status=status.HTTP_403_FORBIDDEN)
        books = Book.objects.all()
        total_titles = books.count()
        total_stock = sum(b.current_stock for b in books)
        total_stock_value = sum(b.stock_value for b in books)
        total_sales_revenue = sum(b.total_sales_revenue for b in books)
        total_sales_quantity = sum(b.total_sales_quantity for b in books)
        total_predicted_need = sum(b.predicted_need for b in books)

        now_local = timezone.localtime(timezone.now())
        generated_at_jalali = jdatetime.datetime.fromgregorian(datetime=now_local).strftime('%Y/%m/%d - %H:%M:%S')

        return Response({
            'total_titles': total_titles,
            'total_stock': total_stock,
            'total_stock_value': total_stock_value,
            'total_sales_revenue': total_sales_revenue,
            'total_sales_quantity': total_sales_quantity,
            'total_predicted_need': total_predicted_need,
            'generated_at': now_local.isoformat(),
            'generated_at_jalali': generated_at_jalali,
            'books': BookSerializer(books, many=True).data,
        })
