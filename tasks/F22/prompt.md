Feature request for packaging:

I'm writing tooling that compares dependency constraints, for example checking that a project's `requires-python` is compatible with a dependency's. I'd like `SpecifierSet` to answer set questions about the versions it accepts: `is_subset(other)`, `is_superset(other)` and `is_disjoint(other)`, each returning a bool. For example `>=3.12,<3.13` should be a subset of `>=3.12`, and `<3.12` should be disjoint from `>=3.12`.

Please add these. The exact behaviour is something I'd like to settle with you, so ask me before you lock it in. Add tests and keep the suite passing.
