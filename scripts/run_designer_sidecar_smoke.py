import argparse
import hashlib
import json
import math
import queue
import subprocess
import threading
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    binary = args.binary.resolve()
    responses = queue.Queue()
    cases = []
    process = subprocess.Popen([str(binary)], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)

    def read():
        for line in process.stdout:
            responses.put(json.loads(line))

    threading.Thread(target=read, daemon=True).start()
    sequence = 0

    def call(method, params=None, ok=True):
        nonlocal sequence
        sequence += 1
        request_id = f"designer-smoke-{sequence}"
        process.stdin.write(json.dumps({"request_id": request_id, "schema_version": 1,
                                       "method": method, "params": params or {}}) + "\n")
        process.stdin.flush()
        response = responses.get(timeout=90)
        assert response["request_id"] == request_id
        assert response["ok"] is ok, response
        return response.get("result") if ok else response["error"]

    def passed(name):
        cases.append({"name": name, "status": "PASS"})

    try:
        source = {"parts": [{"part_id": "one", "template": "box", "params": {}}], "operations": []}
        initial = call("build", source)
        assert abs(initial["stats"]["volume"] - 24000) < 0.01
        passed("packaged primitive")
        resized = {**source, "operations": [{"op": "resize_body", "target_id": "one", "size": [60, 30, 20], "anchor": [-1, -1, -1]}]}
        assert abs(call("build", resized)["stats"]["volume"] - 36000) < 0.01
        passed("affine resize and accurate volume")
        plate = {"parts": [{"part_id": "one", "template": "plate_with_holes", "params": {}}], "operations": [{"op": "resize_parametric", "target_id": "one", "size": [100, 50, 6], "anchor": [-1, -1, -1]}]}
        assert call("build", plate)["stats"]["parts"][0]["parametric_resize"] is True
        passed("preserving resize with holes")
        edge = initial["stats"]["edges"][0]
        fillet = {**source, "operations": [{"op": "fillet", "part_id": "one", "radius": 2, "edge_ref": edge}]}
        assert call("build", fillet)["stats"]["is_valid"]
        prepared = call("designer_action", {"document": fillet, "action": {"type": "edit", "index": 0, "changes": {"radius": 3}}})
        assert prepared["operations"][0]["radius"] == 3
        assert call("build", prepared)["stats"]["is_valid"]
        passed("packaged history editor module and rebuild")
        invalid = call("designer_action", {"document": fillet, "action": {"type": "edit", "index": 0, "changes": {"target_id": "other"}}}, ok=False)
        assert invalid["code"] == "bad_params"
        passed("protected history identity")
        rotated = {**source, "operations": [{"op": "transform", "part_id": "one", "translate": [10, 0, 0], "rotate_deg": [0, 0, 90], "pivot": [0, 0, 10]}]}
        bounds = call("build", rotated)["stats"]["bbox"]
        assert abs(bounds[3] - bounds[0] - 30) < 0.001
        passed("rotation around pivot")
        converted = call("designer_action", {"document": source, "action": {"type": "convert_mesh"}})
        converted_stats = call("build", converted)["stats"]
        assert converted_stats["mesh_mode"] and converted_stats["is_valid"] and converted_stats["triangle_count"] > 12
        passed("dense BRep to mesh conversion")
        sphere = {"parts": [{"part_id": "one", "template": "sphere", "params": {}}], "operations": []}
        sphere_mesh = call("designer_action", {"document": sphere, "action": {"type": "convert_mesh"}})
        assert call("build", sphere_mesh)["stats"]["is_valid"]
        passed("closed sphere conversion without degenerate pole triangles")
        deformed = {**converted, "operations": converted["operations"] + [{"op": "mesh_deform", "center": [20, 0, 10], "radius": 12, "delta": [1, 0, 0]}]}
        assert call("build", deformed)["stats"]["is_valid"]
        passed("soft mesh deformation")
        export_error = call("export", {**deformed, "format": "step", "path": str(args.output.parent / "forbidden.step")}, ok=False)
        assert "STEP" in export_error["message"]
        passed("mesh STEP rejection")
        hole = {"op": "face_feature", "target_id": "one", "mode": "cut", "face_ref": {"kind": "outer_planar", "axis": "z", "side": 1, "anchor": [0, 0]},
                "profile": {"kind": "circle", "diameter": 4, "center": [0, 0]}, "depth": "through", "dimension_bindings": {"u": {"edge": "min", "offset": 8}}}
        bound = {**source, "operations": [hole, {"op": "resize_parametric", "target_id": "one", "size": [60, 30, 20], "anchor": [-1, -1, -1]}]}
        bound_result = call("build", bound)
        hole_face = next(face for face in bound_result["mesh"]["face_ranges"] if face["feature_index"] == 0 and face["surface_ref"]["kind"] == "cylinder")
        assert abs(hole_face["surface_ref"]["radius"] - 2) < 1e-5
        assert abs(hole_face["surface_ref"]["origin"][0] + 12) < 1e-5
        passed("persistent edge offset and local feature provenance through resize")
        first_hole = {**hole, "profile": {"kind": "circle", "diameter": 6, "center": [-8, 0]}, "dimension_bindings": {}}
        second_hole = {**hole, "profile": {"kind": "circle", "diameter": 4, "center": [8, 0]}, "dimension_bindings": {"equal_diameter": 0}}
        equal = call("build", {**source, "operations": [first_hole, second_hole]})
        assert abs(equal["stats"]["volume"] - (24000 - 2 * math.pi * 9 * 20)) < 0.01
        passed("persistent equal hole diameter")
        invalid_binding = call("build", {**source, "operations": [{**hole, "dimension_bindings": {"equal_diameter": 0}}]}, ok=False)
        assert invalid_binding["code"] == "dependency_conflict"
        passed("forward and cyclic dimension reference rejection")
        sketch = {"entities": [{"id": "arc", "type": "arc", "start": [-5, 0], "mid": [0, 5], "end": [5, 0]},
                               {"id": "base", "type": "line", "start": [5, 0], "end": [-5, 0]}], "constraints": [], "regions": [{"outer": ["arc", "base"], "holes": []}]}
        assert call("solve_sketch", {"sketch": sketch})["degrees_of_freedom"] == 10
        arc = call("build", {"parts": [], "operations": [{"op": "constrained_sketch_extrude", "sketch": sketch, "depth": 3}]})
        assert abs(arc["stats"]["volume"] - math.pi * 25 / 2 * 3) < 0.01
        passed("packaged arc solver and exact sketch extrusion")
        top = next(face["surface_ref"] for face in initial["mesh"]["face_ranges"] if face["surface_ref"] and face["surface_ref"]["kind"] == "plane" and face["surface_ref"]["direction"][2] > 0.99)
        bottom = next(face["surface_ref"] for face in initial["mesh"]["face_ranges"] if face["surface_ref"] and face["surface_ref"]["kind"] == "plane" and face["surface_ref"]["direction"][2] < -0.99)
        assembly = {"parts": source["parts"] + [{"part_id": "two", "template": "box", "params": {}}], "operations": []}
        mated = call("designer_action", {"document": assembly, "action": {"type": "append", "operation": {"op": "mate", "kind": "plane", "part_id": "two", "fixed_id": "one", "moving_surface": bottom, "fixed_surface": top, "gap": 2}}})
        mated["operations"].append({"op": "transform", "part_id": "one", "translate": [0, 0, 10]})
        assembly_result = call("build", mated)
        assert assembly_result["stats"]["solid_count"] == 2
        assert abs(next(part for part in assembly_result["stats"]["parts"] if part["part_id"] == "two")["bbox"][2] - 32) < 1e-5
        passed("packaged separate-part mate follows support translation")
        duplicate = call("build", {**mated, "operations": mated["operations"] + [mated["operations"][0]]}, ok=False)
        assert duplicate["code"] == "dependency_conflict"
        passed("overconstrained assembly rejection")
        thin = {"parts": [{"part_id": "one", "template": "box", "params": {"length": 20, "width": 20, "height": 0.5}}], "operations": [], "printer": {"x": 220, "y": 220, "z": 250, "minimum_wall": 0.8}}
        checks = {check["id"]: check for check in call("print_check", thin)["checks"]}
        assert checks["bed_position"]["status"] == "pass" and checks["wall_thickness"]["status"] == "fail" and checks["wall_thickness"]["issues"]
        passed("packaged absolute placement and sampled thin wall markers")
        call("shutdown")
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "PASS", "scope": "packaged sidecar protocol; not native UI",
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "cases": cases}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Packaged designer sidecar: {len(cases)} PASS -> {args.output}")


if __name__ == "__main__":
    main()
