# BACKLOG.md — очередь задач PrintForge

## M6 — предсказуемое моделирование v0.6.0
- [x] Preselection label, Alt-cycle поверхностей, скрытие/возврат без изменения документа
- [x] Однозначный provenance и локальные ручки поддерживаемых элементов
- [x] Отступы центра профиля от min/max края габарита и зависимые равные диаметры
- [x] Canvas: линии/трёхточечные дуги/окружности, замкнутые контуры и отверстия, точки, ограниченный каталог constraints, DOF/conflicts и повторное редактирование
- [x] Направленные plane/axis mates с зазором, отдельными телами и запретом циклов
- [x] Проверенные меньшие размеры fillet/chamfer, абсолютное размещение и выборочные thin-wall markers
- [x] Native recovery безымянного main-документа и безопасное первое Save
- [x] Schema 7, offline-справка и новый урок; 17 packaged geometry gates
- [x] Итоговый stage (540 PASS), финальный macOS native smoke и crash recovery
- [x] Публикация полной платформенной matrix и проверка public updater assets

## M0 — техническая реализуемость (текущий)
- [x] Прочитать требования и закреплённые источники дизайна
- [ ] Окружение: python3.12 + build123d/OCP, node, rust — зафиксировать версии
- [ ] Spike: тело, вычитание отверстий, скругление, пересчёт размера (объёмы по AC-01)
- [ ] Spike: tessellation, выбор грани и ребра BRep, скругление выбранного ребра
- [ ] Минимальный документ (.printforge) и повторное построение из него
- [ ] Технический экспорт STEP/STL/3MF и чтение результата
- [ ] Геометрический worker как отдельный процесс (JSON-stdio), обработка падения
- [x] Tauri desktop bundle с упакованным backend (PyInstaller sidecar), запуск вне dev-окружения
- [ ] ADR-001: стек; lockfiles; STATUS.md

## M1 — первый пользовательский сценарий (AC-01)
- [ ] UI: сцена Three.js, панель параметров, список деталей, строка состояния
- [ ] Сценарий: пластина 80×40×6, 4 отверстия Ø4 с отступом 10, длина 100, Undo, сохранение, открытие, STL
- [ ] PRODUCT.md/DESIGN.md — дизайн-система (перед большим UI; craft-floor.md прочитать перед правками)
- [ ] Справка: реестр команд, help_id, статьи для всех поставленных действий, поиск с синонимами
- [ ] Подсказки: 3 режима, сохранение выбора; «?» и меню Помощь; «Что это?»
- [ ] Уроки 1–3 (навигация; первая деталь; сохранение/проверка/экспорт) на учебной модели
- [ ] AC-13 первый раунд на реальном сценарии (impeccable detect, taste lint/inspect --app, скриншоты)
- [ ] Части AC-06/AC-07/AC-08, относящиеся к M1

## M2 — ручной CAD v0.1 (в работе)
- [x] Первый vertical slice direct editing: выбор внешней плоской грани, Push/Pull preview, точный размер, один commit/Undo
- [x] Профили и выдавливание (4 профиля, сквозной вырез), круговой массив, выравнивание, измерения BRep (pytest 21/21)
- [x] Диагностика импортированной сетки (AC-09)
- [x] Worker: шаблоны пластина/шайба/кронштейн/корпус+крышка (AC-01…AC-04 числа)
- [x] Скругление с мягкой ссылкой на ребро и честной ошибкой fillet_failed
- [x] Экспорт STL/STEP/3MF, импорт STEP/STL (unit_scale), print_check — pytest 13/13
- [x] Справка: 22 статьи, уроки 4–8 в lessons.json
- [x] Rust: обобщённый документ, откат фаски, диалоги, автосохранение 30 с
- [x] UI M2: шаблоны, фаска, булевы, профили, массивы, зеркало, выравнивание, разделение, измерения, импорт/экспорт, проверка печати
- [x] Уроки 4–8 в движке; уроки 2, 5, 6, 7, 8 пройдены в реальном UI
- [x] AC-01…AC-05 (числа), AC-06/07/08 (ядро), AC-09 (mesh diagnostics), AC-13 (инспекторы чисты)
- [x] Бинарный mesh-канал для крупных сеток: raw Tauri `ArrayBuffer`, zero-copy typed arrays, SHA-256/stale guard, строгая проверка layout
- [x] Bounded recovery geometry worker: один автоматический restart/retry полного snapshot после transport death, без retry управляемых CAD-ошибок
- [x] Длительные CAD-операции: elapsed status, ручная отмена с kill worker, timeout 120 с для CAD и 300 с для import/export, без retry после cancel/timeout
- [x] Воспроизводимые perf-замеры TECH-003
  - [x] Component harness: loaded help search, warm CAD build, 20 тел/100 операций, binary decode/map 200 тыс. треугольников
  - [x] Native `.app`: cold ready, WebView/WebGL navigation FPS и полный desktop RSS на текущей signed сборке
