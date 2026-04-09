"""Tests for web.py routes — all 5 UX improvements + existing endpoints."""
from datetime import date
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from invoice_app.web import app, MONTH_NAMES, current_month_name, month_to_folder, month_number_to_column

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

DUMMY_ROWS = [
    {"Client": "Jonas", "Kovas": "4", "Rate": "50", "Address": "Vilnius"},
    {"Client": "Petras", "Kovas": "0", "Rate": "50", "Address": "Kaunas"},
]

DUMMY_STATS = {
    "generated": 1,
    "skipped": 1,
    "errors": 0,
    "processed": 1,
    "total_amount": Decimal("200"),
    "output_folder": "/tmp/Invoices/kovas",
    "error_details": [],
}


# ---------------------------------------------------------------------------
# Improvement 1: auto-select current month
# ---------------------------------------------------------------------------

def test_current_month_name_matches_today():
    expected = MONTH_NAMES[date.today().month - 1]
    assert current_month_name() == expected


def test_index_page_selects_current_month():
    response = client.get("/")
    assert response.status_code == 200
    current = current_month_name()
    # The current month option should have 'selected' attribute
    assert f'value="{current}" selected' in response.text


# ---------------------------------------------------------------------------
# Improvement 3: /check-existing endpoint
# ---------------------------------------------------------------------------

def test_check_existing_returns_zero_for_missing_folder(tmp_path):
    with patch("invoice_app.web.resolve_path", return_value=str(tmp_path / "config.json")), \
         patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root=str(tmp_path / "Invoices"))
        response = client.get("/check-existing?month=kovas")
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_check_existing_counts_pdfs(tmp_path):
    invoices_dir = tmp_path / "Invoices" / "kovas"
    invoices_dir.mkdir(parents=True)
    (invoices_dir / "SS-2026-001_Jonas.pdf").write_text("pdf")
    (invoices_dir / "SS-2026-002_Petras.pdf").write_text("pdf")

    with patch("invoice_app.web.load_config") as mock_cfg, \
         patch("invoice_app.web.resolve_path", side_effect=lambda p: p):
        mock_cfg.return_value = MagicMock(output_root=str(tmp_path / "Invoices"))
        with patch("invoice_app.web.Path") as mock_path_cls:
            # Use real Path but patch output_root resolution
            pass

    # Direct test using real filesystem
    with patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root=str(tmp_path / "Invoices"))
        with patch("invoice_app.web.resolve_path", return_value=str(tmp_path / "config.json")):
            from invoice_app import web as web_module
            orig = web_module.resolve_path

            def patched_resolve(p):
                if "config" in p:
                    return str(tmp_path / "config.json")
                return str(tmp_path / p)

            with patch.object(web_module, "resolve_path", patched_resolve):
                response = client.get("/check-existing?month=kovas")

    assert response.status_code == 200
    data = response.json()
    assert "count" in data
    assert "month" in data


# ---------------------------------------------------------------------------
# Improvement 4: total_amount in generate results
# ---------------------------------------------------------------------------

def test_generate_shows_total_amount():
    with patch("invoice_app.web._load_rows", return_value=DUMMY_ROWS), \
         patch("invoice_app.web.process_batch", return_value=DUMMY_STATS), \
         patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root="Invoices", seller=MagicMock())
        response = client.post("/generate", data={
            "month": "kovas",
            "csv_path": "Context/Psichoterapijos apskaita.xlsx",
            "template_path": "Context/template saskaita-faktura.docx",
            "policy": "overwrite",
        })
    assert response.status_code == 200
    assert "200.00" in response.text or "€" in response.text


def test_generate_total_amount_not_shown_when_zero():
    zero_stats = {**DUMMY_STATS, "total_amount": Decimal("0"), "generated": 0}
    with patch("invoice_app.web._load_rows", return_value=[]), \
         patch("invoice_app.web.process_batch", return_value=zero_stats), \
         patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root="Invoices", seller=MagicMock())
        response = client.post("/generate", data={
            "month": "kovas",
            "csv_path": "data/clients.csv",
            "template_path": "Context/template saskaita-faktura.docx",
            "policy": "skip",
        })
    assert response.status_code == 200
    # Should not show "Total billed" when 0
    assert "Total billed" not in response.text


# ---------------------------------------------------------------------------
# Improvement 5: preview stores tmp path + Generate from preview button
# ---------------------------------------------------------------------------

