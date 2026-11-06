import copy
import hashlib
import json
import math
import struct
import sys
import threading
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path
from xml.etree import ElementTree

import pytest

import worker

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import dev_shim

pytestmark = [pytest.mark.integration, pytest.mark.real_kernel]


@pytest.fixture
def document(monkeypatch):
    monkeypatch.setitem(dev_shim.DOCS, "main", dev_shim.Doc())
    monkeypatch.setitem(dev_shim.DOCS, "tutorial", dev_shim.Doc())
    monkeypatch.setattr(dev_shim, "ACTIVE", ["main"])
    yield dev_shim.doc()
    process = dev_shim._worker
    if process is not None and process.poll() is None:
        process.terminate()
        process.wait(timeout=10)
    dev_shim._worker = None


def box_document(template="box", params=None):
    return {"parts": [{"part_id": "part-1", "template": template, "params": params or {}}], "operations": []}


def assert_mesh_resource_matches_descriptor(resource):
    data = Path(resource["path"]).read_bytes()
    assert len(data) == resource["bytes"]
    assert hashlib.sha256(data).hexdigest() == resource["sha256"]
    vertex_count, triangle_count = struct.unpack_from("<II", data)
    assert vertex_count == resource["vertex_count"]
    assert triangle_count == resource["triangle_count"]
    assert len(data) == 8 + vertex_count * 12 + triangle_count * 12
    positions = struct.unpack_from(f"<{vertex_count * 3}f", data, 8)
    indices = struct.unpack_from(f"<{triangle_count * 3}I", data, 8 + vertex_count * 12)
    assert all(math.isfinite(value) for value in positions)
    assert all(index < vertex_count for index in indices)
    for face_range in resource["face_ranges"]:
        assert 0 <= face_range["tri_start"] <= triangle_count
        assert 0 <= face_range["tri_count"]
        assert face_range["tri_start"] + face_range["tri_count"] <= triangle_count
    if resource["face_ranges"]:
        assert sum(face["tri_count"] for face in resource["face_ranges"]) == triangle_count
    return data


def test_existing_four_bend_mesh_survives_image_preview_cancel_restore(document, tmp_path):
    from PIL import Image

    created = dev_shim.cmd_doc_create({"template": "plate_with_holes", "params": {"hole_offset": 5}})
    common = {
        "target_id": created["parts"][0]["part_id"],
        "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1,
                     "anchor": [0, 0], "selected_area": 3200 - 16 * math.pi},
        "bend_axis": "x", "angle": 45, "inside_radius": 1, "moving_side": 1,
    }
    for position, direction in [(-30, 1), (-10, -1), (10, 1), (30, -1)]:
        state = dev_shim.cmd_doc_sheet_bend({**common, "position": position, "direction": direction})
        assert state["error"] is None
    assert state["stats"]["volume"] == pytest.approx(19200 - 96 * math.pi, abs=0.001)
    before = copy.deepcopy(document.__dict__)
    original_mesh = dev_shim.cmd_doc_get_mesh({})
    original_bytes = assert_mesh_resource_matches_descriptor(document.mesh)
    image_path = tmp_path / "relief.png"
    Image.new("L", (16, 8), 127).save(image_path)
    preview = dev_shim.cmd_image_relief_preview({
        "path": str(image_path), "model": "heightmap-luminance-v1", "seed": 7,
        "width_mm": 40, "relief_height": 4, "base_thickness": 2,
        "samples": 24, "noise_strength": 0.01, "invert": False,
    })
    assert preview["stats"]["mesh_mode"] is True
    assert_mesh_resource_matches_descriptor(preview["mesh"])
    assert document.__dict__ == before
    assert assert_mesh_resource_matches_descriptor(document.mesh) == original_bytes
    restored = dev_shim.cmd_doc_get_mesh({})
    assert restored == original_mesh
    assert restored["face_ranges"]
    assert all(math.isfinite(value) for value in restored["positions"])


