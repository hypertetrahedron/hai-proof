Feature request for poetry-core:

Our export tooling needs to take a marker and a partly known environment (say, the Python version and platform of a target machine) and get back a simpler marker that still carries whatever the environment can't decide. `validate` doesn't help, because it collapses everything to a yes or no. Could you add a method `apply` to the markers in `poetry.core.version.markers` that partially evaluates a marker against a known environment and keeps what can't be decided?

Exactly how it should behave in the odd cases is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
