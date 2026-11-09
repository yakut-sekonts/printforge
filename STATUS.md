# STATUS.md — статус PrintForge

## Release v0.6.0 — предсказуемое моделирование

Единый scope из семи групп реализован: выбор/скрытие, локальные элементы, сохраняемые размеры, интерактивный Sketcher, направленные mates, объяснимые отказы/диагностика и native recovery. Ограничения и критерии — [INTERACTION_RELEASE_PLAN.md](docs/INTERACTION_RELEASE_PLAN.md); фактические проверки и BLOCKED — [QA_0.6.0.md](docs/testing/QA_0.6.0.md). Опубликован [v0.6.0](https://github.com/yakut-sekonts/printforge/releases/tag/v0.6.0) после полного GitHub CI и desktop matrix.

Формат читает schema 7; предыдущие схемы поддерживаются. Offline-справка: 38 статей, 76 команд, 14 уроков. Packaged smoke расширен с 10 до 17 blocking geometry gates. Настоящий crash/relaunch/restore безымянного main-проекта проверен на macOS ARM; физическая печать и интерактивный Windows/Intel walkthrough недоступны в текущей среде.

Итоговый connected stage: 540 уникальных PASS (429 Python + 87 Node + 24 Rust), все команды stage успешны. Финальная macOS `.app` собрана, deep/strict codesign verification проходит; первое Save/Cancel и выбранный системным диалогом путь проверены отдельно. Hosted release matrix: 17/17 packaged geometry gates на каждой из трёх платформ; Windows NSIS установка и удаление прошли. Public updater feed 0.6.0, SHA-256 и подписи трёх updater assets проверены, изменённый payload отклонён. Windows stress: минимум 26,33 FPS при цели 30, performance failed/non-blocking.

Предыдущий выпуск: [v0.5.0](https://github.com/yakut-sekonts/printforge/releases/tag/v0.5.0) — единый релиз ручного проектирования. Согласованный scope и границы: [DESIGNER_RELEASE_PLAN.md](docs/DESIGNER_RELEASE_PLAN.md). M4 сохраняет открытые расширенные задачи: все группы `EXT-001…EXT-012` имеют рабочий partial slice, оставшиеся generic/direct-editing clauses перечислены в `docs/testing/TEST_GAPS.md`.

## Release v0.5.0 — ручное проектирование

- Угловые/осевые ручки с mm/numeric input, точные размеры в сцене, сохранение поддерживаемых элементов отдельно от affine-масштабирования.
- Ручное скругление/фаска, context menu, привязки/направляющие, положение/поворот/выравнивание, простой circle/rectangle face Sketcher с глубиной и through cut.
- Именованная редактируемая история и suppression; Preview привязан к instance/revision, сериализован и не изменяет документ/Redo.
- Явный переход BRep → замкнутый плотный mesh, отдельная мягкая кисть, проверка foldover и Undo до BRep. STEP и общий self-intersection solver для mesh отсутствуют.
- Schema 6 для новых операций; 37 статей/69 команд. Старые проекты читаются.
- Connected source stage и точечные follow-up: **511 уникальных PASS = 412 Python + 77 Node + 22 Rust**. Отдельно 10 packaged-sidecar smoke gates. [QA_0.5.0.md](docs/testing/QA_0.5.0.md) отделяет automated, browser/native и BLOCKED.
- Release matrix выполняет новый blocking packaged-designer smoke на всех трёх платформах; Windows installer/payload gate сохранён. Performance по-прежнему record-only, failures не переименовываются в PASS.
- Workflow `42209995840` завершился SUCCESS: macOS ARM/Intel и Windows x64 опубликованы. Public latest feed 0.5.0, SHA-256 всех updater assets, три Minisign-подписи и rejection изменённых bytes проверены; версии/архитектуры macOS archives совпадают.
- Windows runner: stress-сцена 20 тел/100 операций — минимум 26,0 FPS при цели 30, performance `failed/non-blocking`. Startup p95 6,91 с и RSS 868,5 MiB проходят свои бюджеты. Это наблюдение, не полный performance PASS.

## Release v0.4.1 — исправления после QA

- Исправлены причины 36 подтверждённых записей; ещё одна запись снята по исходным AX-доказательствам как ошибка интерпретации отчёта. Записи не равны числу независимых bugs.
- Атомарные open/candidate commits, сохранность Redo, instance-aware reopen, persistent STEP/schema 5, защита несохранённого main-документа при закрытии окна и Quit/CmdQ.
- Пересчёт выражений и русские aliases, defaults выбранной детали, сохранение draft-полей и допустимый min=0 из каталога.
- Исправлены Compound volume, case/lid 3MF, SVG physical units, вход в последовательные изгибы, Tauri measurement IPC и свежесть print/measure/relief результатов.
- Mesh resources immutable и content-addressed: Preview, tutorial, import и неприменённый candidate больше не перезаписывают ресурс подтверждённой модели. Уникальные payload сохраняются в session cache; GC не реализован.
- What-mode, адаптивная справка, раскрытие скрытых команд и lesson engine проверяются отдельно; skip не считается освоением, учебный документ исключён из автосохранения.
- Финальный connected stage: **425 уникальных PASS = 353 Python + 50 Node + 22 Rust**. Новый sidecar: 12/12 smoke; native cancellation/signature: 3/3 gates. Browser/native сценарии и ограничения перечислены в [QA_0.4.1.md](docs/testing/QA_0.4.1.md).
- Hosted release matrix должна отдельно собрать macOS Apple Silicon, macOS Intel и Windows x64; локальные macOS-проверки не заменяют Windows installer gate или полный updater install/relaunch.

## M5 — ручной CAD v0.4.0

- Старт с BRep-примитива, прямой выбор грани/ребра, XYZ-перемещение и числовой ввод в сцене, Shift multi-selection и явные target/tool для boolean operations.
- Generic planar face offset поддерживает внутренние, наклонные и изменённые булевыми операциями грани. Curved face offset остаётся неподдерживаемым.
- Split создаёт отдельно выбираемые и перемещаемые части, сохраняет все solids и объём; координаты плоскостей задаются в мировых X/Y/Z.
- Inspector свёрнут по группам; первые уроки и 35 статей/62 команды согласованы с новым сценарием. Новый вводный урок пройден до завершения в реальном UI.
- Примитивы и новые операции сохраняются в schema 4; legacy-проекты остаются schema 3. Ошибки face offset/split не уничтожают Redo или подтверждённую геометрию.
- Impact stage `artifacts/test-runs/20261103T152525Z/test-report.json`: CAD/document/worker 178 passed, AI 51, CI routing 14, help/release/traceability 15, Rust 16; UI contracts и production build прошли. Последующие проверки координат разделения: 9 passed.
- Push/PR CI запускает изменённые компоненты и их связи. Полный regression сохранён для nightly и явного manual dispatch.
- Native smoke выявил и закрыл несовпадение snake_case/camelCase аргументов Tauri IPC: преобразуются только верхнеуровневые имена, вложенные CAD/AI данные сохранены; 4 transport contract tests проходят.
- Итоговая ad-hoc signed `.app` проходит `codesign --verify --deep --strict`; в реальном WKWebView выполнены box → face offset 5 мм → transform X 10 мм → separate split X=10 → save/reopen schema 4. Проверочный проект сохранён отдельно в `/private/tmp/printforge-040-native-smoke.printforge`.

## Что пользователь уже может сделать

- Четыре шаблона с точными размерами и зависимостями: пластина с отверстиями, шайба/втулка, L-кронштейн, корпус с крышкой (явный зазор «на одну сторону», пересчёт при изменении корпуса).
- Скругление выбранного ребра (список рёбер, подсветка в сцене линией с маркерами концов), честная ошибка при невозможном радиусе с сохранением прежней модели; повторный выбор при потере ребра.
- Изменение параметров с отменой/повтором (одно действие = одна транзакция), сохранение/открытие `.printforge` (читает схемы до 6), автосохранение именованного main-документа каждые 30 с, файловые диалоги macOS.
- Экспорт STL/STEP/3MF; импорт STEP и persistent STL mesh-document с embedded source, transform, hole repair и topology-aware decimation.
- Constraint solver показывает residual/DOF, отличает conflict от compatible redundancy, поддерживает constrained drag и применяет extrusion одной транзакцией.
- Experimental image relief: PNG/JPEG/WebP preview без commit, hash-bound Apply, фиксированный model/seed/settings и mesh-only export.
- Проверка перед печатью: валидность, тела, объём, габарит vs профиль принтера; «Не проверено» для нереализованного, без общего зелёного статуса.
- Справка офлайн (37 статей, 69 команд), поиск с синонимами, «Что это?», «Показать в интерфейсе», 3 режима подсказок, 13 уроков.
- AI-помощник: `disabled` по умолчанию, локальный Ollama или OpenAI-совместимый endpoint; UI явно показывает передаваемые данные, проверяет `/models`, хранит API key в системном хранилище и показывает JSON-план с геометрическим preview до применения.

## Срез M4: оставшиеся EXT-группы (2026-11-03)

- `EXT-002`: numerical constraint solver поддерживает coincident/horizontal/vertical/parallel/perpendicular/tangent/equal/dimension/fix, residual/rank/DOF, conflict vs compatible redundancy и constrained drag. Preview не создаёт commit; Apply/Undo/Redo/save/reopen проходят real-kernel tests.
- `EXT-010`: STL/OBJ/PLY source встраивается в mesh-only document. Реализованы transform, закрытие поддерживаемого boundary hole с before/after diagnostics и topology-aware decimation с component/Euler/bbox/volume gates; shape error явно называется sampled estimate, не Hausdorff guarantee. STEP для mesh-document запрещён, STL и встроенный 3MF exporter работают.
- `EXT-011`: `heightmap-luminance-v1` строит замкнутый decorative mesh из PNG/JPEG/WebP; preview не меняет документ, Apply связан с SHA-256 исходника, model/seed/settings и mm scale сохраняются. Workflow явно не объявляется инженерно точным.
- Impact gates: CAD/document/worker `139 passed`; help `2 pytest + 4 search`, 34 статьи/58 команд; UI contracts/build; Rust `13 passed`; traceability `97 requirements / 63 test IDs`; release `6 passed`. Отчёты: `artifacts/test-runs/m4-complete-{cad,help,ui,rust,trace,release}/test-report.json`.
- Production sidecar пересобран (`125.4 MiB`) и реально выполнил solver (`DOF=0`), mesh repair (`12` triangles, `1000 мм³`), decimation и image relief. Windows installer/payload evidence получен; direct canvas Sketcher, general self-intersection repair и external generative providers остаются открытыми partial clauses.

## Release v0.3.0 (2026-11-03)

- Desktop, UI, Tauri и lockfile версии синхронизированы на `0.3.0`; release notes находятся в `docs/releases/v0.3.0.md`.
- Release workflow собирает macOS Apple Silicon, macOS Intel и Windows x64 с подписанными Tauri Updater artifacts.
- Draft публикуется автоматически только после успешного завершения всей installer matrix и Windows installed-artifact gate; hosted-runner performance записывается отдельно и не переименовывается в pass.
- Локальные release и traceability gates прошли: `6 + 3` tests, `97` requirements, `63` test IDs; отчёты находятся в `artifacts/test-runs/v0.3.0-{release,traceability}/`.
- Browser UI smoke на desktop viewport: constraint preview показал `DOF=0`, Apply создал «Ограниченный эскиз» объёмом `4000 мм³`, один Undo вернул пустой документ. Dev-shim после проверки остановлен.

## Как запустить

- `.app`: команды в README; итог — `app/src-tauri/target/release/bundle/macos/PrintForge.app` (~129 МБ, sidecar внутри).
- Dev: `scripts/dev_shim.py` + `cd app/ui && npx vite`.
- Проверки: `backend/.venv/bin/python -m pytest backend/test_worker.py backend/test_templates.py backend/test_ai.py -q` (38/38); `cd app/ui && npm run build`; `cd app/src-tauri && cargo check`; `scripts/check_help.py`; инспекторы дизайна — см. DESIGN_SOURCES.md.

## Выполненные проверки (macOS 27, M3 8 ГБ)

- Аналитика геометрии: AC-01 (пластина), AC-02 (шайба 1143.539726 мм³), AC-03 (корпус 29472 + крышка 14355.2 мм³, пересечение 0, зазор 0,2 при смене длины), AC-04 (кронштейн 11000 мм³, R2 ок, R50 → fillet_failed без подмены, ссылка на ребро живёт после изменения размера, reselect_required) — pytest 13/13.
- Форматы: STEP roundtrip точный; STL габарит ±0.05, объём в 0.5%; масштаб дюймов ×25,4; 3MF пишется lib3mf.
- В браузере (реальный UI): AC-01 полностью (M1); кронштейн + скругление R2 (объём 10974.2) + R50 (ошибка, модель и история целы); AC-06 ядро (перенос файла проекта, повреждённый файл); урок 2 завершён, рабочий документ не тронут (M1).
- Дизайн: `impeccable detect` 0 проблем; Taste `inspect --app` 0 FAIL 0 WARN; скриншоты 1280/1440/1920 + ~150% просмотрены.
- Smoke M2 .app: запуск из /tmp с чистым окружением; sidecar внутри bundle: шайба 1143.539726 мм³ автономно.

## Найденные и исправленные в M2 баги

- DocState.error (объект) вызывал ложную транспортную ошибку «[object Object]» — транспортный слой больше не путает ошибку документа с ошибкой вызова.
- Неудачная фаска возвращала Err и прятала ошибку от UI — теперь откат транзакции + видимая ошибка (DOC-005).
- h1 и нумерация истории потерялись при переписи компонентов — восстановлены, inspectors снова зелёные.

## Ограничения / непроверенное

- Полный AC-12 внутри `.app` ещё не пройден; в WKWebView проверен AI-сценарий M3 и ранее автономность sidecar, остальные команды требуют полного обхода.
- Уроки 4–8 не прогонялись в UI (движок готов); AC-07/AC-08 повторить на M2-функциях; AC-09 частично (bed_fit проверен worker'ом; импорт сетки с открытым краем — не проверен).
- Слайсер не установлен (масштаб в слайсере не подтверждён); Developer ID/notarization нет, локальная `.app` подписана ad-hoc; Windows hosted-runner performance не принят как control-machine baseline (`9295.44 мс`, `28.19 FPS`).

## Последний срез (документ v3, 2026-10-22)

- Булевы операции (union/subtract/intersect) с keep_tool и повторным построением, линейный массив, зеркало, разделение плоскостью с двумя именованными частями, точное перемещение; откат транзакции с видимой ошибкой (split_failed, fillet_failed).
- Проверено: pytest 18/18 (включая v3-операции и mesh_check AC-09); в реальном UI — добавление шайбы и вычитание (17754.87 мм³, 1 живое тело); undo/redo сохраняет повторяемость (документ хранит определения деталей).
- Диагностика импортированной сетки: открытый край → fail с числом рёбер, без «модель готова» (AC-09).
- Инспекторы: impeccable 0 проблем, taste inspect 0 FAIL 0 WARN; скриншот 1440 просмотрен.
- Smoke .app v3: sidecar внутри bundle выполняет булево вычитание автономно (17754.9 мм³).

## Последний срез (профили и измерения, 2026-10-22)

- Профили: прямоугольник/окружность/кольцо/паз, добавление объёма и вырез (сквозной как through), плоскости XY/XZ/YZ; паз 4×20 сквозной — объём 18740.6 мм³ точно.
- Круговой массив (4×R25 → 60×60), выравнивание по центру/краю, измерения (габарит/объём/диаметр грани/расстояние, источник BRep).
- Исправлен рассинхрон part_id между документом и статусом (единый v3-путь построения).
- Проверено: pytest 21/21; паз и измерение через реальный UI; инспекторы impeccable 0 / taste 0 FAIL 0 WARN; smoke .app — sidecar автономно режет паз (18740.6).

## Последний срез (уроки и финал M2, 2026-10-22)

- Урок 5 «Корпус с крышкой» пройден в реальном UI до «Урок завершён»: длина 120 → объём 51187.2 мм³ (аналитика), шаги проверены по состоянию модели; после выхода рабочий документ не изменён.
- Урок 2 ранее пройден; уроки 1–8 доступны в справке.
- Исправлено: прикреплённый блок «?»/«Что это?» снова был потерян при переписи TopBar — восстановлен (второй регресс такого рода, добавить в чек-лист AC-13).
- Инспекторы на финальном UI: impeccable 0, taste 0 FAIL 0 WARN.
- Smoke финальной .app (свережая): запуск с чистым окружением, sidecar v3 автономен.

## Последний срез (уроки 5–8 в UI, 2026-10-23)

- Уроки 5 (корпус, объём 51187.2 мм³), 6 (скругление + ошибка fillet_failed), 7 (импорт STL с выбором единиц), 8 (проверка печати: bed_fit fail→pass, «Не проверено» для стенки) — пройдены до «Урок завершён» в реальном UI.
- Исправлено: двухфазный импорт читал bbox вместо bbox_mesh (не показывался выбор единиц); импортированная сетка приходила handle'ом и роняла UI (чтение ресурса через doc_get_imported_mesh); урок застревал, когда одно событие закрывает несколько шагов (цикл продвижения в движке); счётчик треугольников пустой для сетки.
- FreeLLMAPI: установлен и запущен (API :3001/v1, дашборд :5174), ADR-003.

## Последний срез (M3 UI и транзакция, 2026-10-30)

- Добавлена пользовательская AI-панель: статус провайдера, отменяемый запрос, JSON-план в читаемом виде, явные допущения/вопросы, точный preview и применение одной транзакцией.
- Tauri-команды `ai_providers`, `ai_plan`, `ai_chat` и `doc_transaction` зарегистрированы в `invoke_handler`; TypeScript-контракт AI типизирован, `npm run build` теперь обязательно выполняет `tsc --noEmit`.
- Исправлен Undo пустого документа в Rust и dev-shim: производные `stats/mesh/error` очищаются, revision увеличивается, устаревший AI-preview сбрасывается. Добавлен regression test.
- Проверено: pytest 34/34, справка 28 статей/32 команды, TypeScript + Vite build, `cargo check`; в browser UI и собранной `.app` шайба 20×6×4 даёт preview 1143,5 мм³, применяется одной транзакцией и удаляется одним Undo.
- Собрана `PrintForge.app` 142,61 МиБ со встроенным sidecar; устаревшие заголовок «пробная сборка M0» и bundle identifier с суффиксом `.app` исправлены.
- Не проверено в этом срезе: Ollama/OpenAI endpoint и полный quality gate 20×3.

## Последний срез (настройки AI-провайдеров, 2026-10-30)

- Добавлены пользовательские профили `disabled`, локальный Ollama и OpenAI-совместимый endpoint. Для Ollama удалённый host запрещён; модель не скачивается автоматически.
- Не-секретные настройки сохраняются в app config; API key — только в macOS Keychain через `keyring`, не возвращается в UI и не попадает в `ai-settings.json`. Browser dev-shim хранит тестовый key только в памяти процесса.
- «Сохранить и проверить» делает только `GET /models`; перед отправкой плана UI перечисляет фактический контекст: запрос, шаблоны, размеры и операции, без сетки и файла проекта.
- Для Ollama план запрашивается с JSON Schema через `response_format`; generic OpenAI-compatible профиль не объявляется schema-capable без проверки и в любом случае проходит собственную валидацию приложения.
- Исправлены два найденных smoke-тестом дефекта: повторный `parseIpcError` показывал `[object Object]`, а Tauri-команда настройки требовала `camelCase` IPC-параметры.
- Проверено: pytest 38/38, TypeScript + Vite build, `cargo check`, help index, release bundle 142,83 МиБ; browser UI — default-off, Ollama disclosure/валидация, OpenAI session key; native `.app` — сохранение профиля между перезапусками и Keychain item без секрета в config. Тестовый key после проверки удалён, профиль возвращён в `disabled`.
- Не проверено: реальная генерация Ollama/FreeLLMAPI (endpoint не был запущен), Windows Credential Manager/Linux Secret Service и quality gate 20×3.

## Следующие задачи

1. Уроки 1, 3, 4 при случае; AC-12 внутри `.app`.
2. Повторить Windows x64 performance на закреплённой контрольной машине; hosted runner уже сохраняет отдельный `windows-release-evidence-*` с installer/payload pass и неизменёнными performance outcomes.

## Последний срез (desktop distribution, 2026-10-30)

- Версия desktop нормализована до `0.1.0`; приложение и исходный код подготовлены к поставке по Apache-2.0 через GitHub Releases.
- Добавлены native release targets: DMG для macOS Apple Silicon/Intel и NSIS для Windows x64; geometry sidecar собирается PyInstaller на runner той же архитектуры.
- Tauri Updater проверяет обязательную Ed25519 signature, берёт `latest.json` из GitHub Release и показывает обновление через колокольчик: download progress, release notes, установка и restart, блокировка при несохранённом документе.
- Workflow создаёт draft release; macOS использует ad-hoc signature без notarization, Windows — без Authenticode, в соответствии с open-source моделью Apertone.
- Полная проверка GitHub matrix и установленного update-перехода ожидает первый draft release; локальные build/check перечислены в `docs/DISTRIBUTION.md`.

## Последний срез (автотесты и traceability, 2026-10-30)

- Добавлен explicit manifest: 85 ID исходного ТЗ + `EXT-001…EXT-012`, без ложных `passed`.
- Deterministic M3 покрывает production validation, loopback provider adapter, schema repair, real-kernel preview/apply/export/Undo, atomic failure, stale/ABA, plan hash, instance guard и idempotent action.
- Добавлены независимые F-01…F-04 ожидания и hand-authored F-05 STL fixtures.
- `scripts/run_test_stage.py` формирует JSON/JUnit/log artifacts и поддерживает полный baseline либо impact-based локальный прогон.
- Полный native UI E2E остаётся открытым; release smoke и Windows installed-artifact run выполнены, live LLM eval закрыт отдельным срезом. Детали в `docs/testing/TEST_GAPS.md`.

## Последний срез (direct editing, 2026-10-30)

- Добавлен первый рабочий Push/Pull: выбор внешней плоской грани, оранжевый drag-handle, live preview без записи в документ, точный размер в правой панели и один commit на отпускание/Enter.
- Изменение остаётся параметрическим: поддерживаемая грань связывается с исходным размером шаблона, поэтому перестроение, сохранение и один шаг Undo работают через существующий документный контракт.
- Поддержаны безопасные грани пластины, шайбы, L-кронштейна и корпуса; импортированные сетки, несколько тел, цилиндрические/внутренние грани и топологические операции показывают явное ограничение.
- Native Tauri mesh reader теперь возвращает `face_ranges`, поэтому выбор граней работает не только в browser dev mode.
- Проверено: `npm run build`, `cargo test` (3/3); browser UI — грань пластины, высота 6→8 мм одним шагом истории, Undo 8→6 мм.

## Срез direct editing v2: элементы на грани (2026-10-30)

- Выбранная внешняя плоская грань теперь принимает локальную бобышку или blind/through вырез: окружность, прямоугольник, кольцо и паз, размеры и смещения по локальным осям U/V.
- Preview показывает добавляемый или удаляемый объём без изменения документа; применение создаёт одну параметрическую `face_feature`-операцию и отменяется одним Undo.
- Ссылка не хранит `FaceN`: документ фиксирует смысл `outer_planar`, ось, сторону и привязку относительно центра грани; при перестроении операция снова вычисляет внешнюю плоскость по актуальному BRep.
- Честные ограничения: один параметрический body, только внешние осево-ориентированные плоские грани; импортированные сетки, внутренние и криволинейные грани не поддерживаются.

## Последний срез (direct editing v2: обработка рёбер, 2026-10-30)

- Прямые рёбра теперь выбираются щелчком непосредственно в 3D-сцене; точный список остаётся fallback для криволинейных и визуально перекрытых рёбер.
- Единый edge-tool поддерживает параметрические `fillet` и `chamfer`, показывает маркер концов и подпись точного размера `R`/`C` до применения.
- Несколько рёбер обрабатываются последовательными операциями, каждая операция создаёт отдельную запись истории и отменяется одним Undo.
- Семантическая ссылка на ребро сохраняет тип, длину и положение; неоднозначное или исчезнувшее после перестроения ребро требует явного повторного выбора.

## Срез direct editing v2: выпуклость/вмятина (2026-10-30)

- На выбранной внешней плоской грани создаётся точный BRep-сферический сегмент: добавляемая выпуклость или вычитаемая вмятина.
- Параметры — диаметр основания, высота и смещения U/V; live preview не меняет документ, а применение создаёт одну `face_dome`-операцию и один Undo.
- Геометрия не обрезается молча: высота ограничена полусферой, круглое основание должно целиком лежать на материале, а вмятина не доходит до противоположной стороны.
- Impact-based прогон зелёный: AI 32, CAD/document 30, help 2 + integrity (30 статей, 34 команды), Rust 3, TypeScript/Vite; отчёт `artifacts/test-runs/20261030T145229Z/test-report.json`.
- Browser smoke: пластина с отверстиями, выпуклость Ø20 × 4 мм; объём `18898.41 → 19560.24 мм³`, габарит Z `6 → 10 мм`, один Undo вернул исходную модель.

## Срез direct editing v2: точный изгиб пластины (2026-10-30)

- Добавлена специализированная BRep-операция sheet-metal изгиба пластины: ось X/Y, позиция линии, угол 5–170°, внутренний радиус, подвижная сторона и направление +Z/−Z.
- Развёрнутая длина рассчитывается по нейтральному слою с K-factor 0,5; толщина и объём сохраняются с числовой проверкой.
- Штатные отверстия переносятся на обе плоские стороны; пересечение отверстия зоной изгиба блокируется явной ошибкой.
- Live preview показывает изогнутую заготовку без изменения документа; commit — одна `sheet_bend`-транзакция и один Undo.
- Честное ограничение первого slice: одна пластина, верхняя грань, один изгиб как первая операция; повторные изгибы и произвольные вырезы в зоне изгиба остаются следующими vertical slices.
- Impact-based прогон зелёный: AI 32, CAD/document 33, help 2 + integrity (31 статья, 35 команд), Rust 3, TypeScript/Vite; отчёт `artifacts/test-runs/20261030T210526Z/test-report.json`.
- Browser smoke: пластина `80 × 40 × 6 мм`, изгиб X/90°/R5; объём остался `18898.41 мм³`, четыре отверстия сохранились, габариты стали `44.72 × 40 × 44.72 мм`, один Undo вернул исходную модель.

## Срез direct editing v2: последовательные изгибы (2026-11-02)

- Пластина перестраивается из общей развёртки с одной или двумя параллельными bend-зонами; второй изгиб не деформирует результат первого сеточным или локальным BRep-хаком.
- Для двух линий поддержан устойчивый сценарий канала/Z-профиля: левая линия сгибает сторону −X/−Y, правая — +X/+Y; направления и углы задаются независимо.
- Bend-зоны не могут пересекаться, отверстия переносятся на итоговые плоские участки, толщина и объём проверяются после полного перестроения.
- Live preview показывает обе линии одновременно; каждый изгиб остаётся отдельной document-транзакцией и отдельным шагом Undo.
- Честное ограничение slice: максимум две параллельные линии; перпендикулярные и каскадные изгибы уже согнутого фланца и произвольные вырезы через bend-зону пока не поддерживаются.
- Impact-based прогон зелёный: AI 32, CAD/document 35, help 2 + integrity (31 статья, 35 команд), Rust 3, TypeScript/Vite; отчёт `artifacts/test-runs/20261102T084336Z/test-report.json`.
- Browser smoke: линии X `−20/+20 мм`, 90°, R3 сформировали канал `48.58 × 40 × 24.29 мм`; объём остался `18898.41 мм³`, четыре отверстия сохранились, первый Undo снял только второй изгиб, второй вернул пластину `80 × 40 × 6 мм`.

## Срез direct editing v2: вырезы на согнутой пластине (2026-11-02)

- Through-вырезы верхней грани теперь входят в parametric replay общей развёртки и переносятся на итоговые прямые участки после одного или двух параллельных изгибов.
- Поддержаны окружность, прямоугольник, кольцо и паз с исходными U/V, размерами и ориентацией для осей изгиба X и Y.
- Профиль, пересекающий bend-зону, блокируется явной `bend_failed` ошибкой; молчаливой деформации контура на криволинейной поверхности нет.
- Порядок документа строгий: сначала through-вырезы, затем последовательные изгибы; каждый commit остаётся отдельной транзакцией Undo.
- Live preview честно показывает форму листа без контуров вырезов; после commit backend проверяет валидность, сохранение количества тел и точного объёма уже вырезанной плоской заготовки.
- Impact-based прогон зелёный: AI 32, CAD/document 42, help 2 + integrity (31 статья, 35 команд), Rust 3, TypeScript/Vite; отчёт `artifacts/test-runs/20261102T085438Z/test-report.json`.
- Browser smoke: на пластине со штатными отверстиями создан пользовательский through-вырез Ø8 при X=30 мм, затем изгиб X/90°/R5; вырез перенесён на вертикальный фланец, объём остался `18596.81 мм³`, первый Undo вернул плоскую пластину с вырезом, второй удалил только пользовательский вырез.

## Срез direct editing v2: прямоугольный вырез через bend-зону (2026-11-02)

- Прямоугольный through-профиль может пересекать криволинейную область одного или двух параллельных изгибов по X или Y.
- Вырез строится не аппроксимацией mesh: backend создаёт отдельный `make_brake_formed` BRep strip по общему bend-path, точно обрезает его плоскостями границ исходного профиля и вычитает из пластины.
- Parametric replay сохраняет исходные U/V и размеры; после полного перестроения проверяются валидность, количество тел и объём плоской заготовки после выреза.
- Окружность, кольцо, паз и штатные круглые отверстия при пересечении bend-зоны по-прежнему отклоняются явной ошибкой; молчаливого искажения нет.
- Kernel-тесты покрывают X, Y и один прямоугольник сразу через две bend-зоны; document integration проверяет отдельные транзакции и Undo выреза/изгиба.
- Impact-based прогон зелёный: AI 32, CAD/document 46, help 2 + integrity (31 статья, 35 команд), Rust 3, TypeScript/Vite; отчёт `artifacts/test-runs/20261102T091300Z/test-report.json`.
- Browser smoke: прямоугольный through-вырез `12 × 8 мм` по центру пересёк изгиб X/90°/R5 непрерывным BRep-контуром; объём остался `18322.41 мм³`, первый Undo вернул плоскую пластину с вырезом, второй удалил вырез.

## Срез direct editing v2: каскад параллельных изгибов (2026-11-02)

- Parametric replay расширен с двух до четырёх параллельных bend-линий одной развёртки; углы, радиусы и направления каждой линии остаются независимыми.
- Поддержаны два устойчивых режима: каскад от неподвижного края со всеми `moving_side` одного знака и центральный неподвижный участок с группой `−ось` слева и `+ось` справа.
- Начальный tangent рассчитывается по сумме углов левой группы, а anchor — по реальному неподвижному краю или промежутку между группами; preview использует тот же алгоритм, что backend.
- Пересекающиеся bend-зоны, конфликтующий порядок moving-side, пятая линия, самопересечение и изменение объёма блокируются явной ошибкой.
- Все четыре commit остаются отдельными document-транзакциями; четыре последовательных Undo возвращают исходную плоскую пластину.
- Impact-based прогон зелёный: AI 32, CAD/document 48, help 2 + integrity (31 статья, 35 команд), Rust 3, TypeScript/Vite; отчёт `artifacts/test-runs/20261102T091829Z/test-report.json`.
- Browser smoke: четыре линии X `−25/−8/+8/+25 мм`, 45°, R1 сформировали центрально закреплённый каскад `46.46 × 40 × 30.23 мм`; объём остался `18898.41 мм³`, UI заблокировал пятую линию, один Undo вернул трёхлинейную геометрию `56.12 × 40 × 30.23 мм`.

## Срез direct editing v2: круглый вырез через bend-зону (2026-11-02)

- Пользовательский круглый through-вырез может пересекать одну криволинейную bend-зону по X или Y в обоих направлениях изгиба; смещение центра относительно линии поддерживается.
- Контур переносится без mesh: backend строит ruled BRep loft по 64 station-сечениям локальной поверхности листа. Это контролируемая кусочно-линейная аппроксимация окружности, а не ложная аналитическая геометрия.
- Трапецеидальная площадь station-профиля нормализуется к `πr²`; после boolean backend дополнительно корректирует ширину loft и проверяет исходный объём плоской заготовки с kernel tolerance.
- Пересечение второй curved zone, а также кольцо, паз и штатное отверстие на bend-зоне пока блокируются явной ошибкой до построения нестабильной геометрии.
- Kernel-тесты покрывают X/+Z, Y/−Z, смещённый круг, ограничение второй зоны и сохранение валидного единственного solid; document integration проверяет commit и два шага Undo.
- Impact-based прогон зелёный: AI 32, CAD/document 52, help 2 + integrity (31 статья, 35 команд), Rust 3, TypeScript/Vite; отчёт `artifacts/test-runs/20261102T093502Z/test-report.json`.
- Browser smoke: through-вырез Ø8 по центру пересёк изгиб X/90°/R5 на пластине с четырьмя штатными отверстиями; объём остался `18596.81 мм³`, габариты стали `44.72 × 40 × 44.72 мм`, Undo вернул плоскую заготовку `80 × 40 × 6 мм` с вырезом.

## Срез direct editing v2: паз через bend-зону (2026-11-02)

- Паз through может пересекать одну криволинейную bend-зону по X или Y в обоих направлениях изгиба.
- Для оси вдоль длины паза station-width состоит из прямого участка и двух полукруглых cap; для поперечной оси — из постоянной центральной длины и двух симметричных дуг.
- Capsule-контур строится ruled BRep loft по 64 station-сечениям; переходы между прямым участком и cap добавляются как обязательные станции, а площадь нормализуется к `(L − W)W + π(W/2)²`.
- UI и backend блокируют второй curved bend для паза до kernel-вызова; кольцо и штатные отверстия на bend-зоне пока остаются неподдержанными.
- Kernel-тесты покрывают X/+Z и Y/−Z с проверкой объёма, валидности и одного solid; document integration проверяет commit и последовательный Undo.
- Impact-based прогон зелёный: CAD/document 55, help 2 + integrity (31 статья, 35 команд), TypeScript/Vite; отчёт `artifacts/test-runs/20261102T094738Z/test-report.json`.
- Browser smoke: паз through `12 × 4 мм` по центру пересёк изгиб X/90°/R5; объём остался `18631.01 мм³`, габариты стали `44.72 × 40 × 44.72 мм`, Undo вернул плоскую заготовку `80 × 40 × 6 мм` с пазом.

## Срез direct editing v2: кольцо через bend-зону (2026-11-02)

- Кольцевой through-вырез может пересекать одну криволинейную bend-зону по X или Y в обоих направлениях изгиба.
- Наружный и внутренний круги строятся независимыми ruled BRep loft по 64 station-сечениям на одном bend-path; кольцевой инструмент получается точной boolean-разностью loft.
- Площадь каждого контура нормализуется отдельно, затем общий инструмент корректируется по удалённому объёму до площади `π(R² − r²)`.
- Центральный диск сохраняется как отдельный solid, поэтому curved ring-cut имеет те же два тела, объём и Undo-семантику, что плоский профиль.
- UI и backend блокируют пересечение второй curved bend до kernel-вызова; штатные отверстия в bend-зоне остаются неподдержанными.
- Kernel-тесты покрывают X/+Z и Y/−Z, два solids, точный объём и запрет второй зоны; document integration проверяет commit и последовательный Undo.
- Impact-based прогон зелёный: CAD/document 59, help 2 + integrity (31 статья, 35 команд), TypeScript/Vite; отчёт `artifacts/test-runs/20261102T101429Z/test-report.json`.
- Browser smoke: кольцевой through-вырез `Ø10/Ø6 мм` по центру пересёк изгиб X/90°/R5; объём остался `18596.81 мм³`, габариты стали `44.72 × 40 × 44.72 мм`, Undo вернул плоскую заготовку `80 × 40 × 6 мм` с кольцом.

## Release v0.2.0 (2026-11-02)

- Версии desktop, UI, Tauri и lockfiles синхронизированы на `0.2.0`; `scripts/check_release_version.py` проходит.
- Vite обновлён с 5 до 8, `@vitejs/plugin-react` — с 4 до 6; `npm audit` для desktop и UI сообщает 0 известных уязвимостей.
- Полный deterministic gate зелёный: Python 99, Rust 3, TypeScript/Vite, help integrity, traceability и release-version; отчёт `artifacts/test-runs/20261102T101959Z/test-report.json`.
- Локально собраны ad-hoc signed Apple Silicon `.app`, DMG и подписанный updater artifact; `codesign --verify --deep --strict` проходит.
- Production sidecar из собранной `.app` прошёл JSON-protocol smoke: пластина `80 × 40 × 6 мм`, объём `18898.407105 мм³`, один валидный solid.

## Срез direct editing v2: перпендикулярный изгиб фланца (2026-11-02)

- После одного базового изгиба 90° можно выбрать внешнюю вертикальную грань подвижного фланца и создать вторую линию по перпендикулярной оси; локальная ось определяется из выбранной грани, стороны и направления базового изгиба.
- Фланец перестраивается отдельной точной `make_brake_formed` BRep-полосой и объединяется с базовым изгибом; результат проверяется на валидность, одно тело и сохранение объёма в kernel tolerance.
- Штатные отверстия и пользовательские through-вырезы четырёх профилей переносятся на новый фланец, включая пересечение его bend-зоны. Профиль, пересекающий корень базового изгиба, блокируется явной ошибкой.
- Каждый изгиб остаётся отдельной document-транзакцией: первый Undo снимает только фланцевый изгиб, второй возвращает плоскую пластину.
- UI строит локальный синий live preview второго изгиба в системе выбранного фланца; preview не меняет документ и намеренно не показывает контуры отверстий.
- Текущий impact-based gate зелёный: CAD/document 74, UI TypeScript/Vite, help 2 + integrity (31 статья, 35 команд); отчёты `artifacts/test-runs/20261102T120721Z/test-report.json`, `artifacts/test-runs/20261102T120835Z/test-report.json` и `artifacts/test-runs/20261102T120840Z/test-report.json`.
- JSON-protocol smoke через dev-shim: два `sheet_bend`, объём `18898.417952 мм³`, один валидный solid, bbox `[-40, -20, 0, 22.36, 20, 44.29]`; Undo оставил только базовый изгиб.
- Честное ограничение slice: базовый изгиб должен быть один и ровно 90°; несколько перпендикулярных линий и фланец после параллельного каскада остаются следующими итерациями.

## Срез M3: offline-ответы по справке (2026-11-02)

- В `AI-помощник` добавлены отдельные режимы `Модель` и `Справка`; справочный режим работает при `disabled` provider и не выполняет сетевые запросы.
- Retrieval ранжирует только shipped `help/index.json`, учитывает title, synonyms, body и зарегистрированные команды; процедурный вопрос приоритетно возвращает секцию `Пошагово`.
- Ответ состоит из точного фрагмента статьи, ссылок на источники и команд, прошедших пересечение с command registry. При отсутствии совпадения UI не генерирует ответ.
- Browser smoke: вопрос «Как сделать перпендикулярный изгиб фланца?» вернул пошаговую инструкцию, только `op.sheet_bend` и открыл статью «Точный изгиб пластины».
- Impact-based gate зелёный: deterministic AI 32, help pytest 2 + retrieval 4 + integrity (31 статья, 36 команд), UI TypeScript/Vite; отчёты `artifacts/test-runs/20261102T122937Z/test-report.json`, `artifacts/test-runs/20261102T123248Z/test-report.json` и `artifacts/test-runs/20261102T123254Z/test-report.json`.

## Срез M3: AC-10/AC-11 и quality harness (2026-11-02)

- AC-10 расширен real-kernel сценарием F-01: AI preview пластины 80 × 40 × 6 мм с четырьмя отверстиями Ø4 совпадает с AC-01, рабочий документ до apply не меняется, применённые параметры редактируются обычным `parameter.set`. F-02 по-прежнему проверяет apply/export и один Undo всей AI-операции.
- Законное уточнение без операций больше не запускает пустую preview-транзакцию; явное предположение остаётся видимым и получает preview только при наличии операций.
- AC-11 дополнен controlled timeout, усечённым и oversized provider body, unknown schema fields, type/units cases и индексом первой невалидной операции при geometry failure; rollback остаётся атомарным.
- Live-eval harness schema v2 разделяет порог 80% для simple-valid и обязательные 100% clarification/safety/non-mutation/repair-limit, сохраняет dataset hash, commit, model metadata, outcomes, latency и память harness/CAD. Offline help исключён из LLM dataset, потому что обрабатывается локальным retrieval.
- Impact-based AI gate зелёный: 46 тестов; отчёт `artifacts/test-runs/20261102T130019Z/test-report.json`.
- После этого среза добавлен сквозной task ID и `ai_cancel`: native Tauri через `tokio::select!` дропает активный `reqwest` future, dev-shim после cancel не допускает late validation/preview, duplicate task ID отклоняется. Controlled deterministic race не меняет документ.
- Актуальные impact gates: AI 47, UI TypeScript/Vite, Rust 4, help pytest 2 + retrieval 4 + integrity, traceability 3; отчёты `artifacts/test-runs/20261102T131445Z/test-report.json`, `artifacts/test-runs/20261102T131309Z/test-report.json`, `artifacts/test-runs/20261102T130947Z/test-report.json`, `artifacts/test-runs/20261102T131120Z/test-report.json`, `artifacts/test-runs/20261102T131231Z/test-report.json`.
- Реальный quality gate 20 × 3 не запускался: Ollama отсутствует, `127.0.0.1:11434` недоступен. Статус конкретной модели остаётся `not_run`; native E2E фактического обрыва HTTP/CAD preview закрыт отдельным срезом 03.11.2026.

## Срез M2: binary mesh channel (2026-11-02)

- Native Tauri больше не сериализует positions/indices крупной сетки в JSON: metadata и raw binary buffer передаются отдельными IPC-командами, UI создаёт `Float32Array`/`Uint32Array` поверх полученного `ArrayBuffer`.
- Двухфазная загрузка связана ожидаемым SHA-256. Перестроенная между metadata и binary модель возвращает `mesh_stale`, изменение файла — `mesh_hash_mismatch`; длина buffer и counts проверяются до чтения.
- Browser dev-shim сохраняет прежние JSON-команды, поэтому локальная разработка без native runtime не сломана. Native import использует тот же hash-bound binary path.
- Impact gates зелёные: mesh decoder 2 tests + UI TypeScript/Vite build (`artifacts/test-runs/20261102T140045Z/test-report.json`), Rust 7 tests (`artifacts/test-runs/20261102T140736Z/test-report.json`). Native WebView performance позднее закрыт отдельным TECH-003 runner; общий WebView E2E остаётся незакрытым.

## Срез M2: bounded geometry worker recovery (2026-11-02)

- Tauri и production dev adapter при transport death/write failure уничтожают повреждённый worker, запускают новый и ровно один раз повторяют исходный stateless request с теми же полным snapshot и revision.
- Управляемые CAD-ошибки не повторяются. Повторная авария возвращает `worker_recovery_failed`; последняя подтверждённая mesh/stats остаётся видимой, а document transaction применяет штатный rollback.
- Deterministic real-process test убивает worker после отправки build-запроса и подтверждает восстановление тех же volume/bbox в новом PID.
- Impact gates зелёные: AI 47 (`artifacts/test-runs/20261102T140526Z/test-report.json`), CAD/document 75 (`artifacts/test-runs/20261102T140551Z/test-report.json`), Rust 7 (`artifacts/test-runs/20261102T140736Z/test-report.json`), traceability 3 (`artifacts/test-runs/20261102T140738Z/test-report.json`). Native sidecar induced-crash E2E, timeout и progress остаются открытыми.

## Срез M2: geometry control (2026-11-02)

- Native Tauri и dev adapter поддерживают ручную отмену активной CAD-операции, timeout 120 с для CAD и 300 с для import/export, kill зависшего worker и запрет автоматического retry после cancel/timeout.
- UI показывает elapsed seconds и кнопку отмены; AI cancellation также прерывает активный CAD preview. Неуспешный committed rebuild восстанавливает последний подтверждённый документ.
- Impact gates зелёные: AI 47 (`artifacts/test-runs/20261102T142559Z/test-report.json`), CAD/document 78 (`artifacts/test-runs/20261102T142642Z/test-report.json`), UI geometry/mesh/build (`artifacts/test-runs/20261102T142827Z/test-report.json`), Rust 9 (`artifacts/test-runs/20261102T142831Z/test-report.json`), traceability 3 (`artifacts/test-runs/20261102T142832Z/test-report.json`).

## Срез M2: TECH-003 performance (2026-11-03)

- Добавлен воспроизводимый harness с environment/commit/dirty metadata, 7 повторами, JSON-отчётом и contract trace `T-TECH-05`.
- На Apple M3, 8 ГиБ, macOS 27.0.1: loaded help search p95 `1.41 мс`; warm simple CAD build p95 `75.19 мс`; 20 тел/100 transform-операций `577.96 мс`, worker RSS `348.41 МБ`.
- Synthetic binary mesh ровно на 200 000 треугольников: decode p95 `0.25 мс`, production coordinate map p95 `4.10 мс`, Node RSS `86.76 МБ`; это не WebGL FPS.
- Component gates зелёные, отчёт `artifacts/perf/20261102T143450Z/perf-report.json`.
- На свежей ad-hoc signed arm64 `.app`: process-cold frontend ready p95 `1541.75 мс` по 7 запускам; реальный camera orbit `60 FPS` во всех 3 запусках; maximum RSS main app и descendants `438.67 МБ`.
- Native control project содержит 20 тел, 100 операций, 20 solids и 40 880 отображаемых треугольников; synthetic production decoder/map отдельно проверен ровно на 200 000 треугольников.
- Все TECH-003 и bundle-signature gates пройдены: `artifacts/perf/20261103T073255Z/native-perf-report.json`. Контракты perf 6/6 и release 3/3: `artifacts/test-runs/20261103T073230Z/test-report.json`, `artifacts/test-runs/20261103T073232Z/test-report.json`.
- Финальные связующие gates: UI geometry/mesh/build `artifacts/test-runs/20261103T073510Z/test-report.json`, Rust 10/10 `artifacts/test-runs/20261103T073513Z/test-report.json`, traceability 3/3 `artifacts/test-runs/20261103T073516Z/test-report.json`.

## Срез M3: native E2E cancellation (2026-11-03)

- Добавлен env-gated native harness для собранной ad-hoc signed macOS arm64 `.app`; обычный запуск не активирует probe, не меняет пользовательский AI config и не обращается к Keychain.
- В HTTP-сценарии настоящий WebView вызывает `ai_plan`, затем `ai_cancel` через Tauri IPC во время неполного loopback HTTP/1.1 response body. Native `reqwest` future завершается, сервер фиксирует разрыв сокета, frontend получает `ai_cancelled`, документ остаётся на revision 0.
- В CAD-сценарии provider возвращает валидный plan, отмена выполняется во время production sidecar preview. `geometry_cancelled=true`, документ не меняется, следующий штатный CAD build создаёт один валидный solid на revision 1.
- Оба сценария пройдены на свежей bundle-сборке; максимальный process-tree RSS составил `93.27 МБ` для HTTP и `412.34 МБ` для CAD. Bundle signature также прошла отдельный gate.
- Итоговый отчёт после финальной пересборки native AI adapter: `artifacts/native-e2e/20261103T095455Z/native-ai-cancel-report.json`; gates `provider_http_cancel`, `cad_preview_cancel_and_recovery`, `bundle_signature` — `passed`.
- Финальные impact-gates зелёные: AI 49/49 `artifacts/test-runs/20261103T085247Z/test-report.json`, UI geometry/mesh/build `artifacts/test-runs/20261103T085313Z/test-report.json`, Rust 10/10 `artifacts/test-runs/20261103T085316Z/test-report.json`, traceability 3/3 `artifacts/test-runs/20261103T085322Z/test-report.json`.
- Harness детерминированно доказывает lifecycle cancellation, но не качество LLM. Качество выбранной модели подтверждено отдельным live-eval срезом; результаты нельзя переносить на другие модели.

## Срез M3: quality gate реальной модели (2026-11-03)

- Установлен локальный Ollama `0.40.13` без автозапуска; проверен профиль `qwen3:4b`, фактически `Qwen3-4B-Thinking-2507`, GGUF `Q4_K_M`, digest `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`.
- Для Ollama adapters в Python и native Rust добавлен `reasoning_effort: none`: schema-result больше не вытесняется reasoning-трассой за 30-секундный timeout. Generic OpenAI-compatible запросы не изменены.
- Structured output теперь ограничен реальными template IDs, параметрами и текущими `part_id`; intent scope не допускает нерелевантную operation branch, а ambiguity/safety принудительно остаются без исполнения. Validator и одна repair-попытка сохранены.
- Полный набор: 20 русскоязычных запросов × 3 запуска, dataset SHA-256 `9847006045d9fa713307a9bee33745b6c952e69e5ef50c2c408f072935e61e5d`. Simple-valid preview `30/36 = 83,3%` при пороге 80%; clarification `9/9`, safety `15/15`, preview non-mutation `60/60`, repair-limit `60/60`.
- Категории: build `12/15`, edit `18/21`, clarify `9/9`, refusal `9/9`, invalid `6/6`. Оставшиеся failures стабильны: `LE-03` передал неуказанный `hole_offset=0`; `LE-09` не имеет настоящего selected `edge_ref` в AI-контексте и получает geometry error.
- Latency p50 `9.523 с`, p95 `32.894 с`, max `51.668 с`; harness + CAD children peak RSS `141.85 МБ`. Отдельный post-run process-tree RSS загруженного Ollama/llama-server — `2.83 ГБ`.
- Итоговый отчёт `artifacts/live-eval/20261103T093919Z/live-ai-eval.json`, отдельная память provider `artifacts/live-eval/20261103T093919Z/provider-memory.json`; общий статус `passed`. Первый честный непройденный baseline сохранён в `artifacts/live-eval/20261103T090519Z/live-ai-eval.json`.
- Финальные impact-gates зелёные: AI 51/51 `artifacts/test-runs/20261103T095323Z/test-report.json`, Rust 13/13 `artifacts/test-runs/20261103T095401Z/test-report.json`, traceability 3/3 `artifacts/test-runs/20261103T095407Z/test-report.json`.
- Финальная ad-hoc signed `.app` пересобрана с native schema/prompt изменениями; связанный native cancellation E2E повторно пройден: `artifacts/native-e2e/20261103T095455Z/native-ai-cancel-report.json`.

## Срез M2: автоматизация Windows release evidence (2026-11-03)

- Release workflow после Windows NSIS build запускает отдельный installed-artifact gate и всегда выгружает `windows-release-evidence-*` с JSON, native performance report и логами.
- Runner выполняет silent per-user install, находит установленный `printforge.exe` через Windows uninstall registry, проверяет geometry sidecar, SHA-256 installer/binary и ожидаемое отсутствие Authenticode.
- Установленный binary выполняет тот же native control project: 7 startup runs, 3 WebView camera-orbit runs, process-tree RSS и 20 тел/100 операций; после проверки тестовая установка удаляется.
- Локальные release contracts, traceability, release version `0.3.0`, YAML и `git diff --check` валидны.
- GitHub Windows Server 2025 runner подтвердил installer/payload/cleanup и измерил cold p95 `9295.44 мс`, minimum navigation `28.19 FPS`, RSS `902676480 bytes`. Performance thresholds остаются `failed`, а не переименованы в pass; это observation, не control-machine baseline.
