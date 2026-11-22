Feature request for Scrapy:

I run large crawls and when something odd shows up in the logs or an item I can't tell which request led to which. Retries, redirects, and the requests a callback yields all just appear as new `Request` objects with nothing linking them back. I'd like every request to carry an identifier of its own, and a way to see which request it came from, so I can reconstruct the chain afterwards. I'd call them `Request.id` and `Request.parent_id`.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests next to the existing request tests and keep the suite passing.
