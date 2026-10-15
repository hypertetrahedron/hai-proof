import asyncio
from collections import OrderedDict

import pytest

from jinja2 import DictLoader
from jinja2 import Environment
from jinja2 import meta
from jinja2 import TemplateAssertionError
from jinja2 import TemplateSyntaxError
from jinja2.nativetypes import NativeEnvironment
from jinja2.sandbox import SandboxedEnvironment


def render(source, env=None, **context):
    return (env or Environment()).from_string(source).render(**context)


def each(cases, values, env=None, **context):
    """Render one match over every value, joined with '|'."""
    source = (
        "{% for v in values %}{% if not loop.first %}|{% endif %}"
        "{% match v %}" + cases + "{% endmatch %}{% endfor %}"
    )
    return render(source, env, values=values, **context)


def syntax_error(source, env=None):
    with pytest.raises(TemplateSyntaxError) as info:
        (env or Environment()).from_string(source)
    return info.value


# -- statement ---------------------------------------------------------------


def test_first_matching_case_wins():
    cases = "{% case 1 %}one{% case 2 %}two{% case 1 %}again{% case _ %}other"
    assert each(cases, [1, 2, 3]) == "one|two|other"


def test_no_match_renders_nothing():
    assert render("[{% match 5 %}{% case 1 %}one{% endmatch %}]") == "[]"


def test_subject_evaluated_once():
    calls = []

    def subject():
        calls.append(1)
        return 9

    src = "{% match f() %}{% case 1 %}a{% case 2 %}b{% case n %}{{ n }}{% endmatch %}"
    assert render(src, f=subject) == "9"
    assert calls == [1]


def test_tuple_subject_and_bare_sequence_pattern():
    src = "{% match a, b %}{% case 1, x %}{{ x }}{% case _ %}no{% endmatch %}"
    assert render(src, a=1, b=7) == "7"
    assert render(src, a=2, b=7) == "no"


def test_whitespace_and_comments_before_first_case():
    src = "{% match 1 %}\n  {# pick #}\n  {%- case 1 %}one{% endmatch %}"
    assert render(src) == "one"


def test_whitespace_control_and_trim_blocks():
    src = (
        "<{% match v %}\n  {% case 1 %}\n    one\n  {% case _ %}\n    other\n"
        "{% endmatch %}>"
    )
    env = Environment(trim_blocks=True, lstrip_blocks=True)
    assert render(src, env, v=1) == "<    one\n>"
    assert render(src, env, v=2) == "<    other\n>"
    src = "{%- match 1 -%}\n  {%- case 1 -%}\n one \n{%- endmatch -%}"
    assert render(src) == "one"


def test_line_statements():
    env = Environment(line_statement_prefix="#")
    src = "# match v\n# case [a, b]\n{{ a + b }}\n# case _\nnone\n# endmatch\n"
    assert render(src, env, v=[1, 2]) == "3\n"
    assert render(src, env, v=5) == "none\n"


def test_match_and_case_still_usable_as_names():
    assert render("{{ match }}{% set case = 2 %}{{ case }}", match=1) == "12"


@pytest.mark.parametrize(
    "source",
    [
        "{% match 1 %}x{% case 1 %}{% endmatch %}",
        "{% match 1 %}{{ 2 }}{% case 1 %}{% endmatch %}",
        "{% match 1 %}{% endmatch %}",
        "{% case 1 %}",
        "{% endmatch %}",
        "{% match 1 %}{% case 1 %}",
        "{% match 1 %}{% case 1 %}{% endfor %}",
    ],
)
def test_statement_syntax_errors(source):
    syntax_error(source)


# -- literal, capture and value patterns -------------------------------------


def test_literals():
    cases = (
        '{% case "a" %}A{% case 2 %}two{% case 1.5 %}f{% case -3 %}neg'
        "{% case -0.5 %}negf{% case _ %}-"
    )
    assert each(cases, ["a", 2, 1.5, -3, -0.5, "b", 2.0]) == "A|two|f|neg|negf|-|two"


