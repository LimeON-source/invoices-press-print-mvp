# Copilot Instructions for Invoices Press Print MVP

## 1) Workspace snapshot (as of 2026-03-24)
- Python 3.9/3.11 oriented MVP with `src/invoice_app` package.
- Root files now include `config.json`, `invoice_counter.json`, `data/clients.csv` sample.
- Main app module: `src/invoice_app/main.py`; domain models in `src/invoice_app/models.py`.

## 2) What to do first
- Setup environment:
  - `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
- Run baseline:
  - `PYTHONPATH=src python3 -m src.invoice_app.main --month kovas --csv data/clients.csv --template "Context/template saskaita-faktura .docx"`
- Run tests:
  - `python3 -m pytest -q`

## 3) Big picture architecture
- Data model: `InvoiceModel` + `LineItem` + `AppConfig` in `models.py`.
- Config loader: `config.py` handles `config.json` and defaults.
- Data input: `data_source.py` supports CSV and optional Google Sheets (`gspread`).
- Template binding: `template_filler.py` replaces placeholders in DOCX and saves file.
- Business logic + file output: `invoice_service.py` handles numbering and folder structure.
- CLI: `main.py` routes arguments and orchestrates generation.

## 4) Critical workflows
- Run all clients: `--month <month> --csv data/clients.csv`.
- Options:
  - `--policy overwrite|skip|version` for existing files.
  - `--select <name> ...` to generate specific clients.
- Output folder: `Invoices/YYYY-MM`.
- Invoice file naming: `SS-YYYY-XXX_ClientName.pdf` (with DOCX fallback when PDF conversion unavailable).

## 5) Project-specific conventions
- Use full ISO month flow with Lithuanian headers and normalize keys.
- For data rows, required fields:
  - Client name + address
  - Rate >0
  - integer sessions >=0 for selected month.
- Error handling: invalid rows are skipped and logged by stats.
- Number-to-words uses `num2words(..., lang='lt')` (fallback to numeric literal if dependency missing).

## 6) Integration points
- Google Sheets (optional): `load_clients_from_gsheet(sheet_id, credentials_path)` in `data_source.py`.
- DOCX template: `Context/template saskaita-faktura .docx` with placeholders `<number>`, `<yyyy-mm-dd>`, `<suma zodziais>`, optionally `<client_name>`, `<client_address>`, `<total>`.
- Local file state: `invoice_counter.json` + `Logs` can be added later.

## 7) CI / GitHub Actions
- Add `.github/workflows/ci.yml` to run tests and lints.
- Use existing local commands and ensure `PYTHONPATH=src` is set.

## 8) Feedback request
- Confirm if there is a preferred Google Sheets repro key format.
- Confirm unit test style (pytest fixtures vs plain functions).
- Confirm if you want DOCX-only or mandatory PDF output in this environment.

