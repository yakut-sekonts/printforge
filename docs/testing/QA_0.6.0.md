# QA PrintForge 0.6.0

## Область

Проверяются изменённые компоненты и их связующие, не повторный FULL всего исторического каталога. В составе выпуска: выбор/видимость, provenance локальных элементов, зависимости размеров, canvas Sketcher, направленные mates, диагностика печати и native recovery. Границы продукта — [план выпуска](../INTERACTION_RELEASE_PLAN.md), [инструкция](../help/articles/predskazuemoe-modelirovanie.md).

## Automated

- PASS: итоговый связанный stage `20261106T144059Z`, **540 уникальных automated-тестов = 429 Python + 87 Node + 24 Rust**. Все 16 команд stage прошли: CAD/document/worker, deterministic AI integration, UI/selection/mesh/IPC, справка/обучение, CI routing, release contracts, traceability и Rust. Machine report — `artifacts/test-runs/20261106T144059Z/test-report.json`. После него отдельно повторены help tests и frontend build для адресных текстов подсказок.
- Новые real-kernel тесты проверяют provenance отверстия/скругления и transform/resize, отступы и равные диаметры, invalid/cyclic refs, arc solver/extrusion, вырез на локальной грани, plane/axis mates, запрет циклов/дубликатов, JSON/export без утечки OCP-объектов, абсолютные границы/толщину и schema 7/Preview/Undo/Redo/save/reopen через production shim.
- Node: infer/snap/arc geometry/контуры и отверстия, локальные изменения без мутации источника, bounded проверенный подбор размера, cycling перекрытий и скрытие без изменения mesh indices. Новый урок проверяется отдельной реальной последовательностью событий движка.
- Rust: версия формата и запись безымянного recovery snapshot без присвоения пути документу; валидация имён recovery, старые atomicity/close/identity contracts.
- Packaged sidecar: **17 blocking gates** на текущем macOS ARM binary, включая новые зависимости, arc Sketcher, mate, отказы и thin-wall markers. Перед публикацией те же gates обязательны для каждой платформы release matrix. Это проверка executable/protocol, не native UI.

## Browser smoke — изолированная среда

Frontend на 5175 и отдельный dev-shim на 8788; пользовательский dev-сервер и его документ не заменяются.

- PASS: примитив → выбор верхней грани → окружность мышью → ограничение радиуса 5 мм → точный Preview → вырез глубиной 5 мм. До Apply revision остаётся прежней; после Apply объём 23607,3 мм³ соответствует `24000 − π × 5² × 5`.
- PASS: один Undo возвращает 24000 мм³, Redo — 23607,3 мм³; отдельная операция эскиза присутствует в истории.
- PASS: скрытие/возврат тела не изменяет revision 4 и объём документа.
- PASS: проверка печати показывает отдельные результаты absolute placement и Z=0, а отсутствие найденных тонких мест — unknown с объяснением выборочного метода.
- Исправлены выявленные при walkthrough ошибки: StrictMode lifecycle игнорировал ответы solver; выход из эскиза до завершения solver мог терять неподтверждённую правку; конкурирующие панели выбора перекрывали рабочую область.

## macOS native

- PASS: собранная `.app` запускает bundled worker без dev-shim, создаёт BRep 40×30×20 и показывает новый Sketcher/selection controls.
- PASS: безымянный изменённый main-проект получил отдельный recovery ZIP. Аварийное завершение только QA-процесса, повторный запуск и «Восстановить» вернули BRep 40×30×20 в грязный безымянный документ; оригинальный путь отсутствует. Копия прежней сессии заменяется новой только после успешного checkpoint.
- PASS: восстановленный QA-проект сохранён отдельно; итоговый файл — `/private/tmp/printforge-060-recovery-smoke.printforge`. Проверено, что временный путь заготовки был новым файлом, не перезаписью существующего пользовательского проекта. Выявленное автоматическое первое Save исправлено: финальная версия запрашивает системный диалог.
- PASS на финальном bundle: первое Save открывает системный диалог; Cancel оставляет документ безымянным и грязным, с неизменной revision. Подтверждённое сохранение записывает `/private/tmp/printforge-060-native-final.printforge`; обычное повторное Save использует этот путь. `codesign --verify --deep --strict` проходит.

## BLOCKED / вне заявленной проверки

- BLOCKED: интерактивный Windows UI walkthrough и SmartScreen на физическом ПК — в текущей сессии доступен только macOS host. Hosted installer/payload, geometry gates и измерения FPS/RSS выполняются release workflow и не выдаются за ручной UI-проход.
- BLOCKED: ручной macOS Intel UI walkthrough — нет Intel host. Intel executable/protocol проверяется hosted release job.
- BLOCKED: физическая печать образцов, точность посадок и универсальная минимальная толщина — нет физического принтера/образцов; выборочная диагностика не заменяет эти проверки.
- NOT_RUN: повторный полный каталог 179 сценариев, общий a11y/visual baseline и live LLM quality eval. Не объявляются пройденными по результатам unit tests; не затронутый AI provider/model не переоценивается.
- Известные границы: нет universal assembly solver/topological naming/general self-intersection repair; неполный каталог sketch constraints для дуг. Эти ограничения не маскируются статусом PASS.

## Поставка

До публикации: согласованная версия 0.6.0, исходный код и tests, актуальная offline-справка, macOS ARM/Intel + Windows x64 matrix, 17 packaged gates на каждой платформе, подписанный updater feed. Ключ updater и policy отсутствия Apple notarization/Windows Authenticode не меняются. Историческое Windows v0.5.0 наблюдение 26 FPS при цели 30 не объявляется исправленным без нового evidence.
