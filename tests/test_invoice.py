from invoice_app.models import LineItem


def test_line_item_total():
    item = LineItem(description="Service A", quantity=1, unit_price=100.0)
    assert float(item.total) == 100.0


def test_line_item_total_batch():
    items = [
        LineItem(description="Service A", quantity=1, unit_price=100.0),
        LineItem(description="Service B", quantity=2, unit_price=50.0),
    ]
    total = sum(float(item.total) for item in items)
    assert total == 200.0
