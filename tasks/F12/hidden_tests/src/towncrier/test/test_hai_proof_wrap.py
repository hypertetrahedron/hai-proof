# The `wrap` setting end to end: `towncrier build --draft` with `wrap` in pyproject.toml.

from twisted.trial.unittest import TestCase

from ..build import _main
from .helpers import with_project, write


WORDS = " ".join(["word"] * 80)


def _config(wrap: str) -> str:
    return f"""\
        [tool.towncrier]
        package = "foo"
        wrap = {wrap}
        """


class TestWrapWidth(TestCase):
    maxDiff = None

    def _build(self, runner):
        write("foo/newsfragments/123.feature", WORDS)
        result = runner.invoke(
            _main, ["--draft", "--version", "7.8.9", "--date", "01-01-2001"]
        )
        self.assertEqual(0, result.exit_code, result.output)
        return [line for line in result.output.splitlines() if "word" in line]

    def _assert_wrapped_at(self, lines, width):
        self.assertGreater(len(lines), 1, lines)
        longest = max(len(line) for line in lines)
        self.assertLessEqual(longest, width, lines)
        # Wrapped close to the width, not at some narrower one.
        self.assertGreater(longest, width - 6, lines)

    @with_project(config=_config("40"))
    def test_integer_width(self, runner):
        self._assert_wrapped_at(self._build(runner), 40)

    @with_project(config=_config("120"))
    def test_integer_width_wider_than_default(self, runner):
        self._assert_wrapped_at(self._build(runner), 120)

    @with_project(config=_config("true"))
    def test_true_is_79(self, runner):
        self._assert_wrapped_at(self._build(runner), 79)

    @with_project(config=_config("0"))
    def test_zero_falls_back_to_79(self, runner):
        self._assert_wrapped_at(self._build(runner), 79)

    @with_project(config=_config("-5"))
    def test_negative_falls_back_to_79(self, runner):
        self._assert_wrapped_at(self._build(runner), 79)

    @with_project(config=_config("false"))
    def test_false_does_not_wrap(self, runner):
        lines = self._build(runner)
        self.assertEqual(1, len(lines), lines)
        self.assertIn(WORDS, lines[0])
