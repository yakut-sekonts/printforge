# PrintForge

Настольное приложение для точного 3D-моделирования деталей под 3D-печать с простым русскоязычным интерфейсом и встроенным обучением.

- Требования: [REQUIREMENTS.md](REQUIREMENTS.md)
- Продукт: [PRODUCT.md](PRODUCT.md) · Дизайн: [DESIGN.md](DESIGN.md) · Источники дизайна: [DESIGN_SOURCES.md](DESIGN_SOURCES.md)
- Статус и проверки: [STATUS.md](STATUS.md) · Решения: [DECISIONS.md](DECISIONS.md) · Очередь: [BACKLOG.md](BACKLOG.md)
- Поставка: [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md) · Лицензия: [Apache-2.0](LICENSE)

## Стек

- Desktop: Tauri 2 (Rust), интерфейс TypeScript/React/Three.js (M1).
- Геометрия: отдельный Python-процесс, build123d + OCP (Open CASCADE), упаковывается PyInstaller в sidecar.
- Документ: собственный формат `.printforge` (zip: manifest.json + document.json + assets/).

## Среда разработки (macOS Apple Silicon)

```bash
brew install rust node python@3.12
python3.12 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
```

## Проверки M0 (фактически выполненные — см. STATUS.md)

```bash
# Геометрический spike: пластина AC-01, выбор грани/ребра, скругление,
# документ, экспорт STEP/STL/3MF
backend/.venv/bin/python backend/spike_m0.py

# Изоляция процесса: протокол, падение worker, восстановление
backend/.venv/bin/python -m pytest backend/test_worker.py -q

# Упаковка backend в target-specific sidecar
backend/.venv/bin/python scripts/build_sidecar.py --target aarch64-apple-darwin

# Локальная .app (sidecar не хранится в git)
cd app && npm install && npm run build:desktop
# Результат: app/src-tauri/target/release/bundle/macos/PrintForge.app
```

## Платформы

GitHub Actions собирает установщики для macOS Apple Silicon, macOS Intel и Windows x64. Обновления публикуются через GitHub Releases и устанавливаются из приложения через колокольчик. Детали и ограничения unsigned open-source distribution описаны в [docs/DISTRIBUTION.md](docs/DISTRIBUTION.md).

## Лицензия

Исходный код PrintForge распространяется по [Apache License 2.0](LICENSE). Лицензии сторонних зависимостей сохраняются отдельно.

## Автотесты

Первый прогон выполняется полностью, последующие локальные — по impact mapping:

```bash
backend/.venv/bin/python scripts/run_test_stage.py --scope full
backend/.venv/bin/python scripts/run_test_stage.py --scope changed
```

Стратегия, traceability и известные gaps: [TEST_STRATEGY.md](docs/testing/TEST_STRATEGY.md), [requirements.yaml](docs/testing/requirements.yaml), [TEST_GAPS.md](docs/testing/TEST_GAPS.md).