def test_singletons_match_by_identity():
    cases = "{% case true %}T{% case false %}F{% case none %}N{% case 1 %}one{% case _ %}-"
    assert each(cases, [True, False, None, 1, 0]) == "T|F|N|one|-"
    cases = "{% case True %}T{% case False %}F{% case None %}N{% case _ %}-"
    assert each(cases, [True, False, None, 1]) == "T|F|N|-"


def test_capture_and_wildcard():
    assert render("{% match v %}{% case x %}<{{ x }}>{% endmatch %}", v=[1]) == "<[1]>"
    assert render("{% match v %}{% case _ %}any{{ _ }}{% endmatch %}", v=3) == "any"


def test_dotted_value_pattern():
    class Colors:
        RED = "r"
        GREEN = "g"

    cases = "{% case colors.RED %}red{% case colors.GREEN %}green{% case c %}{{ c }}"
    assert each(cases, ["r", "g", "b"], colors=Colors) == "red|green|b"
    nested = {"a": {"b": 5}}
    src = "{% match 5 %}{% case cfg.a.b %}yes{% case _ %}no{% endmatch %}"
    assert render(src, cfg=nested) == "yes"


def test_loop_attribute_value_pattern():
    src = (
        "{% for i in [1, 2] %}{% match true %}{% case loop.first %}F"
        "{% case _ %}-{% endmatch %}{% endfor %}"
    )
    assert render(src) == "F-"


def test_capture_shadows_outer_name_instead_of_comparing():
    src = "{% match 5 %}{% case x %}{{ x }}{% endmatch %}"
    assert render(src, x=1) == "5"


# -- sequence patterns -------------------------------------------------------


def test_sequence_exact_length():
    cases = "{% case [a, b] %}{{ a }}+{{ b }}{% case [a] %}1:{{ a }}{% case [] %}empty{% case _ %}-"
    assert each(cases, [[1, 2], (3, 4), [5], (), [1, 2, 3]]) == "1+2|3+4|1:5|empty|-"


def test_sequence_paren_forms():
    cases = "{% case (a, b) %}two{% case (a,) %}one {{ a }}{% case () %}empty{% case (x) %}x={{ x }}"
    assert each(cases, [[1, 2], [7], [], 9]) == "two|one 7|empty|x=9"


def test_star_patterns():
    cases = (
        "{% case [first, *mid, last] %}{{ first }}/{{ mid }}/{{ last }}"
        "{% case [only] %}only{% case [] %}none"
    )
    assert each(cases, [[1, 2, 3, 4], [1, 2], [1], []]) == (
        "1/[2, 3]/4|1/[]/2|only|none"
    )


def test_star_rest_is_always_a_list():
    src = "{% match v %}{% case [*rest] %}{{ rest.__class__.__name__ }}{{ rest }}{% endmatch %}"
    assert render(src, v=(1, 2)) == "list[1, 2]"
    assert render(src, v=range(3)) == "list[0, 1, 2]"


def test_star_wildcard():
    src = "{% match v %}{% case [_, *_, x] %}{{ x }}{% case _ %}short{% endmatch %}"
    assert render(src, v=[1, 2, 3, 4]) == "4"
    assert render(src, v=[1]) == "short"


def test_strings_bytes_iterators_are_not_sequences():
    cases = "{% case [a, b] %}S{% case _ %}-"
    values = ["ab", b"ab", bytearray(b"ab"), iter([1, 2]), (x for x in [1, 2])]
    assert each(cases, values) == "-|-|-|-|-"
    assert each(cases, [range(2), (1, 2)]) == "S|S"


def test_nested_sequences():
    cases = "{% case [[a, b], [c, *_]] %}{{ a }}{{ b }}{{ c }}{% case _ %}-"
    assert each(cases, [[[1, 2], [3, 4, 5]], [[1, 2], []], [[1], [3]]]) == "123|-|-"


# -- mapping patterns --------------------------------------------------------


def test_mapping_pattern():
    cases = (
        '{% case {"type": "user", "name": name} %}user {{ name }}'
        '{% case {"type": "group"} %}group{% case {} %}map{% case _ %}-'
    )
    values = [
        {"type": "user", "name": "ann", "extra": 1},
        {"type": "group", "members": []},
        {"other": 1},
        [("type", "user")],
        "type",
    ]
    assert each(cases, values) == "user ann|group|map|-|-"


