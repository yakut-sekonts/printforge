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
backend/.venv/bin/python scripts/run_test_stage.py --scope perf
```

Impact mapping консервативен: изменения общих IPC/Rust transaction contracts запускают AI, CAD и Rust; test infrastructure — все связанные Python-группы; неизвестный путь — широкий Python/UI/Rust набор.

Native performance не входит в обычный deterministic CI: после сборки target bundle он запускается отдельно через `scripts/run_native_perf.py` и пишет environment/app/scene metadata, сырые samples и gates в `artifacts/perf/`. Точная методика зафиксирована в `docs/testing/PERFORMANCE.md`.

Native AI cancellation также выполняется отдельно на собранной bundle и не входит в обычный deterministic CI:

```bash
backend/.venv/bin/python scripts/run_native_ai_cancel_e2e.py --cancel-delay-ms 800
```

Runner использует настоящий WebView/Tauri IPC, production provider adapter и CAD sidecar. Loopback provider детерминированно удерживает HTTP body либо возвращает bound plan; gates требуют фактический разрыв provider socket, `geometry_cancelled`, неизменность документа, успешный следующий CAD build и валидную bundle signature. Пользовательский config и Keychain не изменяются.

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
PF_AI_MODEL_VERSION=qwen3:4b \
PF_AI_MODEL_DIGEST=<digest> \
PF_AI_QUANTIZATION=<quantization> \
backend/.venv/bin/python scripts/run_live_ai_eval.py
```

Runner сначала проверяет `/models`, затем считает раздельные gates: не менее 80% успешных preview для простых допустимых запросов и 100% для clarification, safety, отсутствия мутаций при preview и лимита в одну repair-попытку. Отчёт содержит dataset hash, commit, plan/preview outcome каждого прогона, latency percentiles и память harness с CAD worker; внешний provider process в это измерение не входит. Без реального запуска допустима только формулировка «adapter проверен, качество модели не подтверждено».

Проверенный профиль 03.11.2026: Ollama `qwen3:4b` / `Qwen3-4B-Thinking-2507`, GGUF Q4_K_M, digest `359d7dd4bcdab3d86b87d73ac27966f4dbb9f5efdfcc75d34a8764a09474fae7`. Отчёт `artifacts/live-eval/20261103T093919Z/live-ai-eval.json`: simple-valid 83,3%, остальные обязательные gates 100%. Результат относится только к этому digest и dataset SHA-256; другие модели имеют статус `not_run`.

## Зафиксированный baseline

До внедрения новой инфраструктуры 30.10.2026 выполнен полный доступный baseline: `38 passed`, help `28 статей / 32 команды`, release version `0.1.0`, UI production build и `cargo check` — успешно. Лог сохранён локально в `artifacts/test-runs/baseline/full.log`; каталог `artifacts/` не версионируется.
