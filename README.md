# PrintForge

Настольное приложение для точного 3D-моделирования деталей под 3D-печать с простым русскоязычным интерфейсом и встроенным обучением.

- Требования: [REQUIREMENTS.md](REQUIREMENTS.md)
- Продукт: [PRODUCT.md](PRODUCT.md) · Дизайн: [DESIGN.md](DESIGN.md) · Источники дизайна: [DESIGN_SOURCES.md](DESIGN_SOURCES.md)
- Статус и проверки: [STATUS.md](STATUS.md) · Решения: [DECISIONS.md](DECISIONS.md) · Очередь: [BACKLOG.md](BACKLOG.md)

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

# Упаковка backend в один бинарник (sidecar)
cd backend && .venv/bin/pyinstaller --onefile --name printforge-geo \
  --collect-all build123d --collect-all OCP --collect-all OCP_modules \
  --collect-all lib3mf --clean --noconfirm worker.py

# Пробная .app (sidecar не хранится в git — сначала восстановить)
cp backend/dist/printforge-geo \
  app/src-tauri/binaries/printforge-geo-aarch64-apple-darwin
cd app && npm install && npx tauri build
# Результат: app/src-tauri/target/release/bundle/macos/PrintForge.app
```

## Платформы

Первая поддерживаемая платформа — macOS arm64 (контрольная машина: MacBook Pro M3, 8 ГБ). Windows/Linux не заявлены до фактических сборок.
