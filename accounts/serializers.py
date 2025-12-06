from rest_framework import serializers
from .models import User, Wallet, Transaction, Statement
from django.contrib.auth.hashers import make_password
from django.utils import timezone
import re

from .models import Beneficiary 

class UserSerializer(serializers.ModelSerializer):
    password2 = serializers.CharField(write_only=True, required=True)
    pin = serializers.CharField(write_only=True, required=True, min_length=4, max_length=4)
    pin2 = serializers.CharField(write_only=True, required=True, min_length=4, max_length=4)
    
    class Meta:
        model = User
        fields = [
            'id', 'email', 'phone_number', 'first_name', 'last_name', 
            'nin', 'date_of_birth', 'address', 'password', 'password2',
            'pin', 'pin2', 'date_joined'
        ]
        extra_kwargs = {
            'password': {'write_only': True},
            'first_name': {'required': True},
            'last_name': {'required': True},
            'nin': {'required': True},
            'date_of_birth': {'required': True},
        }
    
    def validate(self, data):
        # Password validation
        if data['password'] != data['password2']:
            raise serializers.ValidationError({"password": "Passwords do not match"})
        
        if len(data['password']) < 8:
            raise serializers.ValidationError({"password": "Password must be at least 8 characters"})
        
        # PIN validation
        if data['pin'] != data['pin2']:
            raise serializers.ValidationError({"pin": "PINs do not match"})
        
        if not data['pin'].isdigit():
            raise serializers.ValidationError({"pin": "PIN must contain only numbers"})
        
        if len(data['pin']) != 4:
            raise serializers.ValidationError({"pin": "PIN must be exactly 4 digits"})
        
        # NIN validation
        nin = data.get('nin', '')
        if not re.match(r'^\d{11}$', nin):
            raise serializers.ValidationError({"nin": "NIN must be 11 digits"})
        
        # Phone validation for Nigeria
        phone = data.get('phone_number', '')
        if not re.match(r'^0[7-9][0-1]\d{8}$', phone):
            raise serializers.ValidationError({"phone_number": "Please enter a valid Nigerian phone number"})
        
        # Age validation (must be at least 18)
        date_of_birth = data.get('date_of_birth')
        if date_of_birth:
            age = (timezone.now().date() - date_of_birth).days / 365
            if age < 15:
                raise serializers.ValidationError({"date_of_birth": "You must be at least 18 years old"})
        
        return data
    
    def create(self, validated_data):
        # Remove confirmation fields
        validated_data.pop('password2')
        validated_data.pop('pin2')
        
        # Extract PIN and remove from validated_data
        pin = validated_data.pop('pin')
        
        # Create user
        user = User.objects.create_user(
            email=validated_data['email'],
            phone_number=validated_data['phone_number'],
            password=validated_data['password'],
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            nin=validated_data.get('nin', ''),
            date_of_birth=validated_data.get('date_of_birth'),
            address=validated_data.get('address', ''),
        )
        
        # Create wallet for the new user
        Wallet.objects.create(user=user)
        
        return user

class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = ['account_number', 'balance']

# accounts/serializers.py

class TransactionSerializer(serializers.ModelSerializer):
    formatted_time = serializers.SerializerMethodField()
    formatted_amount = serializers.SerializerMethodField()  # ← Remove source, decimal_places, etc.

    # These two fields will now appear correctly in API responses
    counterparty = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    account_number = serializers.CharField(allow_blank=True, allow_null=True, required=False)

    class Meta:
        model = Transaction
        fields = [
            'id',
            'amount',
            'type',
            'description',
            'timestamp',
            'counterparty',
            'account_number',
            'formatted_time',
            'formatted_amount',
        ]

    def get_formatted_time(self, obj):
        now = timezone.now()
        diff = now - obj.timestamp

        if diff.days == 0:
            if diff.seconds < 60:
                return "Just now"
            elif diff.seconds < 3600:
                return f"{diff.seconds // 60}m ago"
            else:
                return f"{diff.seconds // 3600}h ago"
        elif diff.days == 1:
            return "Yesterday"
        elif diff.days < 7:
            return f"{diff.days}d ago"
        else:
            return obj.timestamp.strftime("%b %d")

    def get_formatted_amount(self, obj):
        amount = abs(obj.amount)
        sign = "+" if obj.amount > 0 else "-"
        return f"{sign}₦{amount:,.2f}"
    
