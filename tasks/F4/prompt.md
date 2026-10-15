Our templates are full of long `if`/`elif` ladders that pick apart the shape of the data they are given: "if it's a list of two things do this, if it's a dict with a `type` of `user` do that, if it's a string do something else". Python has had structural pattern matching for a while and I'd like the same thing in Jinja: a `{% match %}` statement, modelled on Python's `match` but adapted to template syntax. Please add it to the core language (not as an extension), so it works with every `Environment` out of the box.

```jinja
{% match event %}
  {% case {"type": "login", "user": {"name": name}} %}
    {{ name }} logged in
  {% case {"type": "error", "code": 500 | 503 as code} if not quiet %}
    server error {{ code }}
  {% case [first, *rest] %}
    batch of {{ rest|length + 1 }} starting with {{ first }}
  {% case is string %}
    note: {{ event }}
  {% case _ %}
    unknown event
{% endmatch %}
```

## The statement

- `{% match <expression> %}` … one or more `{% case <pattern> [if <guard>] %}` sections … `{% endmatch %}`. The subject may be any expression, including a bare tuple (`{% match a, b %}`). It is evaluated exactly once.
- The cases are tried top to bottom. The first case whose pattern matches **and** whose guard (if any) is truthy is rendered, and no other case is. If nothing matches, the statement renders nothing. A guard is an ordinary expression and can use the names the pattern bound.
- The body of a case is everything up to the next `case` or `endmatch`, rendered like the body of an `if`, so whitespace and whitespace control (`{%- … -%}`, `trim_blocks`, `lstrip_blocks`) behave as they do for `if`/`elif`. Line statements work too (`# match x` / `# case 1` / `# endmatch`).
- Between `{% match … %}` and the first `case` only whitespace and comments are allowed. Anything else is a `TemplateSyntaxError`. A `match` without any `case` is a `TemplateSyntaxError`, as is a `case` or `endmatch` outside a `match`, or a missing `endmatch`.

## Patterns

| Pattern | Matches | Binds |
|---|---|---|
| `_` | anything | nothing |
| `name` (a bare name) | anything | the subject to `name` |
| a literal: string, integer, float, negative number (`-1`, `-2.5`) | a subject that is `==` to it | nothing |
| `none` / `None`, `true` / `True`, `false` / `False` | a subject that *is* that object (identity, so `true` does not match `1`) | nothing |
| a dotted name, `colors.RED`, `loop.first`, `a.b.c` | a subject `==` to the value, looked up exactly like `{{ colors.RED }}` would look it up | nothing |
| `[p1, p2, …]` or `(p1, p2, …)` | a sequence (see below) of exactly that length whose items match | whatever the items bind |
| `[p1, *rest, p2]` | a sequence of at least the non-star length; `rest` gets the middle items as a **list** (`*_` binds nothing) | |
| `{key: p, …}` | a mapping that contains every listed key, whose values match; extra keys are allowed | |
| `{key: p, …, **rest}` | as above; `rest` gets a new `dict` of the keys that were not listed | |
| `p1 \| p2 \| …` | the first alternative that matches | |
| `p as name` | `p` matches | what `p` binds, plus the matched value as `name` |
| `is test`, `is test(args…)`, `is not test` | the Jinja test (`string`, `number`, `divisibleby(3)`, `in([1, 2])`, a custom test, …) passes / fails for the subject | nothing |

Details:

- Patterns nest arbitrarily: `{"items": [{"id": id}, *_]}`, `[is number as n, _] | [_, is number as n]`.
- A top-level comma-separated list without brackets is a sequence pattern: `{% case a, b %}` is `{% case [a, b] %}`. `(p)` is just `p` in parentheses, `(p,)` and `()` are sequence patterns.
- `as` binds more loosely than `|`, so `1 | 2 as n` binds `n` for either alternative.
- **Sequences** are instances of `collections.abc.Sequence` (lists, tuples, `range`, …) except `str`, `bytes` and `bytearray`, which never match a sequence pattern. Iterators and generators are not sequences.
- **Mappings** are instances of `collections.abc.Mapping`. Keys in a mapping pattern must be literals (including `none`/`true`/`false`) or dotted names; a key is present if `key in subject`. `**rest` must be the last item, and `**_` is not allowed.
- A value pattern looks up dotted names the same way `{{ a.b }}` does, so a `SandboxedEnvironment` applies its usual rules to them, and in async mode the lookups and test calls behave like they do elsewhere in the template.
- Any test name that is valid after `is` in an expression is valid in a test pattern. A test pattern naming a test the environment does not have fails when the template is compiled (`TemplateAssertionError`), just like `{{ x is nosuchtest }}`.

### Errors at compile time (`TemplateSyntaxError`, with the line number of the offending `case`)

- The same name bound twice in one pattern (`[a, a]`, `{"x": a, **a}`, `[a, b] as a`).
- Alternatives of `|` that bind different sets of names (`[a] | [b]`, `a | 1`).
- More than one star in a sequence pattern, a star outside a sequence pattern, or `**_`.
- The same literal key twice in one mapping pattern.
- Binding a literal name (`true`, `none`, …) or `_` with `as` or a star (only `*_` is allowed, meaning "ignore").
- An *irrefutable* pattern that is not the last thing it could be: a case without a guard whose pattern matches everything (`_`, a bare name, `x as y` where `x` is irrefutable, or an alternation containing one) followed by more cases; or an irrefutable alternative followed by more alternatives (`_ | 1`).

## Scoping

Each case is its own scope, like the body of a `{% with %}` block:

- Names bound by the pattern exist only inside that case (guard and body). After `endmatch`, a name that was shadowed by a capture has its old value again, and a name that did not exist before is still undefined.
- `{% set %}` inside a case body does not leak out of the `match`, and does not export anything from the template module, even at the top level of a template. (Use a `namespace()` to carry a value out, which must keep working.)
- Captured names are visible to everything inside the body as you would expect: nested `match`/`for`/`if` statements, macros defined or called in the body (including `caller()` in `call` blocks), and templates `include`d from the body.
- `{% break %}` and `{% continue %}` (with the `loopcontrols` extension) inside a case body affect the enclosing `for` loop.
- `jinja2.meta.find_undeclared_variables` must understand the new statement: the names a pattern binds are not undeclared inside its case, but the subject, the root names of dotted value patterns and mapping keys, the arguments of test patterns, and everything else a guard or body uses from outside are.

## Everything else

- It has to work in sync and async (`enable_async=True`, including awaitable subjects such as an async function call) environments, the sandbox, and `NativeEnvironment` (a case body that outputs a single expression gives a native value, as with `if`).
- A template that does not use the new syntax must compile and render exactly as it does now, and `match`/`case` stay usable as ordinary variable names in expressions (`{{ match }}`, `{% set case = 1 %}`).
- Please document the statement in `docs/templates.rst` next to the other control structures.
