Feature request for WTForms:

When I pass a callable as `choices` to a `SelectField` (or a callable to a `DataList`), WTForms calls it eagerly, while the form is being built. In our app the callable hits the database, so every form construction pays for a query, even for requests that never render or validate that field. I'd like these callables to be lazy: evaluated only when the choices are actually needed, instead of at form construction.

Exactly how it should behave, including the odd cases, is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