def test_mapping_rest():
    src = '{% match v %}{% case {"a": 1, **rest} %}{{ rest|dictsort }}{% endmatch %}'
    assert render(src, v=OrderedDict([("a", 1), ("b", 2), ("c", 3)])) == (
        "[('b', 2), ('c', 3)]"
    )
    src = '{% match v %}{% case {"a": _, **rest} %}{{ rest.__class__.__name__ }}{% endmatch %}'
    assert render(src, v={"a": 1}) == "dict"


def test_mapping_rest_is_a_copy():
    data = {"a": 1, "b": 2}
    src = '{% match v %}{% case {"a": _, **rest} %}{{ rest.pop("b") }}{% endmatch %}'
    assert render(src, v=data) == "2"
    assert data == {"a": 1, "b": 2}


def test_mapping_literal_and_dotted_keys():
    class K:
        name = "n"

    cases = (
        "{% case {1: one, none: n} %}{{ one }}{{ n }}"
        "{% case {keys.name: v} %}v={{ v }}{% case {-1: m} %}m={{ m }}{% case _ %}-"
    )
    values = [{1: "x", None: "y"}, {"n": 4}, {-1: 0}, {1: "x"}]
    assert each(cases, values, keys=K) == "xy|v=4|m=0|-"


def test_mapping_value_may_be_present_but_none():
    src = '{% match v %}{% case {"k": none} %}null{% case {"k": x} %}{{ x }}{% case _ %}missing{% endmatch %}'
    assert render(src, v={"k": None}) == "null"
    assert render(src, v={}) == "missing"


def test_nested_mapping_and_sequence():
    src = (
        '{% match v %}{% case {"items": [{"id": first}, *_], "meta": {"n": n}} %}'
        "{{ first }}/{{ n }}{% case _ %}-{% endmatch %}"
    )
    assert render(src, v={"items": [{"id": 7}, {"id": 8}], "meta": {"n": 2}}) == "7/2"
    assert render(src, v={"items": [], "meta": {"n": 2}}) == "-"


# -- alternatives, as, tests -------------------------------------------------


def test_or_pattern():
    cases = '{% case 1 | 2 | 3 %}small{% case "a" | "b" %}ab{% case _ %}-'
    assert each(cases, [1, 3, "b", 4]) == "small|small|ab|-"


def test_or_pattern_with_captures():
    cases = "{% case [x, 0] | [0, x] %}{{ x }}{% case _ %}-"
    assert each(cases, [[5, 0], [0, 6], [1, 1]]) == "5|6|-"


def test_as_pattern():
    src = "{% match v %}{% case [1 | 2 as n, *rest] as whole %}{{ n }} {{ whole }}{% case _ %}-{% endmatch %}"
    assert render(src, v=[2, 9]) == "2 [2, 9]"
    assert render(src, v=[3, 9]) == "-"


def test_as_binds_looser_than_or():
    src = "{% match v %}{% case 1 | 2 as n %}{{ n }}{% case _ %}-{% endmatch %}"
    assert render(src, v=1) == "1"
    assert render(src, v=2) == "2"


def test_test_patterns():
    cases = (
        "{% case is not number %}NaN{% case is divisibleby(3) %}fizz"
        "{% case is in([1, 2]) %}low{% case _ %}num"
    )
    assert each(cases, ["x", 9, 1, 4]) == "NaN|fizz|low|num"


def test_test_pattern_with_as_and_nested():
    cases = "{% case [is number as n, _] | [_, is number as n] %}{{ n }}{% case _ %}-"
    assert each(cases, [[1, "a"], ["a", 2], ["a", "b"]]) == "1|2|-"


def test_custom_test_and_outer_arguments():
    env = Environment()
    env.tests["even"] = lambda x: x % 2 == 0
    cases = "{% case is even %}even{% case is divisibleby(step) %}step{% case _ %}-"
    assert each(cases, [2, 3, 5], env, step=3) == "even|step|-"


def test_unknown_test_fails_at_compile_time():
    with pytest.raises(TemplateAssertionError):
        Environment().from_string("{% match 1 %}{% case is nosuchtest %}{% endmatch %}")


