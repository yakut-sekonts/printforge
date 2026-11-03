# PrintForge

[![Release](https://img.shields.io/github/v/release/yakut-sekonts/printforge)](https://github.com/yakut-sekonts/printforge/releases/latest)
[![Tests](https://github.com/yakut-sekonts/printforge/actions/workflows/ci.yml/badge.svg)](https://github.com/yakut-sekonts/printforge/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/yakut-sekonts/printforge)](LICENSE)

Опенсорс настольное приложение для точного 3D-моделирования деталей под 3D-печать. PrintForge объединяет параметрическое CAD-ядро, простой русскоязычный интерфейс, встроенное обучение и управляемого AI-помощника.

## Скачать

Текущий релиз: **[PrintForge v0.3.0](https://github.com/yakut-sekonts/printforge/releases/tag/v0.3.0)** · [что нового](docs/releases/v0.3.0.md).

- macOS Apple Silicon: DMG для Mac на M1/M2/M3/M4 и новее.
- macOS Intel: DMG для Mac на Intel.
- Windows x64: NSIS installer для 64-битной Windows.

Сборки распространяются без Apple notarization и Windows Authenticode. При первом запуске ОС покажет стандартное предупреждение для unsigned open-source приложений. Инструкции по установке и модель обновлений описаны в [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md).

После установки PrintForge проверяет подписанные обновления в GitHub Releases. Доступная версия появляется в приложении через колокольчик; загрузка, установка и перезапуск выполняются только после подтверждения пользователя.

## Возможности

- Параметрические детали, профили, выдавливание, отверстия, скругления, булевы операции, массивы, зеркало, выравнивание и разделение тел.
- M4-контур расширенного моделирования: эскизные тела и constraint solver с residual/DOF, sweep/loft, оболочка, уклон, ребро, посадки, безопасное SVG/DXF, текстовый BRep-рельеф, настоящая резьбовая пара, калибровка зазоров и разделение со штифтами. Отдельный persistent mesh workflow поддерживает transform, repair конкретного отверстия, topology-aware decimation и experimental image heightmap preview/Apply. Direct canvas Sketcher, generic face tools и general self-intersection repair ещё в разработке.
- Прямое редактирование поддерживаемых граней и рёбер: Push/Pull размеров, локальные бобышки и blind/through отверстия, сферические выпуклости/вмятины, каскад до четырёх параллельных sheet-metal изгибов и перпендикулярный изгиб выбранного фланца после базового изгиба 90°, перенос четырёх through-профилей на прямые участки и через одну перпендикулярную bend-зону, прямоугольного профиля через две параллельные bend-зоны, скругления и фаски с точными параметрами и одним шагом Undo на операцию.
- Готовые шаблоны пластины, шайбы/втулки, L-кронштейна и корпуса с крышкой.
- Импорт STEP/STL и экспорт STEP/STL/3MF.
- Формат проекта `.printforge`, автосохранение, Undo/Redo и транзакционное применение операций.
- Проверка геометрии и размещения на столе принтера без ложного общего статуса «готово» для непроверенных параметров.
- Офлайн-справка, контекстный режим «Что это?» и интерактивные уроки.
- AI-помощник с локальным Ollama или OpenAI-compatible endpoint: отменяемый запрос с task ID, JSON-план, точный preview и явное подтверждение до применения; справочные ответы работают offline по встроенному индексу и показывают только зарегистрированные команды.

- Требования: [REQUIREMENTS.md](REQUIREMENTS.md)
- Продукт: [PRODUCT.md](PRODUCT.md) · Дизайн: [DESIGN.md](DESIGN.md) · Источники дизайна: [DESIGN_SOURCES.md](DESIGN_SOURCES.md)
- Статус и проверки: [STATUS.md](STATUS.md) · Решения: [DECISIONS.md](DECISIONS.md) · Очередь: [BACKLOG.md](BACKLOG.md)
- Поставка: [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) · Лицензия: [Apache-2.0](LICENSE)

## Стек

- Desktop: Tauri 2 и Rust; интерфейс TypeScript, React и Three.js.
- Геометрия: отдельный Python-процесс, build123d + OCP (Open CASCADE), упаковывается PyInstaller в sidecar; transport death допускает один bounded restart/retry полного snapshot, длительную операцию можно остановить из status bar.
- Документ: собственный формат `.printforge` (zip: manifest.json + document.json + assets/).
- Viewport mesh: бинарный little-endian ресурс, raw Tauri `ArrayBuffer`, SHA-256 binding и typed arrays без JSON-сериализации positions/indices.

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

```bash
backend/.venv/bin/python scripts/run_test_stage.py --scope full
backend/.venv/bin/python scripts/run_test_stage.py --scope changed
```

CI выполняет полный детерминированный stage: Python integration tests, TypeScript/Vite build, Rust tests, help integrity, traceability и release version checks. Стратегия, traceability и известные gaps: [TEST_STRATEGY.md](docs/testing/TEST_STRATEGY.md), [requirements.yaml](docs/testing/requirements.yaml), [TEST_GAPS.md](docs/testing/TEST_GAPS.md).

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
