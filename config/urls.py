from django.contrib import admin
from django.urls import path, include
from django.http import HttpResponse


def health_check(request):
    return HttpResponse("OK")

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/auth/', include('accounts.urls')),
    path('healthz/', health_check),  # <--- Add this line for Render
]