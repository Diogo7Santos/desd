"""
WSGI config for the Django project.

It exposes the WSGI callable as a module-level variable named ``application``.

This file is used by production servers (e.g. Gunicorn, uWSGI) to serve your Django app.
"""

import os
from django.core.wsgi import get_wsgi_application

# Set the default Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Create the WSGI application object
application = get_wsgi_application()