def test_main_mesh_survives_tutorial_build_and_slot_return(document):
    dev_shim.cmd_doc_create({"template": "box", "params": {"length": 55}})
    before = copy.deepcopy(document.__dict__)
    original_mesh = dev_shim.cmd_doc_get_mesh({})
    original_bytes = assert_mesh_resource_matches_descriptor(document.mesh)
    dev_shim.cmd_doc_new_tutorial({})
    dev_shim.cmd_doc_create({"template": "sphere", "params": {"diameter": 15}})
    assert_mesh_resource_matches_descriptor(dev_shim.doc().mesh)
    dev_shim.cmd_doc_switch_slot({"slot": "main"})
    assert dev_shim.doc() is document
    assert document.__dict__ == before
    assert assert_mesh_resource_matches_descriptor(document.mesh) == original_bytes
    assert dev_shim.cmd_doc_get_mesh({}) == original_mesh


def test_committed_mesh_survives_discarded_candidate_build(document):
    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    before = copy.deepcopy(document.__dict__)
    original_bytes = assert_mesh_resource_matches_descriptor(document.mesh)
    candidate = copy.deepcopy(document)
    candidate.parts[0]["params"]["length"] = 75
    candidate.rebuild()
    assert candidate.error is None
    assert candidate.stats["volume"] == pytest.approx(45000, abs=0.001)
    assert_mesh_resource_matches_descriptor(candidate.mesh)
    assert document.__dict__ == before
    assert assert_mesh_resource_matches_descriptor(document.mesh) == original_bytes


@pytest.mark.parametrize("first_format", ["step", "stl"])
def test_import_mesh_resources_keep_earlier_descriptor_bytes(tmp_path, first_format):
    import trimesh
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    step_path = tmp_path / "source.step"
    writer = STEPControl_Writer()
    writer.Transfer(BRepPrimAPI_MakeBox(10, 20, 30).Shape(), STEPControl_AsIs)
    assert writer.Write(str(step_path)) == IFSelect_RetDone
    stl_path = tmp_path / "source.stl"
    trimesh.creation.box(extents=[5, 6, 7]).export(stl_path)
    paths = {"step": step_path, "stl": stl_path}
    first = worker.handle_import({"format": first_format, "path": str(paths[first_format])})
    original = assert_mesh_resource_matches_descriptor(first["mesh"])
    second_format = "stl" if first_format == "step" else "step"
    second = worker.handle_import({"format": second_format, "path": str(paths[second_format])})
    assert_mesh_resource_matches_descriptor(second["mesh"])
    assert assert_mesh_resource_matches_descriptor(first["mesh"]) == original
    assert first["mesh"]["path"] != second["mesh"]["path"]


def test_identical_mesh_bytes_reuse_immutable_resource():
    first = worker.handle_build(box_document())
    original = assert_mesh_resource_matches_descriptor(first["mesh"])
    original_mtime = Path(first["mesh"]["path"]).stat().st_mtime_ns
    second = worker.handle_build(box_document())
    assert second["mesh"] == first["mesh"]
    assert assert_mesh_resource_matches_descriptor(first["mesh"]) == original
    assert Path(first["mesh"]["path"]).stat().st_mtime_ns == original_mtime


def test_nested_compound_statistics_and_measurement_sum_real_solids():
    case = worker.handle_build(box_document("case_with_lid"))
    assert case["stats"]["volume"] == pytest.approx(43827.2, abs=0.001)
    assert case["stats"]["parts"][0]["volume"] == pytest.approx(43827.2, abs=0.001)
    array = box_document()
    array["operations"] = [{"op": "array_linear", "part_id": "part-1", "count": 3, "step": [50, 0, 0]}]
    result = worker.handle_build(array)
    assert result["stats"]["volume"] == pytest.approx(72000, abs=0.001)
    assert result["stats"]["parts"][0]["volume"] == pytest.approx(72000, abs=0.001)
    measured = worker.handle_measure({**array, "type": "volume"})
    assert measured["volume"] == pytest.approx(72000, abs=0.001)


def test_case_lid_3mf_keeps_two_individually_closed_objects(tmp_path):
    import trimesh

    destination = tmp_path / "case.3mf"
    worker.handle_export({**box_document("case_with_lid"), "format": "3mf", "path": str(destination)})
    with zipfile.ZipFile(destination) as archive:
        model = ElementTree.fromstring(archive.read("3D/3dmodel.model"))
    namespace = {"m": "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"}
    volumes = []
    meshes = model.findall("m:resources/m:object/m:mesh", namespace)
    assert len(meshes) == 2
    for mesh in meshes:
        vertices = [[float(vertex.attrib[axis]) for axis in ["x", "y", "z"]] for vertex in mesh.findall("m:vertices/m:vertex", namespace)]
        triangles = [[int(triangle.attrib[axis]) for axis in ["v1", "v2", "v3"]] for triangle in mesh.findall("m:triangles/m:triangle", namespace)]
        independent = trimesh.Trimesh(vertices=vertices, faces=triangles, process=True)
        assert independent.is_watertight
        assert independent.is_winding_consistent
        volumes.append(independent.volume)
    assert sorted(volumes) == pytest.approx([14355.2, 29472], abs=0.001)


