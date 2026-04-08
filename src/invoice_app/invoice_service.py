import json
import re
import unicodedata
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional

try:
    from docx2pdf import convert as docx_to_pdf
except ImportError:
    docx_to_pdf = None

try:
    from num2words import num2words
except ImportError:
    num2words = None

from invoice_app.models import AppConfig, InvoiceModel, LineItem, SellerConfig
from invoice_app.template_filler import fill_template


def sanitize_filename(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z\-_. ]", "", name).strip().replace(" ", "-")


def load_counter(path: str = "invoice_counter.json") -> Dict[str, int]:
    p = Path(path)
    if not p.exists():
        return {"year": date.today().year, "counter": 0}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_counter(data: Dict[str, int], path: str = "invoice_counter.json") -> None:
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def next_invoice_number(series: str, counter_data: Dict[str, int], target_year: int) -> str:
    if counter_data.get("year") != target_year:
        counter_data["year"] = target_year
        counter_data["counter"] = 0
    counter_data["counter"] += 1
    return f"{series}-{target_year}-{counter_data['counter']:03d}"


def convert_amount_to_words(amount) -> str:
    if not num2words:
        return f"{amount:.2f}"
    amount_dec = Decimal(str(amount))
    rounded = amount_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    integer_part = int(rounded)
    cents = int((rounded - integer_part) * 100)
    words = num2words(integer_part, lang="lt")
    if cents > 0:
        words += f" eur {num2words(cents, lang='lt')} ct"
    return words


def build_invoice(model: InvoiceModel, template_path: str, out_root: str, policy: str = "overwrite", month_folder: str = None) -> str:
    if month_folder:
        # Use the specified month folder (e.g., "vasaris")
        dest_folder = Path(out_root) / month_folder
    else:
        # Fallback to date-based folder
        year_month = model.date.strftime("%Y-%m")
        dest_folder = Path(out_root) / year_month
    dest_folder.mkdir(parents=True, exist_ok=True)

    clean_client = sanitize_filename(model.buyer_name)
    target_filename = f"{model.number}_{clean_client}.pdf"
    target_pdf = dest_folder / target_filename

    if target_pdf.exists():
        if policy == "skip":
            return f"skipped: {target_pdf}"
        if policy == "version":
            version = 2
            while True:
                candidate = dest_folder / f"{model.number}_v{version}_{clean_client}.pdf"
                if not candidate.exists():
                    target_pdf = candidate
                    break
                version += 1

    temp_docx = dest_folder / f"{model.number}_{clean_client}.docx"
    replacements = {
        "<number>": model.number,
        "<yyyy-mm-dd>": model.date.isoformat(),
        "<suma zodziais>": model.total_words,
        "<client_name>": model.buyer_name,
        "<client_address>": model.buyer_address,
        "<Customer-name>": model.buyer_name,
        "<customer-name>": model.buyer_name,
        "<Customer-address>": model.buyer_address,
        "<customer-address>": model.buyer_address,
        "<kiekis>": str(model.sessions),
        "<Kiekis>": str(model.sessions),
        "<quantity>": str(model.sessions),
        "<kaina>": f"{model.rate:.2f}",
        "<rate>": f"{model.rate:.2f}",
        "<total>": f"{model.total:.2f}",
    }
    fill_template(template_path, str(temp_docx), replacements)

    if docx_to_pdf is not None:
        try:
            docx_to_pdf(str(temp_docx), str(target_pdf))
            if target_pdf.exists():
                if temp_docx.exists():
                    temp_docx.unlink()
                return str(target_pdf)
            # fallback to docx when PDF was not created
        except Exception:
            pass

    # Fallback: keep DOCX path if PDF conversion unavailable or failed
    return f"not_converted_saved_docx:{temp_docx}"


def normalize_key(value: str) -> str:
    if value is None:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(c for c in normalized if not unicodedata.combining(c)).lower().strip()


