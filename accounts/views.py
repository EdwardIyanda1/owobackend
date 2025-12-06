from rest_framework import views, status, permissions
from rest_framework.response import Response
from django.db import transaction
from django.core.mail import send_mail
from .models import User, Wallet, Transaction, Statement, Beneficiary  # Added Beneficiary
from .serializers import UserSerializer, WalletSerializer, TransactionSerializer, StatementRequestSerializer, StatementSerializer, BankSerializer, BeneficiarySerializer, CreateBeneficiarySerializer, VerifyAccountSerializer  # Added new serializers
import time
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta
from django.utils import timezone
from django.contrib.auth.hashers import make_password, check_password
from django.db.models import Sum, Count, Q
import json
from django.http import HttpResponse
import csv
import io
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
import uuid
import os
from django.conf import settings
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

NIN_VERIFICATION_API_KEY = 'your_api_key_here'
NIN_VERIFICATION_URL = 'https://api.verificationservice.com/v1/nin/verify'

class BankListView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get list of supported banks"""
        banks = [
            {"code": "050", "name": "Owo Bank"},
            {"code": "001", "name": "Access Bank"},
            {"code": "002", "name": "First Bank"},
            {"code": "003", "name": "GTBank"},
            {"code": "004", "name": "UBA"},
            {"code": "005", "name": "Zenith Bank"},
            {"code": "006", "name": "Fidelity Bank"},
            {"code": "030", "name": "Opay"},
            {"code": "032", "name": "Kuda Bank"},
        ]
        return Response(banks)
    
class HealthCheckView(APIView):
    permission_classes = [AllowAny]
    
    def get(self, request):
        """
        Health check endpoint for backend status
        """
        return Response({
            'status': 'healthy',
            'service': 'OWO Banking API',
            'timestamp': timezone.now().isoformat(),
            'version': '1.0.0'
        })

class DebugRequestView(views.APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request, *args, **kwargs):
        from django.urls import resolve, Resolver404
        
        current_path = request.path
        try:
            match = resolve(current_path)
            match_info = {
                'resolved': True,
                'view': match.func.__name__,
                'view_class': getattr(match.func, 'view_class', None).__name__ if hasattr(match.func, 'view_class') else 'N/A',
                'args': match.args,
                'kwargs': match.kwargs,
                'url_name': match.url_name,
            }
        except Resolver404:
            match_info = {
                'resolved': False,
                'error': 'No match found',
            }
        
        # Also check the statement export URL specifically
        test_path = '/api/auth/statement/export/TEST123/pdf/'
        try:
            test_match = resolve(test_path)
            test_resolved = True
        except Resolver404:
            test_resolved = False
        
        return Response({
            'current_request': {
                'path': current_path,
                'method': request.method,
                'resolved': match_info,
            },
            'test_export_url': {
                'path': test_path,
                'resolved': test_resolved,
            },
            'all_urls': list(request.resolver_match.urlconf.urlpatterns) if hasattr(request, 'resolver_match') and request.resolver_match else 'No resolver match',
        })

class GenerateStatementView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    @transaction.atomic
    def post(self, request):
        """
        Generate account statement
        Expected payload: {
            "period": "today" | "this_month" | "custom" | etc.,
            "start_date": "2024-01-01",  # optional for custom
            "end_date": "2024-01-31",    # optional for custom
            "transaction_type": "transfer"  # optional filter
        }
        """
        serializer = StatementRequestSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        
        try:
            data = serializer.validated_data
            user = request.user
            wallet = user.wallet
            
            # Determine date range based on period
            today = timezone.now().date()
            period = data['period']
            
            if period == 'custom':
                start_date = data['start_date']
                end_date = data['end_date']
            elif period == 'today':
                start_date = today
                end_date = today
            elif period == 'yesterday':
                start_date = today - timedelta(days=1)
                end_date = start_date
            elif period == 'this_week':
                start_date = today - timedelta(days=today.weekday())
                end_date = start_date + timedelta(days=6)
            elif period == 'last_week':
                start_date = today - timedelta(days=today.weekday() + 7)
                end_date = start_date + timedelta(days=6)
            elif period == 'this_month':
                start_date = today.replace(day=1)
                end_date = (start_date + timedelta(days=32)).replace(day=1) - timedelta(days=1)
            elif period == 'last_month':
                first_day_current = today.replace(day=1)
                last_day_previous = first_day_current - timedelta(days=1)
                start_date = last_day_previous.replace(day=1)
                end_date = last_day_previous
            elif period == 'this_year':
                start_date = today.replace(month=1, day=1)
                end_date = today.replace(month=12, day=31)
            else:
                return Response({"error": "Invalid period"}, status=400)
            
            # Convert to timezone aware datetime
            start_datetime = timezone.make_aware(datetime.combine(start_date, datetime.min.time()))
            end_datetime = timezone.make_aware(datetime.combine(end_date, datetime.max.time()))
            
            # Build query
            query = Q(wallet=wallet, timestamp__range=(start_datetime, end_datetime))
            
            # Apply transaction type filter if specified
            transaction_type = data.get('transaction_type')
            if transaction_type and transaction_type.lower() != 'all':
                if transaction_type.lower() == 'deposit':
                    query &= Q(amount__gt=0)
                elif transaction_type.lower() == 'withdrawal':
                    query &= Q(amount__lt=0)
                else:
                    query &= Q(type__iexact=transaction_type)
            
            # Get transactions
            transactions = Transaction.objects.filter(query).order_by('-timestamp')
            
            # Calculate totals
            total_transactions = transactions.count()
            total_income = transactions.filter(amount__gt=0).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00')
            total_expense = abs(transactions.filter(amount__lt=0).aggregate(Sum('amount'))['amount__sum'] or Decimal('0.00'))
            net_change = total_income - total_expense
            
            # Create statement record
            statement = Statement.objects.create(
                user=user,
                period_start=start_date,
                period_end=end_date,
                transaction_type=transaction_type if transaction_type and transaction_type.lower() != 'all' else None,
                total_transactions=total_transactions,
                total_income=total_income,
                total_expense=total_expense,
                net_change=net_change
            )
            
            print(f"Created statement with ID: {statement.statement_id}")
            print(f"Statement saved: {statement.id}")

            # Serialize transactions for response
            transaction_data = TransactionSerializer(transactions[:50], many=True).data  # Limit for preview
            
            return Response({
                "success": True,
                "statement_id": statement.statement_id,
                "period": {
                    "label": period,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "display": f"{start_date.strftime('%b %d, %Y')} to {end_date.strftime('%b %d, %Y')}"
                },
                "summary": {
                    "total_transactions": total_transactions,
                    "total_income": str(total_income),
                    "total_expense": str(total_expense),
                    "net_change": str(net_change),
                    "average_daily": str((net_change / max((end_date - start_date).days, 1))),
                    "most_common_type": transactions.values('type').annotate(count=Count('type')).order_by('-count').first()
                },
                "transactions": transaction_data,
                "generated_at": statement.generated_at.isoformat(),
                "download_url": f"/api/auth/statement/export/{statement.statement_id}/pdf/"  # FIXED THIS URL
            })
            
        except Exception as e:
            print(f"Statement generation error: {str(e)}")
            return Response({"error": str(e)}, status=500)

class ExportStatementView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, statement_id, format):
        print(f"=== ExportStatementView GET called! ===")
        print(f"Path: {request.path}")
        print(f"User: {request.user}")
        print(f"Authenticated: {request.user.is_authenticated}")
        print(f"Statement ID: {statement_id}")
        print(f"Format: {format}")
        
        # Check if statement exists
        try:
            statement = Statement.objects.get(
                statement_id=statement_id,
                user=request.user
            )
        except Statement.DoesNotExist:
            print(f"Statement not found or access denied")
            return Response(
                {"error": "Statement not found or access denied"}, 
                status=404
            )
        
        # TEMPORARILY: Return a simple response
        return Response({
            'success': True,
            'message': 'Export endpoint is working!',
            'statement_id': statement_id,
            'format': format,
            'user': request.user.email if request.user.is_authenticated else 'Anonymous',
            'statement_data': {
                'period_start': statement.period_start,
                'period_end': statement.period_end,
                'total_transactions': statement.total_transactions,
            }
        })
    
# In views.py, update the DebugURLView
class DebugURLView(views.APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        from django.urls import get_resolver
        from django.urls.resolvers import RegexPattern, URLPattern, URLResolver
        
        resolver = get_resolver()
        
        def get_urls(url_patterns, prefix=''):
            urls = []
            for pattern in url_patterns:
                if isinstance(pattern, URLPattern):
                    urls.append({
                        'pattern': str(pattern.pattern),
                        'name': pattern.name,
                        'callback': pattern.callback.__name__ if hasattr(pattern.callback, '__name__') else str(pattern.callback),
                        'full_pattern': prefix + str(pattern.pattern)
                    })
                elif isinstance(pattern, URLResolver):
                    urls.extend(get_urls(pattern.url_patterns, prefix + str(pattern.pattern)))
            return urls
        
        all_urls = get_urls(resolver.url_patterns)
        
        # Filter for auth URLs
        auth_urls = [url for url in all_urls if '/api/auth/' in url['full_pattern']]
        
        return Response({
            'total_urls': len(all_urls),
            'auth_urls': auth_urls,
            'current_request': {
                'path': request.path,
                'method': request.method,
                'user': str(request.user) if request.user.is_authenticated else 'Anonymous',
            }
        })
    
# In views.py, add this
class CheckURLPatternsView(views.APIView):
    permission_classes = [permissions.AllowAny]
    
    def get(self, request):
        from django.urls import get_resolver
        import re
        
        resolver = get_resolver()
        patterns = []
        
        def extract_patterns(urlpatterns, prefix=''):
            for pattern in urlpatterns:
                if hasattr(pattern, 'pattern'):
                    full_pattern = prefix + str(pattern.pattern)
                    # Clean up the pattern
                    full_pattern = full_pattern.replace('^', '').replace('$', '')
                    patterns.append({
                        'pattern': full_pattern,
                        'name': getattr(pattern, 'name', 'No name'),
                        'lookup_str': str(pattern.lookup_str) if hasattr(pattern, 'lookup_str') else 'N/A'
                    })
                    if hasattr(pattern, 'url_patterns'):
                        extract_patterns(pattern.url_patterns, full_pattern)
        
        extract_patterns(resolver.url_patterns)
        
        # Filter for auth patterns
        auth_patterns = [p for p in patterns if '/api/auth/' in p['pattern']]
        
        return Response({
            'all_patterns_count': len(patterns),
            'auth_patterns': auth_patterns,
            'test_url': '/api/auth/statement/export/STM-D57685E946F9/pdf/',
            'expected_pattern': 'api/auth/statement/export/<str:statement_id>/<str:format>/'
        })
    
class StatementHistoryView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get user's statement history"""
        statements = Statement.objects.filter(user=request.user).order_by('-generated_at')[:20]
        serializer = StatementSerializer(statements, many=True)
        return Response(serializer.data)
    
