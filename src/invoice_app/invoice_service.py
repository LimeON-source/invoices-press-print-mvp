import json
import platform
import re
import subprocess
import unicodedata
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from num2words import num2words
except ImportError:
    num2words = None

from invoice_app.models import AppConfig, InvoiceModel, LineItem, SellerConfig
from invoice_app.template_filler import fill_template


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Invoice number registry — stable, year-scoped, idempotent
# ---------------------------------------------------------------------------

def load_registry(path: str) -> dict:
    """Load {year: {counter: N, months: {month: {client: number}}}}."""
    p = Path(path)
    if not p.exists():
        return {}
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_registry(registry: dict, path: str) -> None:
    Path(path).write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8")


def preview_invoice_numbers(
    month: str,
    client_names: List[str],
    year: int,
    series: str,
    registry_path: str,
) -> Dict[str, dict]:
    """Return proposed numbers WITHOUT writing to registry.

    Returns {client_name: {"number": "SS-2026-001", "locked": bool}}
    locked=True means the number already exists in the registry for this client/month.
    """
    registry = load_registry(registry_path)
    year_data = registry.get(str(year), {"counter": 0, "months": {}})
    month_data = year_data.get("months", {}).get(month, {})
    counter = year_data.get("counter", 0)
    result: Dict[str, dict] = {}
    for client in client_names:
        if client in month_data:
            result[client] = {
                "number": f"{series}-{year}-{month_data[client]:03d}",
                "locked": True,
            }
        else:
            counter += 1
            result[client] = {
                "number": f"{series}-{year}-{counter:03d}",
                "locked": False,
            }
    return result


def assign_invoice_numbers(
    month: str,
    client_names: List[str],
    year: int,
    series: str,
    registry_path: str,
) -> Dict[str, str]:
    """Assign numbers, persisting to registry. Idempotent for existing entries.

    Returns {client_name: "SS-2026-001"}.
    """
    registry = load_registry(registry_path)
    year_str = str(year)
    if year_str not in registry:
        registry[year_str] = {"counter": 0, "months": {}}
    year_data = registry[year_str]
    if month not in year_data["months"]:
        year_data["months"][month] = {}
    month_data = year_data["months"][month]
    result: Dict[str, str] = {}
    for client in client_names:
        if client in month_data:
            result[client] = f"{series}-{year}-{month_data[client]:03d}"
        else:
            year_data["counter"] += 1
            month_data[client] = year_data["counter"]
            result[client] = f"{series}-{year}-{year_data['counter']:03d}"
    save_registry(registry, registry_path)
    return result


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


# ---------------------------------------------------------------------------
# PDF conversion — batch, no per-file Word windows
# ---------------------------------------------------------------------------

def _libreoffice_path() -> Optional[str]:
    """Return the soffice binary path if LibreOffice is installed."""
    candidates = [
        "soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        "/usr/bin/soffice",
        "/usr/local/bin/soffice",
    ]
    for c in candidates:
        try:
            result = subprocess.run([c, "--version"], capture_output=True, timeout=5)
            if result.returncode == 0:
                return c
        except Exception:
            continue
    return None


def batch_convert_to_pdf(docx_paths: List[Path], output_dir: Path) -> Dict[str, Optional[Path]]:
    """
    Convert a list of DOCX files to PDF as a single batch.
    Returns a dict mapping docx_path -> pdf_path (or None if conversion failed).

    Strategy:
      1. LibreOffice headless  — silent, no UI, converts all files in one call
      2. docx2pdf folder mode  — opens Word once for the whole folder
      3. Fallback              — keep DOCX, return None for pdf_path
    """
    if not docx_paths:
        return {}

    results: Dict[str, Optional[Path]] = {}

    # --- Strategy 1: LibreOffice headless -----------------------------------
    soffice = _libreoffice_path()
    if soffice:
        try:
            cmd = [
                soffice,
                "--headless",
                "--convert-to", "pdf",
                "--outdir", str(output_dir),
            ] + [str(p) for p in docx_paths]
            subprocess.run(cmd, capture_output=True, timeout=120)
            for docx in docx_paths:
                pdf = output_dir / (docx.stem + ".pdf")
                results[str(docx)] = pdf if pdf.exists() else None
            return results
        except Exception:
            pass  # fall through to next strategy

    # --- Strategy 2: docx2pdf folder mode (one Word session) ----------------
    try:
        from docx2pdf import convert as _docx2pdf

        # Move all target DOCX files into a temporary staging folder so we can
        # convert exactly that folder — avoids touching unrelated DOCX files.
        import tempfile, shutil
        with tempfile.TemporaryDirectory() as stage_dir:
            stage = Path(stage_dir)
            # copy each docx into stage
            for docx in docx_paths:
                shutil.copy2(docx, stage / docx.name)
            # one Word session converts the whole folder
            _docx2pdf(str(stage) + "/", str(output_dir) + "/")
            for docx in docx_paths:
                pdf = output_dir / (docx.stem + ".pdf")
                results[str(docx)] = pdf if pdf.exists() else None
        return results
    except Exception:
        pass

    # --- Strategy 3: fallback — keep DOCX -----------------------------------
    for docx in docx_paths:
        results[str(docx)] = None
    return results


