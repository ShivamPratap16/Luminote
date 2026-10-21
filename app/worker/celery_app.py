from celery import Celery
from app.core.config import settings

celery_app = Celery(
    "worker",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    include=["app.worker.tasks"]
)

celery_app.conf.task_routes = {"app.worker.tasks.*": "main-queue"}

@celery_app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    from app.worker.tasks import cleanup_stale_temp_dirs
    # Run every 10 minutes (600s)
    sender.add_periodic_task(600.0, cleanup_stale_temp_dirs.s(), name='cleanup-stale-temp')

from celery.signals import worker_ready

@worker_ready.connect
def on_worker_startup(**kwargs):
    from app.worker.tasks import cleanup_stale_temp_dirs
    cleanup_stale_temp_dirs.delay()
