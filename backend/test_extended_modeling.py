import base64
import math
from io import StringIO

import pytest

import worker


pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


def polygon(points):
    return {"kind": "polygon", "points": points}


def circle(radius, center=(0, 0)):
    return {"kind": "circle", "radius": radius, "center": list(center)}


def profile(outer, holes=None):
    return {"regions": [{"outer": outer, "holes": holes or []}]}


def build(operation):
    return worker.handle_build({"parts": [], "operations": [operation]})


def embedded_mesh(mesh):
    return {
        "op": "mesh_source", "format": "stl", "unit_scale": 1,
        "source_base64": base64.b64encode(mesh.export(file_type="stl")).decode("ascii"),
    }


def constrained_rectangle(include_width=True):
    entities = [
        {"id": "bottom", "type": "line", "start": [0.1, -0.2], "end": [39.8, 0.3]},
        {"id": "right", "type": "line", "start": [40.2, 0.1], "end": [39.7, 19.8]},
        {"id": "top", "type": "line", "start": [40.1, 20.2], "end": [-0.2, 19.7]},
        {"id": "left", "type": "line", "start": [0.2, 20.1], "end": [-0.1, 0.2]},
    ]
    order = ["bottom", "right", "top", "left"]
    constraints = [
        {"type": "coincident", "a": [entity_id, "end"],
         "b": [order[(index + 1) % 4], "start"]}
        for index, entity_id in enumerate(order)
    ]
    constraints += [
        {"type": "horizontal", "entity": "bottom"},
        {"type": "horizontal", "entity": "top"},
        {"type": "vertical", "entity": "right"},
        {"type": "vertical", "entity": "left"},
        {"type": "dimension", "kind": "distance_y", "a": ["right", "start"],
         "b": ["right", "end"], "value": 20},
        {"type": "fix", "point": ["bottom", "start"], "value": [0, 0]},
    ]
    if include_width:
        constraints.insert(-1, {
            "type": "dimension", "kind": "distance_x", "a": ["bottom", "start"],
            "b": ["bottom", "end"], "value": 40,
        })
    return {
        "entities": entities,
        "constraints": constraints,
        "regions": [{"outer": order, "holes": []}],
    }


def test_arbitrary_sketch_extrudes_outer_contour_and_hole():
    result = build({
        "op": "sketch_extrude",
        "depth": 5,
        "profile": profile(
            polygon([[0, 0], [40, 0], [40, 20], [0, 20]]),
            [circle(5, [20, 10])],
        ),
    })

    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == 1
    assert result["stats"]["volume"] == pytest.approx((800 - 25 * math.pi) * 5, abs=1e-6)
    assert result["stats"]["bbox"] == pytest.approx([0, 0, 0, 40, 20, 5], abs=1e-7)


def test_arbitrary_sketch_rejects_open_and_self_intersecting_contours():
    open_profile = profile({
        "kind": "segments",
        "segments": [
            {"type": "line", "start": [0, 0], "end": [10, 0]},
            {"type": "line", "start": [10, 0], "end": [10, 10]},
        ],
    })
    with pytest.raises(worker.GeometryError) as open_error:
        build({"op": "sketch_extrude", "depth": 5, "profile": open_profile})
    assert open_error.value.code == "sketch_open"

    bow_tie = profile(polygon([[0, 0], [10, 10], [0, 10], [10, 0]]))
    with pytest.raises(worker.GeometryError) as invalid_error:
        build({"op": "sketch_extrude", "depth": 5, "profile": bow_tie})
    assert invalid_error.value.code == "sketch_invalid"


def test_constraint_solver_reports_exact_rectangle_dof_and_extrudes_solution():
    sketch = constrained_rectangle()
    solution = worker.handle_solve_sketch({"sketch": sketch})
    result = build({"op": "constrained_sketch_extrude", "sketch": sketch, "depth": 5})

    assert solution["status"] == "fully_constrained"
    assert solution["degrees_of_freedom"] == 0
    assert solution["max_residual"] < 1e-7
    assert result["stats"]["volume"] == pytest.approx(40 * 20 * 5, abs=1e-5)
    assert result["stats"]["parts"][0]["metadata"]["degrees_of_freedom"] == 0


