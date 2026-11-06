# PrintForge

[![Release](https://img.shields.io/github/v/release/yakut-sekonts/printforge)](https://github.com/yakut-sekonts/printforge/releases/latest)
[![Tests](https://github.com/yakut-sekonts/printforge/actions/workflows/ci.yml/badge.svg)](https://github.com/yakut-sekonts/printforge/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/yakut-sekonts/printforge)](LICENSE)

Опенсорс настольное CAD-приложение для моделирования деталей под 3D-печать. Начните с простой фигуры, выберите нужную грань или ребро и задайте действие прямо в сцене. PrintForge объединяет точное CAD-ядро, русскоязычные подсказки, встроенное обучение и управляемого AI-помощника.

## Ручное проектирование — v0.5.0

- **Форма мышью**: тяните угол или сторону рамки, видя XYZ в миллиметрах. Можно набрать размер во время жеста. Двойной щелчок по размеру открывает точный ввод с Preview.
- Выберите сохранение поддерживаемых отверстий/радиусов или явное масштабирование всей геометрии. Для произвольного STEP сохранение элементов не обещается.
- Скругление/фаска мышью и точный Preview, контекстное меню выбранной области, привязки к сетке/центрам/границам, перемещение, поворот и выравнивание тел.
- Нарисуйте круг или прямоугольник непосредственно на внешней плоской грани, затем выдавите или вырежьте его. Именованные операции можно редактировать и отключать с перестроением истории.
- Отдельная **мягкая mesh-форма**: подтверждаемое преобразование BRep в плотную сетку, кисть с плавным затуханием и Undo. Это не точный CAD: STEP недоступен; общий анализ самопересечений отсутствует.

Все точные Preview отменяемые и привязаны к document instance/revision. До «Применить» документ не меняется. Ограничения и инструкции — [ручное проектирование](docs/help/articles/ruchnoe-proektirovanie.md), [форма мышью](docs/help/articles/forma-myshyu.md).

## Скачать

[Скачать последний опубликованный релиз](https://github.com/yakut-sekonts/printforge/releases/latest) · изменения этой версии: **[PrintForge v0.5.0](docs/releases/v0.5.0.md)**.

- macOS Apple Silicon: DMG для Mac на M1/M2/M3/M4 и новее.
- macOS Intel: DMG для Mac на Intel.
- Windows x64: NSIS installer для 64-битной Windows.

Сборки распространяются без Apple notarization и Windows Authenticode. При первом запуске ОС покажет стандартное предупреждение для unsigned open-source приложений. Инструкции по установке и модель обновлений описаны в [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md).

После установки PrintForge проверяет подписанные обновления в GitHub Releases. Доступная версия появляется в приложении через колокольчик; загрузка, установка и перезапуск выполняются только после подтверждения пользователя.

## Возможности

- Модель начинается с визуального выбора параллелепипеда, цилиндра или сферы. Новые формы добавляются прямо в сцене через `+ Форма`.
- Выбор грани и прямого или криволинейного ребра непосредственно в сцене; context bar объясняет, какая область выбрана и какие действия доступны.
- Ручное перемещение через XYZ-gizmo с живым смещением в миллиметрах и точным вводом. Push/Pull смещает поддерживаемые плоские BRep-грани, в том числе после операций над телом; криволинейные поверхности пока не поддерживаются.
- Multi-selection тел и явный выбор основного тела и инструмента для объединения/вычитания; разделение плоскостью создаёт отдельные выбираемые части. Скругление и фаска доступны рядом с моделью с точным вводом размеров.
- Основные действия находятся в сцене; расширенные параметры и заготовки собраны в раскрываемом Inspector. Первые уроки проходят сценарий «примитив → выбранная область → действие».
- Параметрические детали, профили, выдавливание, отверстия, скругления, булевы операции, массивы, зеркало, выравнивание и разделение тел.
- M4-контур расширенного моделирования: эскизные тела и constraint solver с residual/DOF, sweep/loft, оболочка, уклон, ребро, посадки, безопасное SVG/DXF, текстовый BRep-рельеф, настоящая резьбовая пара, калибровка зазоров и разделение со штифтами. Отдельный persistent mesh workflow поддерживает transform, repair конкретного отверстия, topology-aware decimation и experimental image heightmap preview/Apply. Произвольный constrained canvas Sketcher, редактирование криволинейных поверхностей и general self-intersection repair ещё в разработке; простой circle/rectangle face Sketcher уже доступен.
- Прямое редактирование поддерживаемых граней и рёбер: Push/Pull размеров, локальные бобышки и blind/through отверстия, сферические выпуклости/вмятины, каскад до четырёх параллельных sheet-metal изгибов и перпендикулярный изгиб выбранного фланца после базового изгиба 90°, перенос четырёх through-профилей на прямые участки и через одну перпендикулярную bend-зону, прямоугольного профиля через две параллельные bend-зоны, скругления и фаски с точными параметрами и одним шагом Undo на операцию.
- Готовые шаблоны пластины, шайбы/втулки, L-кронштейна и корпуса с крышкой.
- Импорт STEP/STL и экспорт STEP/STL/3MF. STEP открывается как новый точный документ: исходник встраивается в проект, последующие измерения и операции работают с той же геометрией.
- Формат проекта `.printforge`, автосохранение, Undo/Redo и транзакционное применение операций. Новые resize/deform и отключаемые операции требуют v0.5.0 или новее; STEP — v0.4.1, примитивы/face offset/separate split — v0.4.
- Проверка геометрии и размеров относительно рабочей области принтера. Абсолютное размещение на столе, Z≥0 и универсальный анализ толщин пока не проверяются; результаты очищаются после правки модели или профиля.
- Офлайн-справка, контекстный режим «Что это?» и интерактивные уроки.
- AI-помощник с локальным Ollama или OpenAI-compatible endpoint: отменяемый запрос с task ID, JSON-план, точный preview и явное подтверждение до применения; справочные ответы работают offline по встроенному индексу и показывают только зарегистрированные команды.

- Требования: [REQUIREMENTS.md](REQUIREMENTS.md)
- Продукт: [PRODUCT.md](PRODUCT.md) · Дизайн: [DESIGN.md](DESIGN.md) · Источники дизайна: [DESIGN_SOURCES.md](DESIGN_SOURCES.md)
- Статус и проверки: [STATUS.md](STATUS.md) · Решения: [DECISIONS.md](DECISIONS.md) · Очередь: [BACKLOG.md](BACKLOG.md)
- Поставка: [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) · Лицензия: [Apache-2.0](LICENSE)

## Стек

- Desktop: Tauri 2 и Rust; интерфейс TypeScript, React и Three.js.
- Геометрия: отдельный Python-процесс, build123d + OCP (Open CASCADE), упаковывается PyInstaller в sidecar; transport death допускает один bounded restart/retry полного snapshot, длительную операцию можно остановить из status bar.
- Документ: собственный формат `.printforge` (zip: `manifest.json` + `document.json`). Читает схемы до 6: resize/deform, выключение операций и поворот вокруг центра требуют schema 6; embedded STEP — schema 5; примитивы/face offset/separate split — schema 4; legacy — schema 3. Подробнее: [формат проекта](docs/help/articles/format-proekta.md), [IPC](app/shared/ipc.md).
- Viewport mesh: бинарный little-endian ресурс, raw Tauri `ArrayBuffer`, SHA-256 binding и typed arrays без JSON-сериализации positions/indices.

### Работа с файлами

- Импорт STEP заменяет активный документ только после успешного построения. Несохранённые изменения требуют явного решения; новый документ не наследует путь прежнего проекта. STEP до 25 MiB хранится внутри операции `step_source` вместе с SHA-256: после сохранения исходный `.step` больше не нужен для открытия `.printforge`.
- Декоративный image relief требует актуального Preview: Apply проверяет hash изображения и `settings_sha256`, связывающий путь, источник и все настройки. Изменение файла или параметров требует повторного Preview.
- Native закрытие окна и команда Quit/CmdQ защищают несохранённый основной документ, в том числе безымянный: «Сохранить и продолжить», «Не сохранять» или «Отмена». Во время вычисления закрытие блокируется. Quit из Dock/AppleEvent отдельно не проверен. Автосохранение именованного основного проекта выполняется раз в 30 секунд; учебный слот исключён. Это не аварийное восстановление безымянного проекта после сбоя.

## Разработка

Базовая среда для macOS Apple Silicon:

```bash
brew install rust node python@3.12
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
npm ci --prefix app/ui
```

Запуск browser development mode:

```bash
backend/.venv/bin/python scripts/dev_shim.py
npm run dev --prefix app/ui
```

Локальная native-сборка:

```bash
backend/.venv/bin/python scripts/build_sidecar.py
npm ci --prefix app
npm run build:desktop --prefix app
```

Target-specific sidecar не хранится в Git. Результат native-сборки находится в `app/src-tauri/target/release/bundle/`.

## Автотесты

Первый baseline выполняется полностью, последующие локальные прогоны — по impact mapping:

Срез v0.5.0: **511 уникальных automated-тестов PASS** в connected stage и точечных follow-up; отдельно 10 packaged-sidecar smoke gates, browser/native проверки. Полный каталог из 179 сценариев не объявляется пройденным повторно: границы и BLOCKED описаны в [QA-отчёте](docs/testing/QA_0.5.0.md). В release matrix packaged geometry проверяется на каждой платформе до публикации.

Windows runner: в stress-сцене 20 тел/100 операций минимум 26,0 FPS при цели 30. Это `failed/non-blocking` performance observation, не полный performance PASS; installer/payload и startup/memory gates проходят. Подробности — в release notes и QA-отчёте.

```bash
backend/.venv/bin/python scripts/run_test_stage.py --scope full
backend/.venv/bin/python scripts/run_test_stage.py --scope changed
```

Для push и PR CI определяет изменённые файлы относительно предыдущего commit или базы PR и проверяет затронутые компоненты со связанными контрактами. Полный deterministic stage выполняется по nightly-расписанию, при ручном запуске или отсутствии доступной базы сравнения. Стратегия, traceability и известные gaps: [TEST_STRATEGY.md](docs/testing/TEST_STRATEGY.md), [requirements.yaml](docs/testing/requirements.yaml), [TEST_GAPS.md](docs/testing/TEST_GAPS.md).

Воспроизводимый component performance smoke запускается отдельно и сохраняет JSON-отчёт в `artifacts/perf/`:

```bash
backend/.venv/bin/python scripts/run_test_stage.py --scope perf
backend/.venv/bin/python scripts/run_perf_smoke.py --runs 7 --triangles 200000
backend/.venv/bin/python scripts/run_native_perf.py --startup-runs 7 --workload-runs 3 --duration-ms 3000
backend/.venv/bin/python scripts/run_native_ai_cancel_e2e.py --cancel-delay-ms 800
```

Component smoke измеряет production help search, geometry worker и binary mesh decode/map. Native performance runner запускает свежую bundle-сборку отдельными процессами, открывает контрольный проект через production IPC, вращает камеру в реальном WebView/WebGL и измеряет RSS всего дерева процессов. Native cancellation runner отдельно проверяет реальный разрыв provider socket, kill CAD sidecar, отсутствие мутации и восстановление worker. Методика performance и текущие результаты описаны в [PERFORMANCE.md](docs/testing/PERFORMANCE.md).

Windows release workflow после сборки NSIS автоматически запускает `python scripts/run_windows_release_evidence.py --performance-policy record`: устанавливает пакет в silent mode, проверяет установленный `printforge.exe` и geometry sidecar, измеряет native startup/FPS/RSS и публикует отдельный `windows-release-evidence-*` artifact. Installer/payload gates блокируют выпуск; performance thresholds не переименовываются в pass и принимаются только на закреплённой контрольной среде.

Качество конкретной LLM проверяется отдельно и никогда не подменяется scripted provider: `PF_LIVE_AI_EVAL=1 ... backend/.venv/bin/python scripts/run_live_ai_eval.py`. Gate выполняет 20 фиксированных русскоязычных запросов по три раза, требует минимум 80% корректных preview для простых допустимых запросов и 100% отсутствия исполнения/мутаций для safety cases. До такого запуска профиль модели имеет статус `not_run`.

Текущий проверенный профиль: Ollama `qwen3:4b` (`Qwen3-4B-Thinking-2507`, Q4_K_M, immutable digest зафиксирован в отчёте) — simple-valid 83,3%, clarification/safety/non-mutation/repair-limit 100%. Результат не переносится на другие модели; подробности в [STATUS.md](STATUS.md) и [TEST_GAPS.md](docs/testing/TEST_GAPS.md).

## Документация

- [PRODUCT.md](PRODUCT.md) — назначение и продуктовые границы.
- [REQUIREMENTS.md](REQUIREMENTS.md) — функциональные и технические требования.
- [STATUS.md](STATUS.md) — фактическое состояние реализации и проверок.
- [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) — сборка, публикация, установка и обновления.
- [docs/testing/TEST_STRATEGY.md](docs/testing/TEST_STRATEGY.md) — тестовая стратегия и quality gates.
- [docs/testing/PERFORMANCE.md](docs/testing/PERFORMANCE.md) — методика и фактический статус TECH-003.

## Лицензия

Исходный код PrintForge распространяется по [Apache License 2.0](LICENSE). Лицензии сторонних зависимостей сохраняются отдельно.
