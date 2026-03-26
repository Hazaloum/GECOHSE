#!/bin/bash

DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$DIR/watcher.log"
PID_FILE="$DIR/watcher.pid"

# Check if already running
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Watcher is already running (PID $(cat "$PID_FILE"))"
    exit 0
fi

echo "Starting GECO HSE Watcher..."
cd "$DIR"
nohup /opt/anaconda3/bin/python3 watcher.py >> "$LOG" 2>&1 &
echo $! > "$PID_FILE"
echo "Watcher started (PID $(cat "$PID_FILE"))"
echo "Logs: $LOG"
echo "To stop: bash stop_watcher.sh"
