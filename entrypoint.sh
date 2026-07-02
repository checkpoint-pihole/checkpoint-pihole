#!/bin/bash
set -e

echo "=== Checkpoint Pi-hole Starting ==="

# Run migrations
echo "[1/4] Running database migrations..."
uv run python manage.py migrate --noinput

# Auto-discover Pi-hole instances from environment variables
echo "[2/4] Discovering Pi-hole instances..."
uv run python manage.py discover_instances

# File tracking the current scheduler PID. The monitor restarts the scheduler
# in its own subshell, so the parent shell's SCHEDULER_PID can go stale; cleanup()
# reads this file to always signal the live process.
SCHEDULER_PID_FILE="/tmp/checkpoint-scheduler.pid"

# Function to start scheduler
start_scheduler() {
    uv run python manage.py runapscheduler &
    SCHEDULER_PID=$!
    echo "$SCHEDULER_PID" > "$SCHEDULER_PID_FILE"
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
                echo "ERROR: Scheduler exceeded $MAX_RESTARTS restarts, giving up"
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

# Start monitor in background
monitor_scheduler &
MONITOR_PID=$!

# Trap signals to clean up
cleanup() {
    echo "Shutting down..."
    kill $MONITOR_PID 2>/dev/null || true
    # Read the live scheduler PID from the file — the parent's SCHEDULER_PID may
    # be stale if the monitor restarted the scheduler in its own subshell.
    local scheduler_pid
    scheduler_pid=$(cat "$SCHEDULER_PID_FILE" 2>/dev/null || true)
    kill "$scheduler_pid" 2>/dev/null || true
    kill $GUNICORN_PID 2>/dev/null || true
    wait "$scheduler_pid" 2>/dev/null || true
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

# Wait for gunicorn — allows bash to receive signals
wait $GUNICORN_PID
