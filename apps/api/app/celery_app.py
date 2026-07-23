from celery import Celery
from app.config import settings

celery = Celery("richstudio", broker=settings.redis_url, backend=settings.redis_url, include=["app.tasks"])
celery.conf.update(
    task_track_started=True,
    task_acks_late=True,
    # If a worker process disappears after accepting a generation, Redis must
    # redeliver it. process_project safely reclaims that delivery under a DB
    # row lock and records the partial run before restarting.
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=2400,
    task_soft_time_limit=2300,
    task_routes={
        "app.tasks.watchdog_stuck_projects": {"queue": "maintenance"},
        "app.tasks.dispatch_pending_projects": {"queue": "maintenance"},
    },
    # A dedicated maintenance worker runs beat, so long generations cannot
    # delay outbox recovery or watchdog checks.
    beat_schedule={
        "watchdog-stuck-projects": {
            "task": "app.tasks.watchdog_stuck_projects",
            "schedule": 300.0,
            "options": {"queue": "maintenance"},
        },
        "dispatch-pending-projects": {
            "task": "app.tasks.dispatch_pending_projects",
            "schedule": 60.0,
            "options": {"queue": "maintenance"},
        },
    },
)
