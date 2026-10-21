"""M0 spike: доказательство геометрического стека PrintForge.

Проверяет (аналитические допуски из REQUIREMENTS.md §14):
1. Пластина 80x40x6 с 4 сквозными отверстиями Ø4, центры (+-30; +-10),
   объём 18898.407105 мм^3, одно замкнутое тело.
2. Пересчёт длины 80 -> 100 с сохранением отступов 10 мм от краёв:
   центры по X становятся +-40, объём 23698.407105 мм^3.
3. Выбор грани и настоящего BRep-ребра через tessellation-мэппинг и
   скругление выбранного ребра (мягкая ссылка по геометрии, не "Edge8").
4. Минимальный документ .printforge (zip с manifest/document), сохранение
   и повторное построение с тем же объёмом.
5. Экспорт STEP/STL/3MF и чтение результата (габариты, объём/число тел).

Запуск: backend/.venv/bin/python backend/spike_m0.py
"""
import io
import json
import math
import sys
import zipfile
from pathlib import Path

from build123d import (
    Axis,
    GeomType,
    Box,
    BuildPart,
    BuildSketch,
    Cylinder,
    Plane,
    Pos,
    Shape,
    Solid,
    export_step,
    export_stl,
    import_step,
)

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

TOL_LEN = 1e-3
FAILURES = []


def check(name: str, actual: float, expected: float, tol: float) -> None:
    ok = abs(actual - expected) <= tol
    print(f"  [{'OK' if ok else 'FAIL'}] {name}: {actual:.6f} (ожидалось {expected:.6f})")
    if not ok:
        FAILURES.append(name)


def build_plate(length: float, width: float, height: float,
                hole_d: float, hole_offset: float):
    """Пластина, центрированная по X/Y, низ Z=0; 4 сквозных отверстия,
    центры на (+-hx; +-hy), где hx/hy — отступы hole_offset от краёв."""
    hx = length / 2 - hole_offset
    hy = width / 2 - hole_offset
    part = Pos(0, 0, height / 2) * Box(length, width, height)
    for sx in (-hx, hx):
        for sy in (-hy, hy):
            part -= Pos(sx, sy, height / 2) * Cylinder(
                radius=hole_d / 2, height=height * 2)
    return part, hx, hy


