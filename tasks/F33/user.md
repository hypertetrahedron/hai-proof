This is how I want the `$GENERATE` substitution to work, both in the owner name and in the data of a line:

- Every `$` in a template is handled on its own, left to right. A plain `$` becomes the current iterator value. `${offset}`, `${offset,width}` and `${offset,width,base}` modify it: the offset is added to the iterator (and may carry a sign), the width zero-pads, and the base is one of `d`, `o`, `x`, `X`, `n`, `N` (`d` when left out). Several `$` in one template, with or without modifiers, are all substituted: `host${0,2,d}-$` with `h${10}-$.` for 1-2 gives `host01-1` pointing at `h11-1.`, then `host02-2` pointing at `h12-2.`. At the moment only one of them is replaced.
- `$$` is a literal `$`, so `a$$` produces the name `a$` and `b$$.$` produces `b$.1` on the first iteration.
- A backslash-escaped dollar, `\$`, is not substituted and stays exactly `\$` in the result (backslash included), so `c\$` stays `c\$` as the name and `d\$.$` gives `d\$.2` on iteration 2.
- The nibble bases `n` (lower case) and `N` (upper case) write the value as hexadecimal digits separated by dots, least significant nibble first. Every nibble of the value is written, never truncated, whatever the width. The width only pads with zero nibbles, and it counts the dots as characters. So `${0,0,n}` for 10 is `a` and for 11 is `b`; `${0,3,n}` for 427 (hex 1ab) is `b.a.1`; `${0,5,N}` for 10 is `A.0.0`; and `${10,3,n}` for iteration 1 (value 11) is `b.0`.
- A width of 0 is fine for the nibble bases: it just means no padding, and it must never produce an empty label.
- The other bases behave as before: the value is formatted in decimal, octal or hex (lower or upper case) and zero-padded to the width.
- A malformed modifier is an error, `dns.exception.SyntaxError`, instead of being copied into the output: an unknown base (`${1,2,q}`), a non-numeric offset (`${bogus}`), an empty width (`${1,}`), and a modifier with no closing brace (`${1,2,d`).
- A negative value in a nibble base (for example offset -1 at iteration 0, `${-1,0,n}`) is a `dns.exception.SyntaxError` too.
- The text of the error messages is up to you.