class NINVerificationView(views.APIView):
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        """
        Verify NIN details
        Expected payload: { "nin": "12345678901", "first_name": "John", "last_name": "Doe", "date_of_birth": "1990-01-01" }
        """
        nin = request.data.get('nin')
        first_name = request.data.get('first_name', '').upper()
        last_name = request.data.get('last_name', '').upper()
        date_of_birth = request.data.get('date_of_birth')
        
        if not nin:
            return Response({"error": "NIN is required"}, status=400)
        
        # Check if NIN already exists
        if User.objects.filter(nin=nin).exists():
            return Response({"error": "NIN already registered"}, status=400)
        
        try:
            # For now, we'll simulate verification
            # In production, you would call the actual API
            
            # Simulate API call (replace with actual API call)
            # headers = {
            #     'Authorization': f'Bearer {NIN_VERIFICATION_API_KEY}',
            #     'Content-Type': 'application/json'
            # }
            # payload = {
            #     'nin': nin,
            #     'first_name': first_name,
            #     'last_name': last_name
            # }
            # response = requests.post(NIN_VERIFICATION_URL, json=payload, headers=headers)
            
            # Simulated response (replace with actual response parsing)
            # For demo purposes, we'll assume verification is successful
            simulated_response = {
                "status": "success",
                "data": {
                    "nin": nin,
                    "first_name": first_name,
                    "last_name": last_name,
                    "date_of_birth": date_of_birth or "1990-01-01",
                    "photo": "base64_encoded_photo_data",
                    "is_verified": True,
                    "verification_date": timezone.now().isoformat()
                }
            }
            
            return Response({
                "verified": True,
                "message": "NIN verification successful",
                "data": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "date_of_birth": simulated_response['data']['date_of_birth']
                }
            })
            
        except Exception as e:
            print(f"NIN verification error: {str(e)}")
            return Response({
                "verified": False,
                "error": "NIN verification failed. Please ensure details are correct.",
                "details": str(e)
            }, status=400)