# -- guards ------------------------------------------------------------------


def test_guards():
    cases = (
        "{% case [x, y] if x == y %}same{% case [x, y] if x > limit %}big {{ x }}"
        "{% case [x, y] %}pair{% case _ %}-"
    )
    assert each(cases, [[1, 1], [9, 1], [1, 2], 5], limit=5) == "same|big 9|pair|-"


def test_guard_allows_irrefutable_case_before_others():
    cases = "{% case n if n > 2 %}big{% case n %}small {{ n }}"
    assert each(cases, [3, 1]) == "big|small 1"


# -- compile time pattern errors ---------------------------------------------


@pytest.mark.parametrize(
    "pattern",
    [
        "[a, a]",
        '{"x": a, **a}',
        "[a, b] as a",
        "[a] | [b]",
        "a | 1",
        "[*a, *b]",
        "*a",
        "(*a)",
        "{**_}",
        '{"a": 1, "a": 2}',
        "1 as true",
        "1 as _",
        "[*none]",
        "_ | 1",
        '{**rest, "a": 1}',
    ],
)
def test_pattern_syntax_errors(pattern):
    syntax_error("{% match 1 %}{% case " + pattern + " %}x{% case 1 %}y{% endmatch %}")


@pytest.mark.parametrize("pattern", ["_", "x", "x as y", "1 | _", "(x)", "[1] | _ as y"])
def test_irrefutable_case_must_be_last(pattern):
    src = "{% match 1 %}\n{% case 2 %}\n{% case " + pattern + " %}\n{% case 3 %}\n{% endmatch %}"
    assert syntax_error(src).lineno == 3
    # as the last case it is fine
    Environment().from_string("{% match 1 %}{% case 2 %}{% case " + pattern + " %}{% endmatch %}")


def test_error_line_number():
    src = "{% match v %}\n{% case 1 %}\n\n{% case [a, a] %}\n{% endmatch %}"
    assert syntax_error(src).lineno == 4


# -- scoping -----------------------------------------------------------------


def test_captures_do_not_leak():
    src = (
        "{% set x = 'outer' %}{% match [1, 2] %}{% case [x, y] %}{{ x }}{{ y }}"
        "{% endmatch %}|{{ x }}|{{ y is defined }}"
    )
    assert render(src) == "12|outer|False"


def test_set_in_case_body_does_not_leak():
    src = (
        "{% set a = 1 %}{% match 0 %}{% case _ %}{% set a = 2 %}{% set b = 3 %}"
        "{{ a }}{{ b }}{% endmatch %}|{{ a }}|{{ b is defined }}"
    )
    assert render(src) == "23|1|False"


def test_set_in_case_body_is_not_exported():
    tmpl = Environment().from_string(
        "{% match 1 %}{% case 1 %}{% set hidden = 3 %}{% endmatch %}{% set shown = 4 %}"
    )
    module = tmpl.module
    assert module.shown == 4
    assert not hasattr(module, "hidden")


def test_namespace_carries_values_out():
    src = (
        "{% set ns = namespace(total=0) %}{% for v in values %}{% match v %}"
        "{% case is number %}{% set ns.total = ns.total + v %}{% case _ %}{% endmatch %}"
        "{% endfor %}{{ ns.total }}"
    )
    assert render(src, values=[1, "a", 2]) == "3"


def test_captures_visible_in_nested_constructs():
    src = (
        "{% match v %}{% case [x, items] %}"
        "{% for i in items %}{% if i > x %}{% match i %}{% case 9 %}nine"
        "{% case j %}{{ x }}<{{ j }}{% endmatch %}{% endif %}{% endfor %}"
        "{% endmatch %}"
    )
    assert render(src, v=[2, [1, 3, 9]]) == "2<3nine"


def test_captures_visible_in_macros_and_call_blocks():
    src = (
        "{% match v %}{% case [a, b] %}{% macro m() %}{{ a }}-{{ b }}{% endmacro %}"
        "{{ m() }}{% endmatch %}"
    )
    assert render(src, v=[1, 2]) == "1-2"
    src = (
        "{% macro m(x) %}{% match x %}{% case (a, b) %}{{ caller(a, b) }}"
        "{% case _ %}?{% endmatch %}{% endmacro %}"
        "{% call(p, q) m(v) %}{{ p * q }}{% endcall %}"
    )
    assert render(src, v=[3, 4]) == "12"
    assert render(src, v=5) == "?"


