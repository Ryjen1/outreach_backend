import os
from celery import Celery

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')

# Initialize Celery app
app = Celery('outreach_celery')

# Load settings from Django
app.config_from_object('django.conf:settings', namespace='CELERY')

# In eager mode, override the broker to avoid Redis connection attempts
from django.conf import settings as _settings  # noqa: E402
if getattr(_settings, 'CELERY_TASK_ALWAYS_EAGER', False):
    app.conf.broker_url = 'memory://'
    app.conf.result_backend = 'cache+memory://'
else:
    # Force the broker URL from settings — config_from_object with namespace
    # can fail to pick up CELERY_BROKER_URL in the runserver child process.
    app.conf.broker_url = _settings.CELERY_BROKER_URL
    app.conf.result_backend = _settings.CELERY_RESULT_BACKEND

# Automatically discover tasks from all installed apps
app.autodiscover_tasks()
