import io
import os
import platform
import subprocess
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from invoice_app.config import load_config, save_default_config
from invoice_app.data_source import load_clients_from_csv, load_clients_from_xlsx
from invoice_app.invoice_service import find_field, prepare_invoice, process_batch
from invoice_app.models import MONTHS_LT, normalize_month

app = FastAPI(title="Invoices Press Print UI")

MONTH_NAMES = [
    "sausis", "vasaris", "kovas", "balandis", "geguze", "birzelis",
    "liepa", "rugpjutis", "rugsejis", "spalis", "lapkritis", "gruodis",
]

project_root = Path(__file__).resolve().parents[2]
templates_dir = project_root / "templates"
static_dir = project_root / "static"
tmp_dir = project_root / "tmp"

static_dir.mkdir(parents=True, exist_ok=True)
tmp_dir.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(templates_dir))

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


def resolve_path(p: str) -> str:
    """Resolve a path relative to the project root if it is not absolute."""
    path = Path(p)
    if path.is_absolute():
        return str(path)
    return str(project_root / path)


def current_month_name() -> str:
    """Return the Lithuanian month name for today's month."""
    return MONTH_NAMES[date.today().month - 1]


@app.on_event("startup")
def startup():
    config_path = resolve_path("config.json")
    counter_path = resolve_path("invoice_counter.json")
    if not Path(config_path).exists():
        save_default_config(config_path)
    if not Path(counter_path).exists():
        Path(counter_path).write_text('{"year": 0, "counter": 0}', encoding="utf-8")


def _save_upload_to_tmp(uploaded_file: UploadFile) -> str:
    """Save an uploaded file to the tmp directory and return its path."""
    suffix = Path(uploaded_file.filename).suffix
    tmp_path = tmp_dir / f"{uuid.uuid4().hex}{suffix}"
    contents = uploaded_file.file.read()
    tmp_path.write_bytes(contents)
    return str(tmp_path)


def _load_rows(csv_path: str, uploaded_file: Optional[UploadFile] = None):
    """Load client rows from an uploaded file or a path on disk."""
    if uploaded_file and uploaded_file.filename:
        contents = uploaded_file.file.read()
        fname = uploaded_file.filename.lower()
        if fname.endswith(".xlsx") or fname.endswith(".xls"):
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                tmp.write(contents)
                tmp_path = tmp.name
            rows = load_clients_from_xlsx(tmp_path)
            Path(tmp_path).unlink(missing_ok=True)
        else:
            text = contents.decode("utf-8-sig")
            import csv as csv_mod
            reader = csv_mod.DictReader(io.StringIO(text))
            rows = [dict(r) for r in reader]
        return rows

    csv_path = csv_path.strip()
    if csv_path.lower().endswith(".xlsx") or csv_path.lower().endswith(".xls"):
        return load_clients_from_xlsx(csv_path)
    return load_clients_from_csv(csv_path)


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    default_source = "Context/Psichoterapijos apskaita.xlsx"
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "months": MONTH_NAMES,
            "policies": ["overwrite", "skip", "version"],
            # Improvement 1: auto-select today's month
            "selected_month": current_month_name(),
            "data_source": default_source,
        },
    )


def month_name_to_number(month_name: str) -> int:
    try:
        return normalize_month(month_name)
    except ValueError:
        if "-" in month_name:
            parts = month_name.split("-")
            if parts[-1].isdigit():
                try:
                    return normalize_month(parts[-1])
                except ValueError:
                    pass
        return 0


def month_to_folder(month_name: str) -> str:
    try:
        month_number = month_name_to_number(month_name)
        if 1 <= month_number <= 12:
            return MONTH_NAMES[month_number - 1]
    except ValueError:
        pass
    normalized = month_name.strip().lower()
    return normalized


def month_number_to_column(month_name: str) -> str:
    """Convert month name/number to column header name (e.g. 'kovas' -> 'Kovas')"""
    try:
        month_number = normalize_month(month_name)
        return MONTH_NAMES[month_number - 1].capitalize()
    except ValueError:
        return month_name


# Improvement 3: check how many invoices already exist for a month
@app.get("/check-existing")
def check_existing(month: str = "kovas") -> JSONResponse:
    config = load_config(resolve_path("config.json"))
    month_folder = month_to_folder(month)
    folder = Path(resolve_path(config.output_root)) / month_folder
    if not folder.exists():
        return JSONResponse({"count": 0, "month": month_folder})
    count = len(list(folder.glob("*.pdf"))) + len(list(folder.glob("*.docx")))
    return JSONResponse({"count": count, "month": month_folder})


