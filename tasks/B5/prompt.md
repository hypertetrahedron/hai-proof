dateparser isn't safe to use from multiple threads, and it's biting us in production.

We parse dates in a threaded web service (a `ThreadPoolExecutor` behind each worker) and every so often a request fails with a `KeyError` from deep inside dateparser. The key is a different hash every time, and retrying the same input works. A typical traceback ends like this:

```
  File ".../dateparser/date.py", line 676, in _get_applicable_locales
    if self._is_applicable_locale(locale, s, ignore_surrounding_text):
  File ".../dateparser/languages/locale.py", line 93, in is_applicable
    return dictionary.are_tokens_valid(date_tokens)
  File ".../dateparser/languages/dictionary.py", line 145, in are_tokens_valid
    match_relative_regex = self._get_match_relative_regex_cache()
  ...
  File ".../dateparser/languages/dictionary.py", line 347, in _get_sorted_relative_strings_from_cache
    return self._sorted_relative_strings_cache[self._settings.registry_key][
KeyError: '86f0601c4589570a9b883f716c3e92b3'
```

It reproduces quickly, especially with a small `CACHE_SIZE_LIMIT`:

```python
import dateparser
from concurrent.futures import ThreadPoolExecutor

with ThreadPoolExecutor(16) as executor:
    futures = [executor.submit(dateparser.parse, "tomorrow") for _ in range(100)]
for f in futures:
    print(f.result())
```

While digging we found two more problems of the same kind, which matter to us because we share parser and settings objects between threads:

- With `DateDataParser(languages=["de"], settings={"PREFER_LOCALE_DATE_ORDER": True})`, a thread that reads `parser._settings.DATE_ORDER` while other threads call `get_date_data()` on the same parser sometimes sees `"DMY"` instead of the configured `"MDY"`. Parsing seems to write the locale's date order into the shared settings object and put it back afterwards, so concurrent parses can pick up each other's order.
- `search_dates()` changes `RELATIVE_BASE` on the shared default settings (`dateparser.conf.settings`) while it resolves relative dates like "2 дня назад", so concurrent parses and searches can see a foreign relative base.

Please make dateparser thread-safe: concurrent calls to `parse`, `DateDataParser.get_date_data` and `search_dates` must not raise, must give the same results as sequential calls, and must never mutate settings objects that other threads can see. The caches still have to respect `CACHE_SIZE_LIMIT`. A single global lock around all parsing isn't an option for us, because throughput matters. Please keep the existing test suite passing.