def find_field(row: Dict[str, str], field_name: str) -> Optional[str]:
    target = normalize_key(field_name)
    for key, value in row.items():
        if normalize_key(str(key)) == target:
            return value
    return None


def prepare_invoice(
    row: Dict[str, str],
    month_column: str,
    config: AppConfig,
    next_number: str,
    invoice_date: date,
) -> Optional[InvoiceModel]:
    name = (
        find_field(row, "Client")
        or find_field(row, "Client Name")
        or find_field(row, "Name Surname")
        or ""
    ).strip()

    # If name is still missing, try second column positional fallback (column B style)
    if not name and len(row) > 1:
        keys = list(row.keys())
        name = str(row.get(keys[1], "")).strip()

    address = (find_field(row, "Address") or "").strip()
    rate_val = find_field(row, "Rate") or find_field(row, "Kaina") or ""
    sessions_val = find_field(row, month_column) or ""

    # ignore header/summary rows that accidentally may be present
    if not name or name.strip().lower() in {"sesijų skaičius per mėnesį", "viso", "total", "sum"}:
        return None

    # Use default address if not provided
    if not address:
        address = "N/A"

    try:
        sessions = int(float(sessions_val)) if sessions_val else 0
    except Exception:
        raise ValueError("sessions must be integer")

    if sessions < 0:
        raise ValueError("sessions must be >=0")

    # Do NOT generate invoice if no sessions for the month
    if sessions == 0:
        return None

    try:
        rate = Decimal(str(rate_val))
    except Exception:
        raise ValueError("rate must be numeric")

    if rate <= 0:
        raise ValueError("rate must be >0")

    subtotal = Decimal(sessions) * rate
    vat_amount = subtotal * Decimal(config.vat_percent) / Decimal(100)
    total = subtotal + vat_amount

    line_item = LineItem(description=f"{month_column} sessions", quantity=sessions, unit_price=rate)

    return InvoiceModel(
        number=next_number,
        date=invoice_date,
        seller=config.seller,
        buyer_name=name,
        buyer_address=address,
        sessions=sessions,
        rate=rate,
        subtotal=subtotal,
        vat_amount=vat_amount,
        total=total,
        total_words=convert_amount_to_words(total),
        line_item=line_item,
    )


def process_batch(
    rows: List[Dict[str, str]],
    month_column: str,
    config: AppConfig,
    template_path: str,
    output_root: str,
    counter_file: str,
    policy: str,
    selected_clients: Optional[List[str]] = None,
    month_folder: str = None,
) -> Dict[str, int]:
    counter_data = load_counter(counter_file)
    year = date.today().year

    if month_folder:
        output_folder_path = (Path(output_root) / month_folder).resolve()
    else:
        output_folder_path = Path(output_root).resolve()

    stats = {
        "processed": 0,
        "generated": 0,
        "skipped": 0,
        "errors": 0,
        "output_folder": str(output_folder_path),
    }

    for row in rows:
        # Find client name using normalized key matching
        name = find_field(row, "Client") or find_field(row, "Client Name") or find_field(row, "Name Surname") or ""
        name = name.strip()
        
        # Skip empty rows
        if not name:
            continue
            
        if selected_clients and name not in selected_clients:
            continue

        try:
            next_num = next_invoice_number(config.invoice_series, counter_data, year)
            model = prepare_invoice(row, month_column, config, next_num, date.today())

            if model is None:
                stats["skipped"] += 1
                continue

            result = build_invoice(model, template_path, output_root, policy=policy, month_folder=month_folder)
            stats["generated"] += 1
            stats["processed"] += 1
        except Exception as e:
            # record and continue. Use print/log for debugging.
            print(f"Row error (row maybe has header/sum): {e}")
            stats["errors"] += 1
            if policy == "skip":
                stats["skipped"] += 1
            continue

    save_counter(counter_data, counter_file)
    return stats
