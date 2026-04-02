"""
URL configuration for fingerprint_project project.
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include('fingerprint.urls')),
    # Frontend SPA — served at root
    path('', TemplateView.as_view(template_name='fingerprint/index.html'), name='frontend'),
]
