#!/bin/bash

DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$DIR/watcher.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    kill "$(cat "$PID_FILE")"
    rm "$PID_FILE"
    echo "Watcher stopped."
else
    echo "Watcher is not running."
    rm -f "$PID_FILE"
fi
