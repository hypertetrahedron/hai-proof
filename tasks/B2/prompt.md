We run an order-import service on top of marshmallow, and since we rebuilt our images last week (picking up the latest 4.3.x) our import tests started disagreeing with production behaviour in a few places. Nothing crashes, but three things we depend on have changed. All of these are against one small, self-contained schema set that I've boiled our real code down to:

```python
from marshmallow import Schema, ValidationError, fields, validates


class LineSchema(Schema):
    sku = fields.Str(required=True)
    qty = fields.Int()
    price = fields.Float()

    @validates("qty")
    def check_qty(self, value, **kwargs):
        if value < 0:
            raise ValidationError("Quantity cannot be negative.")

    @validates("price")
    def check_price(self, value, **kwargs):
        if value <= 0:
            raise ValidationError("Price must be positive.")


class OrderSchema(Schema):
    ref = fields.Str(required=True)
    lines = fields.Nested(LineSchema(many=True))
    label = fields.Method("make_label", deserialize="parse_label")

    def make_label(self, order):
        return f"#{order['ref']}"

    def parse_label(self, value):
        return value.lstrip("#")
```

**1. Bulk line updates skip validation.** We PATCH order lines in bulk with `partial=True`:

```python
lines = [{"sku": "a", "price": 9.5}, {"sku": "b", "qty": -5}]
LineSchema(many=True).load(lines, partial=True)
# observed: [{'sku': 'a', 'price': 9.5}, {'sku': 'b', 'qty': -5}]
# expected: ValidationError {1: {'qty': ['Quantity cannot be negative.']}}
```
Whether the bad quantity is caught depends on what the other records in the batch contain; if every record has a `qty` it is rejected correctly.

**2. The `label` field disappeared from responses.**

```python
OrderSchema().dump({"ref": "1042", "lines": []})
# observed: {'ref': '1042', 'lines': []}
# expected: {'ref': '1042', 'lines': [], 'label': '#1042'}
```
Loading still works (`{"label": "#1042", ...}` gives `'1042'` for it), only the dumped output is missing the field.

**3. Our API error format for malformed `lines` changed.** A client sent an object where a list is expected:

```python
OrderSchema().load({"ref": "1042", "lines": {"sku": "a"}})
# observed: {'lines': {'_schema': ['Invalid input type.']}}
# expected: {'lines': ['Invalid type.']}
```
A client library we ship parses the `expected` shape, so this broke it.

Can you work out what's going on with each of these and fix them?
