# PrintForge

[![Release](https://img.shields.io/github/v/release/yakut-sekonts/printforge)](https://github.com/yakut-sekonts/printforge/releases/latest)
[![Tests](https://github.com/yakut-sekonts/printforge/actions/workflows/ci.yml/badge.svg)](https://github.com/yakut-sekonts/printforge/actions/workflows/ci.yml)
[![License](https://img.shields.io/github/license/yakut-sekonts/printforge)](LICENSE)

Опенсорс настольное приложение для точного 3D-моделирования деталей под 3D-печать. PrintForge объединяет параметрическое CAD-ядро, простой русскоязычный интерфейс, встроенное обучение и управляемого AI-помощника.

## Скачать

Текущий релиз: **[PrintForge v0.2.0](https://github.com/yakut-sekonts/printforge/releases/tag/v0.2.0)** · [что нового](docs/releases/v0.2.0.md).

- macOS Apple Silicon: DMG для Mac на M1/M2/M3/M4 и новее.
- macOS Intel: DMG для Mac на Intel.
- Windows x64: NSIS installer для 64-битной Windows.

Сборки распространяются без Apple notarization и Windows Authenticode. При первом запуске ОС покажет стандартное предупреждение для unsigned open-source приложений. Инструкции по установке и модель обновлений описаны в [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md).

После установки PrintForge проверяет подписанные обновления в GitHub Releases. Доступная версия появляется в приложении через колокольчик; загрузка, установка и перезапуск выполняются только после подтверждения пользователя.

## Возможности

- Параметрические детали, профили, выдавливание, отверстия, скругления, булевы операции, массивы, зеркало, выравнивание и разделение тел.
- Прямое редактирование поддерживаемых граней и рёбер: Push/Pull размеров, локальные бобышки и blind/through отверстия, сферические выпуклости/вмятины, каскад до четырёх параллельных sheet-metal изгибов с переносом through-вырезов на прямые участки, прямоугольного профиля через две bend-зоны, круглого, кольцевого профиля или паза через одну, скругления и фаски с точными параметрами и одним шагом Undo на операцию.
- Готовые шаблоны пластины, шайбы/втулки, L-кронштейна и корпуса с крышкой.
- Импорт STEP/STL и экспорт STEP/STL/3MF.
- Формат проекта `.printforge`, автосохранение, Undo/Redo и транзакционное применение операций.
- Проверка геометрии и размещения на столе принтера без ложного общего статуса «готово» для непроверенных параметров.
- Офлайн-справка, контекстный режим «Что это?» и интерактивные уроки.
- AI-помощник с локальным Ollama или OpenAI-compatible endpoint: JSON-план, точный preview и явное подтверждение до применения.

- Требования: [REQUIREMENTS.md](REQUIREMENTS.md)
- Продукт: [PRODUCT.md](PRODUCT.md) · Дизайн: [DESIGN.md](DESIGN.md) · Источники дизайна: [DESIGN_SOURCES.md](DESIGN_SOURCES.md)
- Статус и проверки: [STATUS.md](STATUS.md) · Решения: [DECISIONS.md](DECISIONS.md) · Очередь: [BACKLOG.md](BACKLOG.md)
- Поставка: [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) · Лицензия: [Apache-2.0](LICENSE)

## Стек

- Desktop: Tauri 2 и Rust; интерфейс TypeScript, React и Three.js.
- Геометрия: отдельный Python-процесс, build123d + OCP (Open CASCADE), упаковывается PyInstaller в sidecar.
- Документ: собственный формат `.printforge` (zip: manifest.json + document.json + assets/).

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

## Документация

- [PRODUCT.md](PRODUCT.md) — назначение и продуктовые границы.
- [REQUIREMENTS.md](REQUIREMENTS.md) — функциональные и технические требования.
- [STATUS.md](STATUS.md) — фактическое состояние реализации и проверок.
- [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) — сборка, публикация, установка и обновления.
- [docs/testing/TEST_STRATEGY.md](docs/testing/TEST_STRATEGY.md) — тестовая стратегия и quality gates.

## Лицензия

Исходный код PrintForge распространяется по [Apache License 2.0](LICENSE). Лицензии сторонних зависимостей сохраняются отдельно.
