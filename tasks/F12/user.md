I maintain a Python project that uses towncrier for its NEWS file. Our code style is 120 columns, and `wrap = true` wraps the changelog at 79, which looks out of place and breaks the long issue links badly. I just want to pick the width.

The design I want:

- No new setting. The existing `wrap` key should accept an integer as well as a boolean: `wrap = 120` wraps at 120 columns. I don't want a second key like `wrap_width` or `line_length` next to `wrap`, because two settings that have to agree are confusing.
- `wrap = true` keeps wrapping at 79, and `wrap = false` (the default) keeps not wrapping, so existing configs don't change.
- `wrap = 0` or a negative number is not a way to turn wrapping off; `false` is for that. Treat any integer of 0 or less as "wrap at the default", 79. Don't raise an error for it.
- Careful with Python: `True` is also the integer 1. `wrap = true` must mean 79, never a width of 1.
- Everything else about wrapping stays as it is (indentation of continuation lines, not breaking long words or URLs).
- Update the description of `wrap` in the configuration docs to say it can also be an integer greater than 0.
