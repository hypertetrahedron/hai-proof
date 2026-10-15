We want to move our services to standard JSONPath, RFC 9535, but jsonpath-ng speaks its own dialect: different filter syntax, no `match`/`search`/`value`, Python-ish comparisons and so on (see the long-standing upstream issue "not RFC 9535 compliant"). Please add a strict RFC 9535 implementation to the library, next to the existing parser, without changing how `jsonpath_ng.parse` / `jsonpath_ng.ext.parse` behave.

I've put the text of RFC 9535 and of RFC 9485 (I-Regexp, which `match()` and `search()` use) in `docs/rfc/`. The RFC is the spec. Where this request and the RFC disagree, the RFC wins, except for the Python API below, which the RFC leaves open.

## API

A new module `jsonpath_ng.rfc9535`:

```python
from jsonpath_ng.rfc9535 import parse, normalized_path

query = parse("$.store.book[?@.price < 10].title")
matches = query.find(document)          # list of jsonpath_ng.DatumInContext
[m.value for m in matches]              # the selected values, in RFC nodelist order
[normalized_path(m) for m in matches]   # e.g. ["$['store']['book'][0]['title']", ...]
```

- `parse(query, functions=None)` returns a query object, and `find(document)` returns the RFC 9535 *nodelist* as a list of `DatumInContext`. `document` is the usual Python form of a JSON value: `dict`, `list`, `str`, `int`, `float`, `bool`, `None`. `find()` must not modify the document, and the same query object can be used any number of times on different documents.
- `normalized_path(datum)` returns the node's Normalized Path exactly as RFC 9535 section 2.7 defines it (`$['a'][0]`, with the escaping rules of that section), for any datum returned by `find()`.
- Any string that is not a valid, well-typed query according to the RFC must make `parse()` raise `jsonpath_ng.exceptions.JsonPathParserError`. That includes the whitespace rules, integer ranges, string escapes, unknown functions, wrong arity and every well-typedness rule of section 2.4.3. `find()` itself never raises for any JSON document. The message should say what is wrong and where.
- `str(query)` returns the original query string. Two query objects parsed from the same string compare equal and hash equal.
- Duplicate nodes are kept, and order follows the RFC. Where the RFC leaves order open (object members), use the dict's iteration order.

### Function extensions

All five functions of section 2.4 are built in: `length`, `count`, `match`, `search`, `value`. Users can add their own, and can replace the built-in ones, per call to `parse`:

```python
from jsonpath_ng.rfc9535 import parse, FunctionExtension, ValueType, LogicalType, NodesType, NOTHING

def first_word(value):
    return value.split()[0] if isinstance(value, str) and value.split() else NOTHING

q = parse("$[?first_word(@.title) == 'The']",
          functions={"first_word": FunctionExtension(first_word, (ValueType,), ValueType)})
```

- `FunctionExtension(func, parameters, result)`: `parameters` is a tuple of declared parameter types, and `result` is the declared result type. Each type is one of `ValueType`, `LogicalType`, `NodesType`, all importable from `jsonpath_ng.rfc9535`. They are used by the same well-typedness checks as the built-in functions, at `parse()` time.
- `func` is called with one positional argument per parameter:
  - for a `ValueType` parameter: a JSON value, or `NOTHING` (the RFC's special result "Nothing") when the argument is an empty singular query or a function that returned Nothing;
  - for a `LogicalType` parameter: a `bool`;
  - for a `NodesType` parameter: a `list` of `DatumInContext` (empty if no nodes).
- `func` returns a JSON value or `NOTHING` for a `ValueType` result, a truthy/falsy value for a `LogicalType` result, and a list of `DatumInContext` for a `NodesType` result. Exceptions it raises are not caught.
- `NOTHING` is a singleton and is falsy. Function names must match the RFC function-name rule, otherwise `ValueError` is raised when calling `parse`. The extra functions apply only to that `parse` call.

## Command line

The `jsonpath_ng` script gets a `--rfc9535` flag. With it, the expression is parsed by the new parser and every match is printed as JSON (`json.dumps(value, ensure_ascii=False)`), one per line. With `--rfc9535 --paths`, each line is the normalized path, a tab, then the JSON value. `--paths` without `--rfc9535` is a usage error. An invalid RFC 9535 query is reported as a usage error (exit status 2, message on stderr) instead of a traceback. Without the flag the script behaves exactly as before. Input files are read as UTF-8.

## Notes

- Comparisons, existence tests and logical operators work exactly as in section 2.3.5. Pay attention to the JSON type rules: for example, `true` is not equal to `1`, `1` equals `1.0`, and comparisons involving Nothing behave as the RFC says.
- `match()` and `search()` use I-Regexp (RFC 9485) semantics, not Python's `re` dialect. In particular, `.` matches any character except line feed and carriage return, and Unicode character class escapes such as `\p{Lu}` and `\P{L}` must work. An argument that is not a string, or a pattern that is not a valid I-Regexp, makes the function return false; it is not an error.
- Python's recursion limit must not be a problem for documents nested a few thousand levels deep when using `..`.
- Please add a short section to `README.rst` showing the new module and the CLI flag.