@pytest.mark.parametrize("units,width,height", [("mm", 20, 10), ("cm", 2, 1), ("in", 20 / 25.4, 10 / 25.4)])
def test_svg_physical_units_meet_strict_volume_oracle(units, width, height):
    source = f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.17g}{units}" height="{height:.17g}{units}" viewBox="0 0 20 10"><rect width="20" height="10"/></svg>'
    result = worker.handle_build({"parts": [], "operations": [{"op": "vector_extrude", "format": "svg", "source_text": source, "height": 5}]})
    assert abs(result["stats"]["volume"] - 1000) <= 0.001
    assert result["stats"]["bbox"] == pytest.approx([0, 0, 0, 20, 10, 5], abs=0.001)


def test_bad_geometry_open_preserves_entire_working_document(document, tmp_path):
    dev_shim.cmd_doc_create({"template": "box", "params": {"length": 55}})
    before = copy.deepcopy(document.__dict__)
    destination = tmp_path / "invalid.printforge"
    content = {"schema_version": 4, "document_id": "other", "parts": [{"part_id": "part-1", "template": "box", "params": {"length": -10}}]}
    with zipfile.ZipFile(destination, "w") as archive:
        archive.writestr("document.json", json.dumps(content))
    with pytest.raises(RuntimeError, match="bad_params"):
        dev_shim.cmd_doc_open({"path": str(destination)})
    assert dev_shim.doc() is document
    assert document.__dict__ == before


@pytest.mark.parametrize("command,args", [
    ("cmd_doc_create", {"template": "box", "params": {"length": -10}}),
    ("cmd_doc_add_part", {"template": "washer", "params": {"inner_diameter": 50}}),
    ("cmd_doc_shell", {"outer_radius": 10, "height": 20, "wall": 10, "bottom": 3}),
    ("cmd_doc_array", {"part_id": "part-1", "count": 1, "step": [50, 0, 0]}),
])
def test_failed_geometry_operation_preserves_redo_and_revision(document, command, args):
    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    dev_shim.cmd_doc_set_parameter({"name": "length", "value": 50})
    dev_shim.cmd_doc_undo({})
    before = copy.deepcopy(document.__dict__)
    failed = getattr(dev_shim, command)(args)
    assert failed["error"]
    for key, value in before.items():
        if key != "error":
            assert document.__dict__[key] == value, key
    redone = dev_shim.cmd_doc_redo({})
    assert redone["params"]["length"] == 50


def test_open_polyline_failure_preserves_redo(document, tmp_path):
    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    dev_shim.cmd_doc_undo({})
    before = copy.deepcopy(document.__dict__)
    source = tmp_path / "open.svg"
    source.write_text('<svg xmlns="http://www.w3.org/2000/svg"><path fill="none" d="M0 0 L20 0 L20 10"/></svg>')
    failed = dev_shim.cmd_doc_vector_extrude({"path": str(source), "format": "svg", "height": 5})
    assert failed["error"]
    assert document.history == before["history"]
    assert document.revision == before["revision"]
    assert document.index == before["index"]
    assert failed["can_redo"]


@pytest.mark.parametrize("direction", ["undo", "redo"])
def test_failed_history_rebuild_preserves_current_document(document, monkeypatch, direction):
    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    dev_shim.cmd_doc_set_parameter({"name": "length", "value": 50})
    if direction == "redo":
        dev_shim.cmd_doc_undo({})
    before = copy.deepcopy(document.__dict__)

    def interrupted(*args, **kwargs):
        raise dev_shim.geo_error("geometry_cancelled", "Операция отменена")

    monkeypatch.setattr(dev_shim, "worker_call", interrupted)
    result = getattr(dev_shim, f"cmd_doc_{direction}")({})
    assert result["error"]["code"] == "geometry_cancelled"
    for key, value in before.items():
        if key != "error":
            assert document.__dict__[key] == value, key