class RealTimeDataView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get real-time wallet and transaction data"""
        try:
            wallet = request.user.wallet
            
            # Get latest transactions (last 10)
            latest_transactions = Transaction.objects.filter(
                wallet=wallet
            ).order_by('-timestamp')[:10]
            
            # Get today's date using timezone
            today = timezone.now().date()
            today_start = timezone.make_aware(datetime.combine(today, datetime.min.time()))
            today_end = timezone.make_aware(datetime.combine(today, datetime.max.time()))
            
            # Get today's transactions
            today_transactions = Transaction.objects.filter(
                wallet=wallet,
                timestamp__range=(today_start, today_end)
            )
            
            # Calculate today's stats
            today_income = Decimal('0.00')
            today_expense = Decimal('0.00')
            
            for transaction in today_transactions:
                if transaction.amount > 0:
                    today_income += transaction.amount
                else:
                    today_expense += abs(transaction.amount)
            
            return Response({
                'wallet': {
                    'balance': str(wallet.balance),
                    'account_number': wallet.account_number,
                },
                'stats': {
                    'today_income': str(today_income),
                    'today_expense': str(today_expense),
                    'today_transactions': today_transactions.count(),
                },
                'latest_transactions': TransactionSerializer(
                    latest_transactions, many=True
                ).data,
                'last_updated': timezone.now().isoformat()
            })
        except Exception as e:
            print(f"Real-time data error: {str(e)}")
            return Response({'error': str(e)}, status=500)
        
class RegisterView(views.APIView):
    permission_classes = [permissions.AllowAny]
    
    @transaction.atomic
    def post(self, request):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()  # Wallet is now created in serializer
            send_mail('Verify Owo Account', f'Click here: owo://verify/{user.id}', 'admin@owo.bank', [user.email])
            return Response(serializer.data, status=201)
        return Response(serializer.errors, status=400)

class WalletInfoView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        try:
            wallet = request.user.wallet
            return Response(WalletSerializer(wallet).data)
        except User.wallet.RelatedObjectDoesNotExist:
            # If no wallet exists, create one
            wallet = Wallet.objects.create(user=request.user)
            return Response(WalletSerializer(wallet).data)
from decimal import Decimal, InvalidOperation

class UpdatePinView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        old_pin = request.data.get('old_pin')
        new_pin = request.data.get('new_pin')
        confirm_pin = request.data.get('confirm_pin')
        
        if not new_pin or not confirm_pin:
            return Response({"error": "PIN fields are required"}, status=400)
        
        if len(new_pin) != 4 or not new_pin.isdigit():
            return Response({"error": "PIN must be 4 digits"}, status=400)
        
        if new_pin != confirm_pin:
            return Response({"error": "PINs do not match"}, status=400)
        
        # Check for simple patterns
        if new_pin in ['1234', '0000', '1111', '4321', '2580']:
            return Response({"error": "Please choose a stronger PIN"}, status=400)
        
        # If user already has a PIN, require old PIN
        if request.user.pin:
            if not old_pin:
                return Response({"error": "Current PIN is required"}, status=400)
            
            if not check_password(old_pin, request.user.pin):
                return Response({"error": "Current PIN is incorrect"}, status=401)
        
        # Update the PIN
        request.user.pin = make_password(new_pin)
        request.user.save()
        
        return Response({
            "message": "PIN updated successfully",
            "status": "success"
        })
      
class TransferView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        data = request.data
        amount = data.get('amount')
        recipient_account = data.get('account_number')
        bank_code = data.get('bank_code', '050')  # Default to Owo Bank if not provided
        description = data.get('description', '')
        pin = data.get('pin')
        recipient_name = data.get('recipient_name')

        # Only require bank_code if it's NOT an Owo Bank transfer
        required_fields = [amount, recipient_account, pin]
        if bank_code != '050':  # External bank
            required_fields.append(bank_code)
        
        if not all(required_fields):
            return Response({"error": "Missing required fields"}, status=400)

        try:
            amount_decimal = Decimal(amount)
            if amount_decimal <= 0:
                return Response({"error": "Amount must be positive"}, status=400)

            user = request.user
            if not check_password(pin, user.pin):
                return Response({"error": "Invalid PIN"}, status=400)

            sender_wallet = user.wallet
            if sender_wallet.balance < amount_decimal:
                return Response({"error": "Insufficient funds"}, status=400)

            recipient_wallet = None
            sender_name = f"{user.first_name} {user.last_name}".strip() or user.email.split('@')[0]

            if bank_code == '050':  # Internal Owo Bank transfer
                try:
                    recipient_wallet = Wallet.objects.get(account_number=recipient_account)
                    if recipient_wallet.user == user:
                        return Response({"error": "Cannot transfer to own account"}, status=400)

                    # Override recipient_name with actual user details
                    recipient_name = f"{recipient_wallet.user.first_name} {recipient_wallet.user.last_name}".strip() or recipient_wallet.user.email.split('@')[0]

                except Wallet.DoesNotExist:
                    return Response({"error": "Recipient account not found"}, status=400)
            else:
                # External transfer: Ensure recipient_name was provided (from verification)
                if not recipient_name:
                    return Response({"error": "Recipient name required for external transfers"}, status=400)

            # Perform transfer
            if recipient_wallet:
                recipient_wallet.balance += amount_decimal
                recipient_wallet.save()

                # Recipient's transaction (incoming)
                Transaction.objects.create(
                    wallet=recipient_wallet,
                    amount=amount_decimal,
                    type='TRANSFER',
                    description=description or f"Transfer from {sender_name}",
                    counterparty=sender_name,  # Set to sender's name
                    account_number=sender_wallet.account_number  # Sender's account number
                )

            # Sender's transaction (outgoing) - always created
            sender_transaction = Transaction.objects.create(
                wallet=sender_wallet,
                amount=-amount_decimal,
                type='TRANSFER',
                description=description or f"Transfer to {recipient_name}",
                counterparty=recipient_name,  # Set to recipient's name
                account_number=recipient_account  # Recipient's account number
            )

            sender_wallet.balance -= amount_decimal
            sender_wallet.save()

            # Optional: Update beneficiary if requested (existing logic preserved)
            add_beneficiary = data.get('add_beneficiary', False)
            if add_beneficiary:
                beneficiary_data = {
                    'account_number': recipient_account,
                    'bank_code': bank_code,
                    'name': recipient_name,
                    'nickname': data.get('nickname', ''),
                }
                beneficiary_serializer = CreateBeneficiarySerializer(
                    data=beneficiary_data,
                    context={'request': request}
                )
                if beneficiary_serializer.is_valid():
                    beneficiary = beneficiary_serializer.save()
                    beneficiary.transfer_count += 1
                    beneficiary.last_used = timezone.now()
                    beneficiary.save()

            return Response({
                "message": "Transfer successful",
                "new_balance": str(sender_wallet.balance),
                "transaction_id": sender_transaction.id
            })

        except InvalidOperation:
            return Response({"error": "Invalid amount"}, status=400)
        except Exception as e:
            return Response({"error": str(e)}, status=500)
             
class BillPaymentView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]

    @transaction.atomic
    def post(self, request):
        bill_type = request.data.get('type') # AIRTIME or DATA
        amount = request.data.get('amount')
        phone = request.data.get('phone_number')
        pin = request.data.get('pin')  # Get PIN from request
        
        if not pin:
            return Response({"error": "PIN is required"}, status=400)
        
        if len(pin) != 4 or not pin.isdigit():
            return Response({"error": "PIN must be 4 digits"}, status=400)
        
        # Verify user's PIN matches using password checking
        if not check_password(pin, request.user.pin):
            return Response({"error": "Invalid PIN"}, status=401)
        
        try:
            amount_decimal = Decimal(str(amount))
        except (InvalidOperation, TypeError, ValueError):
            return Response({"error": "Invalid amount format"}, status=400)
        
        sender_wallet = request.user.wallet

        if sender_wallet.balance < amount_decimal:
            return Response({"error": "Insufficient funds"}, status=400)
        
        # --- Simulating 3rd Party API Call ---
        time.sleep(1) 
        # --- End Simulation ---

        sender_wallet.balance -= amount_decimal
        sender_wallet.save()

        Transaction.objects.create(
            wallet=sender_wallet, 
            amount=-amount_decimal, 
            type=bill_type.upper(), 
            description=f"{bill_type.capitalize()} purchase for {phone}"
        )
        
        return Response({
            "message": f"{bill_type.capitalize()} purchase successful for ₦{amount}",
            "new_balance": str(sender_wallet.balance)
        })
       
class UserProfileView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        user = request.user
        try:
            wallet = user.wallet
            account_number = wallet.account_number
            balance = wallet.balance
        except User.wallet.RelatedObjectDoesNotExist:
            # Create wallet if it doesn't exist
            wallet = Wallet.objects.create(user=user)
            account_number = wallet.account_number
            balance = wallet.balance
        
        return Response({
            'email': user.email,
            'phone_number': user.phone_number,
            'first_name': user.first_name if hasattr(user, 'first_name') else '',
            'last_name': user.last_name if hasattr(user, 'last_name') else '',
            'full_name': f"{user.first_name} {user.last_name}".strip() if user.first_name and user.last_name else user.email.split('@')[0],
            'account_number': account_number,
            'balance': str(balance),
            'date_joined': user.date_joined.strftime("%B %Y"),
            'is_email_verified': user.is_email_verified,
            'is_active': user.is_active,
        })

class RecentTransactionsView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        try:
            wallet = request.user.wallet
            # Get transactions with optional limit parameter
            limit = request.GET.get('limit', 10)
            transactions = Transaction.objects.filter(wallet=wallet).order_by('-timestamp')[:int(limit)]
            
            serializer = TransactionSerializer(transactions, many=True)
            return Response(serializer.data)
        except User.wallet.RelatedObjectDoesNotExist:
            return Response([], status=200)
        
class VerifyAccountView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get endpoint for simple account verification (existing functionality)"""
        account_number = request.GET.get('account_number')
        
        if not account_number:
            return Response({"error": "Account number is required"}, status=400)
        
        try:
            wallet = Wallet.objects.get(account_number=account_number)
            # Don't return the user's own account
            if wallet.user == request.user:
                return Response({"error": "Cannot verify own account"}, status=400)
                
            return Response({
                "account_number": wallet.account_number,
                "user_email": wallet.user.email,
                "user_name": f"{wallet.user.first_name} {wallet.user.last_name}".strip() or wallet.user.email.split('@')[0],
                "verified": True,
                "message": "Account verified successfully"
            })
        except Wallet.DoesNotExist:
            # Account not found - return a fallback response instead of error
            return Response({
                "account_number": account_number,
                "user_name": "Account Not Found",
                "verified": False,
                "message": "Account not found in Owo Bank. You can still proceed with transfer.",
                "can_proceed": True  # Allow user to proceed anyway
            })
    
    def post(self, request):
        """POST endpoint for bank account verification with bank code (new functionality)"""
        serializer = VerifyAccountSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=400)
        
        account_number = serializer.validated_data['account_number']
        bank_code = serializer.validated_data['bank_code']
        
        # Skip verification for Owo Bank accounts (handled during transfer)
        if bank_code == '050':
            try:
                wallet = Wallet.objects.get(account_number=account_number)
                # Don't return own account
                if wallet.user == request.user:
                    return Response({
                        "verified": False,
                        "error": "Cannot verify own account",
                        "can_proceed": False
                    }, status=400)
                
                return Response({
                    "verified": True,
                    "user_name": f"{wallet.user.first_name} {wallet.user.last_name}".strip() or wallet.user.email.split('@')[0],
                    "user_email": wallet.user.email,
                    "message": "Owo Bank account verified"
                })
            except Wallet.DoesNotExist:
                # Account not found - return a fallback response
                return Response({
                    "verified": False,
                    "user_name": "Account Not Found",
                    "message": "Account not found in Owo Bank. Please verify the account number.",
                    "can_proceed": False  # Don't allow proceeding for Owo Bank
                })
        
        # For external banks, you would call a bank verification API
        # This is a mock implementation
        try:
            # Simulate API call delay
            import time
            time.sleep(1)
            
            # Mock verification for demo
            if account_number == "0123456789":
                verified_name = "Jane Smith"
            elif account_number == "9876543210":
                verified_name = "Mike Johnson"
            else:
                # For demo, generate a random name for valid-looking numbers
                if len(account_number) == 10 and account_number.isdigit():
                    names = ["John Doe", "Sarah Williams", "David Brown", "Lisa Johnson"]
                    import random
                    verified_name = random.choice(names)
                else:
                    # Invalid account number format
                    return Response({
                        "verified": False,
                        "error": "Invalid account number format",
                        "message": "Account number must be 10 digits",
                        "can_proceed": False
                    })
            
            return Response({
                "verified": True,
                "user_name": verified_name,
                "message": "Account verified successfully"
            })
            
        except Exception as e:
            # Any other error - return a fallback
            return Response({
                "verified": False,
                "error": str(e),
                "message": "Verification service unavailable. You can proceed with caution.",
                "can_proceed": True  # Allow user to proceed with caution
            }, status=400)
             
