# Versioned IPC-контракт PrintForge (Tauri commands ↔ frontend)

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
  "operations": [ {"op": "fillet", "radius": 2, "edge_ref": {"solid_index":0,"kind":"LINE","length":30.0,"midpoint":[x,y,z]}}, {"op":"chamfer","distance":1,"edge_ref":{…}} ],
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

Коды ошибок: `bad_value`, `bad_params`, `no_model`, `fillet_failed`, `chamfer_failed`, `dome_failed`, `bend_failed`, `reselect_required` (нужен повторный выбор ребра или грани), `bad_file`, `worker_terminated`, `geometry_error`.

## Команды

- `doc_create({template, params?})` → DocState. Новый документ с одной деталью из шаблона (одна транзакция). Шаблоны и поля — `app/shared/templates.json`.
- `doc_add_part({template, params?})` → DocState. Добавить деталь в документ (для булевых операций и массивов).
- `doc_set_parameter({part_id?, name, value, expression?})` → DocState. Без part_id — первая деталь.
- `doc_boolean({boolean: "union"|"subtract"|"intersect", target_id, tool_id, keep_tool?})` → DocState. Инструмент поглощается операцией (если не keep_tool), но его определение остаётся в документе для повторного построения; живые тела — в `stats.parts`.
- `doc_array({part_id, count, step: [x,y,z]})` / `doc_mirror({part_id, plane: "XY"|"XZ"|"YZ"})` / `doc_split({part_id, plane, offset, separate?})` / `doc_transform({part_id, translate: [x,y,z]})` → DocState. UI использует `separate: true`: каждая полученная часть получает собственный `part_id`, первая сохраняет исходный ID, остальные — `${part_id}-split-${operation_index + 1}-part-${part_index + 1}`. Сохраняются все полученные твёрдые тела. Новая операция разделения проверяется до commit и неудача сохраняет redo, revision и сохранённый файл. Отсутствующий/false `separate` воспроизводит прежний формат операции без изменения ID.
- Для `doc_split` с `separate: true` `offset` задаёт мировую координату плоскости: Z для XY, Y для XZ, X для YZ. Legacy XZ без флага сохраняет прежнее смещение вдоль нормали -Y.
- `doc_face_offset({target_id, face_ref, distance})` → DocState. Точная BRep-экструзия всей выбранной плоской грани вдоль наружной нормали: положительное смещение добавляет материал, отрицательное убирает. Отверстия в грани сохраняются. `face_ref` берётся из `mesh.face_ranges[].face_ref`: `{kind: "planar", center: [x,y,z], normal: [x,y,z], area, solid_index}`; у криволинейной грани `face_ref: null`. `solid_index` относится к общей сцене, повторный поиск выполняется геометрически внутри `target_id`. Изменившаяся/неоднозначная грань возвращает `reselect_required`; пересечение других поверхностей, разделение и уничтожение тела — `face_offset_failed`. Неудачная операция откатывается, успешная занимает один Undo.
- `doc_fillet({edge_ref, radius})` → DocState. Одна транзакция; при `fillet_failed` история откатывается, модель остаётся прежней.
- `doc_chamfer({edge_ref, distance})` → DocState. Плоская фаска по выбранному ребру; одна транзакция и один Undo, при `chamfer_failed` модель не изменяется.
- `doc_face_feature({target_id, mode: "add"|"cut", face_ref: {kind: "outer_planar", axis, side, anchor, selected_area}, profile, depth: number|"through"})` → DocState. Локальная бобышка либо blind/through вырез на выбранной внешней плоской грани; семантическая ссылка хранит сторону и локальную привязку, а не номер `FaceN`. Одна операция — один Undo.
- `doc_face_dome({target_id, mode: "add"|"cut", face_ref, center: [u,v], diameter, height})` → DocState. Точный BRep-сферический сегмент: выпуклость (`add`) или вмятина (`cut`) на выбранной внешней плоской грани. Высота не больше половины диаметра; основание должно целиком лежать на материале. Одна операция — один Undo.
- `doc_sheet_bend({target_id, face_ref, bend_axis: "x"|"y", position, angle, inside_radius, moving_side: -1|1, direction: -1|1})` → DocState. Точный sheet-metal изгиб пластины или выбранного внешнего фланца с сохранением толщины, объёма, штатных отверстий и поддерживаемых through-вырезов. Поддерживаются до четырёх параллельных линий одной развёртки либо один перпендикулярный изгиб фланца после базового изгиба 90°; каждый вызов — отдельный Undo.
- `doc_sketch_extrude({profile, plane, depth, result_id?, name?})` → DocState. `profile.regions` содержит внешние polygon/circle/segments-контуры и внутренние отверстия. Замыкание, вырождение и самопересечение валидируются до commit; операция может создать первый body документа без фиктивного template-part.
- `sketch_solve({sketch, drag?, tolerance?})` → `{status, degrees_of_freedom, constraint_rank, redundant_constraints, max_residual, entities}`. Preview не меняет документ; конфликт возвращает `constraint_conflict`, совместимая redundancy остаётся успешной.
- `doc_constrained_sketch_extrude({sketch, drag?, plane, depth, result_id?, name?})` → DocState. Решает constraints и создаёт BRep одной транзакцией; metadata результата содержит DOF, residual и solved entities.
- `doc_revolve({profile, plane, axis: {point, direction}, angle, result_id?, name?})` → DocState. Вращение замкнутого профиля на `0 < angle <= 360`; нулевая ось и самопересечение отклоняются.
- `doc_sweep({section: {kind: "circle", radius}, path: {points: [[x,y,z], ...]}, frenet?, result_id?, name?})` → DocState. Первый slice использует круглое сечение и открытую polyline-траекторию минимум из двух различных точек.
- `doc_loft({sections: [{plane, offset, profile}, ...], ruled?, result_id?, name?})` → DocState. Минимум два упорядоченных сечения, одна замкнутая область на каждое сечение.
- `doc_shell({outer_radius, height, wall, bottom, result_id?, name?})` → DocState. Создаёт цилиндрическую оболочку с открытым верхом; исчезающая стенка или полость отклоняется.
- `doc_draft_prism({width, depth, height, angle, result_id?, name?})` → DocState. Создаёт прямоугольное тело с линейным signed-уклоном боковых стенок.
- `doc_rib({base_length, base_width, base_thickness, rib_length, rib_height, rib_width, overlap, result_id?, name?})` → DocState. Объединяет основание и треугольное ребро с явным заглублением.
- `doc_fit_pocket({fixture_id, fixture_version?, body_length, body_width, body_height, clearance, clearance_mode, pocket_depth?, result_id?, name?})` → DocState. Создаёт корпус с карманом под версионированную размерную fixture; `radial`, `diametral` и `one_sided` имеют разную геометрическую семантику.
- `doc_vector_extrude({path, format, height, unit_scale?, result_id?, name?})` → DocState. Читает локальный SVG/DXF, валидирует безопасность/единицы и сохраняет source text внутри операции проекта.
- `doc_text_relief({text, font_size, relief_height, body_length, body_width, body_height, mode, result_id?, name?})` → DocState. Создаёт выпуклый текст или гравировку фиксированным проверяемым шрифтом.
- `doc_thread_pair({profile_version?, major_diameter, pitch, length, hand, starts, clearance, nut_height, nut_across_flats, result_id?, name?})` → DocState. Создаёт внешнюю и внутреннюю однозаходную винтовую геометрию и проверяет их сборочное пересечение.
- `doc_clearance_calibration({values, nominal_diameter, coupon_length, coupon_width, thickness, spacing, font_size, label_height, profile_name?, result_id?, name?})` → DocState. Создаёт маркированную серию образцов как одну транзакцию.
- `doc_split_connector_pair({length, width, height, pin_radius, pin_length, radial_clearance, print_separation, result_id?, name?})` → DocState. Разделяет rectangular fixture, добавляет pins/sockets, проверяет сборку и хранит print/assembly transforms.
- `doc_clear_error()` → DocState.
- `doc_undo()` / `doc_redo()` / `doc_get_state()` → как в M1.
- Browser/dev-shim fallback: `doc_get_mesh()` и `doc_get_imported_mesh({path})` возвращают JSON `positions/indices/face_ranges`.
- Native Tauri: `doc_get_mesh_meta()` → `{bytes, sha256, vertex_count, triangle_count, face_ranges}`, затем `doc_get_mesh_binary({expected_sha256})` → raw `ArrayBuffer`. SHA-256 связывает обе фазы и исключает выдачу устаревшего ресурса при перестроении модели; повреждённые, усечённые и расширенные buffers отклоняются.
- Native import: `doc_get_imported_mesh_binary({path, expected_sha256})` → raw `ArrayBuffer`; path берётся только из результата `doc_import`, содержимое обязательно проверяется по SHA-256.
- Binary mesh layout little-endian: `u32 vertex_count`, `u32 triangle_count`, затем `vertex_count × 3` значений `f32` и `triangle_count × 3` индексов `u32`. В WebView данные декодируются в typed-array views без JSON-раздувания; преобразование CAD → Three.js выполняется только для positions.
- `doc_save({path})` / `doc_open({path})` → DocState. Формат v3 (parts+operations), читает прежние template-документы и operation-only M4-документы.
- `doc_export({path, format: "stl"|"step"|"3mf", linear_deflection?})` → `{path, bytes, format, stats}`.
- `doc_import({path, format: "step"|"stl", unit_scale?})` → `{stats, mesh, mode: "brep"|"mesh"}`. Для STL `unit_scale` задаётся после показа габарита пользователю.
- `doc_mesh_import_apply({path, format: "stl"|"obj"|"ply", unit_scale})` → DocState. Встраивает source bytes и начинает отдельную mesh-history без симуляции параметрического BRep.
- `doc_mesh_transform({translate, rotate_deg, scale})`, `doc_mesh_repair({action:"fill_holes"})`, `doc_mesh_decimate({target_ratio, minimum_ratio?, maximum_ratio?, volume_tolerance?})` → DocState. Repair закрывает только поддерживаемый boundary loop; decimation сохраняет компоненты/Euler number и публикует только sampled vertex error, не глобальный Hausdorff bound.
- `image_relief_preview({path, model, seed, width_mm, relief_height, base_thickness, samples, noise_strength, invert})` → `{stats, mesh, source_sha256}` без commit. `doc_image_relief_apply({...settings, expected_sha256})` повторно проверяет source hash и создаёт experimental mesh-document одной транзакцией.
- `print_check({printer: {x, y, z}})` → `{checks: [{id, title, status: "pass"|"fail"|"unknown", detail?}]}`.
- `doc_new_tutorial()` / `doc_switch_slot({slot})` → DocState.

