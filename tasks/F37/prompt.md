Feature request for Falcon:

Our API has endpoints where a query parameter is meant to appear once, like `?limit=10`. When a client sends it twice (`?limit=10&limit=20`), `req.get_param()` and its siblings quietly return one of the values and we end up acting on a guess. I'd like a way to have the `get_param*` helpers refuse such a request instead, with a normal client error, while keeping today's behaviour for everyone who doesn't ask for it. Please call the option `allow_multiple`.

Exactly how it should behave across the helpers and the odd cases is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