def test_constraint_solver_preserves_one_free_width_and_drag_respects_fixed_point():
    sketch = constrained_rectangle(include_width=False)
    solution = worker.handle_solve_sketch({"sketch": sketch})
    dragged = worker.handle_solve_sketch({
        "sketch": sketch,
        "drag": {"point": ["bottom", "end"], "value": [50, 0]},
    })

    assert solution["status"] == "under_constrained"
    assert solution["degrees_of_freedom"] == 1
    bottom = next(entity for entity in dragged["entities"] if entity["id"] == "bottom")
    assert bottom["start"] == pytest.approx([0, 0], abs=1e-7)
    assert bottom["end"] == pytest.approx([50, 0], abs=1e-7)
    assert dragged["degrees_of_freedom"] == 0


def test_constraint_solver_distinguishes_conflict_from_compatible_redundancy():
    redundant = constrained_rectangle()
    redundant["constraints"].append({"type": "parallel", "a": "bottom", "b": "top"})
    solution = worker.handle_solve_sketch({"sketch": redundant})
    assert solution["degrees_of_freedom"] == 0
    assert solution["redundant_constraints"] >= 1

    conflicting = constrained_rectangle()
    conflicting["constraints"].append({
        "type": "dimension", "kind": "length", "entity": "bottom", "value": 35,
    })
    with pytest.raises(worker.GeometryError) as error:
        worker.handle_solve_sketch({"sketch": conflicting})
    assert error.value.code == "constraint_conflict"


def test_constraint_solver_parallel_perpendicular_tangent_equal_and_dimension_fixtures():
    sketch = {
        "entities": [
            {"id": "fixed", "type": "line", "start": [0, 0], "end": [10, 0]},
            {"id": "parallel", "type": "line", "start": [0, 5], "end": [9, 5.5]},
            {"id": "normal", "type": "line", "start": [5, 0], "end": [5.2, 8]},
            {"id": "circle", "type": "circle", "center": [5, 2.8], "radius": 2.5},
        ],
        "constraints": [
            {"type": "fix", "entity": "fixed", "value": [0, 0, 10, 0]},
            {"type": "horizontal", "entity": "parallel"},
            {"type": "parallel", "a": "fixed", "b": "parallel"},
            {"type": "perpendicular", "a": "fixed", "b": "normal"},
            {"type": "equal", "a": "fixed", "b": "parallel"},
            {"type": "dimension", "kind": "length", "entity": "normal", "value": 8},
            {"type": "dimension", "kind": "radius", "entity": "circle", "value": 3},
            {"type": "tangent", "line": "fixed", "circle": "circle", "side": 1},
        ],
    }
    solution = worker.handle_solve_sketch({"sketch": sketch})
    entities = {entity["id"]: entity for entity in solution["entities"]}

    assert solution["max_residual"] < 1e-7
    assert math.dist(entities["parallel"]["start"], entities["parallel"]["end"]) == pytest.approx(10)
    assert math.dist(entities["normal"]["start"], entities["normal"]["end"]) == pytest.approx(8)
    assert entities["circle"]["radius"] == pytest.approx(3)
    assert entities["circle"]["center"][1] == pytest.approx(3)


def test_mesh_transform_and_hole_repair_report_specific_diagnostics():
    import numpy as np
    import trimesh
    source = trimesh.creation.box(extents=[10, 10, 10])
    removed = np.where(source.face_normals[:, 2] > 0.9)[0]
    source.update_faces(~np.isin(np.arange(len(source.faces)), removed))
    source.remove_unreferenced_vertices()

    result = worker.handle_build({
        "parts": [],
        "operations": [
            embedded_mesh(source),
            {"op": "mesh_repair", "action": "fill_holes"},
            {"op": "mesh_transform", "translate": [20, 0, 5],
             "rotate_deg": [0, 0, 0], "scale": [2, 1, 0.5]},
        ],
    })

    assert result["stats"]["mesh_mode"] is True
    assert result["stats"]["is_valid"] is True
    assert result["stats"]["triangle_count"] == 12
    assert result["stats"]["volume"] == pytest.approx(1000, abs=1e-5)
    assert result["stats"]["bbox"] == pytest.approx([10, -5, 2.5, 30, 5, 7.5], abs=1e-6)
    repair = result["stats"]["mesh_history"][1]
    assert repair["before"]["boundary_edges"] == 4
    assert repair["after"]["boundary_edges"] == 0
    assert repair["after"]["self_intersection"] == "unknown"


