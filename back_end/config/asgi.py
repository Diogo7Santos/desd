"""
ASGI config for the Django project.

It exposes the ASGI callable as a module-level variable named ``application``.

ASGI is used for asynchronous servers and supports features such as WebSockets
and long-lived connections. It is commonly used with Daphne, Uvicorn, or
ASGI-compatible deployments.
"""

import os
from django.core.asgi import get_asgi_application

# Set the default Django settings module
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Create the ASGI application object
application = get_asgi_application()