# In serializers.py, add these serializers
class StatementSerializer(serializers.ModelSerializer):
    period_label = serializers.SerializerMethodField()
    
    class Meta:
        model = Statement
        fields = [
            'statement_id', 'period_start', 'period_end', 'period_label',
            'transaction_type', 'total_transactions', 'total_income',
            'total_expense', 'net_change', 'generated_at'
        ]
    
    def get_period_label(self, obj):
        from datetime import datetime
        start = obj.period_start
        end = obj.period_end
        
        if start == end:
            return f"Daily - {start.strftime('%b %d, %Y')}"
        elif (end - start).days <= 7:
            return f"Weekly - {start.strftime('%b %d')} to {end.strftime('%b %d, %Y')}"
        elif start.month == end.month:
            return f"Monthly - {start.strftime('%B %Y')}"
        elif start.year == end.year:
            return f"Quarterly - {start.strftime('%b')} to {end.strftime('%b %Y')}"
        else:
            return f"Yearly - {start.year} to {end.year}"


class StatementRequestSerializer(serializers.Serializer):
    period = serializers.CharField(required=True)
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    transaction_type = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    
    def validate(self, data):
        period = data.get('period')
        
        if period == 'custom':
            if not data.get('start_date') or not data.get('end_date'):
                raise serializers.ValidationError("Start and end dates are required for custom period")
            
            start_date = data['start_date']
            end_date = data['end_date']
            
            if start_date > end_date:
                raise serializers.ValidationError("Start date cannot be after end date")
            
            # Limit to 90 days for custom periods
            if (end_date - start_date).days > 90:
                raise serializers.ValidationError("Custom period cannot exceed 90 days")
        
        return data


class StatementExportSerializer(serializers.Serializer):
    statement_id = serializers.CharField(required=True)
    # ✅ FIX: Restrict choices to 'txt'
    format = serializers.ChoiceField(choices=['txt'])

# Add these serializers to serializers.py

class BankSerializer(serializers.Serializer):
    code = serializers.CharField()
    name = serializers.CharField()

class BeneficiarySerializer(serializers.ModelSerializer):
    bank_name = serializers.CharField(read_only=True)
    is_owobank = serializers.SerializerMethodField()
    
    class Meta:
        model = Beneficiary
        fields = [
            'id', 'name', 'account_number', 'bank_code', 'bank_name',
            'nickname', 'created_at', 'last_used', 'transfer_count', 'is_owobank'
        ]
        read_only_fields = ['created_at', 'last_used', 'transfer_count', 'is_owobank']
    
    def get_is_owobank(self, obj):
        return obj.bank_code == '050'
    
    def validate(self, data):
        # Check for duplicates
        user = self.context['request'].user
        if Beneficiary.objects.filter(
            user=user, 
            account_number=data['account_number'],
            bank_code=data['bank_code']
        ).exists():
            raise serializers.ValidationError("Beneficiary already exists")
        
        return data

class CreateBeneficiarySerializer(serializers.ModelSerializer):
    class Meta:
        model = Beneficiary
        fields = ['name', 'account_number', 'bank_code', 'bank_name', 'nickname']
    
    def create(self, validated_data):
        validated_data['user'] = self.context['request'].user
        return super().create(validated_data)

class VerifyAccountSerializer(serializers.Serializer):
    account_number = serializers.CharField(required=True, max_length=20)
    bank_code = serializers.CharField(required=True, max_length=10)