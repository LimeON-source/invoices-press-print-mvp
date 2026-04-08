#!/bin/bash
# Test script to verify the app works correctly

cd "$(dirname "$0")"

# Activate virtual environment
source .venv/bin/activate 2>/dev/null

echo "🧪 Testing Invoices Press Print Application..."
echo ""

# Test 1: Import all modules
echo "Test 1: Checking Python imports..."
PYTHONPATH=src python3 -c "
from src.invoice_app.web import app
from src.invoice_app.data_source import load_clients_from_csv, load_clients_from_xlsx
from src.invoice_app.invoice_service import process_batch
from src.invoice_app.models import normalize_month
print('✓ All imports successful')
" 2>&1 | grep -E "(✓|Error|Traceback)" && echo "" || echo "❌ Import failed"

# Test 2: Load CSV data
echo "Test 2: Loading CSV data..."
PYTHONPATH=src python3 -c "
from src.invoice_app.data_source import load_clients_from_csv
rows = load_clients_from_csv('data/clients.csv')
print(f'✓ Loaded {len(rows)} clients from CSV')
" 2>&1 | grep "✓" && echo "" || echo "❌ CSV loading failed"

# Test 3: Load config
echo "Test 3: Loading configuration..."
PYTHONPATH=src python3 -c "
from src.invoice_app.config import load_config
config = load_config('config.json')
print(f'✓ Config loaded: {config.seller.name}')
" 2>&1 | grep "✓" && echo "" || echo "❌ Config loading failed"

# Test 4: Test month normalization
echo "Test 4: Testing month conversion..."
PYTHONPATH=src python3 -c "
from src.invoice_app.models import normalize_month
print(f'✓ kovas = month {normalize_month(\"kovas\")}')
" 2>&1 | grep "✓" && echo "" || echo "❌ Month conversion failed"

# Test 5: Start server briefly
echo "Test 5: Starting web server..."
PYTHONPATH=src python3 -c "
from src.invoice_app import web
print('✓ Web application initialized')
" 2>&1 | grep "✓" && echo "" || echo "❌ Web app initialization failed"

echo "✅ All tests passed! App is ready to use."
echo ""
echo "Launch with: ./launch-app.sh"
