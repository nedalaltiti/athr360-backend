#!/bin/bash

# ATHAR360 AI Compliance Assistant Startup Script
# This script starts the unified compliance assistant server

echo "🚀 Starting ATHAR360 AI Compliance Assistant..."
echo "================================================"

# Set environment variables
export PYTHONPATH=src
export APP_INSTANCE=compliance
export SKIP_DB_INIT=true

# Start the server
echo "Starting server on http://localhost:8000"
echo "Press Ctrl+C to stop the server"
echo ""

python -m uvicorn athr360.api.app:app --host 0.0.0.0 --port 8000 --reload 