Tornado's only built-in CSRF defence today is `xsrf_cookies`. It requires a token in every form and AJAX call, so most of our apps never turned it on. Modern browsers send `Sec-Fetch-Site` (and `Origin`) on every request, which lets a server reject cross-site state-changing requests without any changes to the HTML or JavaScript (see Go's `net/http.CrossOriginProtection` and https://words.filippo.io/csrf/). Please add this to Tornado as an opt-in feature.

## Settings

- `cross_origin_protection` (default `False`): when `True`, `RequestHandler` checks every state-changing request.
- `trusted_origins` (default empty): a list of origins such as `"https://example.com"`, always without a trailing slash, that may make cross-origin requests. Compare origins exactly: a trailing slash or a different scheme does not match.

## The check

It runs before `prepare()` and before the HTTP method is dispatched. An unsafe method that the handler doesn't implement therefore gets 403 rather than 405 when the check fails.

1. `GET`, `HEAD` and `OPTIONS` are never checked. The exception is a WebSocket upgrade, a `GET` with `Upgrade: websocket`, where the header value is case-insensitive. Every other method (`POST`, `PUT`, `DELETE`, `PATCH`, ...) is checked when `cross_origin_protection` is on.
2. If `Sec-Fetch-Site` is `same-origin` or `none`, allow.
3. If `Sec-Fetch-Site` is absent, use the `Origin` header:
   - no `Origin`: allow (a non-browser client);
   - the host part of `Origin` equals the request's `Host` header, compared case-insensitively and ignoring any path in `Origin`: allow;
   - otherwise allow only if `self.check_origin(origin)` returns True;
   - else reject with `HTTPError(403, "Origin %r not allowed" % origin)`.
   - `Referer` is never consulted. An `Origin` of `null` (sandboxed frames) is rejected unless `check_origin` accepts it.
4. Any other `Sec-Fetch-Site` value (`cross-site`, `same-site`): allow only if there is an `Origin` header and `check_origin(origin)` returns True. Otherwise reject with `HTTPError(403, "Sec-Fetch-Site %s & origin %r not allowed" % (sec_fetch_site, origin))`. A present `Sec-Fetch-Site` takes precedence: a matching `Origin` alone is not enough.

`check_origin` is only consulted for requests that look cross-origin. It is never called for requests already allowed by `same-origin`/`none` or by an Origin/Host match.

## `check_origin`

Move `check_origin(self, origin) -> bool` from `WebSocketHandler` to `RequestHandler`, so handlers can override it, for example to allow subdomains. The default returns whether `origin` is in the `trusted_origins` setting. `WebSocketHandler` should no longer define its own version. Existing subclasses that override `check_origin` must keep working.

## WebSockets

WebSocket upgrades always get the check above, whether or not `cross_origin_protection` is set. It replaces the old Origin/Host test inside `WebSocketHandler`, and it uses the same `trusted_origins` and `check_origin`. A rejected upgrade is a 403 raised as the `HTTPError` above, so it is logged like any other 403. `xsrf_cookies` must not apply to WebSocket upgrades: they are `GET` requests and can't carry the token.

## Interactions

- With `xsrf_cookies` on as well, both checks apply to unsafe methods, and a request must pass both.
- `ErrorHandler` (used for unknown URLs, among other things) must treat every origin as trusted, so a cross-site `POST` to a missing page still returns its 404 (or other configured status), not 403.
- With `cross_origin_protection` off, non-WebSocket requests behave exactly as before.

Please also update the docstrings for the new settings and for `check_origin`.
