# IPC-контракт PrintForge M2 (Tauri commands ↔ frontend)

Все вызовы: `invoke(name, args)` из `@tauri-apps/api/core`, либо HTTP POST `http://localhost:8787/api/<command>` (dev-shim). Ошибки — `Promise.reject`/HTTP 500 со строкой JSON `{"code","message","detail"}`.

## DocState

```jsonc
{
  "doc_id": "doc-3",           // меняется при open/new (страж устаревших ответов — по паре doc_id+revision)
  "revision": 3, "dirty": true,
  "path": "/…/case.printforge" | null,
  "slot": "main" | "tutorial",
  "template": "plate_with_holes" | "washer" | "bracket_l" | "case_with_lid" | null,
  "params": { "length": 80 },  // параметры первой детали (совместимость)
  "parts": [ {"part_id": "part-1", "name": "Пластина", "template": "plate_with_holes", "params": {…}} ],
  "expressions": { "length": "80" },
  "operations": [ {"op": "fillet", "radius": 2, "edge_ref": {"solid_index":0,"kind":"LINE","length":30.0,"midpoint":[x,y,z]}} ],
  "stats": {
    "volume": 18898.4, "solid_count": 1, "face_count": 10,
    "bbox": [-40,-20,0, 40,20,6], "is_valid": true,
    "edges": [ {"solid_index":0,"kind":"LINE","length":30.0,"midpoint":[…]} ],  // для выбора ребра
    "hole_centers": [[-30,-10],…],          // plate
    "case_volume": 29472, "lid_volume": 14355.2, "intersection_volume": 0,  // case_with_lid
    "parts": [ {"part_id": "part-1", "name": "Пластина", "volume": 18898.4, "solid_count": 1} ],  // живые тела после операций
  } | null,
  "error": { "code": "…", "message": "…", "detail": "…" } | null,
  "can_undo": true, "can_redo": false,
  "history_len": 3, "history_index": 2
}
```

Коды ошибок: `bad_value`, `bad_params`, `no_model`, `fillet_failed`, `reselect_required` (нужен повторный выбор ребра), `bad_file`, `worker_terminated`, `geometry_error`.

## Команды

- `doc_create({template, params?})` → DocState. Новый документ с одной деталью из шаблона (одна транзакция). Шаблоны и поля — `app/shared/templates.json`.
- `doc_add_part({template, params?})` → DocState. Добавить деталь в документ (для булевых операций и массивов).
- `doc_set_parameter({part_id?, name, value, expression?})` → DocState. Без part_id — первая деталь.
- `doc_boolean({boolean: "union"|"subtract"|"intersect", target_id, tool_id, keep_tool?})` → DocState. Инструмент поглощается операцией (если не keep_tool), но его определение остаётся в документе для повторного построения; живые тела — в `stats.parts`.
- `doc_array({part_id, count, step: [x,y,z]})` / `doc_mirror({part_id, plane: "XY"|"XZ"|"YZ"})` / `doc_split({part_id, plane, offset})` / `doc_transform({part_id, translate: [x,y,z]})` → DocState. Ошибки (`split_failed` и др.) — откат транзакции с видимой ошибкой.
- `doc_fillet({edge_ref, radius})` → DocState. Одна транзакция; при `fillet_failed` история откатывается, модель остаётся прежней.
- `doc_clear_error()` → DocState.
- `doc_undo()` / `doc_redo()` / `doc_get_state()` / `doc_get_mesh()` → как в M1 (`doc_get_mesh` отдаёт positions/indices/face_ranges c `solid_index`).
- `doc_save({path})` / `doc_open({path})` → DocState. Формат v2 (template+operations), читает и v1.
- `doc_export({path, format: "stl"|"step"|"3mf", linear_deflection?})` → `{path, bytes, format, stats}`.
- `doc_import({path, format: "step"|"stl", unit_scale?})` → `{stats, mesh, mode: "brep"|"mesh"}`. Для STL `unit_scale` задаётся после показа габарита пользователю.
- `print_check({printer: {x, y, z}})` → `{checks: [{id, title, status: "pass"|"fail"|"unknown", detail?}]}`.
- `doc_new_tutorial()` / `doc_switch_slot({slot})` → DocState.

Обратная совместимость M1: `doc_create_plate`, `doc_export_stl` работают.

## Файловые диалоги

В .app используется `tauri-plugin-dialog` (save/open с фильтрами). В браузерном dev-режиме — ручной ввод пути (как в M1).
