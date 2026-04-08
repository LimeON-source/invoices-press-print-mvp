import os
import platform
import subprocess
from datetime import date
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from invoice_app.config import load_config, save_default_config
from invoice_app.data_source import load_clients_from_csv, load_clients_from_xlsx
from invoice_app.invoice_service import process_batch
from invoice_app.models import MONTHS_LT, normalize_month

app = FastAPI(title="Invoices Press Print UI")

project_root = Path(__file__).resolve().parents[2]
templates_dir = project_root / "templates"
static_dir = project_root / "static"
static_dir.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(templates_dir))

if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.on_event("startup")
def startup():
    if not Path("config.json").exists():
        save_default_config("config.json")
    if not Path("invoice_counter.json").exists():
        Path("invoice_counter.json").write_text('{"year": 0, "counter": 0}', encoding="utf-8")


@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    default_source = "Context/Psichoterapijos apskaita.xlsx"
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "months": ["sausis", "vasaris", "kovas", "balandis", "geguze", "birzelis", "liepa", "rugpjutis", "rugsejis", "spalis", "lapkritis", "gruodis"],
            "policies": ["overwrite", "skip", "version"],
            "selected_month": "kovas",
            "data_source": default_source,
        },
    )


def month_name_to_number(month_name: str) -> int:
    try:
        # support numeric months too
        return normalize_month(month_name)
    except ValueError:
        # 2026-03 style input supports this also
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
            months = ["sausis", "vasaris", "kovas", "balandis", "geguze", "birzelis", "liepa", "rugpjutis", "rugsejis", "spalis", "lapkritis", "gruodis"]
            return months[month_number - 1]
    except ValueError:
        pass
    normalized = month_name.strip().lower()
    if normalized in MONTHS_LT:
        return normalized
    return normalized


def month_number_to_column(month_name: str) -> str:
    """Convert month name/number to column header name (e.g. 'kovas' -> 'Kovas')"""
    try:
        month_number = normalize_month(month_name)
        months = ["sausis", "vasaris", "kovas", "balandis", "geguze", "birzelis", "liepa", "rugpjutis", "rugsejis", "spalis", "lapkritis", "gruodis"]
        return months[month_number - 1].capitalize()
    except ValueError:
        return month_name


@app.post("/generate", response_class=HTMLResponse)
def generate(
    request: Request,
    month: str = Form("kovas"),
    csv_path: str = Form("data/clients.csv"),
    template_path: str = Form("Context/template saskaita-faktura .docx"),
    policy: str = Form("overwrite"),
    selected: Optional[str] = Form(None),
):
    selected_clients: Optional[List[str]] = None
    if selected:
        selected_clients = [name.strip() for name in selected.split(",") if name.strip()]

    config = load_config("config.json")
    template_path = template_path.strip()
    if csv_path.lower().endswith(".xlsx") or csv_path.lower().endswith(".xls"):
        rows = load_clients_from_xlsx(csv_path)
    else:
        rows = load_clients_from_csv(csv_path)

    # Convert month name to column header (e.g. 'kovas' -> 'Kovas')
    month_column = month_number_to_column(month)

    month_folder = month_to_folder(month)

    stats = process_batch(
        rows=rows,
        month_column=month_column,
        config=config,
        template_path=template_path,
        output_root=config.output_root,
        counter_file="invoice_counter.json",
        policy=policy,
        selected_clients=selected_clients,
        month_folder=month_folder,
    )

    invoice_folder = str(Path(config.output_root) / month_folder)

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "months": ["sausis", "vasaris", "kovas", "balandis", "geguze", "birzelis", "liepa", "rugpjutis", "rugsejis", "spalis", "lapkritis", "gruodis"],
            "policies": ["overwrite", "skip", "version"],
            "stats": stats,
            "message": "Invoice generation completed",
            "invoice_folder": invoice_folder,
            "invoice_month_folder": month_folder,
            "selected_month": month,
            "data_source": csv_path,
        },
    )


@app.get("/open-folder")
def open_folder(month: str = "kovas"):
    config = load_config("config.json")
    month_folder = month_to_folder(month)

    folder_path = Path(config.output_root) / month_folder
    folder_path.mkdir(parents=True, exist_ok=True)

    if platform.system() == "Darwin":
        subprocess.run(["open", str(folder_path)])
    elif platform.system() == "Windows":
        os.startfile(str(folder_path))
    else:
        subprocess.run(["xdg-open", str(folder_path)])

    return RedirectResponse(url=f"/?month={month}")
