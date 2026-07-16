from celery import Celery
from app.config import settings

celery = Celery("richstudio", broker=settings.redis_url, backend=settings.redis_url, include=["app.tasks"])
celery.conf.update(
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_time_limit=2400,
    task_soft_time_limit=2300,
    # The worker runs beat inline (-B), so no separate scheduler container is needed.
    beat_schedule={
        "watchdog-stuck-projects": {
            "task": "app.tasks.watchdog_stuck_projects",
            "schedule": 300.0,
        },
    },
)
