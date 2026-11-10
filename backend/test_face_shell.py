import math

import pytest
from build123d import Box, Compound, Pos, Rotation

import worker

pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


def reference(shape, axis, side, center=None):
    for index, solid in enumerate(shape.solids()):
        for face in solid.faces():
            result = worker.face_offset_reference(face, index)
            if result and result["normal"][axis] * side > 0.999999:
                if center is None or math.dist(result["center"], center) < 1e-5:
                    return result
    raise AssertionError("Face not found")


@pytest.mark.parametrize("axis,side", [(axis, side) for axis in range(3) for side in (-1, 1)])
def test_box_shell_opens_selected_face_with_exact_thickness(axis, side):
    shape = Pos(0, 0, 10) * Box(40, 30, 20)
    before = shape.volume
    result = worker._apply_face_shell(shape, {"face_ref": reference(shape, axis, side), "thickness": 2})
    spans = [40, 30, 20]
    others = [spans[i] - 4 for i in range(3) if i != axis]
    assert result.volume == pytest.approx(before - (spans[axis] - 2) * math.prod(others))
    assert result.is_valid and len(result.solids()) == 1
    opening = [0, 0, 10]
    opening[axis] += side * (spans[axis] / 2 - 1)
    opposite_wall = [0, 0, 10]
    opposite_wall[axis] -= side * (spans[axis] / 2 - 1)
    assert not result.is_inside(opening)
    assert result.is_inside(opposite_wall)
    assert tuple(result.bounding_box().min) == pytest.approx(tuple(shape.bounding_box().min))
    assert tuple(result.bounding_box().max) == pytest.approx(tuple(shape.bounding_box().max))


def test_shell_keeps_other_solid_unchanged():
    shape = Compound(children=[Box(10, 10, 10), Pos(30, 0, 0) * Box(10, 10, 10)])
    result = worker._apply_face_shell(shape, {"face_ref": reference(shape, 2, 1, [30, 0, 5]), "thickness": 1})
    assert sorted(solid.volume for solid in result.solids()) == pytest.approx([424, 1000])


@pytest.mark.parametrize("thickness", [0, -1, 5, 10, None, True, "2", float("inf"), float("nan")])
def test_shell_rejects_invalid_thickness(thickness):
    shape = Box(10, 10, 10)
    with pytest.raises(worker.GeometryError) as error:
        worker._apply_face_shell(shape, {"face_ref": reference(shape, 2, 1), "thickness": thickness})
    assert error.value.code == "bad_params"
    assert shape.volume == pytest.approx(1000)


def test_shell_rejects_stale_face_and_nonbox_shape():
    shape = Box(20, 20, 20)
    ref = reference(shape, 2, 1)
    with pytest.raises(worker.GeometryError) as error:
        worker._apply_face_shell(shape, {"face_ref": {**ref, "center": [0, 0, 200]}, "thickness": 1})
    assert error.value.code == "reselect_required"
    holed = shape - Box(4, 4, 24)
    with pytest.raises(worker.GeometryError) as error:
        worker._apply_face_shell(holed, {"face_ref": reference(holed, 2, 1), "thickness": 1})
    assert error.value.code == "shell_unsupported"


def test_shell_rejects_tilted_box_with_unreliable_axis_aligned_size():
    shape = Rotation(0, 0, 30) * Box(20, 10, 10)
    with pytest.raises(worker.GeometryError) as error:
        worker._apply_face_shell(shape, {"face_ref": reference(shape, 2, 1), "thickness": 1})
    assert error.value.code == "shell_unsupported"
