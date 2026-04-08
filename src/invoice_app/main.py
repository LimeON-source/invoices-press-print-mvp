import argparse
import json
from pathlib import Path
from typing import List, Optional

from invoice_app.config import load_config, save_default_config
from invoice_app.data_source import load_clients_from_csv, load_clients_from_gsheet, load_clients_from_xlsx
from invoice_app.invoice_service import process_batch
from invoice_app.models import MONTHS_LT


def create_default_files() -> None:
    if not Path("config.json").exists():
        save_default_config("config.json")
    if not Path("invoice_counter.json").exists():
        Path("invoice_counter.json").write_text(json.dumps({"year": 0, "counter": 0}, indent=2), encoding="utf-8")


def to_month_column(month: str) -> str:
    month_lower = month.strip().lower()
    if month_lower.isdigit():
        month_index = int(month_lower)
    else:
        month_index = MONTHS_LT.get(month_lower)
        if month_index is None:
            raise ValueError(f"Invalid month: {month}")
    names = ["sausis", "vasaris", "kovas", "balandis", "geguze", "birzelis", "liepa", "rugpjutis", "rugsejis", "spalis", "lapkritis", "gruodis"]
    return names[month_index - 1]


def main() -> None:
    parser = argparse.ArgumentParser(description="Invoices Press Print MVP")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--template", default="Context/template saskaita-faktura .docx")
    parser.add_argument("--month", required=True, help="month number or name, e.g. 3 or kovas")
    parser.add_argument("--sheet-id", default=None)
    parser.add_argument("--credentials", default=None)
    parser.add_argument("--csv", default="data/clients.csv")
    parser.add_argument("--policy", choices=["overwrite", "skip", "version"], default="overwrite")
    parser.add_argument("--select", nargs="*", help="optional client names to process")
    args = parser.parse_args()

    create_default_files()

    config = load_config(args.config)
    month_column = to_month_column(args.month)

    if args.sheet_id and args.credentials:
        rows = load_clients_from_gsheet(args.sheet_id, args.credentials)
    elif args.csv.lower().endswith('.xlsx') or args.csv.lower().endswith('.xls'):
        rows = load_clients_from_xlsx(args.csv)
    else:
        rows = load_clients_from_csv(args.csv)

    template_path = args.template.strip()

    stats = process_batch(
        rows=rows,
        month_column=month_column,
        config=config,
        template_path=template_path,
        output_root=config.output_root,
        counter_file="invoice_counter.json",
        policy=args.policy,
        selected_clients=args.select,
        month_folder=args.month,  # Use the month name for folder
    )

    print("Finished processing")
    if stats.get("output_folder"):
        print(f"Invoices written to: {stats['output_folder']}")
    print(json.dumps(stats, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
