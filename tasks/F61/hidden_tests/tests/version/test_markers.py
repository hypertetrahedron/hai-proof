from __future__ import annotations

import os

from typing import TYPE_CHECKING

import pytest

from poetry.core.constraints.generic import UnionConstraint
from poetry.core.constraints.generic import parse_constraint as parse_generic_constraint
from poetry.core.constraints.version import parse_constraint as parse_version_constraint
from poetry.core.version.markers import AnyMarker
from poetry.core.version.markers import AtomicMarkerUnion
from poetry.core.version.markers import EmptyMarker
from poetry.core.version.markers import InvalidMarkerError
from poetry.core.version.markers import MarkerUnion
from poetry.core.version.markers import MultiMarker
from poetry.core.version.markers import SingleMarker
from poetry.core.version.markers import cnf
from poetry.core.version.markers import dnf
from poetry.core.version.markers import intersection
from poetry.core.version.markers import parse_marker
from poetry.core.version.markers import union


if TYPE_CHECKING:
    from poetry.core.version.markers import BaseMarker

EMPTY = "<empty>"


@pytest.mark.parametrize(
    ("marker_string", "environment", "expected"),
    [
        # AnyMarker / EmptyMarker are returned unchanged.
        ("", {}, ""),
        ("", {"os_name": "linux"}, ""),
        (EMPTY, {}, EMPTY),
        (EMPTY, {"os_name": "linux"}, EMPTY),
        # Empty environment preserves the marker.
        ("os_name == 'foo'", {}, "os_name == 'foo'"),
        (
            "python_version >= '3.8' and sys_platform == 'linux'",
            {},
            "python_version >= '3.8' and sys_platform == 'linux'",
        ),
        # SingleMarker with name in env collapses to Any/Empty.
        ("os_name == 'foo'", {"os_name": "foo"}, ""),
        ("os_name == 'foo'", {"os_name": "bar"}, EMPTY),
        ("python_version >= '3.8'", {"python_version": "3.10"}, ""),
        ("python_version >= '3.8'", {"python_version": "3.7"}, EMPTY),
        # SingleMarker with name not in env is returned unchanged.
        ("os_name == 'foo'", {}, "os_name == 'foo'"),
        ("os_name == 'foo'", {"sys_platform": "linux"}, "os_name == 'foo'"),
        # MultiMarker: only one name in env -> residual is the other branch.
        (
            "python_version >= '3.8' and sys_platform == 'linux'",
            {"python_version": "3.10"},
            "sys_platform == 'linux'",
        ),
        (
            "python_version >= '3.8' and sys_platform == 'linux'",
            {"sys_platform": "linux"},
            "python_version >= '3.8'",
        ),
        # MultiMarker: one branch is False -> whole thing collapses to Empty.
        (
            "python_version >= '3.8' and sys_platform == 'linux'",
            {"python_version": "3.7"},
            EMPTY,
        ),
        # MultiMarker: both names known.
        (
            "python_version >= '3.8' and sys_platform == 'linux'",
            {"python_version": "3.10", "sys_platform": "linux"},
            "",
        ),
        (
            "python_version >= '3.8' and sys_platform == 'linux'",
            {"python_version": "3.10", "sys_platform": "win32"},
            EMPTY,
        ),
        # MarkerUnion: one branch True -> collapses to Any.
        (
            "python_version >= '3.8' or sys_platform == 'linux'",
            {"python_version": "3.10"},
            "",
        ),
        # MarkerUnion: one branch False -> residual is the other branch.
        (
            "python_version >= '3.8' or sys_platform == 'linux'",
            {"python_version": "3.7"},
            "sys_platform == 'linux'",
        ),
        # MarkerUnion: both names known.
        (
            "python_version >= '3.8' or sys_platform == 'linux'",
            {"python_version": "3.7", "sys_platform": "win32"},
            EMPTY,
        ),
        # Nested: (A or B) and C, only python_version known.
        (
            "(python_version >= '3.8' or sys_platform == 'win32') and extra == 'foo'",
            {"python_version": "3.10"},
            "extra == 'foo'",
        ),
        (
            "(python_version >= '3.8' or sys_platform == 'win32') and extra == 'foo'",
            {"python_version": "3.7"},
            "sys_platform == 'win32' and extra == 'foo'",
        ),
        # extra: name in env is evaluated, including empty-tuple case.
        ("extra == 'a'", {"extra": "a"}, ""),
        ("extra == 'a'", {"extra": "b"}, EMPTY),
        ("extra == 'a'", {"extra": ()}, EMPTY),
        ("extra != 'a'", {"extra": ()}, ""),
        # extra: name not in env is preserved.
        ("extra == 'a'", {}, "extra == 'a'"),
        ("extra == 'a'", {"python_version": "3.10"}, "extra == 'a'"),
        # AtomicMultiMarker / AtomicMarkerUnion (compact extra forms).
        ("extra != 'a' and extra != 'b'", {"extra": ("c",)}, ""),
        ("extra != 'a' and extra != 'b'", {"extra": ("a",)}, EMPTY),
        ("extra != 'a' and extra != 'b'", {}, "extra != 'a' and extra != 'b'"),
        ("extra == 'a' or extra == 'b'", {"extra": ("a",)}, ""),
        ("extra == 'a' or extra == 'b'", {"extra": ("c",)}, EMPTY),
        ("extra == 'a' or extra == 'b'", {}, "extra == 'a' or extra == 'b'"),
    ],
)
def test_apply(marker_string: str, environment: dict[str, str], expected: str) -> None:
    m = parse_marker(marker_string)

    assert m.apply(environment) == parse_marker(expected)
