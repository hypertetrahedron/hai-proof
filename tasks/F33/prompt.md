Feature request for dnspython:

I load zone files that I also serve with BIND, and some of them use `$GENERATE`. For a number of templates dnspython expands the iterator into different names and data than BIND does for the same file, so the zones I get from `dns.zone.from_text` don't match what my name servers publish. I'd like dnspython's handling of the substitution in `$GENERATE` templates to follow BIND's behaviour.

Exactly how it should behave is something I'd like to settle with you, so ask me before you lock it in. Add tests next to the existing `$GENERATE` tests and keep the suite passing.
