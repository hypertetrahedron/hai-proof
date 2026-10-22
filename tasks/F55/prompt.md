Feature request for w3lib:

I use `w3lib.html.get_base_url` and `get_meta_refresh` on millions of pages, and some of them are huge, so the functions spend a lot of time scanning megabytes of body for a `<base>` or `<meta http-equiv="refresh">` that, if it exists, is in the first few kilobytes. I'd like to be able to tell both functions how much of the page to look at, with a parameter called `max_scan`.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests next to the existing ones for these two functions and keep the suite passing.
