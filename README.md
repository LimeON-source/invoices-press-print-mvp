# Invoices Press Print MVP

Minimal MVP app for invoice generation and PDF output from tabular data (Google Sheets / CSV).

## Getting started (Python)

1. Create virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. Ensure config and sample data exist:
   - `config.json` (seller, VAT, invoice series, output root)
   - `invoice_counter.json` (year/counter)
   - `data/clients.csv` with month columns (Sausis, Vasaris, ..., Gruodis)
3. Run app for month (example March / kovas):
   ```bash
   python3 -m src.invoice_app.main --month kovas --csv data/clients.csv --template "Context/template saskaita-faktura .docx"
   ```
4. Output location:
   - `Invoices/YYYY-MM/SS-YYYY-XXX_ClientName.pdf`
   - if PDF conversion unavailable, DOCX output is preserved with `not_converted_saved_docx` message.
5. Run tests:
   ```bash
   pytest -q
   ```

## Web UI

1. Install dependencies including FastAPI:
   ```bash
   pip install -r requirements.txt
   ```
2. Start server:
   ```bash
   PYTHONPATH=src uvicorn src.invoice_app.web:app --reload --host 0.0.0.0 --port 8000
   ```
3. Open browser:
   - http://localhost:8000
