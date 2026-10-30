# Стратегия автотестов PrintForge

## Источник и честность статусов

- Основа: `PrintForge_Codex_Autotest_Requirements.md` v1.0 от 30.10.2026, SHA-256 `c1485d569f6b32e25f21b0593f65c21eb4c122f77300ef3af7bde8be43fed09a`.
- `docs/testing/requirements.yaml` содержит все 85 ID из `REQUIREMENTS.md` и `EXT-001…EXT-012`.
- Статический manifest не объявляет локальный запуск доказательством: `last_run_status` остаётся `not_run`. Фактические результаты и команды записываются в `artifacts/test-runs/<run>/test-report.json`, JUnit и logs.
- `scripts/check_test_manifest.py` проверяет структуру. `--strict-stage` дополнительно падает на любом неполном обязательном требовании M0–M3; это release-readiness gate, а не обычная проверка целостности.

## Уровни

- `unit/contract`: schema, provider settings, semantic validation, registry/help, release config и traceability.
- `contract-loopback-http`: настоящий HTTP adapter против локального сервера; внешняя сеть и LLM не используются.
- `integration-real-kernel`: production `dev_shim`/worker, build123d/OCP, реальные BRep/mesh/export и документные транзакции.
- `integration-real-process`: настоящий дочерний worker, включая принудительное завершение и восстановление.
- `browser mock-transport`, `native-e2e`, `release-smoke`, visual/a11y, performance и live LLM eval не смешиваются с уровнями выше. Их текущий статус указан в `TEST_GAPS.md` и generated report.

## Политика запусков

Первый baseline выполняется полностью. После него локально запускаются только изменённые компоненты и их связующие контракты. Полный прогон остаётся для PR, nightly и release gate.

```bash
# Первый baseline / повтор полной deterministic матрицы
backend/.venv/bin/python scripts/run_test_stage.py --scope full

# Автовыбор по git diff и untracked paths
backend/.venv/bin/python scripts/run_test_stage.py --scope changed

# Явный impact-анализ конкретных файлов
backend/.venv/bin/python scripts/run_test_stage.py --scope changed --paths \
  scripts/ai_planner.py scripts/dev_shim.py app/src-tauri/src/ai.rs

# Компонентные контуры
backend/.venv/bin/python scripts/run_test_stage.py --scope ai
backend/.venv/bin/python scripts/run_test_stage.py --scope cad
backend/.venv/bin/python scripts/run_test_stage.py --scope help
backend/.venv/bin/python scripts/run_test_stage.py --scope release
backend/.venv/bin/python scripts/run_test_stage.py --scope traceability
```

Impact mapping консервативен: изменения общих IPC/Rust transaction contracts запускают AI, CAD и Rust; test infrastructure — все связанные Python-группы; неизвестный путь — широкий Python/UI/Rust набор.

## Fixtures и изоляция

- `tests/fixtures/manifest.json` фиксирует происхождение, формулы и допуски F-01…F-06.
- F-01…F-04 имеют независимые аналитические ожидания. F-05 содержит вручную подготовленные STL, не созданные экспортёром PrintForge.
- Каждый AI integration test создаёт новый документ и завершает worker. Provider tests используют только loopback server.
- `PYTHONHASHSEED=0` задаётся runner. Внешние LLM запрещены в обычном CI.

## Live eval

Live eval отделён от deterministic CI. Он выполняет 20 русскоязычных запросов по 3 раза и пишет отдельный JSON:

```bash
PF_LIVE_AI_EVAL=1 \
PF_AI_PROVIDER=ollama \
PF_AI_BASE=http://127.0.0.1:11434/v1 \
PF_AI_MODEL=qwen3:4b \
backend/.venv/bin/python scripts/run_live_ai_eval.py
```

Без этого запуска допустима только формулировка «adapter проверен, качество модели не подтверждено».

## Зафиксированный baseline

До внедрения новой инфраструктуры 30.10.2026 выполнен полный доступный baseline: `38 passed`, help `28 статей / 32 команды`, release version `0.1.0`, UI production build и `cargo check` — успешно. Лог сохранён локально в `artifacts/test-runs/baseline/full.log`; каталог `artifacts/` не версионируется.
