# QA PrintForge 0.7.0 — подготовка

Кандидат в разработке. Полный каталог не объявляется пройденным: по согласованной политике после исходного полного прогона проверяются изменённые компоненты и их связи.

## Проверенные сценарии

- Browser + изолированный dev-shim: окружность, изменение радиуса мышью и точного размера, локальный Undo, Preview без изменения документа, Apply, повторное открытие истории и один Undo модели. Попытка изменить полностью закреплённый элемент отдельно отклонена solver в автоматическом тесте.
- Browser + изолированный dev-shim: отмена первой точки и незавершённой цепочки сохраняет ранее созданный контур; замкнутая цепочка отменяется одной операцией.
- Browser + изолированный dev-shim: линия → дуга → замкнутый контур → точный Preview → вырез на плоской грани → один Undo.
- PASS: итоговый связанный stage `artifacts/test-runs/20261109T150712Z/test-report.json`: 458 Python, 94 Node и 25 Rust tests, все команды прошли. Проверки изменённых файлов и их связей включают геометрию, AI-контракты, справку, формат, release и CI routing.
- PASS: 19/19 geometry gates у пересобранного sidecar и у sidecar внутри `.app`; отчёты `artifacts/sketch-v070/shell-sidecar.json` и `artifacts/sketch-v070/shell-bundle-sidecar.json`.
- PASS: локальный macOS ARM bundle имеет версию 0.7.0, архитектуру arm64, проходит deep/strict codesign; native WebView запустился и записал startup report. Это не полный native UI walkthrough.
- PASS: 18 real-kernel проверок оболочки для шести граней, сохранения остальных тел и отказов. Preview, изменение толщины, Undo/Redo и schema 8 save/reopen проверены через dev-shim. Browser UI: толщина 2 → 3 мм, объём 7152 → 10128 мм³, Undo → 7152 мм³.

## Остаётся проверить

- Hosted matrix macOS ARM/Intel и Windows x64, installer, updater signatures и public feed — при последующей публикации.
- BLOCKED: ручной Windows и macOS Intel UI без соответствующих физических хостов; физическая печать без принтера. Полный каталог 179 сценариев повторно не запускался.
- Windows performance: v0.6.0 на hosted runner показал 26,33 FPS при цели 30; без нового замера исправление не заявляется.
