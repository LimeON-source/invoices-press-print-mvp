import json
from pathlib import Path
from typing import Optional

from pydantic import ValidationError

from invoice_app.models import AppConfig, SellerConfig


def load_config(path: str = "config.json") -> AppConfig:
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with config_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    try:
        return AppConfig(**data)
    except ValidationError as exc:
        raise ValueError(f"Invalid configuration: {exc}")


def save_default_config(path: str = "config.json") -> AppConfig:
    default = {
        "gdrive_folder": "./",
        "seller": {
            "name": "Šaknys ir sparnai MB",
            "address": "",
            "company_code": "",
            "iban": "",
            "issuer_name": "",
        },
        "vat_percent": 0.0,
        "invoice_series": "SS",
        "output_root": "Invoices",
    }
    config_path = Path(path)
    if not config_path.exists():
        config_path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
    return AppConfig(**default)
