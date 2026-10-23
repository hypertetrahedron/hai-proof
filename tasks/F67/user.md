I want `subliminal download --name` to accept a sed-like substitution, `s/pattern/replacement/flags`, as well as a plain name, so I can derive the name for each file from its own path. A plain name keeps working: it is passed to every file as today.

Here is how I want it to behave:

- The pattern is a Python regular expression. The replacement can use back-references `\1`, `\2` and so on.
- `&` in the replacement is a literal character, unlike sed where it means the whole match. A title like `Panty & Stocking S01E\1.mkv` needs no escaping, and `s/[0-9]+/[&]/` on `ep12.mkv` gives `ep[&].mkv`.
- Flags: none means only the first match is replaced, `g` replaces all matches, `i` makes the match case-insensitive. Any other flag (for example `x`, alone or with `g`) is an error.
- An invalid regular expression is an error too. Both errors must be reported as a bad `--name` value on the command line, so the command exits with code 2 before scanning anything.
- Any non-alphanumeric character can be the delimiter, not just `/`: `s|a|b|` and `s#a#b#g` work. Inside the pattern or the replacement, `\<delimiter>` is a literal delimiter, so `s/a\/b/c/` matches `a/b`. Other backslash sequences, such as `\1`, are left alone for the regex.
- The substitution is applied to the whole file path as given (after `--use-absolute-path` has made it absolute if that is on), not just the file name, so the pattern can match parent directories. The part of the path that is not matched is kept, as in sed: `s#Season ([0-9]+)/Episode ([0-9]+)#Show S\1E\2#` on `shows/Season 02/Episode 05.mkv` gives `shows/Show S02E05.mkv`.
- A name that is not a well-formed substitution is a static name, used as is for every file. In particular a name like `s.w.a.t.2017.s01e01.720p.hdtv.x264-killers.mkv` is a static name, even though it starts with `s` and the next character is not alphanumeric. A well-formed substitution has exactly three delimiters: `s`, delimiter, pattern, delimiter, replacement, delimiter, flags (possibly empty). Too few or too many segments, or an alphanumeric character after the `s`, mean a static name.
- A file whose path the pattern does not match is scanned as it is, with no name (`name=None` is passed to `scan_path`), exactly as if `--name` had not been given. It is not an error and does not stop the other files. The same goes for a replacement that fails when applied, for example one that refers to a group the pattern does not have: that file is scanned as is.
- The existing call to `scan_path` keeps its keyword `name`; the resolved name (or `None`) is passed there for each file.

Also describe it in the `--name` help text and in the user docs, and add a changelog fragment the way the project does.
