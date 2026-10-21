# DESIGN_SOURCES.md — закреплённые источники дизайна PrintForge

Дата фиксации: 21 октября 2026 года.

## Источники

| Источник | URL | Закреплённый commit | Локальная копия |
|---|---|---|---|
| Impeccable | https://github.com/pbakaus/impeccable | `dad8dbb3aac21ad1fa236c110315ef4abece23e8` | `design-sources/impeccable/` |
| Taste Skill | https://github.com/Leonxlnx/taste-skill | `6010f91a9935f1c167dfc500fb1a475681892e6b` | `design-sources/taste-skill/` |

Обновление источника выполняется только явным checkout нового commit с записью причины в этом файле. `main` не используется как воспроизводимая версия.

## Прочитанные материалы (M0, 2026-10-21)

Impeccable:
- `README.md` — назначение, установка, CLI `npx impeccable detect` (61 детерминированное правило, работает без LLM).
- `skill/SKILL.src.md` — исходник навыка: режимы Persuade/Operate/Read/Experience, таблица команд (critique, audit, polish, harden, typeset, layout и др.), правила маршрутизации.
- `skill/reference/operate.md` — углублённый режим Operate (рабочие UI) и заметки Read: заработанная привычность, один шрифт, фиксированная rem-шкала, сдержанный цвет, полный набор состояний компонентов, движение только как состояние, запреты (декоративное движение, display-шрифты в UI, модалки как первая мысль и т.п.).

Taste Skill:
- `README.md` — назначение навыка, маршрут app screens (v2.1), требования скриптов (Node 22+, Chrome).
- `skills/taste-skill/SKILL.md` — общий процесс (run), house rules, законы типографики/пространства/цвета, запреты шаблонных приёмов.
- `skills/taste-skill/references/app-screens.md` — прочитан целиком: run для рабочих экранов (инвентарь данных → один вопрос экрана → выбор стиля → shell → данные → состояния → проверка), архетипы shell, правила KPI/таблиц/форм, тип и цвет, токены по умолчанию, house rules для app screens, реестр «tells» сгенерированных дашбордов.

Дополнительные материалы читаются по текущей задаче и фиксируются здесь:
- (планируется перед UI-правками M1) Impeccable `skill/reference/craft-floor.md` — обязателен перед любыми правками UI по SKILL.src.md.
- (планируется для AC-13) Impeccable `skill/reference/audit.md`, `critique.md`, `polish.md`, `harden.md`; Taste `references/critique.md`, `type.md`, `colour.md`, `layout.md`.

## Способ применения в окружении Kimi

Навыки написаны под другие агентные harness (Claude Code, Codex и др.); в Kimi Code прямой установки как skill нет. Применяем явно:

1. Процесс и правила — из прочитанных файлов, применяются вручную при проектировании и правках UI (PRODUCT.md, DESIGN.md, режимы Operate/Read, run для app screens).
2. Автоматические проверки — поддерживаемые инструменты:
   - `npx impeccable detect <target>` — детерминированный детектор анти-паттернов (без LLM, без API-ключа). Запускается с `DO_NOT_TRACK=1`.
   - `node design-sources/taste-skill/skills/taste-skill/scripts/lint.mjs --app <files>` и `inspect.mjs --app <url>` — линт и браузерный инспектор Taste для рабочих экранов (нужны Node 22+ и Chrome/Chromium).
   - `draw.mjs --app` для выбора стиля — используется как источник токенов; выбор фиксируется в DESIGN.md.
3. Эти инструменты — только средства разработки. Их runtime, скрипты и сетевые вызовы не входят в поставку приложения и не нарушают офлайн-работу справочника.

## Роль источников в PrintForge

- Impeccable — процесс проектирования и качество взаимодействия: режим **Operate** для основного CAD-окна, **Read** для справочника; playbook critique/audit/polish/harden для проверок AC-13.
- Taste Skill — выбор и проверка согласованного визуального характера рабочего экрана: маршрут **app screens / builder**, house rules для app screens, токены `library/app.json` как отправная точка.

Разногласия с требованиями владельца (точность CAD, встроенное обучение, русский язык, функциональная сетка/оси/размерные линии, нумерованные шаги уроков) решаются в пользу требований и фиксируются в DESIGN.md (раздел «Адаптации»).

## Лицензии

- Impeccable: Apache-2.0 (см. `design-sources/impeccable/LICENSE`).
- Taste Skill: MIT (см. `design-sources/taste-skill/LICENSE`).

Каталоги `design-sources/` — рабочие копии для чтения; в поставляемое приложение они не включаются. При копировании файлов в репозиторий сохранять лицензии и уведомления; целиком каталоги примеров и зависимостей не переносить.
