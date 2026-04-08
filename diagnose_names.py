from invoice_app.data_source import load_clients_from_xlsx
from invoice_app.invoice_service import prepare_invoice
from invoice_app.config import load_config
from invoice_app.web import month_number_to_column

rows = load_clients_from_xlsx('Context/Psichoterapijos apskaita.xlsx')
config = load_config('config.json')
month_col = month_number_to_column('vasaris')

errors=[]
ok=0
skip=0
for idx,row in enumerate(rows,1):
    try:
        model = prepare_invoice(row, month_col, config, 'TEST-000', __import__('datetime').date.today())
        if model is None:
            skip += 1
        else:
            ok += 1
    except Exception as e:
        errors.append((idx, str(e)))

print('month_col', month_col)
print('total rows', len(rows))
print('ok', ok, 'skip', skip, 'errors', len(errors))
print('first errors', errors[:20])
