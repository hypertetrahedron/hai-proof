import copy
import io
import json
import os
import pathlib
import subprocess
import sys

import pytest

from jsonpath_ng import DatumInContext
from jsonpath_ng import parse as classic_parse
from jsonpath_ng.exceptions import JsonPathParserError
from jsonpath_ng.rfc9535 import FunctionExtension
from jsonpath_ng.rfc9535 import LogicalType
from jsonpath_ng.rfc9535 import NodesType
from jsonpath_ng.rfc9535 import NOTHING
from jsonpath_ng.rfc9535 import ValueType
from jsonpath_ng.rfc9535 import normalized_path
from jsonpath_ng.rfc9535 import parse

HERE = pathlib.Path(__file__).parent
# These cases expect '^' and '$' to act as anchors, but in RFC 9485 (I-Regexp) they are ordinary
# characters, and the task tells the agent to follow the RFC. Implementations may go either way.
RFC9485_CONFLICTS = {
    "functions, match, explicit caret",
    "functions, match, explicit dollar",
}
CTS = [
    case
    for case in json.loads((HERE / "cts.json").read_text(encoding="utf-8"))["tests"]
    if case["name"] not in RFC9485_CONFLICTS
]


def canon(values):
    """Type-strict comparison: True != 1, 1 != 1.0 as JSON text."""
    return json.dumps(values, sort_keys=True, ensure_ascii=False)


def values(query, document, **kwargs):
    return [m.value for m in parse(query, **kwargs).find(document)]


def paths(query, document):
    return [normalized_path(m) for m in parse(query).find(document)]


# -- compliance test suite ---------------------------------------------------------


@pytest.mark.parametrize("case", CTS, ids=[f"{i}:{c['name']}" for i, c in enumerate(CTS)])
def test_compliance(case):
    if case.get("invalid_selector"):
        with pytest.raises(JsonPathParserError):
            parse(case["selector"])
        return
    document = copy.deepcopy(case["document"])
    matches = parse(case["selector"]).find(document)
    assert all(isinstance(m, DatumInContext) for m in matches)
    got = [m.value for m in matches]
    got_paths = [normalized_path(m) for m in matches]
    if "result" in case:
        assert canon(got) == canon(case["result"])
        if "result_paths" in case:
            assert got_paths == case["result_paths"]
    else:
        assert any(canon(got) == canon(r) for r in case["results"]), got
        if "results_paths" in case:
            assert got_paths in case["results_paths"]
    assert document == case["document"]


# -- API ---------------------------------------------------------------------------


def test_query_object_reusable_and_comparable():
    q = parse("$..a")
    assert values("$..a", {"a": 1, "b": {"a": 2}}) == [1, 2]
    assert [m.value for m in q.find([{"a": "x"}])] == ["x"]
    assert [m.value for m in q.find({"a": 3})] == [3]
    assert str(q) == "$..a"
    assert q == parse("$..a")
    assert hash(q) == hash(parse("$..a"))
    assert q != parse("$..b")


def test_find_returns_list_of_datum_in_context():
    matches = parse("$.a[*]").find({"a": [1, 2]})
    assert isinstance(matches, list)
    assert [m.value for m in matches] == [1, 2]
    assert parse("$.missing").find({}) == []


def test_document_not_modified():
    doc = {"a": [{"b": 1}, {"b": 2}], "c": {"d": [3, 4]}}
    before = copy.deepcopy(doc)
    for q in ["$..*", "$.a[?@.b > 1]", "$..[?length(@) > 0]", "$.a[::-1]", "$.x.y"]:
        parse(q).find(doc)
    assert doc == before


def test_duplicates_kept():
    assert values("$[0, 0, -2]", [5, 6]) == [5, 5, 5]
    assert paths("$[0, 0]", [5]) == ["$[0]", "$[0]"]


def test_normalized_path_escaping():
    doc = {"a'b": 1, "c\\d": 2, "e\nf": 3, "g\u0001h": 4, "i\u001fj": 5, "k\u007fl": 6, "é": 7, "\b\f\r\t": 8}
    got = dict(zip(paths("$.*", doc), values("$.*", doc)))
    assert got == {
        "$['a\\'b']": 1,
        "$['c\\\\d']": 2,
        "$['e\\nf']": 3,
        "$['g\\u0001h']": 4,
        "$['i\\u001fj']": 5,
        "$['k\u007fl']": 6,
        "$['é']": 7,
        "$['\\b\\f\\r\\t']": 8,
    }


def test_normalized_path_negative_index_and_descendants():
    doc = {"x": [[0, {"y": 1}], 2]}
    assert paths("$.x[-2][-1].y", doc) == ["$['x'][0][1]['y']"]
    assert paths("$..y", doc) == ["$['x'][0][1]['y']"]
    assert paths("$", doc) == ["$"]


