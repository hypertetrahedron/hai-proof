I want a way for a resource to say "this query parameter may appear only once", and to get a normal 400 if a client repeats it, instead of Falcon guessing which value to use.

The design I want:

- A new keyword argument `allow_multiple` on the query-string helpers, default `True`, so nothing changes unless I pass `False`. It goes on all ten of them: `get_param`, `get_param_as_int`, `get_param_as_float`, `get_param_as_bool`, `get_param_as_uuid`, `get_param_as_date`, `get_param_as_datetime`, `get_param_as_json`, `get_param_as_media` and `get_param_as_dict`. Not on `get_param_as_list`, which exists to return several values. It must work the same for the WSGI `Request` and the ASGI `Request`, including the ASGI override of `get_param`.
- With `allow_multiple=False`, a parameter that resolves to more than one value raises `HTTPInvalidParam` (naming the parameter, so the response is a 400 "Invalid parameter"). The wording of the message is up to you.
- Identical repeated values still count as multiple: `?ant=1&ant=1` is refused. I don't want the code comparing values.
- With `auto_parse_qs_csv` turned on in the request options, a single occurrence with commas (`?ant=1,2`) already resolves to a list of values, so it counts as multiple and is refused too. With that option off, `?ant=1,2` is one plain value and is fine.
- A parameter that is absent is not affected by the flag: the helper returns `None`, or the `default` if one is given, or raises `HTTPMissingParam` when `required=True`, exactly as without it.
- If the value is refused, `store` must not be populated. A single occurrence still goes into `store` as usual.
- The check happens before the value is converted, so a repeated `get_param_as_int` is refused with `HTTPInvalidParam` even if the values would not have parsed.
- `get_param_as_dict`: in the deep-object form (`user[name]=Bond&user[name]=Blofeld`), a repeated key raises `HTTPInvalidParam` when `allow_multiple=False`. With `auto_parse_qs_csv` on, `user[name]=Bond,Blofeld` counts as a repeated key too. The pairs form (`pair=a&pair=1&pair=b&pair=2`) takes its repeats by design, so the flag has no effect there and it still returns the dict. Without the flag the dict helper behaves as before.
- Document it in the docstrings, and add a newsfragment under `docs/_newsfragments/` if that is how the project records changes.
