"""Celery worker configuration."""
from celery import Celery


def make_celery():
    """Create and configure a Celery instance.
    
    Returns:
        Celery instance configured with Redis broker and backend.
    """
    celery = Celery(__name__)
    celery.conf.update(
        broker_url='redis://localhost:6379/1',
        result_backend='redis://localhost:6379/1',
        include=['app.tasks.whatsapp_tasks'],
        task_default_queue='whatsapp',
        task_acks_late=True,
        worker_prefetch_multiplier=1,
    )
    return celery
