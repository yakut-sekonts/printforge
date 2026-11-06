# QA PrintForge 0.5.0

Дата: 2026-11-06. Scope — все восемь пунктов DESIGNER_RELEASE_PLAN.md в одном релизе. После ранее выполненного FULL запускаются изменённые компоненты и связующие, не весь ручной каталог повторно.

## Automated — PASS

511 уникальных тестов: 412 Python, 77 Node, 22 Rust. Повторные прогоны не суммируются. Source connected stage: `artifacts/designer-release/connected/test-report.json`; финальные follow-up: `designer-final.xml`, `final-contracts.xml`, `ui-final-layout/test-report.json` в том же каталоге. Исходный HEAD отчёта — baseline до commit, а не утверждение, что незакоммиченные изменения уже опубликованы.

- CAD/document/worker, AI contracts, expressions, native argument mapping, selection, mesh transport, release/CI routing, help/search/lesson engine, traceability.
- Размеры/anchors, isolation нескольких тел, zero-drag, min size, affine volume, сохранение отверстий и fillet radius, ограничения неподдерживаемой истории.
- Очередь Preview, stale success/failure, atomic commit/edit, Undo/Redo, failed candidate, revision/instance guards, persistence/schema 6.
- Pointer capture, второй pointer, pointercancel, busy/What-mode, numeric drag/Enter, transient mesh restoration.
- Привязки к центрам/границам/сетке, round/uniform constraints, shape weights, защищённые history identifiers.
- Mesh-конвертация всех пяти поддерживаемых исходников сохраняет watertight/winding; инверсия треугольников отклоняется, STEP для mesh запрещён.
- Production UI build и release version contract проходят. Предупреждение Vite о размере chunk не скрывается; это не ошибка сборки.

## Собранный sidecar — PASS

`scripts/run_designer_sidecar_smoke.py`, результат `artifacts/designer-release/sidecar-final.json`: 10 gates. Это настоящий PyInstaller executable, не Python source worker: primitive, affine volume, preserving resize, history module/rebuild, protected IDs, pivot rotation, dense conversion, sphere poles, soft deformation, STEP rejection. JSON содержит SHA-256 бинарника. Этот же smoke добавлен blocking-шагом в release matrix каждой платформы.

macOS ARM `.app` собрана с финальным sidecar; `codesign --verify --deep --strict` проходит для ad-hoc подписи. Это не Apple Developer ID/notarization.

## Browser smoke

Выполнен на production preview, отдельный disposable shim без сохранённых пользовательских проектов:

- Box → точные размеры 60×30×20, до Apply revision остаётся прежней; после Apply volume 36000.
- История → недопустимый X=0 даёт ошибку Preview, модель и revision не меняются; X=70 успешно применяется, volume 42000.
- Реальный canvas: выбор верхней грани → круг мышью → through cut → Apply; volume уменьшается, именованная операция появляется в истории.
- Реальный canvas: выбор прямого ребра → ручка радиуса → точный Preview → Apply.
- Модель с отверстием и скруглением → явный mesh из 165888 треугольников без открытых рёбер → реальный drag поверхности → точный Preview → Apply. Это browser-жест, не native Windows evidence.
- История дополнительно доступна кнопкой над сценой, включая стандартное окно, где боковой список скрыт responsive layout.

Дополнительные native/manual результаты фиксируются отдельно; browser smoke не выдаётся за Windows UI или полный native E2E.

## macOS native manual — PASS

В реально собранной `.app`/WKWebView: sphere 30 → Dimensions X=36 автоматически связывает XYZ=36 → точный Preview при revision 1 → Apply, revision 2. Явная конвертация создаёт mesh из 32000 треугольников, 0 открытых рёбер; Undo восстанавливает точный BRep 36×36×36. Native save в отдельный `/private/tmp/printforge-050-native-smoke.printforge` действительно записал schema 6 с `resize_parametric`; reopen восстановил геометрию, сбросил revision к 1 и принял новый instance. Эти результаты подтверждают native IPC и binary Preview path, но не все мышиные жесты на всех ОС.

## Исправления, найденные проверками

- Designer edge request обязан использовать `part_id`, не `target_id`; добавлен чистый payload builder и regression test.
- У сферы tessellation давала два degenerate pole triangles. Они удаляются до uniform subdivision; адаптивное независимое уплотнение заменено сохраняющим связность. Конвертация, не дающая замкнутую сетку, отклоняется без потери BRep.
- Сохранность transient mesh, подписей transform gizmo и отмена второго pointer проверяются отдельно.
- Первые запуски нового smoke-harness выявили несоответствие shutdown response без `result`; исправлен harness. Неуспешные промежуточные запуски не объявляются PASS.

## BLOCKED / не проверено

- Полный интерактивный Windows UI новых инструментов: нет доступной Windows desktop-сессии. Hosted installer/payload и packaged-sidecar gates проверяют другое и не заменяют эти жесты.
- Native WDIO harness полного каталога: не внедрён; component/browser/manual evidence разделены.
- Полный цикл установленный v0.4.1 → колокольчик → install → relaunch v0.5.0: требует отдельного установленного экземпляра и ОС-диалогов; проверка feed/signature сама по себе не считается таким циклом.
- Apple notarization и Windows Authenticode намеренно отсутствуют по принятой модели open-source distribution; Apache-2.0 — лицензия, не сертификат подписи.
- General mesh self-intersection solver, curved face offset, произвольный constrained canvas Sketcher, гарантированное сохранение features в произвольном STEP не реализованы и не объявляются PASS.
- Остальные ограничения предыдущего FULL QA не закрываются только фактом этого релиза. Native/manual набор из 179 сценариев и все 13 уроков повторно целиком не прогонялись.

Публичный релиз создаётся draft и публикуется только после трёх платформ и blocking Windows installer/payload gate. Performance observations сохраняются с исходным failed-статусом, если превышен budget.
