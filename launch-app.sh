#!/bin/bash
# Invoices Press Print - Application Launcher

cd "$(dirname "$0")"

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
else
    echo "Error: Virtual environment not found at .venv/bin/activate"
    echo "Please run: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi

# Open browser
open "http://localhost:8000" &

# Start application
echo "Starting Invoices Press Print..."
echo "Application will be available at http://localhost:8000"
echo "Press Ctrl+C to stop the server"

PYTHONPATH=src uvicorn src.invoice_app.web:app --host 127.0.0.1 --port 8000
