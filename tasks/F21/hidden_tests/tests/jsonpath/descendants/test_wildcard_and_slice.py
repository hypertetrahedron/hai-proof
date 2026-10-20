"""
Descendant wildcards and slices must follow RFC 9535, sections 2.3.2.2 and 2.3.4.2.2.

A wildcard selects the children of an object or array and nothing from a scalar.
A slice selects nothing from a value that is not an array.
"""

import pytest

import jsonpath_ng
import jsonpath_ng.ext

parsers = pytest.mark.parametrize(
    "parse",
    (jsonpath_ng.parse, jsonpath_ng.ext.parse),
    ids=lambda function: function.__module__,
)


def paths_and_values(parse, expression, data):
    matches = parse(expression).find(data)
    return {str(match.full_path): match.value for match in matches}, len(matches)


@parsers
def test_wildcard_selects_object_members_and_array_elements(parse):
    data = {"a": ["foo", "bar"]}

    found, count = paths_and_values(parse, "$..[*]", data)

    assert count == 3
    assert found == {"a": ["foo", "bar"], "a.[0]": "foo", "a.[1]": "bar"}


@parsers
def test_wildcard_rfc_nested_example(parse):
    data = {"o": {"j": 1, "k": 2}, "a": [5, 3, [{"j": 4}, {"k": 6}]]}

    found, count = paths_and_values(parse, "$..[*]", data)

    assert count == 11
    assert found == {
        "o": {"j": 1, "k": 2},
        "a": [5, 3, [{"j": 4}, {"k": 6}]],
        "o.j": 1,
        "o.k": 2,
        "a.[0]": 5,
        "a.[1]": 3,
        "a.[2]": [{"j": 4}, {"k": 6}],
        "a.[2].[0]": {"j": 4},
        "a.[2].[1]": {"k": 6},
        "a.[2].[0].j": 4,
        "a.[2].[1].k": 6,
    }


@pytest.mark.parametrize("data", (5, "abc", None, True))
@parsers
def test_wildcard_selects_nothing_from_a_scalar(parse, data):
    assert parse("$..[*]").find(data) == []


@parsers
def test_wildcard_full_paths_round_trip(parse):
    """The full path of every match must find the same value in the same data."""
    data = {"a": ["foo", "bar"]}

    for match in parse("$..[*]").find(data):
        found = parse(str(match.full_path)).find(data)
        assert [m.value for m in found] == [match.value], str(match.full_path)


@pytest.mark.parametrize(
    "expression, expected",
    (
        ("$..[:1]", ["a.[0]", "b.[0]"]),
        ("$..[0:2]", ["a.[0]", "a.[1]", "b.[0]", "b.[1]"]),
        ("$..[1:]", ["a.[1]", "b.[1]"]),
    ),
)
@parsers
def test_slice_selects_nothing_from_objects_and_scalars(parse, expression, expected):
    data = {"a": ["foo", "bar"], "b": [1, 2], "c": {"d": 3}, "e": "text"}

    found = parse(expression).find(data)

    assert sorted(str(match.full_path) for match in found) == expected
