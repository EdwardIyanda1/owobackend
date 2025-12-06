from django.urls import path
from rest_framework_simplejwt.views import TokenObtainPairView
from .views import (
    UserProfileView, NINVerificationView, GenerateStatementView, 
    ExportStatementView, StatementHistoryView, TestExportView,
    RegisterView, WalletInfoView, TransferView, BillPaymentView, 
    RecentTransactionsView, VerifyAccountView, RealTimeDataView, UpdatePinView, 
    DebugRequestView, HealthCheckView,
    BankListView, BeneficiaryListView,  # REMOVED duplicate VerifyAccountView here
    CreateBeneficiaryView, DeleteBeneficiaryView, UpdateBeneficiaryView
)

urlpatterns = [
    path('statement/export/<str:statement_id>/<str:format>', 
         ExportStatementView.as_view(), 
         name='export_statement'),
    
    path('statement/test/<str:statement_id>/<str:format>', 
         TestExportView.as_view(), 
         name='test_export'),
    
    path('health/', HealthCheckView.as_view(), name='health-check'),
    
    # Statement URLs without parameters
    path('statement/generate/', GenerateStatementView.as_view(), name='generate_statement'),
    path('statement/history/', StatementHistoryView.as_view(), name='statement_history'),
    
    # Debug endpoints (temporary)
    path('debug-request/', DebugRequestView.as_view(), name='debug_request'),
    
    # Beneficiary URLs
    path('banks/', BankListView.as_view(), name='banks_list'),
    path('beneficiaries/', BeneficiaryListView.as_view(), name='beneficiaries_list'),
    path('beneficiaries/create/', CreateBeneficiaryView.as_view(), name='create_beneficiary'),
    path('beneficiaries/<int:beneficiary_id>/delete/', DeleteBeneficiaryView.as_view(), name='delete_beneficiary'),
    path('beneficiaries/<int:beneficiary_id>/update/', UpdateBeneficiaryView.as_view(), name='update_beneficiary'),
    # KEEP ONLY ONE verify-account path (for POST requests)
    path('verify-account/', VerifyAccountView.as_view(), name='verify_account'),

    # All other URLs
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', TokenObtainPairView.as_view(), name='login'),
    path('wallet/', WalletInfoView.as_view(), name='wallet'),
    path('transfer/', TransferView.as_view(), name='transfer'),
    path('bill/', BillPaymentView.as_view(), name='bill'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('transactions/', RecentTransactionsView.as_view(), name='transactions'),
    # REMOVED the duplicate verify-account path here
    path('real-time-data/', RealTimeDataView.as_view(), name='real_time_data'),
    path('verify-nin/', NINVerificationView.as_view(), name='verify_nin'),
    path('update-pin/', UpdatePinView.as_view(), name='update_pin'),
]