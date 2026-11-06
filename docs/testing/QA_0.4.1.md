# QA-срез v0.4.1

Проверки исправлений выполнены 2026-11-05 на базе commit `5ea60a8a4e7da5fc572ab37a2a0289b43f5e8775`. Версия релиза подготовлена 2026-11-06. Это публичное резюме без локальных путей, секретов и raw UI-данных.

## Область и результат

- Исходный FULL-каталог: 179 сценариев, 125 PASS, 34 FAIL, 19 BLOCKED и один необязательный NOT_RUN. Дополнительные находки учитывались отдельно.
- Исправления реализованы для 36 подтверждённых записей; связанные записи могут описывать одну первопричину. Ещё одна запись PARAM-03 снята как reporting ERRATUM: исходный native AX уже содержал пустое поле и сообщение «Выражение обрывается».
- Для 26 записей повторено описанное дефектное действие в UI; 10 имеют automated evidence без полного повторения соответствующего UI-сценария. Это не переклассификация всего FULL-каталога.
- Финальный connected stage: **425 уникальных PASS** — 353 Python (CAD/document/worker 256, AI 60, CI routing 21, help 5, release 8, traceability 3), 50 Node и 22 Rust.
- Группы повторных прогонов заменяют предыдущие, а не суммируются. Packaged smoke/build gates и ручные сценарии не добавлены к числу automated-тестов.
- Typecheck, production UI build, help integrity и release-version checks проходят. Справка содержит 35 статей и 62 команды.

## Отдельные подтверждения

- В UI выполнены четыре изгиба X −30/−10/+10/+30, 45°, R1, с чередованием +Z/−Z. Независимый OCP-reader подтвердил один valid solid, V18898.40710525495 мм³ и Zspan34.52768 мм.
- Native STEP 10×20×30 мм согласован между измерением, embedded source, экспортом и открытием после полного перезапуска: V6000 мм³, один valid solid.
- Проверены invalid-open с сохранением прежней модели, window close/Cancel/Save, исправленный CmdQ и сохранённый файл перед выходом.
- Browser-повторы покрывают formulas/drafts/defaults/reopen, input Undo, реальные What-gizmo действия, print invalidation, неверные размеры принтера, relief Preview binding, Escape, смену измеряемой грани и справочник 900×700.
- Реально завершены уроки navigation, save-export и import; неправильная фигура не выполняет first-part, skip/checkpoint проверены отдельно. Все 13 последовательностей и отрицательные gates покрыты lesson-engine тестами, но не объявлены повторно пройденными в UI.
- Коллизия изменяемого mesh resource сначала воспроизведена шестью failing-тестами; после исправления те же шесть проходят. В browser видимая четырёхсгибная модель восстанавливается после Preview/Cancel и tutorial/main без console errors.
- Новый packaged sidecar: 12/12 smoke PASS. Native HTTP disconnect, CAD cancellation/recovery и bundle signature: 3/3 gates PASS. Финальная локальная macOS-сборка проверена отдельно; этот результат не переносится на Windows или Intel автоматически.

## Непроверенные варианты

19 исходных BLOCKED сохраняют конкретные границы:

- UX-04/10/13/19/20: right-button drag, pointercancel/capture/hover-only и управляемая перестановка поздних IPC-ответов требуют соответствующего UI API или delay/reorder barrier.
- CAD-31: точный обязательный negative bend-вариант целиком не повторён; успешный CAD-30 и kernel tests его не заменяют.
- IO-04: самостоятельная INCH STEP fixture не переизмерена в native UI после исправления импорта.
- HELP-01/06/07: отключение внешней сети/недоступный индекс и точный hover→tooltip→link timing не проверены через реальную pointer-only последовательность.
- AI-04/06/07: требуются установленная Ollama и изолированный native Keychain-профиль; пользовательские secrets не затрагивались.
- AI-22/24/25: bounded cancellation smoke не заменяет полный late-response/crash/two-plans concurrent barrier.
- UPD-02/03/04: требуется изолированный feed с timeout/error/invalid-signature/known-length вариантами и полный install/relaunch. Обычная публикация подписанных artifacts не доказывает эти негативные сценарии.

Необязательный live AI-13 остаётся NOT_RUN. Windows release workflow выполняет собственные installer/payload gates и отдельно записывает hosted performance; это не полная ручная Windows-приёмка. Dock/AppleEvent Quit, crash recovery безымянного документа и session-cache GC не объявляются реализованными или подтверждёнными этим QA-срезом.
