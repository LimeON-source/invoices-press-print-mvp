import csv
from pathlib import Path
from typing import Dict, List, Optional

try:
    import openpyxl
except ImportError:
    openpyxl = None


def load_clients_from_csv(path: str) -> List[Dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        raise FileNotFoundError(f"CSV data source not found: {path}")

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return [dict(row) for row in reader]


def load_clients_from_xlsx(path: str, sheet_name: Optional[str] = None) -> List[Dict[str, str]]:
    xlsx_path = Path(path)
    if not xlsx_path.exists():
        raise FileNotFoundError(f"Excel data source not found: {path}")
    if openpyxl is None:
        raise RuntimeError("openpyxl not installed; install requirements or read CSV")

    book = openpyxl.load_workbook(str(xlsx_path), read_only=True, data_only=True)
    worksheet = book[sheet_name] if sheet_name else book.active

    rows = list(worksheet.rows)
    if not rows:
        return []

    headers = [cell.value for cell in rows[0]]
    result = []
    for row in rows[1:]:
        obj = {}
        for k, cell in zip(headers, row):
            key = str(k).strip() if k is not None else ""
            if key:
                obj[key] = str(cell.value).strip() if cell.value is not None else ""
        result.append(obj)
    return result


try:
    import gspread
    from google.oauth2.service_account import Credentials

    def load_clients_from_gsheet(sheet_id: str, credentials_file: str, worksheet_name: Optional[str] = None) -> List[Dict[str, str]]:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets.readonly",
            "https://www.googleapis.com/auth/drive.readonly",
        ]
        credentials = Credentials.from_service_account_file(credentials_file, scopes=scopes)
        gc = gspread.authorize(credentials)
        sh = gc.open_by_key(sheet_id)
        worksheet = sh.worksheet(worksheet_name) if worksheet_name else sh.sheet1
        rows = worksheet.get_all_records()
        return rows

except Exception:
    def load_clients_from_gsheet(sheet_id: str, credentials_file: str, worksheet_name: Optional[str] = None) -> List[Dict[str, str]]:
        raise RuntimeError("gspread/google-auth not available; install requirements or use CSV/XLSX source")