class BeneficiaryListView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get user's beneficiaries"""
        beneficiaries = Beneficiary.objects.filter(user=request.user).order_by('-last_used')
        
        # Format for frontend
        data = []
        for beneficiary in beneficiaries:
            # Calculate last transfer time
            now = timezone.now()
            last_used = beneficiary.last_used
            diff = now - last_used
            
            if diff.days == 0:
                if diff.seconds < 60:
                    last_transfer = "Just now"
                elif diff.seconds < 3600:
                    last_transfer = f"{diff.seconds // 60}m ago"
                else:
                    last_transfer = f"{diff.seconds // 3600}h ago"
            elif diff.days == 1:
                last_transfer = "Yesterday"
            elif diff.days < 7:
                last_transfer = f"{diff.days}d ago"
            else:
                last_transfer = last_used.strftime("%b %d")
            
            data.append({
                'id': beneficiary.id,
                'name': beneficiary.name,
                'accountNumber': beneficiary.account_number,
                'bank': beneficiary.bank_name,
                'isOwobank': beneficiary.bank_code == '050',
                'nickname': beneficiary.nickname,
                'lastTransfer': last_transfer,
                'transfersCount': beneficiary.transfer_count
            })
        
        return Response(data)

class CreateBeneficiaryView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    @transaction.atomic
    def post(self, request):
        """Create a new beneficiary"""
        serializer = CreateBeneficiarySerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            beneficiary = serializer.save()
            
            # Increment transfer count if this was created during a transfer
            increment_count = request.data.get('increment_count', False)
            if increment_count:
                beneficiary.transfer_count += 1
                beneficiary.save()
            
            return Response({
                "success": True,
                "message": "Beneficiary added successfully",
                "beneficiary": BeneficiarySerializer(beneficiary, context={'request': request}).data
            }, status=201)
        return Response(serializer.errors, status=400)