def test_mesh_repair_rejects_counterexample_without_supported_hole():
    import trimesh
    source = trimesh.creation.box(extents=[10, 10, 10])
    with pytest.raises(worker.GeometryError) as error:
        worker.handle_build({
            "parts": [],
            "operations": [embedded_mesh(source), {"op": "mesh_repair", "action": "fill_holes"}],
        })
    assert error.value.code == "mesh_repair_no_change"


def test_mesh_decimation_preserves_torus_hole_components_bbox_and_volume_range():
    import trimesh
    source = trimesh.creation.torus(
        major_radius=10, minor_radius=3, major_sections=96, minor_sections=48)
    result = worker.handle_build({
        "parts": [],
        "operations": [
            embedded_mesh(source),
            {"op": "mesh_decimate", "target_ratio": 0.30,
             "minimum_ratio": 0.25, "maximum_ratio": 0.35,
             "volume_tolerance": 0.03},
        ],
    })
    decimation = result["stats"]["mesh_history"][-1]

    assert 0.25 <= decimation["actual_ratio"] <= 0.35
    assert result["stats"]["triangle_count"] < len(source.faces)
    assert result["stats"]["mesh_diagnostics"]["components"] == 1
    assert result["stats"]["mesh_diagnostics"]["euler_number"] == 0
    assert decimation["volume_relative_error"] < 0.03
    assert result["stats"]["bbox"] == pytest.approx([
        *source.bounds[0], *source.bounds[1]], abs=1e-5)
    assert decimation["shape_error"]["global_hausdorff_guarantee"] is False
    assert decimation["shape_error"]["kind"] == "sampled_vertex_nearest_neighbor"


def test_decorative_image_relief_is_reproducible_mesh_with_recorded_model_seed_and_scale():
    from io import BytesIO
    import numpy as np
    from PIL import Image
    pixels = np.tile(np.linspace(0, 255, 64, dtype=np.uint8), (32, 1))
    image = Image.fromarray(pixels, mode="L")
    stream = BytesIO()
    image.save(stream, format="PNG")
    common = {
        "format": "png",
        "source_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
        "model": "heightmap-luminance-v1",
        "width_mm": 40,
        "relief_height": 4,
        "base_thickness": 2,
        "samples": 32,
        "noise_strength": 0.01,
    }
    first = worker.handle_image_relief_preview({**common, "seed": 42})
    repeated = worker.handle_image_relief_preview({**common, "seed": 42})
    changed = worker.handle_image_relief_preview({**common, "seed": 43})
    metadata = first["stats"]["mesh_history"][0]

    assert first["stats"]["is_valid"] is True
    assert first["stats"]["bbox"] == pytest.approx([0, 0, 0, 40, 20, 5.990341955], abs=1e-6)
    assert first["mesh"]["sha256"] == repeated["mesh"]["sha256"]
    assert first["mesh"]["sha256"] != changed["mesh"]["sha256"]
    assert metadata["model"] == "heightmap-luminance-v1"
    assert metadata["seed"] == 42
    assert metadata["settings"]["units"] == "mm"
    assert metadata["quality"]["value"] > 0.99
    assert metadata["quality"]["engineering_accuracy"] is False


@pytest.mark.parametrize("override, code", [
    ({"model": "unknown"}, "bad_params"),
    ({"samples": 4}, "bad_params"),
    ({"width_mm": 0}, "bad_params"),
])
def test_decorative_image_relief_rejects_invalid_model_or_limits(override, code):
    from io import BytesIO
    from PIL import Image
    stream = BytesIO()
    Image.new("L", (8, 8), 128).save(stream, format="PNG")
    operation = {
        "format": "png",
        "source_base64": base64.b64encode(stream.getvalue()).decode("ascii"),
        "model": "heightmap-luminance-v1",
        "seed": 1,
        "width_mm": 20,
        "relief_height": 2,
        "base_thickness": 1,
        "samples": 16,
        **override,
    }
    with pytest.raises(worker.GeometryError) as error:
        worker.handle_image_relief_preview(operation)
    assert error.value.code == code


