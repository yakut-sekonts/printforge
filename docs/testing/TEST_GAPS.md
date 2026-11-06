# Незакрытые проверки PrintForge

Этот список — не quarantine и не `pass`. Обязательные M0–M3 пробелы блокируют заявление о полной приёмке соответствующего этапа.

Актуальный срез исправлений v0.4.1 и границы реальных UI-повторов: [QA_0.4.1.md](QA_0.4.1.md). Исторические milestone gaps ниже не заменяются общим числом успешных тестов.

## Native и UI

- **M1–M3 / B:** нет browser component/E2E набора для пользовательских состояний, доступности, tooltip/search/«Что это?» и AI panel.
- **M1–M3 / B:** нет полного WebdriverIO/Tauri native E2E набора. Точечный native harness с настоящим WebView, IPC и sidecar покрывает AI cancellation, но `T-E2E-01…12` не объявлены пройденными.
- **M2 / B:** локальная macOS `.app` проверялась отдельно. Windows hosted runner подтвердил silent NSIS install, discovery через uninstall registry, installed binary/sidecar smoke, PE unsigned policy и cleanup. Native performance сохраняется тем же artifact, но является отдельной неблокирующей оценкой.
- **M2 / R:** TECH-003 пройден на свежей macOS arm64 `.app`. Windows hosted runner измерил cold p95 `9295.44 мс`, minimum navigation `28.19 FPS`, RSS `902676480 bytes` и корректную сцену; первые два targets честно остаются `failed`, поэтому Windows control-machine baseline не закрыт.
- **M1–M3 / Q/R:** visual baselines, keyboard/focus/a11y matrix и ручная оценка самостоятельности дизайна не выполнены.

## M0–M2

- F-05 неполон: отсутствуют независимо подготовленные STEP 25.4 мм, 3MF components/transforms, inverted/degenerate/non-manifold/intersection fixtures.
- F-06 неполон: нет versioned предыдущего проекта, future-version и portable imported asset fixture.
- Save/reopen identity и базовая геометрия покрыты через production shim; bounded worker recovery имеет deterministic real-process test, но induced-crash через настоящий Tauri sidecar, crash recovery проекта, autosave и tutorial isolation не имеют сквозного native evidence.
- Cancel control flow дополнительно покрыт native `.app`: отмена во время AI CAD preview реально завершает sidecar, не меняет документ и допускает следующий CAD build. Timeout длительной OCP-операции и общий late-result сценарий вне AI cancellation всё ещё требуют native E2E.
- Help registry и 13 shipped lessons проверяются структурно и lesson-engine тестами; navigation, save-export и import повторены в UI. Это не полный native/offline прогон всех уроков и всех отрицательных вариантов.

## M3 AI

- `T-AI-03`: timeout, усечённый body и превышение лимита ответа покрыты; streaming transport пока не реализован и не проверяется.
- `T-AI-05/06`: unknown-field, type-target, unit incompatibility, числовые диапазоны и лимит размера покрыты; отдельный лимит глубины JSON и cycle/reference потребуются при появлении ссылочных AI-операций.
- `T-AI-09/11`: нет протокола help references и UI/AI semantic parity suite.
- `T-AI-10`: F-01 и F-02 проходят через AI preview и real kernel; native WebView evidence остаётся в общем native/UI gap.
- `T-AI-12/14`: model/revision/hash binding покрыты; lifecycle временной геометрии, resource hashes и сохранение/экспорт при активном preview требуют native/UI evidence.
- `T-AI-13`: атомарность при geometry failure и индекс первой невалидной операции покрыты.
- `T-AI-18`: проверены два плана от одной базы последовательно; controlled simultaneous barrier test отсутствует.
- `T-AI-19`: immediate replay идемпотентен; возврат исходного результата после последующих изменений документа ещё не реализован.
- `T-AI-21/22/25`: task ID, duplicate guard и provider cancellation реализованы. Native `.app` harness подтверждает реальный разрыв HTTP-соединения, kill CAD-worker во время preview, отсутствие мутации и восстановление worker; apply остаётся отдельным явным действием после завершённого preview. Windows native evidence ещё не получен.
- `T-AI-23/24`: instance guard и настоящий worker crash покрыты раздельно; late result старой worker session во время AI task не доказан.
- Rust/Tauri contract компилируется и содержит commit-boundary guards; cancellation-ветви подтверждены точечным native `.app` harness, остальные ветви остаются в общем native/UI gap.
- `T-AI-27`: `qwen3:4b` (`Qwen3-4B-Thinking-2507`, Q4_K_M, immutable digest в отчёте) прошёл 20×3: simple-valid 83,3%, clarification/safety/non-mutation/repair-limit 100%. Другие модели остаются `not_run`. Остаточные failures: неуказанный `hole_offset=0` и отсутствие настоящего selected `edge_ref` в AI-контексте. Provider RSS измерен отдельно post-run, а не включён в harness/CAD peak.

