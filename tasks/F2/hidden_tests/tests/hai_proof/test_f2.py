import pytest

from marshmallow import Schema, ValidationError, fields, validate

DUP = "Items must be unique."


class TagsSchema(Schema):
    tags = fields.List(fields.String(), unique=True)


class PointSchema(Schema):
    x = fields.Int()
    y = fields.Int()


class PathSchema(Schema):
    points = fields.List(fields.Nested(PointSchema), unique=True)


# validate.Unique


def test_validator_accepts_unique_and_empty():
    v = validate.Unique()
    assert v([1, 2, 3]) == [1, 2, 3]
    assert v([]) == []
    assert v(["a"]) == ["a"]
    assert v(("a", "b")) == ("a", "b")


def test_validator_rejects_duplicates():
    with pytest.raises(ValidationError) as excinfo:
        validate.Unique()([1, 2, 1])
    assert excinfo.value.messages == [DUP]


def test_validator_handles_unhashable_items():
    v = validate.Unique()
    v([{"a": 1}, {"a": 2}, [1], [2]])
    with pytest.raises(ValidationError):
        v([{"a": 1}, {"a": 2}, {"a": 1}])
    with pytest.raises(ValidationError):
        v([[1, 2], [3], [1, 2]])


def test_validator_custom_error():
    with pytest.raises(ValidationError) as excinfo:
        validate.Unique(error="no repeats")(["a", "a"])
    assert excinfo.value.messages == ["no repeats"]


# fields.List(unique=True)


def test_list_unique_default_off():
    assert fields.List(fields.String()).deserialize(["a", "a"]) == ["a", "a"]


def test_list_unique_accepts_distinct_and_empty():
    schema = TagsSchema()
    assert schema.load({"tags": ["a", "b", "c"]}) == {"tags": ["a", "b", "c"]}
    assert schema.load({"tags": []}) == {"tags": []}
    assert schema.load({"tags": ["only"]}) == {"tags": ["only"]}


def test_list_unique_rejects_duplicates_in_schema_load():
    with pytest.raises(ValidationError) as excinfo:
        TagsSchema().load({"tags": ["a", "b", "a"]})
    assert excinfo.value.messages == {"tags": [DUP]}


def test_list_unique_compares_deserialized_values():
    field = fields.List(fields.Int(), unique=True)
    assert field.deserialize(["1", "2"]) == [1, 2]
    with pytest.raises(ValidationError) as excinfo:
        field.deserialize([1, "1"])
    assert excinfo.value.messages == [DUP]


def test_list_unique_with_nested_items():
    schema = PathSchema()
    ok = {"points": [{"x": 1, "y": 2}, {"x": 2, "y": 1}]}
    assert schema.load(ok) == ok
    with pytest.raises(ValidationError) as excinfo:
        schema.load({"points": [{"x": 1, "y": 2}, {"x": 2, "y": 1}, {"x": 1, "y": 2}]})
    assert excinfo.value.messages == {"points": [DUP]}


def test_list_unique_item_errors_reported_without_duplicate_error():
    with pytest.raises(ValidationError) as excinfo:
        TagsSchema().load({"tags": ["a", 5, "a"]})
    assert excinfo.value.messages == {"tags": {1: ["Not a valid string."]}}


def test_list_unique_custom_error_message():
    class S(Schema):
        tags = fields.List(
            fields.String(),
            unique=True,
            error_messages={"duplicate": "No repeated tags allowed."},
        )

    with pytest.raises(ValidationError) as excinfo:
        S().load({"tags": ["a", "a"]})
    assert excinfo.value.messages == {"tags": ["No repeated tags allowed."]}


def test_list_unique_combined_with_other_validators():
    class S(Schema):
        tags = fields.List(fields.String(), unique=True, validate=validate.Length(max=2))

    with pytest.raises(ValidationError) as excinfo:
        S().load({"tags": ["a", "a", "b"]})
    messages = excinfo.value.messages["tags"]
    assert DUP in messages
    assert len(messages) == 2


def test_list_unique_in_many_schema_reports_index():
    with pytest.raises(ValidationError) as excinfo:
        TagsSchema(many=True).load([{"tags": ["a"]}, {"tags": ["b", "b"]}])
    assert excinfo.value.messages == {1: {"tags": [DUP]}}


def test_list_unique_does_not_affect_dump():
    assert TagsSchema().dump({"tags": ["a", "a"]}) == {"tags": ["a", "a"]}


def test_list_unique_none_items():
    field = fields.List(fields.String(allow_none=True), unique=True)
    assert field.deserialize(["a", None]) == ["a", None]
    with pytest.raises(ValidationError):
        field.deserialize([None, None])