@pytest.mark.parametrize("angle, expected", [(360, 1500 * math.pi), (180, 750 * math.pi)])
def test_revolve_matches_annular_sector_oracle(angle, expected):
    result = build({
        "op": "revolve",
        "plane": "XZ",
        "angle": angle,
        "axis": {"point": [0, 0, 0], "direction": [0, 0, 1]},
        "profile": profile(polygon([[5, 0], [10, 0], [10, 20], [5, 20]])),
    })

    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == 1
    assert result["stats"]["volume"] == pytest.approx(expected, abs=1e-6)


def test_sweep_circle_along_line_matches_cylinder_oracle():
    result = build({
        "op": "sweep",
        "section": {"kind": "circle", "radius": 2},
        "path": {"points": [[0, 0, 0], [0, 0, 20]]},
    })

    assert result["stats"]["is_valid"] is True
    assert result["stats"]["volume"] == pytest.approx(80 * math.pi, abs=1e-6)


def test_ruled_loft_matches_conical_frustum_oracle():
    result = build({
        "op": "loft",
        "ruled": True,
        "sections": [
            {"plane": "XY", "offset": 0, "profile": profile(circle(10))},
            {"plane": "XY", "offset": 20, "profile": profile(circle(5))},
        ],
    })

    expected = math.pi * 20 * (100 + 50 + 25) / 3
    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == 1
    assert result["stats"]["volume"] == pytest.approx(expected, abs=1e-6)


def test_cylindrical_shell_matches_wall_and_bottom_oracle():
    outer_radius, height, wall, bottom = 10, 20, 2, 3
    result = build({
        "op": "shell", "outer_radius": outer_radius, "height": height,
        "wall": wall, "bottom": bottom,
    })

    expected = math.pi * (
        outer_radius ** 2 * height - (outer_radius - wall) ** 2 * (height - bottom))
    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == 1
    assert result["stats"]["volume"] == pytest.approx(expected, abs=1e-6)
    assert result["stats"]["bbox"] == pytest.approx(
        [-outer_radius, -outer_radius, 0, outer_radius, outer_radius, height], abs=1e-7)


@pytest.mark.parametrize("wall,bottom", [(10, 3), (2, 20)])
def test_cylindrical_shell_rejects_disappearing_wall_or_bottom(wall, bottom):
    with pytest.raises(worker.GeometryError) as error:
        build({
            "op": "shell", "outer_radius": 10, "height": 20,
            "wall": wall, "bottom": bottom,
        })
    assert error.value.code == "bad_params"


def test_draft_prism_matches_linear_section_oracle():
    width, depth, height, angle = 20, 12, 10, 5
    result = build({
        "op": "draft_prism", "width": width, "depth": depth,
        "height": height, "angle": angle,
    })

    inset = height * math.tan(math.radians(angle))
    expected = height * (width * depth - inset * (width + depth) + 4 * inset ** 2 / 3)
    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == 1
    assert result["stats"]["volume"] == pytest.approx(expected, abs=1e-6)


def test_rib_union_accounts_for_known_overlap():
    values = {
        "base_length": 40, "base_width": 20, "base_thickness": 4,
        "rib_length": 15, "rib_height": 12, "rib_width": 3, "overlap": 1,
    }
    result = build({"op": "rib", **values})

    base_volume = values["base_length"] * values["base_width"] * values["base_thickness"]
    rib_volume = (
        values["rib_length"] * (values["rib_height"] + values["overlap"])
        * values["rib_width"] / 2)
    overlap_volume = (
        values["rib_length"] * values["overlap"]
        * (1 + values["rib_height"] / (values["rib_height"] + values["overlap"]))
        * values["rib_width"] / 2)
    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == 1
    assert result["stats"]["volume"] == pytest.approx(
        base_volume + rib_volume - overlap_volume, abs=1e-6)