def test_invalid_create_input_does_not_clear_document_before_build(document):
    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    before = copy.deepcopy(document.__dict__)
    with pytest.raises(RuntimeError, match="bad_params"):
        dev_shim.cmd_doc_create({"template": "box", "params": {"length": "abc"}})
    assert document.__dict__ == before


@pytest.mark.parametrize("point", [[None, 0, 0], [float("inf"), 0, 0], ["abc", 0, 0], [0, 0], [True, 0, 0]])
def test_distance_invalid_coordinates_have_meaningful_error(point):
    with pytest.raises(worker.GeometryError, match="конечными числами") as error:
        worker.handle_measure({**box_document(), "type": "distance", "p0": [0, 0, 0], "p1": point})
    assert error.value.code == "bad_params"


def test_step_import_is_persistent_atomic_and_schema_five(document, tmp_path):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer

    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    old_path = tmp_path / "original.printforge"
    dev_shim.cmd_doc_save({"path": str(old_path)})
    original_bytes = old_path.read_bytes()
    source = tmp_path / "independent.step"
    writer = STEPControl_Writer()
    writer.Transfer(BRepPrimAPI_MakeBox(10, 20, 30).Shape(), STEPControl_AsIs)
    assert writer.Write(str(source)) == IFSelect_RetDone
    imported = dev_shim.cmd_doc_import({"format": "step", "path": str(source)})
    state = imported["document"]
    assert state["document_instance_id"] != document.document_instance_id
    assert state["doc_id"] != document.doc_id
    assert state["path"] is None
    assert state["dirty"]
    assert state["stats"]["volume"] == pytest.approx(6000, abs=0.001)
    assert state["stats"]["bbox"] == pytest.approx([0, 0, 0, 10, 20, 30], abs=0.001)
    assert old_path.read_bytes() == original_bytes
    destination = tmp_path / "imported.printforge"
    dev_shim.cmd_doc_save({"path": str(destination)})
    with zipfile.ZipFile(destination) as archive:
        assert json.loads(archive.read("document.json"))["schema_version"] == 5
    source.unlink()
    dev_shim.cmd_doc_create({"template": "sphere", "params": {}})
    reopened = dev_shim.cmd_doc_open({"path": str(destination)})
    assert reopened["stats"]["volume"] == pytest.approx(6000, abs=0.001)
    exported = dev_shim.cmd_doc_export({"format": "step", "path": str(tmp_path / "roundtrip.step")})
    assert exported["stats"]["volume"] == pytest.approx(6000, abs=0.001)
    measured = dev_shim.cmd_measure({"type": "volume"})
    assert measured["volume"] == pytest.approx(6000, abs=0.001)
    added = dev_shim.cmd_doc_add_part({"template": "box", "params": {"length": 2, "width": 2, "height": 2}})
    assert added["error"] is None
    assert added["stats"]["volume"] == pytest.approx(6008, abs=0.001)
    assert added["stats"]["solid_count"] == 2
    current = dev_shim.doc()
    before = copy.deepcopy(current.__dict__)
    source.write_text("invalid STEP")
    with pytest.raises(RuntimeError, match="step_invalid"):
        dev_shim.cmd_doc_import({"format": "step", "path": str(source)})
    assert dev_shim.doc() is current
    assert current.__dict__ == before


def test_dynamic_expressions_are_authoritative_atomic_and_persistent(document, tmp_path):
    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    width = dev_shim.cmd_doc_set_parameter({"name": "width", "value": 123, "expression": "длина / 2"})
    assert width["params"]["width"] == 20
    changed = dev_shim.cmd_doc_set_parameter({"name": "length", "value": 60})
    assert changed["params"]["width"] == 30
    assert changed["stats"]["volume"] == pytest.approx(36000, abs=0.001)
    dev_shim.cmd_doc_set_parameter({"name": "height", "value": 123, "expression": "width / 2 + 1"})
    changed = dev_shim.cmd_doc_set_parameter({"name": "length", "value": 80})
    assert changed["params"] == {"length": 80, "width": 40, "height": 21}
    assert changed["stats"]["volume"] == pytest.approx(67200, abs=0.001)
    undone = dev_shim.cmd_doc_undo({})
    assert undone["params"] == {"length": 60, "width": 30, "height": 16}
    before = copy.deepcopy(document.__dict__)
    failed = dev_shim.cmd_doc_set_parameter({"name": "length", "value": 80, "expression": "width * 2"})
    assert "Циклическая" in failed["error"]["message"]
    for key, value in before.items():
        if key != "error":
            assert document.__dict__[key] == value, key
    dev_shim.cmd_doc_clear_error({})
    project = tmp_path / "expressions.printforge"
    dev_shim.cmd_doc_save({"path": str(project)})
    reopened = dev_shim.cmd_doc_open({"path": str(project)})
    assert reopened["expressions"] == {"part-1.width": "длина / 2", "part-1.height": "width / 2 + 1"}
    changed = dev_shim.cmd_doc_set_parameter({"name": "length", "value": 100})
    assert changed["params"] == {"length": 100, "width": 50, "height": 26}


