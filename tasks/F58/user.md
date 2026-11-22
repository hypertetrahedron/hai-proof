I use `@with_annotated` commands whose Enum parameters have a `_missing_` classmethod for aliases and keywords, and I also want a parameter to take one of several enums. The design I want:

Letting `_missing_` have a say:

- It is opt-in through a keyword flag called `allow_unknown_entry` on both `Argument(...)` and `Option(...)`, default `False`. Plain Enum parameters must behave exactly as they do today: without the flag, an Enum's `_missing_` is never consulted, so an alias like `auto` is rejected as before.
- With the flag, `_missing_` is only a fallback. A token is still matched against member values first and member names second; only a token neither matches is handed to `_missing_`. So canonical values and names keep working, and for an `IntEnum` the string-to-int bridge (typing `1` for a member whose value is `1`) still works.
- If `_missing_` returns a member, that is the result. If it returns `None` (which is also what the default `_missing_` does), the token is rejected with the usual "invalid choice" error that lists the choices. The flag on an Enum with no `_missing_` override changes nothing.
- The flag reaches every place the Enum is resolved: a collection element (`list[Color]` with the flag accepts `auto` for each item) and every member of an Enum union (below).
- When an Enum is used alone and its `_missing_` raises (a strict enum), that exception propagates out of the converter as it is raised. It is not turned into an "invalid choice" message. Inside a union it is different, see below.

Unions of Enums:

- `EnumA | EnumB` (any number of Enum members) is accepted. Each member keeps its own conversion: values, names and, with the flag, its own `_missing_`.
- A token resolves in the order the union is written: the first member that accepts it wins, even if a later member would also accept it. When two enums share a spelling, the earlier one in the union wins, and swapping the order swaps the winner.
- Inside a union, a member whose `_missing_` raises on a token counts as declining that token, exactly like a clean rejection, and the later members are still tried. A raising strict enum listed first must not stop a later enum from accepting the token.
- If every member declines, the error is the standard merged "invalid choice" rejection (an `argparse.ArgumentTypeError`, listing the combined choices). It must not be a member's own error, even one raised by a strict `_missing_`.
- A union that has a `Literal` member or any non-Enum member (`Color | int`, `Color | Literal["auto"]`, `str | int`) is still rejected with a `TypeError` saying it is ambiguous. That holds when the union is written with `| None` too (`Color | int | None`).
- The completion choices of a union are the members' choices merged in order. If two members share a spelling it is listed once, from the first member, and each choice keeps its own member's `display_meta`.
- A union also works as a collection element (`list[Color | Shade]`).
- Shapes: `A | B | None` with no default is an optional positional (`nargs='?'`, `None` when omitted). With `= None` as the default it becomes a `--flag` option, like other optional parameters.