@pytest.mark.parametrize(
    "fixture_id,body,clearance,expected_cut",
    [
        ("nut_m5", (20, 20, 8), 0.4, math.sqrt(3) / 2 * 8.4 ** 2 * 4),
        ("bearing_608", (32, 32, 12), 0.4, math.pi * 22.4 ** 2 / 4 * 7),
        (
            "heat_insert_m3", (16, 16, 10), 0.2,
            math.pi / 4 * (4.8 ** 2 * 5 + 4.2 ** 2 * 5),
        ),
    ],
)
def test_fit_fixtures_match_explicit_dimensional_oracles(
        fixture_id, body, clearance, expected_cut):
    length, width, height = body
    result = build({
        "op": "fit_pocket", "fixture_id": fixture_id, "fixture_version": "1",
        "body_length": length, "body_width": width, "body_height": height,
        "clearance": clearance, "clearance_mode": "diametral",
    })

    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == 1
    assert result["stats"]["volume"] == pytest.approx(
        length * width * height - expected_cut, abs=1e-6)


def test_fit_clearance_modes_have_distinct_size_and_origin_semantics():
    base = {
        "op": "fit_pocket", "fixture_id": "bearing_608", "fixture_version": "1",
        "body_length": 32, "body_width": 32, "body_height": 12, "clearance": 0.4,
    }
    radial = build({**base, "clearance_mode": "radial"})
    diametral = build({**base, "clearance_mode": "diametral"})
    one_sided = build({**base, "clearance_mode": "one_sided"})

    radial_meta = radial["stats"]["parts"][0]["metadata"]
    diametral_meta = diametral["stats"]["parts"][0]["metadata"]
    one_sided_meta = one_sided["stats"]["parts"][0]["metadata"]
    assert radial_meta["effective_size"] == pytest.approx(22.8)
    assert diametral_meta["effective_size"] == pytest.approx(22.4)
    assert one_sided_meta["effective_size"] == pytest.approx(22.4)
    assert radial_meta["pocket_center_x"] == 0
    assert diametral_meta["pocket_center_x"] == 0
    assert one_sided_meta["pocket_center_x"] == pytest.approx(0.2)
    assert radial["stats"]["volume"] < diametral["stats"]["volume"]
    assert one_sided["stats"]["volume"] == pytest.approx(
        diametral["stats"]["volume"], abs=1e-6)


@pytest.mark.parametrize(
    "overrides",
    [
        {"fixture_version": "2"},
        {"clearance": -0.1},
        {"body_length": 22.1},
        {"pocket_depth": 12},
    ],
)
def test_fit_pocket_rejects_unknown_version_or_missing_wall(overrides):
    operation = {
        "op": "fit_pocket", "fixture_id": "bearing_608", "fixture_version": "1",
        "body_length": 32, "body_width": 32, "body_height": 12,
        "clearance": 0.2, "clearance_mode": "diametral",
    }
    with pytest.raises(worker.GeometryError) as error:
        build({**operation, **overrides})
    assert error.value.code == "bad_params"


def test_svg_viewbox_units_and_evenodd_hole_are_extruded():
    rectangle = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" '
        'viewBox="0 0 200 100"><rect width="200" height="100"/></svg>')
    solid = build({
        "op": "vector_extrude", "format": "svg",
        "source_text": rectangle, "height": 5,
    })
    assert solid["stats"]["bbox"] == pytest.approx([0, 0, 0, 20, 10, 5], abs=2e-5)
    assert solid["stats"]["volume"] == pytest.approx(1000, abs=0.01)

    with_hole = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="20mm" height="10mm" '
        'viewBox="0 0 200 100"><path fill-rule="evenodd" '
        'd="M0 0H200V100H0Z M50 25H150V75H50Z"/></svg>')
    hollow = build({
        "op": "vector_extrude", "format": "svg",
        "source_text": with_hole, "height": 5,
    })
    assert hollow["stats"]["volume"] == pytest.approx(750, abs=0.01)


@pytest.mark.parametrize(
    "source",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="https://example.com/a.png"/></svg>',
        '<!DOCTYPE svg [<!ENTITY x "boom">]><svg xmlns="http://www.w3.org/2000/svg">&x;</svg>',
    ],
)
def test_svg_rejects_executable_external_or_entity_content(source):
    with pytest.raises(worker.GeometryError) as error:
        build({"op": "vector_extrude", "format": "svg", "source_text": source, "height": 2})
    assert error.value.code == "vector_unsafe"


