"""Celery application configuration."""

import os

from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "shorts_saas",
    broker=redis_url,
    backend=redis_url,
    include=["workers.tasks"],
)

celery_app.conf.update(
    # Memory management for 4GB VPS
    worker_concurrency=1,
    worker_max_memory_per_child=1_500_000,  # 1.5GB in KB
    worker_max_tasks_per_child=5,
    worker_prefetch_multiplier=1,
    # Reliability
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Time limits
    task_time_limit=600,  # 10 min hard limit
    task_soft_time_limit=540,  # 9 min soft limit
    # Serialization
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # Timezone
    timezone="UTC",
    enable_utc=True,
)
