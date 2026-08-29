from django.urls import path
from .views import (
    LevelChoicesView, LevelTestListCreateView, LevelTestDetailView, LevelTestPriceSettingView,
    StudentRequestLevelTestView, MyLevelTestsView, LevelTestPaymentInfoView,
    StandardLevelListView, StandardLevelDetailView,
)

urlpatterns = [
    path('level-tests/standard-levels/', StandardLevelListView.as_view(), name='standard_level_list'),
    path('level-tests/standard-levels/<int:pk>/', StandardLevelDetailView.as_view(), name='standard_level_detail'),
    path('level-tests/choices/', LevelChoicesView.as_view(), name='level_test_choices'),
    path('level-tests/price-setting/', LevelTestPriceSettingView.as_view(), name='level_test_price_setting'),
    path('level-tests/payment-info/', LevelTestPaymentInfoView.as_view(), name='level_test_payment_info'),
    path('level-tests/request/', StudentRequestLevelTestView.as_view(), name='level_test_student_request'),
    path('level-tests/mine/', MyLevelTestsView.as_view(), name='level_test_mine'),
    path('level-tests/', LevelTestListCreateView.as_view(), name='level_test_list'),
    path('level-tests/<int:pk>/', LevelTestDetailView.as_view(), name='level_test_detail'),
]