Обратная совместимость M1: `doc_create_plate`, `doc_export_stl` работают.

## Файловые диалоги

В .app используется `tauri-plugin-dialog` (save/open с фильтрами). В браузерном dev-режиме — ручной ввод пути (как в M1).

## Geometry worker recovery

- Каждый CAD-запрос stateless: содержит полный document snapshot и revision. При EOF/write failure transport уничтожает текущий sidecar, поднимает новый процесс и повторяет тот же запрос не более одного раза.
- Управляемый ответ `{ok:false,error}` не считается transport failure и никогда автоматически не повторяется.
- Если новый worker также завершается, IPC возвращает `worker_recovery_failed`; последняя подтверждённая геометрия сохраняется, незавершённая document transaction откатывается штатным механизмом.
- `geometry_cancel()` → `{cancelled}`. Активный запрос получает отдельный cancel signal, sidecar принудительно завершается, операция возвращает `geometry_cancelled` и не повторяется. Следующий CAD-запрос запускает чистый worker.
- Deadline считается на весь запрос вместе с возможным transport retry: 120 секунд для build/measure/print и 300 секунд для import/export. По истечении процесс завершается с `worker_timeout`, без retry.
- `ai_cancel` также передаёт cancel активному CAD preview и возвращает дополнительный `geometry_cancelled` diagnostic flag.