def dxf_rectangle_source(unit_code):
    import ezdxf
    document = ezdxf.new("R2010")
    document.header["$INSUNITS"] = unit_code
    document.modelspace().add_lwpolyline(
        [(0, 0), (2, 0), (2, 1), (0, 1)], close=True)
    stream = StringIO()
    document.write(stream)
    return stream.getvalue()


def test_dxf_explicit_units_scale_to_millimeters_and_unitless_requires_policy():
    inches = build({
        "op": "vector_extrude", "format": "dxf",
        "source_text": dxf_rectangle_source(1), "height": 2,
    })
    assert inches["stats"]["bbox"] == pytest.approx([0, 0, 0, 50.8, 25.4, 2], abs=1e-6)
    assert inches["stats"]["volume"] == pytest.approx(50.8 * 25.4 * 2, abs=1e-6)

    with pytest.raises(worker.GeometryError) as missing_units:
        build({
            "op": "vector_extrude", "format": "dxf",
            "source_text": dxf_rectangle_source(0), "height": 2,
        })
    assert missing_units.value.code == "vector_units_required"

    millimeters = build({
        "op": "vector_extrude", "format": "dxf",
        "source_text": dxf_rectangle_source(0), "unit_scale": 1, "height": 2,
    })
    assert millimeters["stats"]["volume"] == pytest.approx(4, abs=1e-6)


def test_cyrillic_text_relief_preserves_counter_and_fixed_font_identity():
    base_volume = 30 * 20 * 4
    common = {
        "op": "text_relief", "text": "О", "font_size": 10,
        "relief_height": 1, "body_length": 30, "body_width": 20, "body_height": 4,
    }
    raised = build({**common, "mode": "add"})
    engraved = build({**common, "mode": "cut"})

    assert raised["stats"]["is_valid"] is True
    assert engraved["stats"]["is_valid"] is True
    assert raised["stats"]["solid_count"] == engraved["stats"]["solid_count"] == 1
    assert raised["stats"]["bbox"][5] == pytest.approx(5)
    assert raised["stats"]["volume"] - base_volume == pytest.approx(
        base_volume - engraved["stats"]["volume"], abs=1e-6)
    assert 0 < raised["stats"]["volume"] - base_volume < 4.8 * 7.5
    metadata = raised["stats"]["parts"][0]["metadata"]
    assert metadata["font"] == "JetBrains Mono 2.211"
    assert metadata["font_sha256"] == worker.TEXT_FONT_SHA256


def test_real_thread_pair_has_helical_geometry_pitch_and_clearance():
    operation = {
        "op": "thread_pair", "profile_version": "metric-60-v1",
        "major_diameter": 10, "pitch": 1.5, "length": 12,
        "hand": "right", "starts": 1, "clearance": 0.3,
        "nut_height": 5, "nut_across_flats": 18,
    }
    result = build(operation)

    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == 2
    part_stats = result["stats"]["parts"]
    bolt = next(part for part in part_stats if part["metadata"]["role"] == "external")
    nut = next(part for part in part_stats if part["metadata"]["role"] == "internal")
    metadata = bolt["metadata"]
    assert metadata["profile_version"] == "metric-60-v1"
    assert metadata["pitch"] == metadata["lead"] == 1.5
    assert metadata["working_length"] == 12
    assert metadata["assembly_intersection_volume"] == pytest.approx(0, abs=1e-9)
    assert nut["metadata"]["clearance"] == 0.3
    core_volume = math.pi * metadata["core_radius"] ** 2 * 12
    major_cylinder_volume = math.pi * 5 ** 2 * 12
    assert core_volume < bolt["volume"] < major_cylinder_volume
    assert len(result["stats"]["edges"]) > 20

    left = build({**operation, "hand": "left"})
    assert left["stats"]["parts"][0]["metadata"]["hand"] == "left"
    assert left["mesh"]["sha256"] != result["mesh"]["sha256"]


