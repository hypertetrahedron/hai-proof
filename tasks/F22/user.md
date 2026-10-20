I compare dependency constraints and want `SpecifierSet` to answer questions about the versions it accepts. The methods are `is_subset(other)`, `is_superset(other)` and `is_disjoint(other)`, each returning a plain `bool`, each taking another `SpecifierSet`.

The behaviour I want:

- `a.is_subset(b)` is true when every version `a` accepts is also accepted by `b`; `is_superset` is the same question the other way round (`a.is_superset(b)` equals `b.is_subset(a)`); `is_disjoint` is true when no version is accepted by both.
- A set is a subset and a superset of itself and of an equal set, so `>=3.12,<3.13` is a subset of `>=3.12,<3.13`.
- Examples: `>2` is a subset of `>1` but not the reverse; `>=3.12,<3.13` is a subset of `>=3.11,<3.13` and of `>=3.12`, but not of `>=3.12,<3.12.5`; `<3.12` and `>=3.12` are disjoint, `<3.12` and `>=3.11` are not; `>=3.12,<3.13` and `==3.12.1` are not disjoint.
- A set nobody can satisfy, such as `>=2.0,<1.0`, accepts no versions at all. So it is a subset of every set (it is a subset of `>=3.12`), and it is disjoint from every set; and every set is a superset of it.
- The empty set `""` accepts everything, so it is not a subset of `>=3.12` (and `>=3.12` is not a superset of it); it is not disjoint from `>=3.12` either.
- The comparison is about the accepted versions, not the spelling, and it should agree with what `to_range()` already gives for the two sets (`spec.to_range().is_subset(other.to_range())`, and likewise for the other two).
- If the two sets were given different `prereleases` arguments, raise `ValueError`. Unset on one side and `False` on the other counts as different, as do `True` and `False`; both unset, or the same value on both, is fine.
- If either set contains a `===` (arbitrary equality) specifier, raise `ValueError`, whichever side it is on, since there is no sensible way to compare those as ranges.
- If `other` is not a `SpecifierSet` (a plain string like `">=1.0"`, say), raise `TypeError`. No coercing strings.
- For all three methods the same checks apply.
- Docstrings that list the errors and give examples, in the style of the other methods.