- [x] Direct editing v2: локальные выдавливания, отверстия, скругления/фаски по выбору в сцене, изгибы и выпуклости
  - [x] Локальная бобышка и blind/through вырез по выбранной внешней плоской грани; 4 профиля, U/V, preview, один Undo
  - [x] Скругления/фаски непосредственным выбором прямого ребра в сцене; криволинейные рёбра доступны через точный список, каждая операция — один Undo
  - [x] Сферическая выпуклость/вмятина на выбранной плоской грани; точные диаметр/высота/U/V, preview, один Undo
  - [x] Управляемый sheet-metal изгиб пластины: X/Y, позиция, 5–170°, внутренний радиус, сторона/направление, preview, сохранение объёма и отверстий вне зоны изгиба
  - [x] Два последовательных параллельных изгиба одной развёртки: непересекающиеся bend-зоны, общий preview, сохранение отверстий и отдельный Undo для каждой линии
  - [x] Перенос пользовательских through-вырезов (окружность, прямоугольник, кольцо, паз) на итоговые прямые участки, если профиль целиком вне bend-зон
  - [x] Точный прямоугольный through-вырез через одну или две криволинейные bend-зоны как brake-formed BRep strip
  - [x] Каскад до четырёх параллельных изгибов: неподвижный край или центральный участок, независимые углы/направления и отдельный Undo каждой линии
  - [x] Круглый through-вырез через одну криволинейную bend-зону: 64 station-сечения, ruled BRep loft и нормализация площади/объёма
  - [x] Паз through через одну криволинейную bend-зону: capsule-профиль вдоль/поперёк оси, 64 station-сечения и нормализация площади/объёма
  - [x] Кольцевой through-вырез через одну криволинейную bend-зону: согласованные outer/inner loft, точная площадь и сохранение центрального solid
  - [x] Первый slice перпендикулярного изгиба фланца: один базовый изгиб 90°, выбор внешней грани, локальный preview, точный BRep, штатные отверстия, четыре through-профиля и отдельный Undo
- [ ] Уроки 1, 3, 4 — прогнать при случае; AC-12 полный обход реестра в .app

## M3 — AI v0.2 (в работе)
- [x] Провайдеры AI: disabled / локальный Ollama / OpenAI-совместимый endpoint; настройки, `/models` smoke, disclosure данных, Keychain
- [x] AI через CommandService: план по JSON Schema, preview, одна транзакция, Undo; панель и AC-10 smoke пройдены в browser UI
- [x] Desktop distribution: DMG macOS arm64/x64, NSIS Windows x64, GitHub Releases, signed Tauri Updater и колокольчик
- [x] Справочные ответы AI по встроенному справочнику: offline retrieval, точные фрагменты и только команды из registry
- [x] AC-10 и детерминированная часть AC-11: F-01/F-02 через AI preview + real kernel, редактирование, один Undo, negative/schema/stale/timeout/partial-body/atomicity
- [x] AC-11 task ID и provider cancellation: native `reqwest` future прерывается, dev-shim блокирует late preview, отменённый план не меняет документ
- [x] Native E2E cancellation во время HTTP/CAD preview: реальный WebView/Tauri IPC, разрыв provider socket, kill CAD sidecar, отсутствие мутации и восстановление worker
- [x] Quality gate реальной модели: `qwen3:4b` Q4_K_M, 20 запросов × 3 прогона; simple-valid 83,3%, остальные обязательные gates 100%

## M5 — interaction-first CAD v0.4 (реализован)
- [x] Новый старт: визуальный выбор BRep-примитива `box`, `cylinder` или `sphere`; готовые заготовки оставлены вторичным путём
- [x] Context bar над сценой: выбранная область, доступные действия и следующий понятный шаг
- [x] Выбор тела по `solid_index` кликом по его грани в многодетальном документе
- [x] XYZ-gizmo перемещения тела: drag, живое смещение в миллиметрах, одна операция `transform` и один Undo
- [x] Добавление второго примитива прямо из viewport через `+ Форма`
- [x] Context actions для `union`, `subtract`, `split`, `fillet` и `chamfer`
- [x] Push/Pull граней примитива `box` и высоты `cylinder`
- [x] Единый hit-testing тела, грани и прямого/криволинейного ребра без предварительного включения edge mode
- [x] On-canvas точный ввод для transform, Push/Pull, fillet/chamfer и split plane с preview плоскости
- [x] Generic planar face offset, включая внутренние и наклонные плоские грани после операций
- [x] Multi-selection тел в viewport и списке деталей, явный выбор target/tool для boolean operations
- [x] Перенести длинные parameter/preset формы в вторичный раскрываемый Inspector
- [x] Переписать первые уроки под сценарий «примитив → выбор области → контекстное действие»
- [x] Независимые части после split без потери solids; точные мировые координаты XY/XZ/YZ
- [x] Атомарные face offset и separate split: failed edit после Undo сохраняет Redo и сохранённый документ
- [x] Schema 4 для примитивов и новых операций; legacy-проекты остаются schema 3

