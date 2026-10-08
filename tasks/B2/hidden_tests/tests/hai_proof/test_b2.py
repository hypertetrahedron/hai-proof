import pytest

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


class OrderByClassSchema(Schema):
    lines = fields.Nested(LineSchema, many=True)


# 1. bulk partial loads keep running field validators


def test_bulk_partial_validates_after_record_missing_field():
    with pytest.raises(ValidationError) as exc:
        LineSchema(many=True).load(
            [{"sku": "a", "price": 9.5}, {"sku": "b", "qty": -5}], partial=True
        )
    assert exc.value.messages == {1: {"qty": ["Quantity cannot be negative."]}}


def test_bulk_partial_every_field_validated_for_every_record():
    with pytest.raises(ValidationError) as exc:
        LineSchema(many=True).load(
            [
                {"sku": "a"},
                {"sku": "b", "qty": -1},
                {"sku": "c", "price": 3.0},
                {"sku": "d", "price": -3.0, "qty": -2},
            ],
            partial=True,
        )
    assert exc.value.messages == {
        1: {"qty": ["Quantity cannot be negative."]},
        3: {
            "qty": ["Quantity cannot be negative."],
            "price": ["Price must be positive."],
        },
    }


def test_bulk_partial_valid_batch_loads():
    data = [{"sku": "a"}, {"price": 2.0}, {"qty": 4}]
    assert LineSchema(many=True).load(data, partial=True) == data


def test_single_partial_unchanged():
    with pytest.raises(ValidationError):
        LineSchema().load({"qty": -1}, partial=True)


# 2. Method field with both serialize and deserialize is dumped and loaded


def test_method_field_with_both_directions_is_dumped():
    assert OrderSchema().dump({"ref": "1042", "lines": []}) == {
        "ref": "1042",
        "lines": [],
        "label": "#1042",
    }


def test_method_field_with_both_directions_is_loaded():
    out = OrderSchema().load({"ref": "1042", "label": "#77"})
    assert out == {"ref": "1042", "label": "77"}


def test_method_field_one_direction_flags():
    class S(Schema):
        a = fields.Method("get_a")
        b = fields.Method(deserialize="set_b")

        def get_a(self, obj):
            return 1

        def set_b(self, value):
            return value

    s = S()
    assert s.dump({"b": 2}) == {"a": 1}
    assert s.load({"b": 2}) == {"b": 2}
    with pytest.raises(ValidationError):
        s.load({"a": 1})


# 3. type error for a non-collection under Nested(Schema(many=True))


def test_nested_instance_many_wrong_type_message():
    with pytest.raises(ValidationError) as exc:
        OrderSchema().load({"ref": "1042", "lines": {"sku": "a"}})
    assert exc.value.messages == {"lines": ["Invalid type."]}


def test_nested_class_many_wrong_type_message():
    with pytest.raises(ValidationError) as exc:
        OrderByClassSchema().load({"lines": "nope"})
    assert exc.value.messages == {"lines": ["Invalid type."]}


def test_nested_instance_many_valid_and_errors():
    out = OrderSchema().load({"ref": "1", "lines": [{"sku": "a", "qty": 1}]})
    assert out["lines"] == [{"sku": "a", "qty": 1}]
    with pytest.raises(ValidationError) as exc:
        OrderSchema().load({"ref": "1", "lines": [{"qty": 1}]})
    assert exc.value.messages == {"lines": {0: {"sku": ["Missing data for required field."]}}}
