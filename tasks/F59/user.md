I scrape dates from Indian news sites and need `IST` to mean Indian Standard Time (+05:30) for my data. I want a setting for it, not a change to the defaults for everybody.

The design I want:

- A new setting called `TIMEZONE_ABBREVIATIONS`. It maps a timezone abbreviation (a string such as `"IST"`) to its UTC offset as a `datetime.timedelta`, for example `{"IST": timedelta(hours=5, minutes=30)}`. Default: an empty dict, so nothing changes unless I set it. It goes through `settings=` like the other settings.
- When a date string contains an abbreviation that is in the mapping, parsing uses my offset instead of the built-in one. Every abbreviation I didn't list keeps its normal built-in offset (`CET` stays +01:00 even when I override `IST`).
- It applies everywhere dateparser reads an abbreviation: plain absolute dates ("10:00 IST"), relative/freshness strings ("in 1 hour IST"), and strings that carry a numeric offset as well as the abbreviation ("10:00 +05:30 IST"). With `RETURN_AS_TIMEZONE_AWARE` on, the result's `utcoffset()` must be my offset in all three.
- It must also work when I don't pass `languages`, so dateparser detects the language from the string. The override can't be dropped just because a language is being detected.
- The keys are matched exactly, case-sensitive, as dateparser spells them: `"IST"` is an abbreviation, `"ist"` is not one. A lowercase `"ist"` key therefore does not match, and I want it rejected (see below), not silently ignored.
- A key that isn't a timezone abbreviation dateparser knows (for example `"XYZ"`) is a mistake. Fail early with `SettingValidationError`, raised when the settings are validated (when I build `DateDataParser(settings=...)`, or call `parse(...)`), not later when a date happens to contain it.
- A value that isn't a `timedelta` (for example the string `"+05:30"`, a number or `None`) is also a mistake: `SettingValidationError`, at the same time. I don't mind the exact wording of the messages, only that it is that exception and the message names the offending key or value.
- It only affects abbreviations found in the date string. `TIMEZONE` and `TO_TIMEZONE` take timezone names and keep resolving them as before; the overrides are not applied to them, even if the same letters are used. With `TO_TIMEZONE="UTC"`, a string "12 Feb 2015 10:56 PM IST" with my override should come out as 17:26 UTC.
- Document the setting in the settings docs next to the other timezone settings, with a short example.