## M4 — P2 v1.0
- [ ] EXT-001 — произвольный эскиз
  - [x] Kernel: line/arc/circle-контуры, несколько областей, внутренние отверстия, выдавливание и явные ошибки невалидного контура
  - [x] Operation-only документ: один commit/Undo, сохранение и повторное открытие
  - [ ] Полноценный интерактивный Sketcher, preview/cancel и прямое редактирование элементов
- [ ] EXT-002 — геометрические ограничения и решатель
  - [x] Численный solver: coincident/horizontal/vertical/parallel/perpendicular/tangent/equal/dimension/fix, residuals и rank/DOF
  - [x] Conflict vs compatible redundancy, constrained drag, preview без commit, Apply/Undo/Redo/save/reopen
  - [ ] Direct canvas editing произвольных sketch elements
- [ ] EXT-003 — revolve, sweep и loft
  - [x] Kernel и IPC: revolve, circular sweep по polyline, ruled/smooth loft
  - [x] Аналитические volume-oracles и управляемые UI presets
  - [ ] Curved-path orientation, self-intersection policy и произвольный редактор сечений
- [ ] EXT-004 — оболочки, уклоны и рёбра
  - [x] Цилиндрическая оболочка, signed-уклон прямоугольной призмы и треугольное ребро с аналитическими oracles
  - [x] IPC/UI presets, отдельные транзакции, Undo/Redo и save/reopen
  - [ ] Generic shell/draft выбранных граней и рёбра из произвольного эскиза
- [ ] EXT-005 — SVG/DXF, текст и рельеф
  - [x] SVG physical units/viewBox/holes и запрет executable/external/entity content
  - [x] DXF explicit units и обязательный явный масштаб для unitless-файла; source встраивается в проект
  - [x] Кириллица, внутренний контур, выпуклый/вырезанный BRep фиксированным JetBrains Mono 2.211 без fallback
  - [ ] Полная entity/transform fixture-матрица, placement на выбранной грани и native file-dialog E2E
- [ ] EXT-006 — параметрические посадки
  - [x] Версионированные fixtures гайки M5, подшипника 608 и термовставки M3 с явными номиналами
  - [x] Раздельная геометрия radial/diametral/one-sided зазора, IPC/UI и document persistence
  - [ ] Внешние размерные источники, посадка на выбранном существующем корпусе и физические print-fixtures
- [ ] EXT-007 — настоящая резьба
  - [x] Однозаходная `metric-60-v1` external/internal helical BRep-пара, right/left hand и диаметральный зазор
  - [x] Проверка сборочного пересечения, отдельные тела, Undo/Redo и save/reopen
  - [ ] Multi-start, standards catalog и физическая fixture с настоящим крепежом
- [ ] EXT-008 — части, штифты и замки
  - [x] Split volume preservation и rectangular pins/sockets с явным radial clearance
  - [x] Assembly non-intersection, обратимый print placement, Undo и save/reopen
  - [ ] Соединители на произвольных выбранных частях, snap-lock и thin-wall warning UI
- [ ] EXT-009 — калибровка зазоров и профили
  - [x] 2–10 отдельных образцов, геометрически разные отверстия и BRep-метки sample→value
  - [x] Локальное имя профиля, одна транзакция, Undo и save/reopen без скрытого изменения старых проектов
  - [ ] Управление printer/material profiles и ввод результатов физической печати
- [ ] EXT-010 — mesh-ремонт и decimation
  - [x] Embedded source, mesh-only history, transform, поддерживаемое закрытие отверстия и before/after diagnostics
  - [x] Topology-aware decimation с диапазоном, component/Euler/bbox/volume gates и sampled shape error
  - [ ] Надёжная диагностика/ремонт self-intersection и произвольное ручное редактирование вершин
- [ ] EXT-011 — экспериментальная декоративная генерация по изображению
  - [x] Локальный `heightmap-luminance-v1`: input limits, preview, hash-bound Apply, model/seed/settings и mm scale
  - [x] Cancel без commit, Undo, embedded source, save/reopen и STL/3MF export как mesh-only документ
  - [ ] Внешние generative providers и отдельная perceptual 3D similarity evaluation
- [ ] EXT-012 — полная справка, примеры, уроки и переносимость формата для EXT-групп
  - [x] Offline help/registry для поставленных M4-команд, embedded vector source и явная future-version ошибка
  - [x] Урок «Расширенные тела M4» в изолированном tutorial document
  - [x] Отдельные уроки constraint solver, mesh repair и image relief
  - [ ] Native walkthrough evidence и примеры всех оставшихся partial clauses
