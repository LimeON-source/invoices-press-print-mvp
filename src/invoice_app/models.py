from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, validator


class LineItem(BaseModel):
    description: str
    quantity: int = Field(ge=0)
    unit_price: Decimal = Field(gt=0)

    @property
    def total(self) -> Decimal:
        return self.unit_price * self.quantity


class SellerConfig(BaseModel):
    name: str
    address: str
    company_code: str
    iban: str
    issuer_name: str


class AppConfig(BaseModel):
    gdrive_folder: Optional[str] = None
    seller: SellerConfig
    vat_percent: Decimal = Field(ge=0)
    invoice_series: str = "SS"
    output_root: str = "Invoices"


class InvoiceModel(BaseModel):
    model_config = {"frozen": False}

    number: str
    date: date
    seller: SellerConfig
    buyer_name: str
    buyer_address: str
    sessions: int
    rate: Decimal
    subtotal: Decimal
    vat_amount: Decimal
    total: Decimal
    total_words: str
    line_item: LineItem


MONTHS_LT: Dict[str, int] = {
    "sausis": 1,
    "vasaris": 2,
    "kovas": 3,
    "balandis": 4,
    "geguze": 5,
    "birzelis": 6,
    "liepa": 7,
    "rugpjutis": 8,
    "rugsejis": 9,
    "spalis": 10,
    "lapkritis": 11,
    "gruodis": 12,
}


def normalize_month(month: str) -> int:
    month = month.strip().lower()
    if month.isdigit():
        m = int(month)
        if 1 <= m <= 12:
            return m
        raise ValueError("month number must be 1..12")
    if month in MONTHS_LT:
        return MONTHS_LT[month]
    raise ValueError(f"Unknown month name: {month}")