@pytest.mark.parametrize(
    "overrides",
    [
        {"profile_version": "unknown"},
        {"starts": 2},
        {"clearance": 0},
        {"nut_across_flats": 10.2},
    ],
)
def test_thread_pair_rejects_unsupported_or_intersecting_contract(overrides):
    operation = {
        "op": "thread_pair", "profile_version": "metric-60-v1",
        "major_diameter": 10, "pitch": 1.5, "length": 12,
        "hand": "right", "starts": 1, "clearance": 0.3,
        "nut_height": 5, "nut_across_flats": 18,
    }
    with pytest.raises(worker.GeometryError) as error:
        build({**operation, **overrides})
    assert error.value.code == "bad_params"


def test_clearance_calibration_builds_distinct_labeled_samples():
    values = [0.1, 0.2, 0.35]
    result = build({
        "op": "clearance_calibration", "values": values,
        "nominal_diameter": 8, "coupon_length": 24, "coupon_width": 18,
        "thickness": 3, "spacing": 28, "font_size": 3, "label_height": 0.6,
        "profile_name": "PLA test v1",
    })

    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == len(values)
    parts = result["stats"]["parts"]
    assert [part["metadata"]["clearance"] for part in parts] == values
    assert [part["metadata"]["label"] for part in parts] == ["0.10", "0.20", "0.35"]
    assert [part["metadata"]["effective_diameter"] for part in parts] == [8.1, 8.2, 8.35]
    assert all(part["metadata"]["clearance_mode"] == "diametral" for part in parts)
    assert all(part["metadata"]["calibration_profile"] == "PLA test v1" for part in parts)
    assert len({round(part["volume"], 6) for part in parts}) == len(values)


@pytest.mark.parametrize(
    "values",
    [
        [0.2],
        [0.1, 0.1],
        [0.1, -0.1],
        list(range(11)),
    ],
)
def test_clearance_calibration_rejects_invalid_series(values):
    with pytest.raises(worker.GeometryError) as error:
        build({
            "op": "clearance_calibration", "values": values,
            "nominal_diameter": 8, "coupon_length": 24, "coupon_width": 18,
            "thickness": 3, "spacing": 28, "font_size": 3, "label_height": 0.6,
        })
    assert error.value.code == "bad_params"


def test_split_connector_pair_preserves_source_and_print_placement_contract():
    values = {
        "length": 40, "width": 24, "height": 10,
        "pin_radius": 2, "pin_length": 6,
        "radial_clearance": 0.25, "print_separation": 5,
    }
    result = build({"op": "split_connector_pair", **values})

    assert result["stats"]["is_valid"] is True
    assert result["stats"]["solid_count"] == 2
    pins = next(
        part for part in result["stats"]["parts"] if part["metadata"]["role"] == "pins")
    sockets = next(
        part for part in result["stats"]["parts"] if part["metadata"]["role"] == "sockets")
    assert pins["metadata"]["source_volume"] == 40 * 24 * 10
    assert pins["metadata"]["source_bbox"] == [40, 24, 10]
    assert pins["metadata"]["assembly_intersection_volume"] == pytest.approx(0, abs=1e-9)
    assert pins["metadata"]["radial_clearance"] == 0.25
    assert sockets["metadata"]["print_translation"] == [0, 29, 0]
    assert sockets["metadata"]["assembly_translation"] == [0, -29, 0]
    expected_pins = 40 * 24 * 10 / 2 + 2 * math.pi * 2 ** 2 * 6
    expected_sockets = 40 * 24 * 10 / 2 - 2 * math.pi * 2.25 ** 2 * 6.5
    assert pins["volume"] == pytest.approx(expected_pins, abs=1e-5)
    assert sockets["volume"] == pytest.approx(expected_sockets, abs=1e-5)


@pytest.mark.parametrize(
    "overrides",
    [
        {"pin_length": 20},
        {"pin_radius": 5},
        {"radial_clearance": 5},
    ],
)
def test_split_connector_pair_rejects_thin_wall_or_oversized_pin(overrides):
    operation = {
        "op": "split_connector_pair", "length": 40, "width": 24, "height": 10,
        "pin_radius": 2, "pin_length": 6,
        "radial_clearance": 0.25, "print_separation": 5,
    }
    with pytest.raises(worker.GeometryError) as error:
        build({**operation, **overrides})
    assert error.value.code == "bad_params"
