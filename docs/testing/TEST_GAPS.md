# Незакрытые проверки PrintForge

Этот список — не quarantine и не `pass`. Обязательные M0–M3 пробелы блокируют заявление о полной приёмке соответствующего этапа.

## Native и UI

- **M1–M3 / B:** нет browser component/E2E набора для пользовательских состояний, доступности, tooltip/search/«Что это?» и AI panel.
- **M1–M3 / B:** нет WebdriverIO/Tauri native E2E с настоящим WebView, IPC и sidecar. `T-E2E-01…12` не объявлены пройденными.
- **M2 / B:** нет автоматического release smoke установленного `.app`/NSIS вне source tree. Локальная macOS сборка проверялась отдельно; Windows installer ещё не запускался.
- **M1–M3 / Q/R:** visual baselines, keyboard/focus/a11y matrix и ручная оценка самостоятельности дизайна не выполнены.

## M0–M2

- F-05 неполон: отсутствуют независимо подготовленные STEP 25.4 мм, 3MF components/transforms, inverted/degenerate/non-manifold/intersection fixtures.
- F-06 неполон: нет versioned предыдущего проекта, future-version и portable imported asset fixture.
- Save/reopen identity и базовая геометрия покрыты через production shim, но crash recovery проекта, autosave и tutorial isolation не имеют сквозного native evidence.
- Help registry и девять shipped lessons проверяются структурно; прохождение уроков, сохранность несохранённой работы и offline UX требуют browser/native сценариев.

## M3 AI

- `T-AI-03`: не покрыты streaming contract, управляемый timeout и обрыв после частичного body.
- `T-AI-05/06`: нужны дополнительные schema depth/size/unknown-field, type-target, cycle/reference и unit incompatibility cases.
- `T-AI-09/11`: нет протокола help references и UI/AI semantic parity suite.
- `T-AI-10`: F-02 проходит через AI и real kernel; F-01 через AI pipeline ещё не доказана.
- `T-AI-12/14`: model/revision/hash binding покрыты; lifecycle временной геометрии, resource hashes и сохранение/экспорт при активном preview требуют native/UI evidence.
- `T-AI-13`: атомарность при geometry failure покрыта, но production error пока не указывает индекс конкретной операции.
- `T-AI-18`: проверены два плана от одной базы последовательно; controlled simultaneous barrier test отсутствует.
- `T-AI-19`: immediate replay идемпотентен; возврат исходного результата после последующих изменений документа ещё не реализован.
- `T-AI-21/22/25`: backend task/session IDs, provider/worker cancellation и controlled Cancel/commit race не реализованы.
- `T-AI-23/24`: instance guard и настоящий worker crash покрыты раздельно; late result старой worker session во время AI task не доказан.
- Rust/Tauri contract компилируется и содержит commit-boundary guards, но native E2E для этих ветвей отсутствует.
- `T-AI-27`: dataset и opt-in runner готовы; ни одна реальная модель не оценена, поэтому качество всех конфигураций `not_run`.

## Поставка и платформы

- GitHub Actions workflow создан, но в текущем локальном окружении ещё не исполнялся.
- macOS Intel и Windows x64 должны быть подтверждены release workflow на соответствующих runners.
- Gatekeeper/SmartScreen остаются ожидаемыми ограничениями unsigned open-source сборок; это не следует скрывать как успешную platform-signing проверку.

## M4

`EXT-001…EXT-012` имеют `required_from: M4` и статус `planned`. Пустых тестов или `xfail`, превращающих будущий scope в green, нет.