# ---------------------------------------------------------------------------
# Invoice building  (DOCX creation only — PDF done in a single batch later)
# ---------------------------------------------------------------------------

def build_invoice_docx(
    model: InvoiceModel,
    template_path: str,
    out_root: str,
    policy: str = "overwrite",
    month_folder: str = None,
) -> Tuple[Optional[Path], Optional[Path]]:
    """
    Fill the DOCX template and save to the output folder.

    Returns (docx_path, existing_pdf_path):
      - existing_pdf_path is set when policy=skip and PDF already exists.
      - docx_path is None when the file is skipped entirely.
    """
    dest_folder = Path(out_root) / (month_folder if month_folder else model.date.strftime("%Y-%m"))
    dest_folder.mkdir(parents=True, exist_ok=True)

    clean_client = sanitize_filename(model.buyer_name)
    target_pdf = dest_folder / f"{model.number}_{clean_client}.pdf"

    if target_pdf.exists():
        if policy == "skip":
            return None, target_pdf          # nothing to do
        if policy == "version":
            version = 2
            while True:
                candidate = dest_folder / f"{model.number}_v{version}_{clean_client}.pdf"
                if not candidate.exists():
                    target_pdf = candidate
                    break
                version += 1

    docx_path = dest_folder / f"{model.number}_{clean_client}.docx"
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
    fill_template(template_path, str(docx_path), replacements)
    return docx_path, None


# ---------------------------------------------------------------------------
# Key lookup helpers
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Invoice model preparation
# ---------------------------------------------------------------------------

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

    if not name and len(row) > 1:
        keys = list(row.keys())
        name = str(row.get(keys[1], "")).strip()

    address = (find_field(row, "Address") or "").strip()
    rate_val = find_field(row, "Rate") or find_field(row, "Kaina") or ""
    sessions_val = find_field(row, month_column) or ""

    _SUMMARY_ROWS = {
        "sesijų skaičius per mėnesį", "viso", "total", "sum",
        "uždarbis", "udarbis", "pajamos", "income", "earnings",
    }
    if not name or normalize_key(name.rstrip(":;,.")) in {normalize_key(s) for s in _SUMMARY_ROWS}:
        return None

    if not address:
        address = "N/A"

    try:
        sessions = int(float(sessions_val)) if sessions_val else 0
    except Exception:
        raise ValueError("sessions must be integer")

    if sessions < 0:
        raise ValueError("sessions must be >=0")

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


# ---------------------------------------------------------------------------
# Batch processing
# ---------------------------------------------------------------------------

def process_batch(
    rows: List[Dict[str, str]],
    month_column: str,
    config: AppConfig,
    template_path: str,
    output_root: str,
    registry_file: str,
    policy: str,
    selected_clients: Optional[List[str]] = None,
    month_folder: str = None,
) -> Dict:
    year = date.today().year
    output_folder_path = (
        (Path(output_root) / month_folder).resolve()
        if month_folder
        else Path(output_root).resolve()
    )

    stats = {
        "processed": 0,
        "generated": 0,
        "skipped": 0,
        "errors": 0,
        "total_amount": Decimal("0"),
        "output_folder": str(output_folder_path),
        "error_details": [],
    }

    # Pass 0 — validate all rows, collect valid models
    valid_models: Dict[str, object] = {}
    for row in rows:
        name = (
            find_field(row, "Client")
            or find_field(row, "Client Name")
            or find_field(row, "Name Surname")
            or ""
        ).strip()
        if not name:
            continue
        if selected_clients and name not in selected_clients:
            continue
        try:
            model = prepare_invoice(row, month_column, config, "__DRAFT__", date.today())
            if model is None:
                stats["skipped"] += 1
                continue
            valid_models[name] = model
        except Exception as e:
            msg = str(e)
            print(f"Row error for '{name}': {msg}")
            stats["errors"] += 1
            stats["error_details"].append({"client": name, "reason": msg})

    # Assign numbers for all valid clients — idempotent via registry
    if valid_models:
        registry_month = month_folder or month_column.lower()
        invoice_numbers = assign_invoice_numbers(
            registry_month, list(valid_models.keys()), year,
            config.invoice_series, registry_file,
        )
        for name, model in valid_models.items():
            model.number = invoice_numbers[name]
            stats["total_amount"] += model.total

    # Pass 1 — create all DOCX files
    pending_docx: List[Path] = []
    for name, model in valid_models.items():
        try:
            docx_path, existing_pdf = build_invoice_docx(
                model, template_path, output_root, policy=policy, month_folder=month_folder
            )
            if existing_pdf is not None:
                stats["skipped"] += 1
                continue
            if docx_path is not None:
                pending_docx.append(docx_path)
                stats["processed"] += 1
        except Exception as e:
            msg = str(e)
            print(f"DOCX error for '{name}': {msg}")
            stats["errors"] += 1
            stats["error_details"].append({"client": name, "reason": msg})

    # Pass 2 — convert all DOCX → PDF in a single batch
    if pending_docx:
        pdf_results = batch_convert_to_pdf(pending_docx, output_folder_path)
        for docx_path in pending_docx:
            pdf = pdf_results.get(str(docx_path))
            if pdf and pdf.exists():
                docx_path.unlink(missing_ok=True)
                stats["generated"] += 1
            else:
                stats["generated"] += 1  # keep DOCX fallback

    return stats
