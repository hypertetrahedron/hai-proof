Feature request for xknx:

Our home automation shows a log of why each KNX device changed state, and right now all it can say is "the device was updated". I'd like devices to record what caused their latest update: either the telegram that came in or went out, or the application action (our own code, e.g. an automation or a user clicking in the UI) that started it.

This is the API I'd like, so that our code and tests can rely on the names:

- `Device.last_update`, an instance of a new `DeviceUpdate` (exported from `xknx.devices`) with the fields `telegram` and `context`.
- `Telegram.context`, an optional field that can also be passed as `Telegram(..., context=...)`, holding an application-defined object that says where a telegram came from.
- `telegram_context`, a context manager exported from `xknx.telegram`, to mark a block of application code with such an object.

Exactly how these should behave, including the odd cases, is something I'd like to settle with you, so ask me before you lock it in. Add tests in the style of the existing ones and keep the suite passing.