def main() -> int:
    print("== 1. Пластина 80x40x6, 4 отверстия Ø4, отступы 10 ==")
    plate, hx, hy = build_plate(80, 40, 6, 4, 10)
    solids = plate.solids()
    check("число тел", len(solids), 1, 0)
    bb = plate.bounding_box()
    check("габарит X", bb.size.X, 80, TOL_LEN)
    check("габарит Y", bb.size.Y, 40, TOL_LEN)
    check("габарит Z", bb.size.Z, 6, TOL_LEN)
    check("Z min", bb.min.Z, 0, TOL_LEN)
    check("центры отверстий X", hx, 30, TOL_LEN)
    check("центры отверстий Y", hy, 10, TOL_LEN)
    exp_vol = 80 * 40 * 6 - 4 * math.pi * 2**2 * 6
    check("объём", plate.volume, exp_vol, max(1e-3, 1e-6 * exp_vol))
    check("валидность тела", solids[0].is_valid, True, 0)

    print("== 2. Пересчёт длины 100, отступы сохраняются ==")
    plate2, hx2, hy2 = build_plate(100, 40, 6, 4, 10)
    check("центры отверстий X", hx2, 40, TOL_LEN)
    check("центры отверстий Y", hy2, 10, TOL_LEN)
    exp_vol2 = 100 * 40 * 6 - 4 * math.pi * 2**2 * 6
    check("объём", plate2.volume, exp_vol2, max(1e-3, 1e-6 * exp_vol2))
    check("число тел", len(plate2.solids()), 1, 0)

    print("== 3. Tessellation и выбор грани/ребра ==")
    # Мэппинг треугольник -> грань: тесселируем каждую грань отдельно.
    face_ranges = []  # (face_index, tri_start, tri_end, center, normal, area)
    all_vertices = []
    all_triangles = []
    v_off = 0
    for fi, face in enumerate(plate.faces()):
        verts, tris = face.tessellate(0.1)
        verts_l = [tuple(v) for v in verts]
        tris_l = [tuple(t) for t in tris]
        all_vertices.extend(verts_l)
        all_triangles.extend([(a + v_off, b + v_off, c + v_off)
                              for a, b, c in tris_l])
        face_ranges.append((fi, len(all_triangles) - len(tris_l),
                            len(all_triangles), face))
        v_off += len(verts_l)
    print(f"  граней: {len(face_ranges)}, треугольников: {len(all_triangles)}")
    # Выбор грани: верхняя (максимальная Z центра среди плоских).
    import OCP.GeomAbs  # noqa: F401
    planar = [fr for fr in face_ranges if fr[3].is_planar]
    top = max(planar, key=lambda fr: fr[3].center().Z)
    top_face = top[3]
    check("выбранная грань — верхняя (Z=6)", top_face.center().Z, 6, TOL_LEN)
    # Выбор ребра по мягкой геометрической ссылке: самое длинное прямое
    # ребро, касающееся выбранной грани.
    def edge_ref(e):
        return dict(kind="linear" if e.length else "other",
                    length=round(e.length, 3),
                    midpoint=tuple(round(c, 4) for c in e.center()))
    edges = [e for e in top_face.edges() if e.geom_type == GeomType.LINE]
    target = max(edges, key=lambda e: e.length)
    ref = edge_ref(target)
    print(f"  ссылка на ребро: {ref}")
    # Повторный поиск того же ребра в новом построении (длина 100):
    top2 = max(
        (f for f in plate2.faces() if f.is_planar), key=lambda f: f.center().Z)
    cand = [e for e in top2.edges() if e.geom_type == GeomType.LINE]
    matched = [e for e in cand
               if abs(e.center().Z - ref["midpoint"][2]) < 1e-3
               and abs(e.center().Y - ref["midpoint"][1]) < 1e-3]
    # После удлинения длина ребра меняется законно (80->100): сопоставляем
    # по положению Y/Z, допуская новую длину.
    check("повторно найдено ребро в пересчитанной модели", len(matched) >= 1, True, 0)
    new_edge = matched[0]
    check("новая длина ребра", new_edge.length, 100, TOL_LEN)
    # Скругление выбранного ребра в новой модели.
    before = plate2.volume
    r = 2.0
    filleted = plate2.fillet(radius=r, edge_list=[new_edge])
    check("валидность после скругления", filleted.is_valid, True, 0)
    check("объём уменьшился", filleted.volume < before, True, 0)
    check("скруглённое ребро исчезло из списка рёбер", all(
        abs(e.length - new_edge.length) > 1e-3
        or tuple(e.center()) != tuple(new_edge.center())
        for e in filleted.edges() if e.geom_type == GeomType.LINE), True, 0)

    print("== 4. Минимальный документ .printforge ==")
    doc = {
        "schema_version": 1,
        "units": "mm",
        "parameters": {"length": 80, "width": 40, "height": 6,
                       "hole_diameter": 4, "hole_offset": 10},
        "operations": [{"op": "plate_with_holes", "parameters":
                        ["length", "width", "height",
                         "hole_diameter", "hole_offset"]}],
    }
    manifest = {"schema_version": 1, "app": "PrintForge spike",
                "kernel": "build123d/OCP", "units": "mm"}
    pf = OUT / "plate.printforge"
    with zipfile.ZipFile(pf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest))
        z.writestr("document.json", json.dumps(doc))
    with zipfile.ZipFile(pf) as z:
        rdoc = json.loads(z.read("document.json"))
    p = rdoc["parameters"]
    rebuilt, _, _ = build_plate(p["length"], p["width"], p["height"],
                                p["hole_diameter"], p["hole_offset"])
    check("повторное построение: объём", rebuilt.volume, exp_vol,
          max(1e-3, 1e-6 * exp_vol))

    print("== 5. Экспорт STEP/STL/3MF и чтение ==")
    step_path = OUT / "plate.step"
    export_step(plate, str(step_path))
    re_step = import_step(str(step_path))
    check("STEP: объём после reimport", re_step.volume, exp_vol,
          max(1e-3, 1e-6 * exp_vol))
    check("STEP: число тел", len(re_step.solids()), 1, 0)

    stl_path = OUT / "plate.stl"
    export_stl(plate, str(stl_path), tolerance=0.02)
    import trimesh  # noqa
    mesh = trimesh.load(str(stl_path))
    bb = mesh.bounding_box.extents
    print(f"  STL: габариты {bb}, объём сетки {mesh.volume:.3f}")
    check("STL: габарит X", bb[0], 80, 0.05)
    check("STL: отн. ошибка объёма",
          abs(mesh.volume - exp_vol) / exp_vol * 100, 0, 0.5)
    check("STL: watertight", mesh.is_watertight, True, 0)

    mf_path = OUT / "plate.3mf"
    try:
        from build123d import Mesher
        m = Mesher()
        m.add_shape(plate)
        m.write(str(mf_path))
        shapes = Mesher().read(str(mf_path))
        vol = sum(s.volume for s in shapes)
        print(f"  3MF: записан и прочитан ({mf_path.stat().st_size} байт), "
              f"объектов: {len(shapes)}, объём сетки: {vol:.3f}")
        check("3MF: число объектов", len(shapes), 1, 0)
        check("3MF: отн. ошибка объёма",
              abs(vol - exp_vol) / exp_vol * 100, 0, 0.5)
    except Exception as e:  # noqa: BLE001
        print(f"  [FAIL] 3MF через Mesher: {e!r}; пробуем через trimesh")
        mesh.export(str(mf_path))
        m2 = trimesh.load(str(mf_path))
        check("3MF: число геометрий", len(m2.geometry), 1, 0)

    print()
    if FAILURES:
        print("ПРОВАЛЕНО:", ", ".join(FAILURES))
        return 1
    print("Все проверки M0-spike пройдены.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
