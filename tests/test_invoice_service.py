import json
import os
from pathlib import Path

from invoice_app.config import load_config
from invoice_app.invoice_service import (
    convert_amount_to_words,
    load_counter,
    next_invoice_number,
    save_counter,
)


def test_config_load():
    cfg = load_config("config.json")
    assert cfg.invoice_series == "SS"
    assert cfg.seller.name == "Šaknys ir sparnai MB"


def test_invoice_counter(tmp_path):
    counter_path = tmp_path / "counter.json"
    save_counter({"year": 2025, "counter": 2}, str(counter_path))

    c = load_counter(str(counter_path))
    assert c["year"] == 2025
    assert c["counter"] == 2

    next_invoice = next_invoice_number("SS", c, 2025)
    assert next_invoice == "SS-2025-003"
    assert c["counter"] == 3


def test_convert_amount_to_words_fallback():
    w = convert_amount_to_words(123.45)
    assert isinstance(w, str)
    assert "123" in w or "eur" in w


def test_process_batch_sets_output_folder_and_stats(monkeypatch, tmp_path):
    from invoice_app import invoice_service
    from invoice_app.models import AppConfig, SellerConfig

    # Dummy invoice model returned by patched prepare_invoice
    class DummyModel:
        number = "SS-2026-001"

    def fake_prepare_invoice(*args, **kwargs):
        return DummyModel()

    def fake_build_invoice(*args, **kwargs):
        return "dummy.pdf"

    monkeypatch.setattr(invoice_service, "prepare_invoice", fake_prepare_invoice)
    monkeypatch.setattr(invoice_service, "build_invoice", fake_build_invoice)

    cfg = AppConfig(
        gdrive_folder="./", 
        seller=SellerConfig(name="Test", address="x", company_code="x", iban="x", issuer_name="x"),
        vat_percent=0,
        invoice_series="SS",
        output_root=str(tmp_path / "Invoices"),
    )

    rows = [{"Client": "Agn", "Kovas": "1", "Rate": "30", "Address": "addr"}]

    stats = invoice_service.process_batch(
        rows=rows,
        month_column="Kovas",
        config=cfg,
        template_path=str(tmp_path / "dummy.docx"),
        output_root=cfg.output_root,
        counter_file=str(tmp_path / "invoice_counter.json"),
        policy="overwrite",
        selected_clients=None,
        month_folder="kovas",
    )

    assert stats["processed"] == 1
    assert stats["generated"] == 1
    assert stats["errors"] == 0
    assert stats["output_folder"] == str((tmp_path / "Invoices" / "kovas").resolve())


def test_month_to_folder_mapping():
    from invoice_app.web import month_to_folder

    assert month_to_folder("2026-03") == "kovas"
    assert month_to_folder("03") == "kovas"
    assert month_to_folder("2") == "vasaris"
    assert month_to_folder("vasaris") == "vasaris"
    assert month_to_folder("2026-02") == "vasaris"


def test_build_invoice_includes_kiekis_replacement(monkeypatch, tmp_path):
    from invoice_app.invoice_service import build_invoice
    from invoice_app.models import InvoiceModel, SellerConfig, LineItem

    captured = {}

    def fake_fill_template(template_path, output_path, replacements):
        captured['replacements'] = replacements

    monkeypatch.setattr('invoice_app.invoice_service.fill_template', fake_fill_template)

    seller = SellerConfig(name='S', address='A', company_code='C', iban='I', issuer_name='E')
    line = LineItem(description='kovas sessions', quantity=5, unit_price='30')
    model = InvoiceModel(
        number='SS-2026-001',
        date='2026-03-31',
        seller=seller,
        buyer_name='Janas',
        buyer_address='Vilnius',
        sessions=5,
        rate='30',
        subtotal='150',
        vat_amount='0',
        total='150',
        total_words='One hundred fifty',
        line_item=line,
    )

    out = build_invoice(model, str(tmp_path / 'template.docx'), str(tmp_path), policy='overwrite', month_folder='kovas')

    assert captured['replacements']['<kiekis>'] == '5'
    assert captured['replacements']['<Kiekis>'] == '5'
    assert captured['replacements']['<quantity>'] == '5'
    assert captured['replacements']['<kaina>'] == '30.00'
    assert captured['replacements']['<rate>'] == '30.00'
