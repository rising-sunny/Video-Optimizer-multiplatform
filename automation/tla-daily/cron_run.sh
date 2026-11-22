#!/bin/bash
# The Lost Atlas: todos los dias a las 17:00 UTC, con reintentos a las 18:00 y 19:00 (idempotente).
cd /home/videoagent/tla-daily || exit 1
exec nice -n 10 /home/videoagent/Video-Optimizer-multiplatform/.venv/bin/python run_day.py >> logs/cron.out 2>&1
