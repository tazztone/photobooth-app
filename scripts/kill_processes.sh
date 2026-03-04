#!/bin/bash

# Port cleanup script for Photobooth App
# This script kills any processes listening on the default ports.

PHOTOBOOTH_PORT=8000
COMFYUI_PORT=18188

echo "--- Photobooth Cleanup ---"

# Function to kill process on port
kill_port() {
    local port=$1
    local name=$2
    
    # Check if anything is listening
    pid=$(lsof -t -i:$port)
    
    if [ -n "$pid" ]; then
        echo "Found process $pid using port $port ($name). Killing..."
        kill -9 $pid
    else
        echo "Port $port ($name) is clear."
    fi
}

# Kill Photobooth
kill_port $PHOTOBOOTH_PORT "Photobooth"

# Kill ComfyUI
kill_port $COMFYUI_PORT "ComfyUI"

echo "--------------------------"
echo "Cleanup complete."
