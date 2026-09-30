from django.urls import path
from .views import (
    BookListView,
    BookDetailView,
    SellBookView,
    AddBookStockView,
    BookSalesHistoryView,
    BookSalesPriceListView,
    LibraryStatsView,
)

urlpatterns = [
    path('library/books/', BookListView.as_view(), name='book_list'),
    path('library/books/sale-prices/', BookSalesPriceListView.as_view(), name='book_sale_prices'),
    path('library/books/<int:pk>/', BookDetailView.as_view(), name='book_detail'),
    path('library/books/<int:pk>/sell/', SellBookView.as_view(), name='book_sell'),
    path('library/books/<int:pk>/add-stock/', AddBookStockView.as_view(), name='book_add_stock'),
    path('library/books/<int:pk>/sales/', BookSalesHistoryView.as_view(), name='book_sales_history'),
    path('library/stats/', LibraryStatsView.as_view(), name='library_stats'),
]