def test_partial_parameters_and_second_part_formulas_use_own_defaults(document, tmp_path):
    project = tmp_path / "partial.printforge"
    with zipfile.ZipFile(project, "w") as archive:
        archive.writestr("document.json", json.dumps({"schema_version": 4, "parts": [
            {"part_id": "part-1", "template": "box", "params": {}},
            {"part_id": "part-2", "template": "box", "params": {"length": 100}},
        ], "expressions": {"part-1.width": "length / 2", "part-2.width": "длина / 4"}}))
    opened = dev_shim.cmd_doc_open({"path": str(project)})
    assert opened["parts"][0]["params"]["width"] == 20
    assert opened["parts"][1]["params"]["width"] == 25
    changed = dev_shim.cmd_doc_set_parameter({"part_id": "part-2", "name": "length", "value": 120})
    assert changed["parts"][0]["params"]["width"] == 20
    assert changed["parts"][1]["params"]["width"] == 30


def test_tutorial_autosave_does_not_overwrite_explicit_lesson_snapshot(document, tmp_path, monkeypatch):
    main_before = copy.deepcopy(document.__dict__)
    dev_shim.ACTIVE[0] = "tutorial"
    dev_shim.cmd_doc_create({"template": "box", "params": {"length": 20}})
    path = tmp_path / "lesson.printforge"
    dev_shim.cmd_doc_save({"path": str(path)})
    frozen = path.read_bytes()
    dev_shim.cmd_doc_set_parameter({"name": "length", "value": 30})
    monkeypatch.setattr(dev_shim, "AUTOSAVE", {"path": None, "at": 0})
    server = ThreadingHTTPServer(("127.0.0.1", 0), dev_shim.Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        request = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/api/doc_get_state", data=b"{}", headers={"content-type": "application/json"})
        with urllib.request.urlopen(request, timeout=10) as response:
            assert json.load(response)["params"]["length"] == 30
        assert path.read_bytes() == frozen
        assert document.__dict__ == main_before
        assert dev_shim.doc().dirty
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize("changes", [
    {"width_mm": 41}, {"relief_height": 5}, {"base_thickness": 3},
    {"samples": 32}, {"seed": 43}, {"noise_strength": 0.02},
    {"invert": True}, {"model": "other"}, {"path_alias": True},
    {"missing_expected": True},
])
def test_image_apply_requires_actual_preview_settings(document, tmp_path, changes):
    from PIL import Image

    image = tmp_path / "gradient.png"
    Image.new("L", (16, 8), 128).save(image)
    settings = {"path": str(image), "width_mm": 40, "relief_height": 4,
                "base_thickness": 2, "samples": 24, "seed": 42,
                "noise_strength": 0, "invert": False, "model": "heightmap-luminance-v1"}
    dev_shim.cmd_doc_create({"template": "box", "params": {}})
    preview = dev_shim.cmd_image_relief_preview(settings)
    before = copy.deepcopy(document.__dict__)
    request = {**settings, **changes, "expected_sha256": preview["source_sha256"],
               "expected_settings_sha256": preview["settings_sha256"]}
    if changes.get("path_alias"):
        copy_path = tmp_path / "other.png"
        copy_path.write_bytes(image.read_bytes())
        request["path"] = str(copy_path)
    if changes.get("missing_expected"):
        del request["expected_settings_sha256"]
    with pytest.raises(RuntimeError, match="image_settings_changed"):
        dev_shim.cmd_doc_image_relief_apply(request)
    assert document.__dict__ == before