def test_type_strict_comparisons():
    doc = [1, 1.0, True, "1", None, [1], {"a": 1}, False, 0]
    assert canon(values("$[?@ == 1]", doc)) == canon([1, 1.0])
    assert canon(values("$[?@ == true]", doc)) == canon([True])
    assert canon(values("$[?@ == false]", doc)) == canon([False])
    assert canon(values("$[?@ == 0]", doc)) == canon([0])
    assert canon(values("$[?@ == null]", doc)) == canon([None])
    assert canon(values("$[?@ == '1']", doc)) == canon(["1"])
    assert canon(values("$[?@ < 2]", doc)) == canon([1, 1.0, 0])
    assert canon(values("$[?@ >= true]", doc)) == canon([True])


def test_deep_structural_equality():
    doc = {"a": {"x": [1, {"y": True}]}, "b": {"x": [1, {"y": 1}]}, "c": {"x": [1.0, {"y": True}]}}
    assert values("$[?@.x == $.a.x]", doc) == [doc["a"], doc["c"]]


def test_nothing_comparisons():
    doc = [{"a": 1}, {"b": 2}, {}]
    assert values("$[?@.a == @.c]", doc) == [{"b": 2}, {}]
    assert values("$[?@.a != @.c]", doc) == [{"a": 1}]
    assert values("$[?@.a <= @.c]", doc) == [{"b": 2}, {}]
    assert values("$[?@.a < @.c]", doc) == []


def test_deeply_nested_document():
    depth = 5000
    doc = leaf = {}
    for _ in range(depth):
        leaf["n"] = {}
        leaf = leaf["n"]
    leaf["x"] = "bottom"
    assert values("$..x", doc) == ["bottom"]
    assert len(parse("$..n").find(doc)) == depth
    assert normalized_path(parse("$..x").find(doc)[0]) == "$" + "['n']" * depth + "['x']"


def test_parse_error_type_and_message():
    with pytest.raises(JsonPathParserError) as info:
        parse("$.a[?@.b ==]")
    assert str(info.value)
    with pytest.raises(JsonPathParserError):
        parse("$[?nosuchfunction(@)]")
    with pytest.raises(JsonPathParserError):
        parse(" $")
    with pytest.raises(JsonPathParserError):
        parse("$[9007199254740992]")
    parse("$[9007199254740991]")
    parse("$[-9007199254740991]")


def test_classic_parser_unchanged():
    data = {"foo": [{"baz": 1}, {"baz": 2}]}
    assert [m.value for m in classic_parse("foo[*].baz").find(data)] == [1, 2]
    assert [m.value for m in classic_parse("$.foo[1].baz").find(data)] == [2]


# -- regex functions -------------------------------------------------------------


def test_iregexp_dot_and_classes():
    doc = ["a\nb", "a\rb", "a b", "a\U0001F600b", "ab"]
    assert values("$[?match(@, 'a.b')]", doc) == ["a b", "a\U0001F600b"]
    assert values("$[?match(@, '\\\\p{Ll}+')]", ["abc", "aBc", "été"]) == ["abc", "été"]
    assert values("$[?search(@, '\\\\P{L}')]", ["abc", "ab1", "a b"]) == ["ab1", "a b"]
    assert values("$[?match(@, '\\\\p{Nd}{2}')]", ["12", "١٢", "1a"]) == ["12", "١٢"]


def test_invalid_regex_is_false_not_error():
    assert values("$[?match(@, '(')]", ["(", "a"]) == []
    assert values("$[?!search(@, '[')]", ["[", "a"]) == ["[", "a"]
    assert values("$[?match(@, 1)]", ["1"]) == []


# -- function extensions ----------------------------------------------------------


def test_custom_value_function():
    def first_word(value):
        if isinstance(value, str) and value.split():
            return value.split()[0]
        return NOTHING

    fns = {"first_word": FunctionExtension(first_word, (ValueType,), ValueType)}
    doc = [{"t": "The End"}, {"t": "A Start"}, {"t": ""}, {}]
    assert values("$[?first_word(@.t) == 'The']", doc, functions=fns) == [{"t": "The End"}]
    # Nothing == Nothing
    assert values("$[?first_word(@.t) == @.missing]", doc, functions=fns) == [{"t": ""}, {}]


def test_custom_function_receives_converted_arguments():
    seen = []

    def spy(value, flag, nodes):
        seen.append((value, flag, nodes))
        return True

    fns = {"spy": FunctionExtension(spy, (ValueType, LogicalType, NodesType), LogicalType)}
    parse("$[?spy(@.a, @.b, @.*)]", functions=fns).find([{"a": 1, "b": 0}, {"b": None}])
    (v1, f1, n1), (v2, f2, n2) = seen
    assert v1 == 1 and f1 is True
    assert all(isinstance(n, DatumInContext) for n in n1) and [n.value for n in n1] == [1, 0]
    assert v2 is NOTHING and f2 is True and [n.value for n in n2] == [None]
    seen.clear()
    parse("$[?spy(@.a, @.c == 2, @.zz)]", functions=fns).find([{"a": 1, "c": 3}])
    assert seen == [(1, False, [])]


