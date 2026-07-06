from django.urls import path
from .views import LevelChoicesView, LevelTestListCreateView, LevelTestDetailView, LevelTestPriceSettingView

urlpatterns = [
    path('level-tests/choices/', LevelChoicesView.as_view(), name='level_test_choices'),
    path('level-tests/price-setting/', LevelTestPriceSettingView.as_view(), name='level_test_price_setting'),
    path('level-tests/', LevelTestListCreateView.as_view(), name='level_test_list'),
    path('level-tests/<int:pk>/', LevelTestDetailView.as_view(), name='level_test_detail'),
]
