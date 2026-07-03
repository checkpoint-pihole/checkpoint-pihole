#!/bin/bash
set -e

echo "=== Checkpoint Pi-hole Starting ==="

# Run migrations
echo "[1/4] Running database migrations..."
uv run python manage.py migrate --noinput

# Auto-discover Pi-hole instances from environment variables
echo "[2/4] Discovering Pi-hole instances..."
uv run python manage.py discover_instances

# Function to start scheduler
start_scheduler() {
    uv run python manage.py runapscheduler &
    SCHEDULER_PID=$!
    echo "Scheduler started with PID: $SCHEDULER_PID"
}

# Start scheduler
echo "[3/4] Starting backup scheduler..."
start_scheduler

# Monitor and restart scheduler if it dies (with exponential backoff)
MAX_RESTARTS=10
monitor_scheduler() {
    local restart_count=0
    local backoff=30
    while true; do
        sleep "$backoff"
        if ! kill -0 $SCHEDULER_PID 2>/dev/null; then
            restart_count=$((restart_count + 1))
            if [ "$restart_count" -gt "$MAX_RESTARTS" ]; then
                echo "ERROR: Scheduler exceeded $MAX_RESTARTS restarts, giving up — terminating container so 'restart: unless-stopped' can recover it"
                # The scheduler is unrecoverable. This monitor runs in a
                # backgrounded subshell, so a bare `return 1` cannot stop PID 1.
                # Kill gunicorn (PID 1's foreground child) with SIGKILL so the
                # main process's `wait` returns nonzero and the container exits;
                # the restart policy then restarts the whole container.
                kill -KILL "$GUNICORN_PID" 2>/dev/null || true
                return 1
            fi
            echo "WARNING: Scheduler process died (restart $restart_count/$MAX_RESTARTS), restarting in ${backoff}s..."
            start_scheduler
            # Exponential backoff: 30, 60, 120, 240, ... capped at 300s
            backoff=$((backoff * 2))
            if [ "$backoff" -gt 300 ]; then
                backoff=300
            fi
        else
            # Scheduler is healthy — reset backoff and counter
            restart_count=0
            backoff=30
        fi
    done
}

# Trap signals to clean up
cleanup() {
    echo "Shutting down..."
    kill $MONITOR_PID 2>/dev/null || true
    kill $SCHEDULER_PID 2>/dev/null || true
    kill $GUNICORN_PID 2>/dev/null || true
    wait $SCHEDULER_PID 2>/dev/null || true
    wait $GUNICORN_PID 2>/dev/null || true
    exit 0
}
trap cleanup SIGTERM SIGINT

# Start Gunicorn (background, so trap can fire)
echo "[4/4] Starting web server..."
uv run gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 2 \
    --access-logfile - \
    --error-logfile - &
GUNICORN_PID=$!

# Start monitor in background — after GUNICORN_PID is set so the monitor can
# terminate the container (by killing gunicorn) if the scheduler is unrecoverable.
monitor_scheduler &
MONITOR_PID=$!

# Wait for gunicorn — allows bash to receive signals
wait $GUNICORN_PID