@app.post("/preview", response_class=HTMLResponse)
def preview(
    request: Request,
    month: str = Form("kovas"),
    csv_path: str = Form("data/clients.csv"),
    uploaded_file: Optional[UploadFile] = File(None),
):
    config = load_config(resolve_path("config.json"))
    month_column = month_number_to_column(month)

    # Improvement 5: save uploaded file to tmp so Generate can reuse it
    effective_csv_path = csv_path
    tmp_csv_path = None
    if uploaded_file and uploaded_file.filename:
        tmp_csv_path = _save_upload_to_tmp(uploaded_file)
        effective_csv_path = tmp_csv_path
        # Reset file pointer for _load_rows (already consumed above, use path)
        uploaded_file = None

    try:
        rows = _load_rows(resolve_path(effective_csv_path) if not tmp_csv_path else effective_csv_path)
    except Exception as e:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "months": MONTH_NAMES,
                "policies": ["overwrite", "skip", "version"],
                "selected_month": month,
                "data_source": csv_path,
                "error": str(e),
            },
        )

    preview_rows = []
    for row in rows:
        name = (
            find_field(row, "Client")
            or find_field(row, "Client Name")
            or find_field(row, "Name Surname")
            or ""
        ).strip()
        if not name:
            continue
        sessions_val = find_field(row, month_column) or ""
        rate_val = find_field(row, "Rate") or find_field(row, "Kaina") or ""
        try:
            sessions = int(float(sessions_val)) if sessions_val else 0
            rate = Decimal(str(rate_val)) if rate_val else Decimal("0")
            total = Decimal(sessions) * rate
        except Exception:
            sessions, rate, total = 0, Decimal("0"), Decimal("0")
        preview_rows.append({
            "name": name,
            "sessions": sessions,
            "rate": f"{rate:.2f}",
            "total": f"{total:.2f}",
            "will_invoice": sessions > 0 and rate > 0,
        })

    preview_total = sum(
        Decimal(r["total"]) for r in preview_rows if r["will_invoice"]
    )

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "months": MONTH_NAMES,
            "policies": ["overwrite", "skip", "version"],
            "selected_month": month,
            "data_source": csv_path,
            "preview_rows": preview_rows,
            "preview_month": month_column,
            "preview_total": f"{preview_total:.2f}",
            # Improvement 5: pass tmp path so Generate button can reuse it
            "tmp_csv_path": tmp_csv_path or resolve_path(csv_path),
        },
    )


@app.post("/generate", response_class=HTMLResponse)
async def generate(
    request: Request,
    month: str = Form("kovas"),
    csv_path: str = Form("data/clients.csv"),
    template_path: str = Form("Context/template saskaita-faktura.docx"),
    policy: str = Form("overwrite"),
    selected: Optional[str] = Form(None),
    uploaded_file: Optional[UploadFile] = File(None),
):
    selected_clients: Optional[List[str]] = None
    if selected:
        selected_clients = [name.strip() for name in selected.split(",") if name.strip()]

    config = load_config(resolve_path("config.json"))
    template_path = resolve_path(template_path.strip())

    # If csv_path is already absolute (came from tmp), use as-is
    effective_csv = csv_path if Path(csv_path).is_absolute() else resolve_path(csv_path)

    try:
        rows = _load_rows(effective_csv, uploaded_file)
    except Exception as e:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "months": MONTH_NAMES,
                "policies": ["overwrite", "skip", "version"],
                "selected_month": month,
                "data_source": csv_path,
                "error": f"Could not load data source: {e}",
            },
        )

    month_column = month_number_to_column(month)
    month_folder = month_to_folder(month)

    stats = process_batch(
        rows=rows,
        month_column=month_column,
        config=config,
        template_path=template_path,
        output_root=resolve_path(config.output_root),
        counter_file=resolve_path("invoice_counter.json"),
        policy=policy,
        selected_clients=selected_clients,
        month_folder=month_folder,
    )

    # Clean up tmp file if it was a temp upload path
    if Path(csv_path).is_absolute() and str(tmp_dir) in csv_path:
        Path(csv_path).unlink(missing_ok=True)

    invoice_folder = str(Path(config.output_root) / month_folder)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "months": MONTH_NAMES,
            "policies": ["overwrite", "skip", "version"],
            "stats": stats,
            # Improvement 4: total_amount from stats
            "total_amount": f"{stats.get('total_amount', Decimal('0')):.2f}",
            "message": "Invoice generation completed",
            "invoice_folder": invoice_folder,
            "invoice_month_folder": month_folder,
            "selected_month": month,
            "data_source": csv_path if not (Path(csv_path).is_absolute() and str(tmp_dir) in csv_path) else "Context/Psichoterapijos apskaita.xlsx",
        },
    )


@app.get("/open-folder")
def open_folder(month: str = "kovas"):
    config = load_config(resolve_path("config.json"))
    month_folder = month_to_folder(month)

    folder_path = Path(resolve_path(config.output_root)) / month_folder
    folder_path.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Darwin":
        subprocess.run(["open", str(folder_path)])
    elif platform.system() == "Windows":
        os.startfile(str(folder_path))
    else:
        subprocess.run(["xdg-open", str(folder_path)])

    return RedirectResponse(url=f"/?month={month}")