def test_custom_nodes_function_and_count():
    def children(nodes):
        out = []
        for n in nodes:
            if isinstance(n.value, list):
                out.extend(DatumInContext(v) for v in n.value)
        return out

    fns = {"kids": FunctionExtension(children, (NodesType,), NodesType)}
    doc = [[1, 2], [], [3]]
    assert values("$[?count(kids(@)) == 2]", [doc], functions=fns) == []
    assert values("$[?count(kids($[*])) == 3]", [[1, 2, 3]], functions=fns) == [[1, 2, 3]]
    # NodesType result as a test expression: non-empty means true
    assert values("$[?kids(@)]", doc, functions=fns) == [[1, 2], [3]]
    # NodesType results cannot be compared
    with pytest.raises(JsonPathParserError):
        parse("$[?kids(@) == 1]", functions=fns)


def test_custom_function_well_typedness():
    lf = {"is_big": FunctionExtension(lambda v: isinstance(v, int) and v > 10, (ValueType,), LogicalType)}
    assert values("$[?is_big(@)]", [5, 50], functions=lf) == [50]
    with pytest.raises(JsonPathParserError):
        parse("$[?is_big(@) == true]", functions=lf)
    with pytest.raises(JsonPathParserError):
        parse("$[?is_big(@.*)]", functions=lf)  # non-singular query for ValueType
    with pytest.raises(JsonPathParserError):
        parse("$[?is_big(@, 1)]", functions=lf)
    vf = {"double": FunctionExtension(lambda v: v * 2 if isinstance(v, int) else NOTHING, (ValueType,), ValueType)}
    assert values("$[?double(@) == 4]", [1, 2, 3], functions=vf) == [2]
    with pytest.raises(JsonPathParserError):
        parse("$[?double(@)]", functions=vf)  # ValueType result is not a test


def test_custom_functions_are_per_parse_call_and_can_replace_builtins():
    fns = {"length": FunctionExtension(lambda v: 42, (ValueType,), ValueType)}
    assert values("$[?length(@) == 42]", ["a", 1], functions=fns) == ["a", 1]
    assert values("$[?length(@) == 1]", ["a", 1]) == ["a"]
    with pytest.raises(JsonPathParserError):
        parse("$[?extra(@)]")


@pytest.mark.parametrize("name", ["Upper", "1abc", "a-b", "", "a b"])
def test_invalid_function_names(name):
    with pytest.raises(ValueError):
        parse("$", functions={name: FunctionExtension(lambda v: v, (ValueType,), ValueType)})


def test_function_exceptions_propagate():
    def boom(value):
        raise RuntimeError("boom")

    q = parse("$[?boom(@) == 1]", functions={"boom": FunctionExtension(boom, (ValueType,), ValueType)})
    with pytest.raises(RuntimeError):
        q.find([1])


def test_nothing_is_falsy_singleton():
    import jsonpath_ng.rfc9535 as m

    assert not NOTHING
    assert m.NOTHING is NOTHING


# -- CLI ---------------------------------------------------------------------------


def run_cli(*args, stdin=""):
    return subprocess.run(
        [sys.executable, "-c", "import sys; from jsonpath_ng.bin.jsonpath import entry_point; entry_point()", *args],
        input=stdin.encode("utf-8"),
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def test_cli_rfc9535_values_and_paths(tmp_path):
    doc = {"a": [1, "xé", {"k": True}, None]}
    r = run_cli("--rfc9535", "$.a[*]", stdin=json.dumps(doc))
    assert r.returncode == 0, r.stderr
    assert r.stdout.decode("utf-8").splitlines() == ["1", '"xé"', '{"k": true}', "null"]
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    r = run_cli("--rfc9535", "--paths", "$.a[?@ == 1 || @ == null]", str(f))
    assert r.returncode == 0, r.stderr
    assert r.stdout.decode("utf-8").splitlines() == ["$['a'][0]\t1", "$['a'][3]\tnull"]


def test_cli_errors():
    r = run_cli("--rfc9535", "$[?@.a ==]", stdin="{}")
    assert r.returncode == 2
    assert r.stderr and b"Traceback" not in r.stderr
    r = run_cli("--paths", "$.a", stdin="{}")
    assert r.returncode == 2


def test_cli_classic_mode_unchanged():
    r = run_cli("foo[*].baz", stdin=json.dumps({"foo": [{"baz": 1}, {"baz": 2}]}))
    assert r.returncode == 0, r.stderr
    assert r.stdout.decode().splitlines() == ["1", "2"]
