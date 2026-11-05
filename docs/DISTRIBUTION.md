# Desktop-поставка PrintForge

PrintForge распространяется только через GitHub Releases репозитория `yakut-sekonts/printforge`.
Исходный код проекта лицензирован по Apache License 2.0. Сторонние зависимости сохраняют собственные лицензии.

## Поддерживаемые сборки

- macOS Apple Silicon (`aarch64`) — установщик `.dmg`.
- macOS Intel (`x86_64`) — установщик `.dmg`.
- Windows 10/11 x64 — установщик NSIS `.exe`.

Python geometry worker собирается PyInstaller нативно на каждом GitHub runner. Cross-build sidecar запрещён скриптом `scripts/build_sidecar.py`, потому что такой бинарник не соответствует архитектуре installer.

## Подпись и модель доверия

Платные Apple Developer ID и Windows Authenticode certificates не используются:

- macOS bundle получает ad-hoc signature (`APPLE_SIGNING_IDENTITY=-`), без Apple notarization;
- Windows installer не получает Authenticode signature;
- пользователи могут увидеть стандартное предупреждение Gatekeeper или SmartScreen при первом запуске загруженного приложения.

Обновления при этом всегда подписываются отдельным ключом Tauri Updater. Это бесплатная Ed25519 keypair, а не platform certificate. Отключить проверку подписи Tauri Updater нельзя.

Public key уже встроен в `app/src-tauri/tauri.conf.json`. Private key хранится вне репозитория:

```bash
~/.config/printforge/updater.key
```

Для GitHub Actions нужно один раз создать repository secret:

```bash
gh secret set TAURI_SIGNING_PRIVATE_KEY < ~/.config/printforge/updater.key
```

Текущий ключ создан без пароля, поэтому `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` не требуется. Private key нельзя коммитить, публиковать или терять: без него уже установленные версии не смогут принять будущие обновления.

## Выпуск версии

1. Установить одинаковую SemVer-версию в `app/package.json`, `app/ui/package.json`, `app/src-tauri/Cargo.toml` и `app/src-tauri/tauri.conf.json`.
2. Обновить lockfiles командами `npm install --package-lock-only` в `app` и `app/ui`, затем выполнить `cargo check` в `app/src-tauri`.
3. Проверить согласованность: `python3 scripts/check_release_version.py`.
4. Подготовить release notes `docs/releases/v<version>.md`, обновить README, создать и отправить тег той же версии, например `v0.4.0`.
5. Workflow `.github/workflows/release.yml` соберёт три native installers, updater artifacts, signatures и `latest.json` в draft GitHub Release.
6. Windows job установит собранный NSIS в silent mode, проверит установленный binary/sidecar и измерит native startup/FPS/RSS. Installer/payload проверки блокируют выпуск; performance сохраняется без изменения результата как отдельная оценка hosted runner. JSON и логи публикуются в workflow artifact `windows-release-evidence-*`.
7. После успешного завершения всех трёх native jobs workflow автоматически публикует draft с release notes из `docs/releases/v<version>.md`. Если хотя бы одна сборка или blocking-проверка не прошла, release остаётся draft. Проверить состав assets, Windows evidence и публичный `latest.json`. Только опубликованный release становится доступен установленным приложениям.

Ручной `workflow_dispatch` также создаёт draft для версии из Tauri config.

## Обновление в приложении

Приложение один раз проверяет обновления после запуска. Доступная версия отмечается badge на колокольчике в TopBar.

1. Пользователь открывает колокольчик и скачивает update artifact.
2. Tauri проверяет его подпись встроенным public key.
3. Установка запускается только отдельной кнопкой.
4. При несохранённом документе установка блокируется до сохранения.
5. На Windows installer закрывает приложение; на macOS приложение перезапускается после установки.

Endpoint обновлений фиксирован: `https://github.com/yakut-sekonts/printforge/releases/latest/download/latest.json`.

## Совместимость проектов

PrintForge v0.4 открывает проекты прежних версий. Документы без новых примитивов и операций сохраняются в schema version 3. Примитивы box/cylinder/sphere, face offset или новое разделение на отдельные части требуют schema version 4; для открытия такого проекта нужен PrintForge v0.4 или новее. Старые версии отклоняют такой документ с явным требованием обновить приложение.

## Локальная проверка release artifact

Обычная локальная сборка не требует updater private key, создаёт ad-hoc signed `.app` и должна проходить `codesign --verify --deep --strict`:

```bash
backend/.venv/bin/python scripts/build_sidecar.py --target aarch64-apple-darwin
cd app
npm run build:desktop
codesign --verify --deep --strict src-tauri/target/release/bundle/macos/PrintForge.app
```

Release-сборка с updater signature:

```bash
export TAURI_SIGNING_PRIVATE_KEY="$HOME/.config/printforge/updater.key"
export APPLE_SIGNING_IDENTITY="-"
cd app
npm run tauri build -- --bundles app,dmg --config src-tauri/tauri.release.conf.json
```

Windows release evidence запускается только на Windows x64 после сборки NSIS:

```powershell
python scripts/run_windows_release_evidence.py --performance-policy record
```

Runner устанавливает NSIS для текущего пользователя, находит `printforge.exe` через uninstall registry, проверяет наличие geometry sidecar, запускает `scripts/run_native_perf.py` для установленного приложения и затем удаляет тестовую установку. Отсутствие Authenticode проверяется напрямую по PE certificate table; SHA-256 installer и установленного binary фиксируются в отчёте. В режиме `record` performance gate сохраняет `failed`, если target не достигнут, но не подменяет отдельный benchmark на закреплённой контрольной машине.
