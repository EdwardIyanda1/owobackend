from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse


def health_check(request):
    return HttpResponse("OK")

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    
    # 1. Handle with trailing slash (already done)
    path('healthz/', health_check), 
    
    # 2. Add the path without a trailing slash to be safe
    path('healthz', health_check),
]