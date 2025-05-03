"""
WSGI config for core project.

It exposes the WSGI callable as a module-level variable named ``app``.

For more information on this file, see
https://docs.djangoproject.com/en/5.2/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

# Get the WSGI application object
_wsgi_app = get_wsgi_application()

# Define 'app' for Vercel
app = _wsgi_app

# Define 'application' for Django's runserver and other traditional WSGI servers
application = _wsgi_app