## Поставка и платформы

- GitHub Actions workflow создан, но в текущем локальном окружении ещё не исполнялся.
- macOS Intel и Windows x64 должны быть подтверждены release workflow на соответствующих runners.
- Gatekeeper/SmartScreen остаются ожидаемыми ограничениями unsigned open-source сборок; это не следует скрывать как успешную platform-signing проверку.

## M4

- `EXT-001` частично реализован: kernel принимает произвольные области из line/arc/circle-контуров, отверстия и operation-only документы; real-kernel tests проверяют объём, ошибки открытого/самопересекающегося контура, один Undo и save/reopen. Полноценный интерактивный Sketcher и preview/cancel ещё отсутствуют.
- `EXT-002` частично реализован: numerical solver покрывает coincident/horizontal/vertical/parallel/perpendicular/tangent/equal/dimension/fix, residuals, rank/DOF, conflict и compatible redundancy, constrained drag, preview без commit и один persistent Apply. Direct canvas editing произвольных элементов ещё отсутствует.
- `EXT-003` частично реализован: revolve, круглый sweep и ruled loft проходят аналитические real-kernel oracles. UI пока предоставляет только управляемые presets; curved-path orientation, self-intersection policy и произвольное редактирование сечений не закрыты.
- `EXT-004` частично реализован: цилиндрическая оболочка, signed-уклон прямоугольной призмы и треугольное ребро имеют real-kernel oracles, проверки недопустимых размеров, Undo/Redo и save/reopen. Generic shell выбранных граней, draft выбранных граней и рёбра из произвольного эскиза ещё отсутствуют.
- `EXT-005` частично реализован: SVG physical units/viewBox/holes, DXF units policy, unsafe-content rejection и embedded source проверены real-kernel tests; кириллический рельеф/гравировка использует проверяемый JetBrains Mono 2.211 без fallback. Полная матрица entities/transforms, placement на выбранной грани и native file-dialog E2E ещё отсутствуют.
- `EXT-006` частично реализован: версионированные явные fixtures гайки M5, подшипника 608 и термовставки M3 различают radial/diametral/one-sided зазор и проходят аналитические oracles, Undo/Redo и save/reopen. Внешние размерные источники, зависимое изменение существующего корпуса и физическая печатная проверка остаются открытыми.
- `EXT-007` частично реализован: versioned `metric-60-v1` строит настоящую external/internal helical BRep-пару, поддерживает правую/левую резьбу, проверяет рабочую длину и сборочное пересечение, сохраняется одной транзакцией. Multi-start, standards catalog и физическая проверка реальным крепежом остаются открытыми.
- `EXT-008` частично реализован: базовый split сохраняет объём, rectangular fixture создаёт pins/sockets с явным radial clearance, нулевым assembly intersection и обратимым print placement; Undo/save/reopen покрыты. Произвольные выбранные тела, snap-lock и thin-wall warning UI ещё отсутствуют.
- `EXT-009` частично реализован: 2–10 геометрически разных образцов с BRep-метками, sample→clearance mapping, Undo и save/reopen создаются одной операцией; имя профиля хранится локально в ней. Управление printer/material profiles и физические результаты печати остаются открытыми.
- `EXT-010` частично реализован: embedded mesh-only history покрывает transform, закрытие конкретного boundary defect с before/after diagnostics и контрпримером, topology-aware decimation с диапазоном triangle ratio, сохранением component/Euler/bbox/volume и явно выборочной shape-error metric. General self-intersection detection/repair и ручное vertex editing остаются открытыми.
- `EXT-011` частично реализован: experimental `heightmap-luminance-v1` имеет input limits, preview без commit, hash-bound Apply, mm scale, model/seed/settings, cancel, Undo, embedded source, save/reopen и mesh export. External generative providers и отдельная perceptual 3D similarity evaluation остаются открытыми.
- `EXT-012` частично реализован: все поставленные M4-команды входят в offline help/registry, SVG/DXF и mesh/image source переносимы внутри проекта, добавлены advanced/constraint/mesh/image уроки, future schema получает явную ошибку обновления. Native walkthrough evidence и примеры всех оставшихся partial clauses остаются открытыми.
