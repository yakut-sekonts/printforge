import argparse
import hashlib
import json
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
                               stderr=subprocess.DEVNULL, text=True, bufsize=1)

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
        call("shutdown")
        process.wait(timeout=10)
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {"status": "PASS", "scope": "packaged sidecar protocol; not native UI",
              "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(), "cases": cases}
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"Packaged designer sidecar: {len(cases)} PASS → {args.output}")


if __name__ == "__main__":
    main()