def test_captures_visible_in_includes_and_blocks():
    env = Environment(
        loader=DictLoader(
            {
                "inc": "[{{ name }}]",
                "base": "<{% block b %}{% endblock %}>",
                "child": "{% extends 'base' %}{% block b %}{% match v %}"
                "{% case {'n': name} %}{% include 'inc' %}{% endmatch %}{% endblock %}",
            }
        )
    )
    assert env.get_template("child").render(v={"n": "ann"}) == "<[ann]>"


def test_nested_match():
    src = (
        "{% match v %}{% case [x, y] %}{% match y %}{% case {'k': z} %}{{ x }}/{{ z }}"
        "{% case _ %}{{ x }}/-{% endmatch %}{% endmatch %}"
    )
    assert render(src, v=[1, {"k": 2}]) == "1/2"
    assert render(src, v=[1, 3]) == "1/-"


def test_loopcontrols():
    env = Environment(extensions=["jinja2.ext.loopcontrols"])
    src = (
        "{% for i in range(6) %}{% match i %}{% case 4 %}{% break %}"
        "{% case 1 | 2 %}{% continue %}{% case _ %}{{ i }}{% endmatch %}{% endfor %}"
    )
    assert render(src, env) == "03"


# -- meta, async, sandbox, native --------------------------------------------


def test_find_undeclared_variables():
    env = Environment()
    ast = env.parse(
        "{% match x %}{% case [a, *b] if a > limit %}{{ a }}{{ b }}{{ c }}"
        "{% case consts.RED %}r{% case is divisibleby(n) %}"
        "{% case {k.v: q, **rest} %}{{ q }}{{ rest }}{% endmatch %}{{ a }}"
    )
    assert meta.find_undeclared_variables(ast) == {
        "x",
        "limit",
        "c",
        "consts",
        "n",
        "k",
        "a",
    }


def test_async():
    async def get():
        return {"user": {"name": "bo"}, "tags": ["x", "y"]}

    class C:
        RED = "x"

    env = Environment(enable_async=True)
    src = (
        "{% match get() %}{% case {'user': {'name': n}, 'tags': [colors.RED, *more]} %}"
        "{{ n }} {{ more }}{% case _ %}-{% endmatch %}"
        "{% match 4 %}{% case is divisibleby(2) %} even{% endmatch %}"
    )
    tmpl = env.from_string(src)
    assert asyncio.run(tmpl.render_async(get=get, colors=C)) == "bo ['y'] even"


def test_async_loop():
    env = Environment(enable_async=True)
    src = (
        "{% for v in values %}{% match v %}{% case [a, b] %}{{ a + b }}"
        "{% case _ %}-{% endmatch %}{% endfor %}"
    )
    tmpl = env.from_string(src)
    assert asyncio.run(tmpl.render_async(values=[[1, 2], 3])) == "3-"


def test_sandbox_value_patterns_use_sandbox_lookup():
    class C:
        pass

    src = "{% match v %}{% case obj.__class__ %}cls{% case _ %}no{% endmatch %}"
    assert render(src, Environment(), v=C, obj=C()) == "cls"
    assert render(src, SandboxedEnvironment(), v=C, obj=C()) == "no"


def test_sandbox_basic_matching():
    src = '{% match v %}{% case {"a": [x, *_]} %}{{ x }}{% endmatch %}'
    assert render(src, SandboxedEnvironment(), v={"a": [1, 2]}) == "1"


def test_native_environment():
    env = NativeEnvironment()
    src = "{% match v %}{% case [a, b] %}{{ a + b }}{% case _ %}{{ none }}{% endmatch %}"
    assert env.from_string(src).render(v=(2, 3)) == 5
    assert env.from_string(src).render(v=1) is None


def test_existing_syntax_unchanged():
    src = "{% for i in x %}{% if i is odd %}{{ i }}{% endif %}{% endfor %}"
    assert render(src, x=range(5)) == "13"
