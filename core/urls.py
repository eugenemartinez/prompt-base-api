"""
URL configuration for core project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings # Import settings
from api import views as api_views # Import the views from your api app

# Define base URL patterns (always active)
urlpatterns = [
    path('api/', include('api.urls')), # Your API urls
]

# Conditionally add the admin URL pattern if DEBUG is True
if settings.DEBUG:
    urlpatterns += [
        path('admin/', admin.site.urls),
    ]

urlpatterns += [
    # --- ADD THE NEW ROOT URL PATTERN ---
    path('', api_views.project_root_view, name='project-root'),
    # --- END ADDITION ---
]

# Make sure no other code follows this urlpatterns definition
