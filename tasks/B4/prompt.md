We run tinycss2 inside a CSS linter and a style-inliner, and after we picked up this build a lot of our golden files changed. We checked each difference against what Chrome and Firefox do and against the CSS Syntax Level 3 and CSS Color 4/5 specs, and in every case below tinycss2 is the one that's wrong. Annoyingly, the test suite in the repo still passes, so it clearly doesn't cover these. Could you track down what broke and fix it?

What we've seen so far (all through the public API: `parse_component_value_list`, `parse_stylesheet`, `parse_one_declaration`, `serialize`, `tinycss2.nth.parse_nth` and the `parse_color` functions in `color3`, `color4` and `color5`):

**Tokenizing**
1. Numbers with a negative exponent fall apart: `1e-3px` should be one dimension token (value 0.001, unit `px`), but it no longer is. Positive exponents (`1e3px`, `1e+3px`) are fine.
2. An escaped NUL in an identifier, e.g. `\0 red` or `\000000red`, produces a real U+0000 character. Per the spec it should become U+FFFD.
3. A hex escape followed by a newline, e.g. `\41` then a newline then `BC`, should swallow that single newline like it swallows a space or tab. Now the newline is left behind and the identifier breaks in two.
4. Hash tokens that start with a non-ASCII character, like `#été` or `#日本`, used to be hash tokens and now come out as a `#` delimiter followed by an identifier.
5. `unicode-range` with an explicit range is truncated when the start is short: `U+0-10FFFF` should be the range 0x0–0x10FFFF, but the end comes out as `0x10FF` with leftover tokens.
6. The `-->` CDC token at the end of an HTML-comment-wrapped stylesheet is no longer recognised. It turns into an identifier and a `>` delimiter.

**Parsing**
7. `color: red !IMPORTANT` (any capitalisation of `important`) should be important, but now only lowercase works.
8. A statement at-rule ending in `;` swallows what follows: in `@import "a.css"; body { color: red }` the import's prelude runs on into the `body` rule.

**`:nth-child()` / An+B**
9. `parse_nth('2n+1')`, `parse_nth('n+3')` and friends return `None`. `2n-1` still works.

**Serializing**
10. Round-tripping through `serialize()` changes some identifiers that start with a digit after an escape or a hyphen: re-parsing the output gives a different identifier than the one we started with.
11. Serializing a `/` delimiter immediately followed by a `*` delimiter produces `/*`, which then parses as the start of a comment. It used to insert an empty comment between them.

**Colors**
12. Alpha given as a percentage is ignored in CSS Color 4/5: `rgb(0 0 0 / 50%)` comes back with alpha 1 instead of 0.5. The same applies to `hsl()`, `lab()`, `oklch()` and the rest.
13. The legacy comma syntax with alpha, e.g. `rgba(255, 0, 0, 0.5)` or `hsla(120, 100%, 50%, 0.3)`, is rejected (returns `None`) by `color4.parse_color` and `color5.parse_color`. Without alpha it still works.
14. `lab()` with a percentage for the **b** axis is scaled wrong. `lab(50% 0 100%)` should give b = 125, but we get a different number. The **a** axis is fine.
15. `oklab()` has the same kind of problem, again only for **b** with a percentage. `oklab(50% 0 100%)` should give b = 0.4.
16. `device-cmyk()` in `color5` doesn't clamp channels above 100%: `device-cmyk(0 81% 81% 130%)` should come out with K = 1.

Please fix the underlying causes rather than special-casing these inputs, and keep the existing tests passing. If you notice anything else that is clearly off against the specs while you are in there, fix that too.
