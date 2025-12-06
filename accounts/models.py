from django.db import models
from django.contrib.auth.models import AbstractUser, BaseUserManager
import random

    
class UserManager(BaseUserManager):
    def create_user(self, email, phone_number, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email field must be set')
        if not phone_number:
            raise ValueError('The Phone Number field must be set')
        
        email = self.normalize_email(email)
        user = self.model(email=email, phone_number=phone_number, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        
        # REMOVE THIS LINE - Wallet is created in RegisterView
        # Wallet.objects.create(user=user)
        
        return user
    
    def create_superuser(self, email, phone_number, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        user = self.create_user(email, phone_number, password, **extra_fields)
        return user
    
class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=15, unique=True)
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    nin = models.CharField(max_length=11, unique=True, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    address = models.TextField(blank=True)
    is_nin_verified = models.BooleanField(default=False)
    is_email_verified = models.BooleanField(default=False)
    pin = models.CharField(max_length=128, blank=True, null=True)  # 4-digit PIN
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['phone_number']
    
    # Add these lines to fix the issue
    groups = models.ManyToManyField(
        'auth.Group',
        related_name='custom_user_groups',  # Custom related_name
        blank=True,
        help_text='The groups this user belongs to.',
        verbose_name='groups'
    )
    
    user_permissions = models.ManyToManyField(
        'auth.Permission',
        related_name='custom_user_permissions',  # Custom related_name
        blank=True,
        help_text='Specific permissions for this user.',
        verbose_name='user permissions'
    )
    
    objects = UserManager()

class Beneficiary(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='beneficiaries')
    name = models.CharField(max_length=255)
    account_number = models.CharField(max_length=20)
    bank_code = models.CharField(max_length=10)
    bank_name = models.CharField(max_length=255)
    nickname = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_used = models.DateTimeField(auto_now=True)
    transfer_count = models.IntegerField(default=0)
    
    class Meta:
        unique_together = ['user', 'account_number', 'bank_code']
        verbose_name_plural = 'Beneficiaries'
    
    def __str__(self):
        return f"{self.name} ({self.account_number}) - {self.user.email}"
    
class Statement(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='statements')
    period_start = models.DateField()
    period_end = models.DateField()
    transaction_type = models.CharField(max_length=20, blank=True, null=True)  # Filter by type
    total_transactions = models.IntegerField(default=0)
    total_income = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    total_expense = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    net_change = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    generated_at = models.DateTimeField(auto_now_add=True)
    statement_id = models.CharField(max_length=50, unique=True, editable=False)
    file_path = models.CharField(max_length=500, blank=True, null=True)
    
    def save(self, *args, **kwargs):
        if not self.statement_id:
            import uuid
            self.statement_id = f"STM-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Statement {self.statement_id} - {self.user.email}"
    
class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='wallet')
    # 10 digit account number
    account_number = models.CharField(max_length=10, unique=True, editable=False)
    # ALWAYS use DecimalField for money
    balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    pin = models.CharField(max_length=4, null=True, blank=True)

    def save(self, *args, **kwargs):
        if not self.account_number:
            if self.user.phone_number and len(self.user.phone_number) >= 10:
                 self.account_number = self.user.phone_number[-10:]
            else:
                 self.account_number = str(random.randint(1000000000, 9999999999))
        super().save(*args, **kwargs)

class Transaction(models.Model):
    wallet = models.ForeignKey(Wallet, on_delete=models.CASCADE, related_name='transactions')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # TRANSFER, AIRTIME, DATA, DEPOSIT
    type = models.CharField(max_length=20) 
    description = models.CharField(max_length=255)
    timestamp = models.DateTimeField(auto_now_add=True)

    counterparty = models.CharField(max_length=255, blank=True, null=True)
    account_number = models.CharField(max_length=20, blank=True, null=True)