class DeleteBeneficiaryView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    @transaction.atomic
    def delete(self, request, beneficiary_id):
        """Delete a beneficiary"""
        try:
            beneficiary = Beneficiary.objects.get(id=beneficiary_id, user=request.user)
            beneficiary.delete()
            return Response({"success": True, "message": "Beneficiary removed successfully"})
        except Beneficiary.DoesNotExist:
            return Response({"error": "Beneficiary not found"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

class UpdateBeneficiaryView(views.APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    @transaction.atomic
    def put(self, request, beneficiary_id):
        """Update beneficiary nickname"""
        try:
            beneficiary = Beneficiary.objects.get(id=beneficiary_id, user=request.user)
            nickname = request.data.get('nickname', '').strip()
            
            if nickname:
                beneficiary.nickname = nickname
                beneficiary.save()
            
            return Response({
                "success": True,
                "message": "Beneficiary updated",
                "beneficiary": BeneficiarySerializer(beneficiary, context={'request': request}).data
            })
        except Beneficiary.DoesNotExist:
            return Response({"error": "Beneficiary not found"}, status=404)
        
class TestExportView(views.APIView):
    permission_classes = [permissions.AllowAny]  # Changed to AllowAny for testing
    
    def get(self, request, statement_id, format):
        """Test endpoint to verify URL patterns work"""
        print(f"=== TestExportView called ===")
        print(f"Statement ID: {statement_id}")
        print(f"Format: {format}")
        print(f"User: {request.user if request.user.is_authenticated else 'Anonymous'}")
        
        return Response({
            'status': 'success',
            'message': 'Test endpoint is working!',
            'statement_id': statement_id,
            'format': format,
            'user': request.user.email if request.user.is_authenticated else 'Anonymous',
            'timestamp': timezone.now().isoformat(),
            'test': 'This proves the URL pattern with parameters is working'
        })