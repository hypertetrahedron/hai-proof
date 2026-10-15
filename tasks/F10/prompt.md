Feature request, from tomlkit's issue tracker (#288, "Support Decimal serialization?"):

We store configuration that contains `decimal.Decimal` values (prices, rates) and want to write it with tomlkit. Today `tomlkit.dumps({"price": Decimal("1.23")})` and `tomlkit.item(Decimal("1.23"))` fail with `ValueError: Invalid type <class 'decimal.Decimal'>`. We could convert everything by hand before dumping, but that is awkward for nested documents, and `Decimal` is only one example: other projects have their own types (`Path`, `UUID`, enums, their own classes) that they would like to serialize too.

Please add a general extension mechanism to tomlkit so that users can teach it to serialize types it doesn't support. Once it is in place, `Decimal` values should be writable through it, both with `tomlkit.item()` and with `tomlkit.dumps()`. Add tests, and keep the existing tests passing. Please also document the new API in its docstrings.

I'd like to know what you decide about the design before it is final, so if there are choices I should weigh in on, ask.
