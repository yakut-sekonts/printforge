import pytest

import worker


pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


def test_separate_split_keeps_all_solids_as_individually_addressable_parts():
    from build123d import Box, Compound, Pos
    base = Compound(children=[Box(10, 10, 10), Pos(0, 30, 0) * Box(10, 10, 10)])
    parts = worker.apply_part_operations({"a": {"shape": base, "name": "Деталь"}}, [{
        "op": "split", "part_id": "a", "plane": "YZ", "offset": 0, "separate": True,
    }])
    assert list(parts) == ["a", "a-split-1-part-2", "a-split-1-part-3", "a-split-1-part-4"]
    assert all(len(part["shape"].solids()) == 1 for part in parts.values())
    assert sum(part["shape"].volume for part in parts.values()) == pytest.approx(2000)


def test_repeated_separate_split_preserves_earlier_parts_and_legacy_ids():
    shape, _ = worker.build_box({"length": 40, "width": 30, "height": 20})
    operations = [
        {"op": "split", "part_id": "a", "plane": "YZ", "offset": 0, "separate": True},
        {"op": "split", "part_id": "a", "plane": "XY", "offset": 10, "separate": True},
    ]
    parts = worker.apply_part_operations({"a": {"shape": shape, "name": "Деталь"}}, operations)
    assert list(parts) == ["a", "a-split-1-part-2", "a-split-2-part-2"]
    assert sum(part["shape"].volume for part in parts.values()) == pytest.approx(24000)
    legacy = worker.apply_part_operations({"a": {"shape": shape, "name": "Деталь"}}, [{
        "op": "split", "part_id": "a", "plane": "YZ", "offset": 0,
    }])
    assert list(legacy) == ["a", "a-part2"]


@pytest.mark.parametrize("plane, axis, coordinate", [("XY", 2, 20), ("XZ", 1, 30), ("YZ", 0, 40)])
def test_separate_split_uses_world_coordinates_on_translated_body(plane, axis, coordinate):
    from build123d import Box, Pos
    shape = Pos(40, 30, 20) * Box(20, 20, 20)
    parts = worker.apply_part_operations({"a": {"shape": shape, "name": "Деталь"}}, [{
        "op": "split", "part_id": "a", "plane": plane, "offset": coordinate, "separate": True,
    }])
    solids = [part["shape"] for part in parts.values()]
    assert len(solids) == 2
    assert [solid.volume for solid in solids] == pytest.approx([4000, 4000])
    assert tuple(solids[0].bounding_box().max)[axis] == pytest.approx(coordinate)
    assert tuple(solids[1].bounding_box().min)[axis] == pytest.approx(coordinate)
    for other_axis in range(3):
        if other_axis != axis:
            for solid in solids:
                assert tuple(solid.bounding_box().min)[other_axis] == pytest.approx(
                    tuple(shape.bounding_box().min)[other_axis])
                assert tuple(solid.bounding_box().max)[other_axis] == pytest.approx(
                    tuple(shape.bounding_box().max)[other_axis])


def test_legacy_xz_split_replays_original_normal_offset_sign():
    from build123d import Box, Pos
    shape = Pos(40, 30, 20) * Box(20, 20, 20)
    parts = worker.apply_part_operations({"a": {"shape": shape, "name": "Деталь"}}, [{
        "op": "split", "part_id": "a", "plane": "XZ", "offset": -30,
    }])
    assert list(parts) == ["a", "a-part2"]
    assert sum(part["shape"].volume for part in parts.values()) == pytest.approx(8000)
    with pytest.raises(worker.GeometryError) as caught:
        worker.apply_part_operations({"a": {"shape": shape, "name": "Деталь"}}, [{
            "op": "split", "part_id": "a", "plane": "XZ", "offset": 30,
        }])
    assert caught.value.code == "split_failed"


@pytest.mark.parametrize("offset", [float("nan"), float("inf"), "bad"])
def test_split_rejects_non_finite_plane_offset(offset):
    shape, _ = worker.build_box({"length": 10, "width": 10, "height": 10})
    with pytest.raises(worker.GeometryError) as caught:
        worker.apply_part_operations({"a": {"shape": shape, "name": "Деталь"}}, [{
            "op": "split", "part_id": "a", "plane": "YZ", "offset": offset, "separate": True,
        }])
    assert caught.value.code == "bad_params"
