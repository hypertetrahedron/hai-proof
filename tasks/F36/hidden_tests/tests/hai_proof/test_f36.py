from datetime import timedelta

import pytest

from dateparser import DateDataParser, parse
from dateparser.conf import SettingValidationError

IST = timedelta(hours=5, minutes=30)
OVERRIDE = {"TIMEZONE_ABBREVIATIONS": {"IST": IST}, "RETURN_AS_TIMEZONE_AWARE": True}


def test_default_is_unchanged():
    date = parse("February 03, 2018 07:18 IST", settings={"RETURN_AS_TIMEZONE_AWARE": True})
    assert date.utcoffset() == timedelta(hours=2)


@pytest.mark.parametrize(
    "date_string",
    ["February 03, 2018 07:18 IST", "in 1 hour IST", "10:00 +05:30 IST"],
)
def test_override_with_language_detection(date_string):
    date = parse(date_string, settings=OVERRIDE)
    assert date.utcoffset() == IST


def test_override_with_detected_non_english_language():
    date = parse("3 février 2018 07:18 IST", settings=OVERRIDE)
    assert date is not None
    assert date.utcoffset() == IST


def test_override_with_explicit_languages():
    date = parse("February 03, 2018 07:18 IST", languages=["en"], settings=OVERRIDE)
    assert date.utcoffset() == IST


def test_other_abbreviations_keep_offset():
    date = parse("February 03, 2018 07:18 CST", settings=OVERRIDE)
    assert date.utcoffset() == timedelta(hours=-6)


def test_to_timezone_gets_the_overridden_source_offset():
    date = parse(
        "12 Feb 2015 10:56 PM IST",
        settings={**OVERRIDE, "TO_TIMEZONE": "UTC"},
    )
    assert (date.hour, date.minute) == (17, 26)


def test_timezone_setting_ignores_overrides():
    date = parse("12 Feb 2015 10:56 PM", settings={**OVERRIDE, "TIMEZONE": "IST"})
    assert date.utcoffset() == timedelta(hours=2)


def test_to_timezone_setting_ignores_overrides():
    date = parse(
        "12 Feb 2015 10:56 PM",
        settings={**OVERRIDE, "TIMEZONE": "UTC", "TO_TIMEZONE": "IST"},
    )
    assert date.utcoffset() == timedelta(hours=2)


@pytest.mark.parametrize("key", ["ist", "Ist", "XYZ", ""])
def test_unknown_or_wrongly_cased_key_is_rejected(key):
    with pytest.raises(SettingValidationError):
        DateDataParser(settings={"TIMEZONE_ABBREVIATIONS": {key: IST}})
    with pytest.raises(SettingValidationError):
        parse("10:00 IST", settings={"TIMEZONE_ABBREVIATIONS": {key: IST}})


@pytest.mark.parametrize("value", ["+05:30", 5.5, 19800, None])
def test_non_timedelta_offset_is_rejected(value):
    with pytest.raises(SettingValidationError):
        DateDataParser(settings={"TIMEZONE_ABBREVIATIONS": {"IST": value}})
    with pytest.raises(SettingValidationError):
        parse("10:00 IST", settings={"TIMEZONE_ABBREVIATIONS": {"IST": value}})


def test_empty_mapping_is_valid():
    assert parse("10:00 IST", settings={"TIMEZONE_ABBREVIATIONS": {}}) is not None