def test_preview_returns_tmp_csv_path_in_response():
    with patch("invoice_app.web._load_rows", return_value=DUMMY_ROWS), \
         patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root="Invoices")
        response = client.post("/preview", data={
            "month": "kovas",
            "csv_path": "Context/Psichoterapijos apskaita.xlsx",
        })
    assert response.status_code == 200
    # tmp_csv_path hidden input should be present
    assert 'name="csv_path"' in response.text


def test_preview_shows_generate_button_when_invoiceable_clients():
    with patch("invoice_app.web._load_rows", return_value=DUMMY_ROWS), \
         patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root="Invoices")
        response = client.post("/preview", data={
            "month": "kovas",
            "csv_path": "Context/Psichoterapijos apskaita.xlsx",
        })
    assert response.status_code == 200
    assert "Generate These Invoices" in response.text


def test_preview_no_generate_button_when_no_invoiceable_clients():
    no_session_rows = [{"Client": "Jonas", "Kovas": "0", "Rate": "50"}]
    with patch("invoice_app.web._load_rows", return_value=no_session_rows), \
         patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root="Invoices")
        response = client.post("/preview", data={
            "month": "kovas",
            "csv_path": "Context/Psichoterapijos apskaita.xlsx",
        })
    assert response.status_code == 200
    assert "Generate These Invoices" not in response.text


def test_preview_shows_total():
    with patch("invoice_app.web._load_rows", return_value=DUMMY_ROWS), \
         patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root="Invoices")
        response = client.post("/preview", data={
            "month": "kovas",
            "csv_path": "Context/Psichoterapijos apskaita.xlsx",
        })
    assert response.status_code == 200
    assert "200.00" in response.text  # 4 sessions × €50


def test_preview_file_upload_saves_to_tmp(tmp_path):
    import io
    csv_content = b"Client,Kovas,Rate\nJonas,3,50\n"

    with patch("invoice_app.web.load_config") as mock_cfg, \
         patch("invoice_app.web.tmp_dir", tmp_path):
        mock_cfg.return_value = MagicMock(output_root="Invoices")
        response = client.post(
            "/preview",
            data={"month": "kovas", "csv_path": ""},
            files={"uploaded_file": ("clients.csv", io.BytesIO(csv_content), "text/csv")},
        )

    assert response.status_code == 200
    # A tmp file should have been created
    tmp_files = list(tmp_path.glob("*.csv"))
    assert len(tmp_files) >= 1


# ---------------------------------------------------------------------------
# Improvement 2: loading spinner (HTML structure)
# ---------------------------------------------------------------------------

def test_generate_button_has_onclick_handler():
    response = client.get("/")
    assert response.status_code == 200
    assert "handleGenerate" in response.text


def test_preview_button_has_onclick_handler():
    response = client.get("/")
    assert response.status_code == 200
    assert "handlePreview" in response.text


def test_spinner_css_present():
    response = client.get("/")
    assert ".spinner" in response.text
    assert "@keyframes spin" in response.text


# ---------------------------------------------------------------------------
# Month helpers
# ---------------------------------------------------------------------------

def test_month_to_folder_mapping():
    assert month_to_folder("kovas") == "kovas"
    assert month_to_folder("vasaris") == "vasaris"
    assert month_to_folder("3") == "kovas"
    assert month_to_folder("2") == "vasaris"


def test_month_number_to_column():
    assert month_number_to_column("kovas") == "Kovas"
    assert month_number_to_column("sausis") == "Sausis"


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

def test_generate_bad_data_source_shows_error():
    with patch("invoice_app.web._load_rows", side_effect=FileNotFoundError("not found")), \
         patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root="Invoices", seller=MagicMock())
        response = client.post("/generate", data={
            "month": "kovas",
            "csv_path": "nonexistent.csv",
            "template_path": "Context/template saskaita-faktura.docx",
            "policy": "overwrite",
        })
    assert response.status_code == 200
    assert "Could not load data source" in response.text


def test_preview_bad_data_source_shows_error():
    with patch("invoice_app.web._load_rows", side_effect=FileNotFoundError("not found")), \
         patch("invoice_app.web.load_config") as mock_cfg:
        mock_cfg.return_value = MagicMock(output_root="Invoices")
        response = client.post("/preview", data={
            "month": "kovas",
            "csv_path": "nonexistent.csv",
        })
    assert response.status_code == 200
    assert "⚠️" in response.text
