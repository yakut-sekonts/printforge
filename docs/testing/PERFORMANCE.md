# Performance-проверки PrintForge

## Запуск

Контракт harness:

```bash
backend/.venv/bin/python scripts/run_test_stage.py --scope perf
```

Воспроизводимый component smoke:

```bash
backend/.venv/bin/python scripts/run_perf_smoke.py --runs 7 --triangles 200000
```

Native `.app` smoke после `npm run build:desktop --prefix app`:

```bash
backend/.venv/bin/python scripts/run_native_perf.py --startup-runs 7 --workload-runs 3 --duration-ms 3000
```

Каждый запуск создаёт `artifacts/perf/<UTC timestamp>/perf-report.json` с commit, признаком dirty working tree, OS, CPU, памятью, версиями Python/Node, размером workload, числом повторов, фактическими значениями и статусом каждого gate.

## Методика

- Geometry worker запускается отдельным production `backend/worker.py` процессом и получает JSONL-запросы. Измеряются startup-to-ping, один cold build и семь warm build в одном процессе.
- Контрольная CAD-сцена содержит 20 независимых тел и 100 детерминированных `transform`-операций, по пять на тело. После build фиксируются время, solids, triangles, размер mesh и RSS worker.
- Help search выполняет 1000 запросов через production `findHelpAnswers` по уже загруженному shipped index. I/O загрузки не входит в target loaded-index latency.
- Mesh workload формирует binary resource ровно на 200 000 треугольников и вызывает production `decodeMeshBinary` и `mapMeshPositionsForViewport` семь раз.
- Synthetic mesh smoke проверяет CPU/binary pipeline, но не создаёт Three.js scene и не измеряет WebGL rendering или navigation FPS.

## Результат 2026-11-02

Среда: Apple M3, 8 ГиБ RAM, macOS 27.0.1, arm64, Python 3.12.15, Node v26.12.0. Working tree был dirty; commit базы `1cba10d22879ae50437dcea91799f529ef80c4c8`.

- Worker startup-to-ping: `50.50 мс`.
- Cold simple build: `2821.51 мс`; включает первую загрузку CAD kernel в уже запущенном worker.
- Warm simple build: p50 `70.70 мс`, p95/max `75.19 мс`; target `<= 1000 мс` пройден.
- 20 тел/100 операций: `577.96 мс`, 20 solids, worker RSS `348 405 760 bytes`; component memory target `< 2 GiB` пройден.
- Loaded help search: p50 `1.20 мс`, p95 `1.41 мс`, max `7.57 мс`; target `<= 200 мс` пройден.
- Binary mesh 200k: `9 600 008 bytes`; decode p95 `0.25 мс`, coordinate map p95 `4.10 мс`, Node RSS `86 757 144 bytes`.

Полный отчёт: `artifacts/perf/20261102T143450Z/perf-report.json`.

## Native `.app`, 2026-11-03

- Bundle: текущая arm64 `.app`, `152 120 687 bytes`, ad-hoc signature; `codesign --verify --deep --strict` пройден.
- Process-cold frontend ready: 7 запусков, p50 `816.43 мс`, p95/max `1541.75 мс`; target `<= 8 с` пройден. OS caches намеренно не очищались и это указано в отчёте.
- Контрольная сцена: 20 тел, 100 `transform`-операций, 20 solids, 40 880 отображаемых треугольников и 40 960 вершин. Synthetic component path отдельно проверен ровно на 200 000 треугольников.
- Native navigation: 3 запуска по 3 секунды программного orbit реальной production camera; minimum/p50/max `60 FPS`; target `>= 30 FPS` пройден.
- Полный RSS main app и всех descendant processes: maximum `438 665 216 bytes`; target `< 2 GiB` пройден.

Полный native-отчёт: `artifacts/perf/20261103T073255Z/native-perf-report.json`. Все TECH-003 gates на контрольной macOS arm64 машине пройдены. Windows performance baseline остаётся отдельной платформенной проверкой и не выводится из macOS-результата.

## Windows hosted runner, 2026-11-03

- Среда: GitHub Actions Windows Server 2025, AMD64, 4 CPU, 16 GiB RAM; установленный NSIS payload, не build-tree executable.
- Installer, PE unsigned policy, uninstall registry, установленный `printforge.exe`, geometry sidecar, control scene и cleanup пройдены.
- Process-cold frontend ready: 7 запусков, p50 `899.10 мс`, p95/max `9295.44 мс`; target `<= 8 с` не пройден из-за первого запуска `9295.44 мс`.
- Native navigation: 3 запуска, minimum/p50/max `28.19/28.19/28.33 FPS`; target `>= 30 FPS` не пройден.
- Process-tree RSS: maximum `902676480 bytes`; target `< 2 GiB` пройден. Сцена: 20 тел, 100 операций, 40 880 треугольников.
- Hosted runner не объявлен закреплённой контрольной машиной. Release evidence сохраняет оба performance gate как `failed`; в режиме `record` они не блокируют installer release, но и не закрывают Windows TECH-003 baseline.

Workflow artifact: `windows-release-evidence-41633795798`. Исходный отчёт относится к commit `a681c2bcbe0d360220a18f45dc9d6efcefd6d52c`.