## Performance probe

- `performance_config()` и `performance_report({payload})` — внутренний native-only probe, не пользовательский command registry и не dev-shim API.
- Probe выключен без пары env `PF_PERF_MODE=startup|workload` и абсолютного `PF_PERF_REPORT`; путь записи никогда не принимается из WebView payload.
- В режиме `workload` `PF_PERF_PROJECT` открывается штатным `doc_open`, mesh загружается штатным binary IPC, а frontend сообщает готовность только после двух animation frames и завершения camera-orbit measurement.
- Отчёт записывается атомарно и связывается с PID main app; обычный запуск не создаёт файлов и не выполняет performance workload.

## Native E2E probe

- `native_e2e_config()` и `native_e2e_report({payload})` — внутренний native-only harness для cancellation, не пользовательский command registry и не dev-shim API.
- Probe включается только при `PF_E2E_MODE=ai-http-cancel|ai-cad-cancel` вместе с абсолютным `PF_E2E_REPORT`; задержка отмены задаётся `PF_E2E_CANCEL_DELAY_MS`.
- Frontend использует штатные `doc_get_state`, `ai_plan`, `ai_cancel` и для CAD recovery — `doc_create`. Harness проверяет `ai_cancelled`, неизменность semantic document state и, для CAD, `geometry_cancelled` с успешным следующим build.
- Provider profile передаётся только через environment дочернего процесса runner. Пользовательский config и Keychain не изменяются; путь отчёта не принимается из WebView payload.

## AI-задачи

- `ai_plan({text, task_id})` → `{plan, preview|null, plan_hash, action_id}`. `task_id` уникален для активной задачи; preview строится на копии и не меняет рабочий документ.
- `ai_cancel({task_id})` → `{task_id, cancelled}`. В native runtime отмена дропает активный provider future; dev-shim кооперативно запрещает validation/preview после возврата provider. Завершённая или неизвестная задача возвращает `cancelled: false`.
- Отмена возвращает `ai_cancelled`; результат отменённой задачи нельзя применить. Повторный активный `task_id` возвращает `ai_task_conflict`.
