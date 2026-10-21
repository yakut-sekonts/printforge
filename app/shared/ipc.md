# IPC-контракт PrintForge M1 (Tauri commands ↔ frontend)

Все вызовы: `invoke(name, args)` из `@tauri-apps/api/core`. Ошибки приходят как `Promise.reject(string)` — строка содержит JSON `{"code","message","detail"}` (нужен JSON.parse с fallback на сам текст).

## DocState (возвращают большинство команд)

```jsonc
{
  "revision": 3,
  "dirty": true,
  "path": "/Users/…/plate.printforge" | null,
  "slot": "main" | "tutorial",
  "params": { "length": 80, "width": 40, "height": 6, "hole_diameter": 4, "hole_offset": 10 },
  "expressions": { "length": "80" },
  "stats": {
    "volume": 18898.407, "solid_count": 1, "face_count": 10,
    "bbox": [-40,-20,0, 40,20,6],
    "hole_centers": [[-30,-10],[30,-10],[-30,10],[30,10]],
    "is_valid": true
  } | null,
  "error": { "code": "…", "message": "…", "detail": "…" } | null,
  "can_undo": true, "can_redo": false
}
```

`stats`/`error`: при ошибке пересчёта `stats` остаётся последним подтверждённым, `error` заполнен (DOC-005) — UI показывает старую модель + ошибку.

## Команды

- `doc_create_plate({length, width, height, hole_diameter, hole_offset})` → DocState. Создаёт/заменяет параметры текущего документа (одна транзакция истории).
- `doc_set_parameter({name, value, expression?})` → DocState. value > 0, конечное число; expression — исходная строка выражения для хранения в документе.
- `doc_undo()` / `doc_redo()` → DocState.
- `doc_get_state()` → DocState.
- `doc_get_mesh()` → `{vertex_count, triangle_count, positions: number[], indices: number[], face_ranges: [{face_index, tri_start, tri_count}]}`. Координаты в мм, Z вверх.
- `doc_save({path})` → DocState. Атомарная запись .printforge (zip).
- `doc_open({path})` → DocState.
- `doc_export_stl({path, linear_deflection?})` → `{path, bytes, linear_deflection, stats}`.
- `doc_new_tutorial()` → DocState. Создаёт пустой учебный документ в слоте tutorial и переключается на него (рабочий документ main не трогается, HELP-009).
- `doc_switch_slot({slot})` → DocState ("main" | "tutorial").

## Диалоги файлов

Плагин dialog не подключён; для M1 используем явный ввод пути в UI (поле с путём по умолчанию `~/plate.printforge`, `~/plate.stl`). Это задокументированное ограничение M1.
