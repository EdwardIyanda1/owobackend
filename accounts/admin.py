from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User, Wallet, Transaction
from django.utils.html import format_html
from .models import Statement

# Custom User Admin
class CustomUserAdmin(UserAdmin):
    model = User
    list_display = ('email', 'phone_number', 'first_name', 'last_name', 'is_staff', 'is_active', 'date_joined')
    list_filter = ('is_staff', 'is_active', 'is_email_verified', 'date_joined')
    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'phone_number')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Verification', {'fields': ('is_email_verified',)}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )
    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'phone_number', 'password1', 'password2', 'is_staff', 'is_active')}
        ),
    )
    search_fields = ('email', 'phone_number', 'first_name', 'last_name')
    ordering = ('-date_joined',)
    readonly_fields = ('date_joined', 'last_login')

# Custom Wallet Admin
class WalletAdmin(admin.ModelAdmin):
    list_display = ('account_number', 'user_email', 'balance_display', 'user_phone', 'created_at')
    list_filter = ('user__is_active',)
    search_fields = ('account_number', 'user__email', 'user__phone_number')
    readonly_fields = ('account_number', 'created_at', 'updated_at')
    ordering = ('-user__date_joined',)
    
    def user_email(self, obj):
        return obj.user.email

    def user_phone(self, obj):
        return obj.user.phone_number

    def balance_display(self, obj):
        amount = float(obj.balance)
        return format_html("<strong>₦{}</strong>", f"{amount:,.2f}")

    def created_at(self, obj):
        return obj.user.date_joined.strftime('%Y-%m-%d %H:%M:%S')

    def updated_at(self, obj):
        return ""

# Custom Transaction Admin
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'user_info', 'amount_display', 'type', 'description_short', 'timestamp')
    list_filter = ('type', 'timestamp', 'wallet__user__email')
    search_fields = ('wallet__user__email', 'wallet__account_number', 'description', 'type')
    readonly_fields = ('timestamp',)
    ordering = ('-timestamp',)
    date_hierarchy = 'timestamp'
    
    def transaction_id(self, obj):
        return f"TX{obj.id:06d}"
    transaction_id.short_description = 'ID'
    
    def user_info(self, obj):
        return f"{obj.wallet.user.email} ({obj.wallet.account_number})"
    user_info.short_description = 'User (Account)'
    
    def amount_display(self, obj):
        color = 'green' if obj.amount > 0 else 'red'
        amount_text = f"+₦{abs(float(obj.amount)):.2f}" if obj.amount > 0 else f"-₦{abs(float(obj.amount)):.2f}"
        # FIXED: Use str.format() instead of f-string in format_html
        return format_html('<strong style="color: {};">{}</strong>'.format(color, amount_text))
    amount_display.short_description = 'Amount'
    
    def description_short(self, obj):
        if len(obj.description) > 50:
            return f"{obj.description[:50]}..."
        return obj.description
    description_short.short_description = 'Description'

class StatementAdmin(admin.ModelAdmin):
    list_display = ('statement_id', 'user_email', 'period_range', 'total_transactions', 'total_income', 'total_expense', 'generated_at')
    list_filter = ('generated_at', 'period_start', 'period_end')
    search_fields = ('statement_id', 'user__email', 'user__phone_number')
    readonly_fields = ('statement_id', 'generated_at', 'total_transactions', 'total_income', 'total_expense', 'net_change')
    ordering = ('-generated_at',)
    
    def user_email(self, obj):
        return obj.user.email
    user_email.short_description = 'User Email'
    
    def period_range(self, obj):
        return f"{obj.period_start} to {obj.period_end}"
    period_range.short_description = 'Period'


# Register your models
admin.site.register(User, CustomUserAdmin)
admin.site.register(Wallet, WalletAdmin)
admin.site.register(Transaction, TransactionAdmin)
admin.site.register(Statement, StatementAdmin)

# Customize admin site
admin.site.site_header = "Owo Bank Administration"
admin.site.site_title = "Owo Bank Admin"
admin.site.index_title = "Welcome to Owo Bank Admin Panel"