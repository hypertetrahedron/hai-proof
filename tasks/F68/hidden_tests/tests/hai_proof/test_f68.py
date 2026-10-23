from __future__ import annotations

import json
import unittest

import pytest

import rtree.index


class TestPropertyJSON(unittest.TestCase):
    def test_roundtrip_default(self) -> None:
        p = rtree.index.Property()
        restored = rtree.index.Property.from_json(p.to_json())
        self.assertNotEqual(p.handle, restored.handle)
        self.assertEqual(p.as_dict(), restored.as_dict())

    def test_roundtrip_custom(self) -> None:
        p = rtree.index.Property(
            dimension=3,
            storage=rtree.index.RT_Disk,
            filename="some_index",
            leaf_capacity=50,
            index_capacity=60,
            fill_factor=0.5,
            overwrite=False,
            variant=rtree.index.RT_Quadratic,
        )
        restored = rtree.index.Property.from_json(p.to_json())
        self.assertEqual(p.as_dict(), restored.as_dict())

    def test_to_json_is_plain_json(self) -> None:
        state = json.loads(rtree.index.Property().to_json())
        self.assertIsInstance(state, dict)
        self.assertNotIn("custom_storage_callbacks", state)
        self.assertNotIn("custom_storage_callbacks_size", state)
        self.assertEqual(state["dimension"], 2)

    def test_from_json_accepts_bytes(self) -> None:
        data = rtree.index.Property(dimension=4).to_json().encode("utf-8")
        self.assertEqual(rtree.index.Property.from_json(data).dimension, 4)

    def test_from_json_rejects_unknown_keys(self) -> None:
        with pytest.raises(ValueError):
            rtree.index.Property.from_json('{"handle": 0}')

    def test_from_json_rejects_non_object(self) -> None:
        with pytest.raises(TypeError):
            rtree.index.Property.from_json("[1, 2, 3]")

    def test_to_json_rejects_oversized(self) -> None:
        limit = rtree.index.INDEX_JSON_SERIALIZATION_LIMIT_SIZE
        p = rtree.index.Property(filename="x" * limit)
        with pytest.raises(ValueError):
            p.to_json()

    def test_to_json_allows_exactly_limit(self) -> None:
        limit = rtree.index.INDEX_JSON_SERIALIZATION_LIMIT_SIZE
        base = len(rtree.index.Property(filename="").to_json().encode("utf-8"))
        p = rtree.index.Property(filename="x" * (limit - base))
        data = p.to_json()
        self.assertEqual(len(data.encode("utf-8")), limit)
        self.assertEqual(rtree.index.Property.from_json(data).as_dict(), p.as_dict())

    def test_from_json_rejects_oversized(self) -> None:
        limit = rtree.index.INDEX_JSON_SERIALIZATION_LIMIT_SIZE
        data = '{"filename": "' + "x" * limit + '"}'
        with pytest.raises(ValueError):
            rtree.index.Property.from_json(data)
        with pytest.raises(ValueError):
            rtree.index.Property.from_json(data.encode("utf-8"))

    def test_from_json_limit_counts_utf8_bytes(self) -> None:
        limit = rtree.index.INDEX_JSON_SERIALIZATION_LIMIT_SIZE
        # Under the limit in characters, over it in UTF-8 bytes.
        data = '{"filename": "' + "\u00e9" * (limit // 2) + '"}'
        self.assertLess(len(data), limit)
        with pytest.raises(ValueError):
            rtree.index.Property.from_json(data)

    def test_index_from_json_properties(self) -> None:
        p = rtree.index.Property(dimension=3)
        idx = rtree.index.Index(properties=rtree.index.Property.from_json(p.to_json()))
        idx.insert(0, (0, 0, 0, 1, 1, 1))
        self.assertEqual(idx.properties.dimension, 3)
        self.assertEqual(list(idx.intersection((0, 0, 0, 1, 1, 1))), [0])
