import math

import pytest

import worker


pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


def planar_reference(shape, normal, center=None):
    for solid_index, solid in enumerate(shape.solids()):
        for face in solid.faces():
            reference = worker.face_offset_reference(face, solid_index)
            if reference is None or math.dist(reference["normal"], normal) > 1e-6:
                continue
            if center is None or math.dist(reference["center"], center) < 1e-5:
                return reference
    raise AssertionError("Selected planar face not found")


@pytest.mark.parametrize("distance", [3, -2])
def test_face_offset_preserves_bore_and_exact_annular_volume(distance):
    shape, _ = worker.build_washer({
        "outer_diameter": 20, "inner_diameter": 6, "height": 8,
    })
    result = worker._apply_face_offset(shape, {
        "face_ref": planar_reference(shape, [0, 0, 1]),
        "distance": distance,
    })
    assert result.is_valid
    assert len(result.solids()) == 1
    assert result.volume == pytest.approx(math.pi * (10 ** 2 - 3 ** 2) * (8 + distance))
    assert result.bounding_box().max.Z == pytest.approx(8 + distance)
    bore = [edge for edge in result.edges()
            if edge.geom_type.name == "CIRCLE" and edge.radius == pytest.approx(3)]
    assert min(edge.center().Z for edge in bore) == pytest.approx(0)
    assert max(edge.center().Z for edge in bore) == pytest.approx(8 + distance)


def test_face_offset_moves_internal_pocket_floor_without_changing_outer_dimensions():
    from build123d import Box, Pos
    shape = Pos(0, 0, 10) * Box(20, 20, 20) - Pos(0, 0, 18) * Box(8, 8, 8)
    reference = planar_reference(shape, [0, 0, 1], [0, 0, 14])
    result = worker._apply_face_offset(shape, {"face_ref": reference, "distance": 2})
    assert result.is_valid
    assert result.volume == pytest.approx(shape.volume + 8 * 8 * 2)
    assert tuple(result.bounding_box().min) == pytest.approx((-10, -10, 0))
    assert tuple(result.bounding_box().max) == pytest.approx((10, 10, 20))
    assert planar_reference(result, [0, 0, 1], [0, 0, 16])


def test_face_offset_supports_inclined_planar_face():
    from build123d import Box, Rotation
    shape = Rotation(0, 30, 0) * Box(10, 12, 8)
    reference = planar_reference(shape, [0.5, 0, math.sqrt(3) / 2])
    result = worker._apply_face_offset(shape, {"face_ref": reference, "distance": 3})
    assert result.is_valid
    assert result.volume == pytest.approx(10 * 12 * 11)


@pytest.mark.parametrize("axis, side", [(0, -1), (0, 1), (1, -1), (1, 1), (2, -1), (2, 1)])
@pytest.mark.parametrize("distance", [-2, 3])
def test_face_offset_uses_outward_normal_for_every_box_side(axis, side, distance):
    shape, _ = worker.build_box({"length": 10, "width": 12, "height": 8})
    normal = [0, 0, 0]
    normal[axis] = side
    result = worker._apply_face_offset(shape, {
        "face_ref": planar_reference(shape, normal), "distance": distance,
    })
    dimensions = [10, 12, 8]
    dimensions[axis] += distance
    assert result.volume == pytest.approx(math.prod(dimensions))
    expected_minimum, expected_maximum = [-5, -6, 0], [5, 6, 8]
    if side == -1:
        expected_minimum[axis] -= distance
    else:
        expected_maximum[axis] += distance
    assert tuple(result.bounding_box().min) == pytest.approx(expected_minimum)
    assert tuple(result.bounding_box().max) == pytest.approx(expected_maximum)


def test_face_offset_changes_only_selected_solid_in_compound():
    from build123d import Box, Compound, Pos
    shape = Compound(children=[Box(10, 10, 10), Pos(30, 0, 0) * Box(10, 10, 10)])
    reference = planar_reference(shape, [0, 0, 1], [30, 0, 5])
    result = worker._apply_face_offset(shape, {"face_ref": reference, "distance": 2})
    assert len(result.solids()) == 2
    assert sorted(solid.volume for solid in result.solids()) == pytest.approx([1000, 1200])
    assert result.solids()[0].bounding_box().max.Z == pytest.approx(5)


@pytest.mark.parametrize("distance", [0, float("nan"), float("inf"), None, "bad"])
def test_face_offset_rejects_invalid_distance(distance):
    shape, _ = worker.build_box({"length": 10, "width": 10, "height": 10})
    with pytest.raises(worker.GeometryError) as caught:
        worker._apply_face_offset(shape, {
            "face_ref": planar_reference(shape, [0, 0, 1]), "distance": distance,
        })
    assert caught.value.code == "bad_params"


def test_face_offset_rejects_stale_and_curved_references_and_body_destruction():
    shape, _ = worker.build_box({"length": 10, "width": 10, "height": 10})
    reference = planar_reference(shape, [0, 0, 1])
    stale_reference = {**reference, "center": [0, 0, 9]}
    for face_ref, distance, code in [
        (stale_reference, 2, "reselect_required"),
        ({"kind": "cylinder"}, 2, "unsupported_face"),
        ({**reference, "normal": [0, 0, 0]}, 2, "bad_ref"),
        (reference, -10, "face_offset_failed"),
        (reference, -12, "face_offset_failed"),
    ]:
        with pytest.raises(worker.GeometryError) as caught:
            worker._apply_face_offset(shape, {"face_ref": face_ref, "distance": distance})
        assert caught.value.code == code


def test_face_offset_rejects_cut_through_hidden_cavity_and_collision_with_other_solid():
    from build123d import Box, Compound, Pos
    hollow = Pos(0, 0, 10) * Box(20, 20, 20) - Pos(0, 0, 10) * Box(4, 4, 4)
    with pytest.raises(worker.GeometryError) as caught:
        worker._apply_face_offset(hollow, {
            "face_ref": planar_reference(hollow, [0, 0, 1], [0, 0, 20]),
            "distance": -12,
        })
    assert caught.value.code == "face_offset_failed"

    separate = Compound(children=[Box(10, 10, 10), Pos(0, 0, 12) * Box(10, 10, 10)])
    with pytest.raises(worker.GeometryError) as caught:
        worker._apply_face_offset(separate, {
            "face_ref": planar_reference(separate, [0, 0, 1], [0, 0, 5]),
            "distance": 5,
        })
    assert caught.value.code == "face_offset_failed"


def test_mesh_metadata_identifies_planar_faces_and_samples_round_edges():
    shape, _ = worker.build_cylinder({"diameter": 20, "height": 10})
    resource = worker.mesh_resource(shape, "offset-metadata")
    references = [face["face_ref"] for face in resource["face_ranges"]]
    assert len([reference for reference in references if reference is not None]) == 2
    assert references.count(None) == 1
    circular_edge = next(edge for edge in worker.list_edges(shape) if edge["kind"] == "CIRCLE")
    assert len(circular_edge["points"]) == 65
    assert circular_edge["points"][0] == pytest.approx(circular_edge["points"][-1])
    assert max(point[0] for point in circular_edge["points"]) == pytest.approx(10, abs=1e-5)
    assert min(point[0] for point in circular_edge["points"]) == pytest.approx(-10, abs=1e-5)
