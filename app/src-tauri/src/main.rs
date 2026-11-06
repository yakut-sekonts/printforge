// PrintForge M2: ядро приложения.
// Документ (шаблон, параметры, операции, история) — authoritative в этом
// процессе; геометрия — отдельный worker-процесс (JSON Lines stdio).
mod ai;

use base64::{engine::general_purpose::STANDARD as BASE64_STANDARD, Engine as _};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap};
use std::io::{Read as _, Write as _};
use std::path::PathBuf;
use std::sync::Mutex as StdMutex;
use std::time::Duration;
use tauri::async_runtime::Receiver;
use tauri::{Emitter, Manager};
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::{watch, Mutex};

const SCHEMA_VERSION: u32 = 6;
const APP_VERSION: &str = env!("CARGO_PKG_VERSION");
const QUIT_MENU_ID: &str = "printforge.quit";

fn application_menu(app: &tauri::AppHandle) -> tauri::Result<tauri::menu::Menu<tauri::Wry>> {
    use tauri::menu::{AboutMetadata, Menu, MenuItem, PredefinedMenuItem, Submenu, HELP_SUBMENU_ID, WINDOW_SUBMENU_ID};

    let quit = MenuItem::with_id(app, QUIT_MENU_ID, "Завершить PrintForge", true, Some("CmdOrCtrl+Q"))?;
    let file = Submenu::with_items(app, "File", true, &[
        &PredefinedMenuItem::close_window(app, None)?,
        #[cfg(not(target_os = "macos"))]
        &quit,
    ])?;
    let edit = Submenu::with_items(app, "Edit", true, &[
        &PredefinedMenuItem::undo(app, None)?,
        &PredefinedMenuItem::redo(app, None)?,
        &PredefinedMenuItem::separator(app)?,
        &PredefinedMenuItem::cut(app, None)?,
        &PredefinedMenuItem::copy(app, None)?,
        &PredefinedMenuItem::paste(app, None)?,
        &PredefinedMenuItem::select_all(app, None)?,
    ])?;
    let window = Submenu::with_id_and_items(app, WINDOW_SUBMENU_ID, "Window", true, &[
        &PredefinedMenuItem::minimize(app, None)?,
        &PredefinedMenuItem::maximize(app, None)?,
        &PredefinedMenuItem::close_window(app, None)?,
    ])?;
    let about = PredefinedMenuItem::about(app, None, Some(AboutMetadata {
        name: Some(app.package_info().name.clone()),
        version: Some(APP_VERSION.into()),
        copyright: app.config().bundle.copyright.clone(),
        authors: app.config().bundle.publisher.clone().map(|publisher| vec![publisher]),
        ..Default::default()
    }))?;
    let help = Submenu::with_id_and_items(app, HELP_SUBMENU_ID, "Help", true, &[
        #[cfg(not(target_os = "macos"))]
        &about,
    ])?;
    #[cfg(target_os = "macos")]
    let application = Submenu::with_items(app, &app.package_info().name, true, &[
        &about,
        &PredefinedMenuItem::separator(app)?,
        &PredefinedMenuItem::services(app, None)?,
        &PredefinedMenuItem::separator(app)?,
        &PredefinedMenuItem::hide(app, None)?,
        &PredefinedMenuItem::hide_others(app, None)?,
        &PredefinedMenuItem::show_all(app, None)?,
        &PredefinedMenuItem::separator(app)?,
        &quit,
    ])?;
    #[cfg(target_os = "macos")]
    let view = Submenu::with_items(app, "View", true, &[&PredefinedMenuItem::fullscreen(app, None)?])?;
    Menu::with_items(app, &[
        #[cfg(target_os = "macos")]
        &application,
        &file,
        &edit,
        #[cfg(target_os = "macos")]
        &view,
        &window,
        &help,
    ])
}

// ---------- геометрический worker ----------

struct GeoWorker {
    child: CommandChild,
    rx: Receiver<CommandEvent>,
    buf: String,
    next_id: u64,
}

static WORKER: Mutex<Option<GeoWorker>> = Mutex::const_new(None);
static GEOMETRY_TASK: StdMutex<Option<watch::Sender<bool>>> = StdMutex::new(None);
static DOCUMENT_TASKS: std::sync::atomic::AtomicUsize = std::sync::atomic::AtomicUsize::new(0);
static CLOSE_CONFIRMED: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

struct DocumentTask;

impl DocumentTask {
    fn begin() -> Self {
        DOCUMENT_TASKS.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
        Self
    }
}

impl Drop for DocumentTask {
    fn drop(&mut self) {
        DOCUMENT_TASKS.fetch_sub(1, std::sync::atomic::Ordering::SeqCst);
    }
}

enum WorkerRequestFailure {
    Write(String),
    Terminated,
    Cancelled,
    Timeout,
}

impl WorkerRequestFailure {
    fn detail(&self) -> String {
        match self {
            Self::Write(message) => format!("не удалось отправить запрос: {message}"),
            Self::Terminated => "geometry worker завершился без ответа".into(),
            Self::Cancelled => "операция отменена пользователем".into(),
            Self::Timeout => "истёк лимит времени geometry worker".into(),
        }
    }

    fn is_retryable_transport(&self) -> bool {
        matches!(self, Self::Write(_) | Self::Terminated)
    }
}

struct GeometryTaskRegistration;

impl Drop for GeometryTaskRegistration {
    fn drop(&mut self) {
        if let Ok(mut task) = GEOMETRY_TASK.lock() {
            *task = None;
        }
    }
}

fn register_geometry_task() -> Result<(watch::Receiver<bool>, GeometryTaskRegistration), String> {
    let mut task = GEOMETRY_TASK
        .lock()
        .map_err(|_| geo_err("worker_state_error", "состояние geometry worker недоступно"))?;
    if task.is_some() {
        return Err(geo_err(
            "worker_busy",
            "другая geometry operation уже выполняется",
        ));
    }
    let (sender, receiver) = watch::channel(false);
    *task = Some(sender);
    Ok((receiver, GeometryTaskRegistration))
}

fn request_geometry_cancel() -> Result<bool, String> {
    let task = GEOMETRY_TASK
        .lock()
        .map_err(|_| geo_err("worker_state_error", "состояние geometry worker недоступно"))?;
    let Some(sender) = task.as_ref() else {
        return Ok(false);
    };
    Ok(sender.send(true).is_ok())
}

fn worker_request_timeout(method: &str) -> Duration {
    match method {
        "import" | "export" => Duration::from_secs(300),
        _ => Duration::from_secs(120),
    }
}

fn kill_geo_worker(worker: &mut Option<GeoWorker>) {
    if let Some(GeoWorker { child, .. }) = worker.take() {
        let _ = child.kill();
    }
}

fn geo_err(code: &str, message: impl Into<String>) -> String {
    json!({"code": code, "message": message.into(), "detail": ""}).to_string()
}

fn spawn_geo_worker(app: &tauri::AppHandle) -> Result<GeoWorker, String> {
    let cmd = app
        .shell()
        .sidecar("printforge-geo")
        .map_err(|e| format!("sidecar не найден: {e}"))?;
    let (rx, child) = cmd
        .spawn()
        .map_err(|e| format!("не удалось запустить геометрический процесс: {e}"))?;
    Ok(GeoWorker {
        child,
        rx,
        buf: String::new(),
        next_id: 0,
    })
}

async fn send_worker_request(
    worker: &mut GeoWorker,
    method: &str,
    params: Value,
    revision: u64,
    cancelled: &mut watch::Receiver<bool>,
    deadline: tokio::time::Instant,
) -> Result<Result<Value, String>, WorkerRequestFailure> {
    if *cancelled.borrow() {
        return Err(WorkerRequestFailure::Cancelled);
    }
    worker.next_id += 1;
    let rid = format!("r{}", worker.next_id);
    let req = json!({
        "request_id": rid, "schema_version": 1,
        "document_id": "doc", "revision": revision,
        "method": method, "params": params,
    });
    worker
        .child
        .write(format!("{req}\n").as_bytes())
        .map_err(|error| WorkerRequestFailure::Write(error.to_string()))?;
    loop {
        let event = tokio::select! {
            biased;
            changed = cancelled.changed() => {
                if changed.is_ok() && *cancelled.borrow() {
                    return Err(WorkerRequestFailure::Cancelled);
                }
                continue;
            }
            _ = tokio::time::sleep_until(deadline) => {
                return Err(WorkerRequestFailure::Timeout);
            }
            event = worker.rx.recv() => event,
        };
        match event {
            Some(CommandEvent::Stdout(bytes)) => {
                worker.buf.push_str(&String::from_utf8_lossy(&bytes));
                while let Some(pos) = worker.buf.find('\n') {
                    let line: String = worker.buf.drain(..=pos).collect();
                    let resp: Value = match serde_json::from_str(line.trim()) {
                        Ok(v) => v,
                        Err(_) => continue,
                    };
                    if resp.get("request_id").and_then(Value::as_str) == Some(rid.as_str()) {
                        if resp.get("ok").and_then(Value::as_bool) == Some(true) {
                            return Ok(Ok(resp.get("result").cloned().unwrap_or(Value::Null)));
                        }
                        let err = resp.get("error").cloned().unwrap_or(json!({}));
                        return Ok(Err(json!({
                            "code": err.get("code").and_then(Value::as_str).unwrap_or("geometry_error"),
                            "message": err.get("message").and_then(Value::as_str).unwrap_or("ошибка геометрии"),
                            "detail": err.get("detail").and_then(Value::as_str).unwrap_or(""),
                        }).to_string()));
                    }
                }
            }
            Some(CommandEvent::Terminated(_)) | None => {
                return Err(WorkerRequestFailure::Terminated);
            }
            _ => {}
        }
    }
}

async fn worker_call(
    app: &tauri::AppHandle,
    method: &str,
    params: Value,
    revision: u64,
) -> Result<Value, String> {
    let mut guard = WORKER.lock().await;
    let (mut cancelled, _registration) = register_geometry_task()?;
    let timeout = worker_request_timeout(method);
    let deadline = tokio::time::Instant::now() + timeout;
    let mut previous_failure: Option<String> = None;
    for attempt in 0..=1 {
        if guard.is_none() {
            match spawn_geo_worker(app) {
                Ok(worker) => *guard = Some(worker),
                Err(message) if attempt == 0 => {
                    return Err(geo_err("worker_unavailable", message));
                }
                Err(message) => {
                    return Err(geo_err(
                        "worker_recovery_failed",
                        format!(
                            "geometry worker не восстановлен после аварии: {message}; исходный сбой: {}",
                            previous_failure.unwrap_or_else(|| "неизвестен".into())
                        ),
                    ));
                }
            }
        }
        let outcome = send_worker_request(
            guard.as_mut().expect("worker initialized"),
            method,
            params.clone(),
            revision,
            &mut cancelled,
            deadline,
        )
        .await;
        match outcome {
            Ok(result) => return result,
            Err(WorkerRequestFailure::Cancelled) => {
                kill_geo_worker(&mut guard);
                return Err(geo_err(
                    "geometry_cancelled",
                    "Операция геометрии отменена. Последняя подтверждённая модель сохранена.",
                ));
            }
            Err(WorkerRequestFailure::Timeout) => {
                kill_geo_worker(&mut guard);
                return Err(geo_err(
                    "worker_timeout",
                    format!(
                        "Geometry worker не завершил {method} за {} с. Процесс остановлен; последняя подтверждённая модель сохранена.",
                        timeout.as_secs()
                    ),
                ));
            }
            Err(failure) => {
                previous_failure = Some(failure.detail());
                kill_geo_worker(&mut guard);
                if !failure.is_retryable_transport() {
                    return Err(geo_err("geometry_error", failure.detail()));
                }
            }
        }
    }
    Err(geo_err(
        "worker_recovery_failed",
        format!(
            "geometry worker повторно завершился после автоматического перезапуска: {}. Последняя подтверждённая модель сохранена.",
            previous_failure.unwrap_or_else(|| "неизвестная transport error".into())
        ),
    ))
}

async fn stop_geo_worker() {
    let mut worker = WORKER.lock().await;
    kill_geo_worker(&mut worker);
}

#[tauri::command]
async fn geometry_cancel() -> Result<Value, String> {
    let cancelled = request_geometry_cancel()?;
    if cancelled {
        stop_geo_worker().await;
    }
    Ok(json!({"cancelled": cancelled}))
}

// ---------- документ ----------

#[derive(Clone, Default)]
struct Snapshot {
    parts: Vec<Value>, // [{part_id, name, template, params}]
    expressions: BTreeMap<String, String>,
    operations: Vec<Value>,
    part_n: u64,
}

struct Document {
    doc_id: u64,
    document_instance_id: u64,
    snap: Snapshot,
    history: Vec<Snapshot>,
    index: usize,
    dirty: bool,
    path: Option<PathBuf>,
    revision: u64,
    stats: Option<Value>,
    mesh: Option<Value>,
    error: Option<Value>,
    applied_actions: HashMap<String, String>,
}

impl Document {
    fn new() -> Self {
        static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
        let doc_id = NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed);
        Self::with_document_id(doc_id)
    }

    fn with_document_id(doc_id: u64) -> Self {
        static NEXT_INSTANCE_ID: std::sync::atomic::AtomicU64 =
            std::sync::atomic::AtomicU64::new(1);
        Document {
            doc_id,
            document_instance_id: NEXT_INSTANCE_ID.fetch_add(
                1,
                std::sync::atomic::Ordering::Relaxed,
            ),
            snap: Snapshot::default(),
            history: vec![Snapshot::default()],
            index: 0,
            dirty: false,
            path: None,
            revision: 0,
            stats: None,
            mesh: None,
            error: None,
            applied_actions: HashMap::new(),
        }
    }

    fn commit(&mut self, snap: Snapshot) {
        self.history.truncate(self.index + 1);
        self.history.push(snap.clone());
        self.index += 1;
        self.snap = snap;
        self.dirty = true;
    }

    fn candidate(&self, snap: Snapshot) -> Self {
        Self {
            doc_id: self.doc_id,
            document_instance_id: self.document_instance_id,
            snap,
            history: vec![],
            index: 0,
            dirty: self.dirty,
            path: self.path.clone(),
            revision: self.revision,
            stats: self.stats.clone(),
            mesh: self.mesh.clone(),
            error: None,
            applied_actions: HashMap::new(),
        }
    }

    fn apply_built_candidate(&mut self, candidate: Document) -> Result<(), String> {
        if self.doc_id != candidate.doc_id
            || self.document_instance_id != candidate.document_instance_id
            || self.revision + 1 != candidate.revision
        {
            return Err(geo_err("document_changed", "Документ изменился перед применением операции."));
        }
        if candidate.error.is_some() {
            self.error = candidate.error;
            return Ok(());
        }
        self.commit(candidate.snap);
        self.revision = candidate.revision;
        self.stats = candidate.stats;
        self.mesh = candidate.mesh;
        self.error = None;
        Ok(())
    }

    fn build_params(&self) -> Value {
        if self.snap.parts.is_empty() && self.snap.operations.is_empty() {
            return json!({"template": null, "params": {}, "operations": []});
        }
        let first_id = self.snap.parts.first()
            .and_then(|p| p.get("part_id")).and_then(Value::as_str).map(String::from);
        let ops: Vec<Value> = self.snap.operations.iter().map(|op| {
            if matches!(op.get("op").and_then(Value::as_str), Some("fillet" | "chamfer"))
                && op.get("part_id").is_none()
            {
                let mut o = op.clone();
                o["part_id"] = json!(first_id);
                o
            } else {
                op.clone()
            }
        }).collect();
        json!({
            "parts": self.snap.parts,
            "operations": ops,
        })
    }

    fn state(&self, slot: &str) -> Value {
        json!({
            "doc_id": self.doc_id,
            "document_instance_id": self.document_instance_id,
            "revision": self.revision,
            "dirty": self.dirty,
            "path": self.path.as_ref().map(|p| p.to_string_lossy()),
            "slot": slot,
            "template": self.snap.parts.first().and_then(|p| p.get("template")),
            "params": self.snap.parts.first().and_then(|p| p.get("params")).cloned().unwrap_or(json!({})),
            "parts": self.snap.parts,
            "expressions": self.snap.expressions,
            "operations": self.snap.operations,
            "stats": self.stats,
            "error": self.error,
            "can_undo": self.index > 0,
            "can_redo": self.index + 1 < self.history.len(),
            "history_len": self.history.len(),
            "history_index": self.index,
        })
    }
}

struct Store {
    main: Document,
    tutorial: Document,
    active: String,
}

static STORE: Mutex<Option<Store>> = Mutex::const_new(None);

async fn with_store<R>(f: impl FnOnce(&mut Store) -> R) -> R {
    let mut guard = STORE.lock().await;
    if guard.is_none() {
        *guard = Some(Store {
            main: Document::new(),
            tutorial: Document::new(),
            active: "main".into(),
        });
    }
    f(guard.as_mut().unwrap())
}

fn active_doc(store: &mut Store) -> &mut Document {
    if store.active == "tutorial" { &mut store.tutorial } else { &mut store.main }
}

async fn current_state() -> Value {
    with_store(|s| {
        let slot = s.active.clone();
        active_doc(s).state(&slot)
    })
    .await
}

async fn rebuild(app: &tauri::AppHandle, doc: &mut Document) {
    doc.revision += 1;
    if doc.snap.parts.is_empty() && doc.snap.operations.is_empty() {
        doc.stats = None;
        doc.mesh = None;
        doc.error = None;
        return;
    }
    let result = async {
        if !doc.snap.parts.is_empty() {
            let resolved = worker_call(app, "resolve_parameters", json!({
                "parts": doc.snap.parts,
                "expressions": doc.snap.expressions,
            }), doc.revision).await?;
            doc.snap.parts = serde_json::from_value(resolved["parts"].clone())
                .map_err(|error| geo_err("bad_parameters", error.to_string()))?;
            doc.snap.expressions = serde_json::from_value(resolved["expressions"].clone())
                .map_err(|error| geo_err("bad_parameters", error.to_string()))?;
        }
        worker_call(app, "build", doc.build_params(), doc.revision).await
    }.await;
    match result {
        Ok(result) => {
            doc.stats = result.get("stats").cloned();
            doc.mesh = result.get("mesh").cloned();
            doc.error = None;
        }
        Err(e) => {
            // DOC-005: последняя подтверждённая ревизия остаётся видимой.
            let err: Value = serde_json::from_str(&e).unwrap_or(json!({
                "code": "geometry_error", "message": e, "detail": ""
            }));
            doc.error = Some(err);
        }
    }
}

async fn edit_snapshot(
    app: &tauri::AppHandle,
    edit: impl FnOnce(&mut Snapshot) -> Result<(), String>,
) -> Result<Value, String> {
    let _task = DocumentTask::begin();
    let (slot, mut candidate) = with_store(|store| {
        if CLOSE_CONFIRMED.load(std::sync::atomic::Ordering::SeqCst) {
            return Err(geo_err("application_closing", "Приложение закрывается."));
        }
        let slot = store.active.clone();
        let document = active_doc(store);
        let mut snapshot = document.snap.clone();
        edit(&mut snapshot)?;
        Ok::<_, String>((slot, document.candidate(snapshot)))
    }).await?;
    rebuild(app, &mut candidate).await;
    with_store(|store| {
        if store.active != slot {
            return Err(geo_err("document_changed", "Активный документ изменился перед применением операции."));
        }
        let document = active_doc(store);
        document.apply_built_candidate(candidate)?;
        Ok(document.state(&slot))
    }).await
}

// ---------- команды IPC ----------

const TEMPLATES: [&str; 7] = [
    "box", "cylinder", "sphere", "plate_with_holes", "washer", "bracket_l", "case_with_lid",
];

fn make_part(part_n: u64, template: &str, params: BTreeMap<String, f64>) -> Value {
    let title = match template {
        "box" => "Параллелепипед",
        "cylinder" => "Цилиндр",
        "sphere" => "Сфера",
        "plate_with_holes" => "Пластина",
        "washer" => "Шайба",
        "bracket_l" => "Кронштейн",
        "case_with_lid" => "Корпус",
        _ => template,
    };
    json!({
        "part_id": format!("part-{part_n}"),
        "name": title,
        "template": template,
        "params": params,
    })
}

#[tauri::command]
async fn doc_create(
    app: tauri::AppHandle,
    template: String,
    params: Option<BTreeMap<String, f64>>,
) -> Result<Value, String> {
    if !TEMPLATES.contains(&template.as_str()) {
        return Err(geo_err("unknown_template", format!("Неизвестный шаблон: {template}")));
    }
    let part = make_part(1, &template, params.unwrap_or_default());
    edit_snapshot(&app, |snapshot| {
        *snapshot = Snapshot {
            parts: vec![part],
            expressions: BTreeMap::new(),
            operations: vec![],
            part_n: 1,
        };
        Ok(())
    }).await
}

#[tauri::command]
async fn doc_add_part(
    app: tauri::AppHandle,
    template: String,
    params: Option<BTreeMap<String, f64>>,
) -> Result<Value, String> {
    if !TEMPLATES.contains(&template.as_str()) {
        return Err(geo_err("unknown_template", format!("Неизвестный шаблон: {template}")));
    }
    let has_model = with_store(|store| {
        let snapshot = &active_doc(store).snap;
        !snapshot.parts.is_empty() || snapshot.operations.iter().any(|operation| operation["op"] == "step_source")
    }).await;
    if !has_model {
        return Err(geo_err("no_model", "Сначала создайте деталь из шаблона."));
    }
    edit_snapshot(&app, |snapshot| {
        snapshot.part_n += 1;
        snapshot.parts.push(make_part(snapshot.part_n, &template, params.unwrap_or_default()));
        Ok(())
    }).await
}

async fn apply_op(app: &tauri::AppHandle, op: Value) -> Result<Value, String> {
    apply_atomic_op(app, op).await
}

async fn apply_atomic_op(app: &tauri::AppHandle, op: Value) -> Result<Value, String> {
    edit_snapshot(app, |snapshot| {
        snapshot.operations.push(op);
        Ok(())
    }).await
}

#[tauri::command]
async fn doc_boolean(
    app: tauri::AppHandle,
    boolean: String,
    target_id: String,
    tool_id: String,
    keep_tool: Option<bool>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "boolean", "boolean": boolean,
        "target_id": target_id, "tool_id": tool_id,
        "keep_tool": keep_tool.unwrap_or(false),
    })).await
}

#[tauri::command]
async fn doc_array(app: tauri::AppHandle, part_id: String, count: u32, step: Vec<f64>) -> Result<Value, String> {
    apply_op(&app, json!({"op": "array_linear", "part_id": part_id, "count": count, "step": step})).await
}

#[tauri::command]
async fn doc_mirror(app: tauri::AppHandle, part_id: String, plane: String) -> Result<Value, String> {
    apply_op(&app, json!({"op": "mirror", "part_id": part_id, "plane": plane})).await
}

#[tauri::command]
async fn doc_split(
    app: tauri::AppHandle,
    part_id: String,
    plane: String,
    offset: f64,
    separate: Option<bool>,
) -> Result<Value, String> {
    let mut operation = json!({"op": "split", "part_id": part_id, "plane": plane, "offset": offset});
    if separate.unwrap_or(false) {
        operation["separate"] = json!(true);
        return apply_atomic_op(&app, operation).await;
    }
    apply_op(&app, operation).await
}

#[tauri::command]
async fn doc_transform(app: tauri::AppHandle, part_id: String, translate: Vec<f64>) -> Result<Value, String> {
    apply_op(&app, json!({"op": "transform", "part_id": part_id, "translate": translate})).await
}

#[tauri::command]
async fn doc_create_plate(
    app: tauri::AppHandle,
    length: f64,
    width: f64,
    height: f64,
    hole_diameter: f64,
    hole_offset: f64,
) -> Result<Value, String> {
    let mut p = BTreeMap::new();
    p.insert("length".into(), length);
    p.insert("width".into(), width);
    p.insert("height".into(), height);
    p.insert("hole_diameter".into(), hole_diameter);
    p.insert("hole_offset".into(), hole_offset);
    doc_create(app, "plate_with_holes".into(), Some(p)).await
}

#[tauri::command]
async fn doc_set_parameter(
    app: tauri::AppHandle,
    name: String,
    value: f64,
    expression: Option<String>,
    part_id: Option<String>,
) -> Result<Value, String> {
    if !value.is_finite() {
        return Err(geo_err("bad_value",
            format!("Значение параметра «{name}» должно быть конечным числом.")));
    }
    let has_model = with_store(|s| !active_doc(s).snap.parts.is_empty()).await;
    if !has_model {
        return Err(geo_err("no_model", "Сначала создайте деталь."));
    }
    edit_snapshot(&app, |next| {
        let pid = part_id.clone().or_else(|| {
            next.parts.first().and_then(|p| p.get("part_id")).and_then(Value::as_str).map(String::from)
        });
        if let Some(part) = next.parts.iter_mut().find(|p| {
            p.get("part_id").and_then(Value::as_str) == pid.as_deref()
        }) {
            part["params"][&name] = json!(value);
        } else {
            return Err(geo_err("bad_ref", "Целевая деталь не существует."));
        }
        let key = format!("{}.{}", pid.unwrap_or_default(), name);
        match &expression {
            Some(e) if !e.trim().is_empty() => {
                next.expressions.insert(key, e.clone());
            }
            _ => {
                next.expressions.remove(&key);
            }
        }
        Ok(())
    }).await
}

#[tauri::command]
async fn doc_fillet(
    app: tauri::AppHandle,
    edge_ref: Value,
    radius: f64,
    part_id: Option<String>,
) -> Result<Value, String> {
    if !radius.is_finite() || radius <= 0.0 {
        return Err(geo_err("bad_value", "Радиус скругления должен быть больше нуля."));
    }
    let pid = part_id.or_else(|| None);
    apply_op(&app, json!({
        "op": "fillet", "radius": radius, "edge_ref": edge_ref, "part_id": pid,
    })).await
}

#[tauri::command]
async fn doc_chamfer(
    app: tauri::AppHandle,
    edge_ref: Value,
    distance: f64,
    part_id: Option<String>,
) -> Result<Value, String> {
    if !distance.is_finite() || distance <= 0.0 {
        return Err(geo_err(
            "bad_value",
            "Размер фаски должен быть больше нуля.",
        ));
    }
    apply_op(
        &app,
        json!({
            "op": "chamfer", "distance": distance, "edge_ref": edge_ref, "part_id": part_id,
        }),
    )
    .await
}

#[tauri::command]
async fn doc_profile_extrude(
    app: tauri::AppHandle,
    mode: String,
    plane: String,
    profile: Value,
    depth: Option<Value>,
    target_id: Option<String>,
) -> Result<Value, String> {
    let mut op = json!({"op": "profile_extrude", "mode": mode, "plane": plane, "profile": profile});
    if let Some(d) = depth { op["depth"] = d; }
    let tid = target_id.or_else(|| None);
    if mode_is_cut(&op) {
        let fallback = with_store(|s| {
            let doc = active_doc(s);
            doc.snap.parts.first().and_then(|p| p.get("part_id")).and_then(Value::as_str).map(String::from)
        }).await;
        op["target_id"] = json!(tid.or(fallback));
    } else if let Some(t) = tid {
        op["target_id"] = json!(t);
    }
    apply_op(&app, op).await
}

#[tauri::command]
async fn doc_sketch_extrude(
    app: tauri::AppHandle,
    profile: Value,
    plane: Option<String>,
    depth: f64,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "sketch_extrude",
        "profile": profile,
        "plane": plane.unwrap_or_else(|| "XY".into()),
        "depth": depth,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn sketch_solve(
    app: tauri::AppHandle,
    sketch: Value,
    drag: Option<Value>,
    tolerance: Option<f64>,
) -> Result<Value, String> {
    let revision = with_store(|s| active_doc(s).revision).await;
    worker_call(&app, "solve_sketch", json!({
        "sketch": sketch,
        "drag": drag,
        "tolerance": tolerance.unwrap_or(1e-7),
    }), revision).await
}

#[tauri::command]
async fn doc_constrained_sketch_extrude(
    app: tauri::AppHandle,
    sketch: Value,
    drag: Option<Value>,
    plane: Option<String>,
    depth: f64,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "constrained_sketch_extrude",
        "sketch": sketch,
        "drag": drag,
        "plane": plane.unwrap_or_else(|| "XY".into()),
        "depth": depth,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_revolve(
    app: tauri::AppHandle,
    profile: Value,
    plane: Option<String>,
    axis: Option<Value>,
    angle: f64,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "revolve",
        "profile": profile,
        "plane": plane.unwrap_or_else(|| "XZ".into()),
        "axis": axis.unwrap_or_else(|| json!({
            "point": [0.0, 0.0, 0.0], "direction": [0.0, 0.0, 1.0]
        })),
        "angle": angle,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_sweep(
    app: tauri::AppHandle,
    section: Value,
    path: Value,
    frenet: Option<bool>,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "sweep",
        "section": section,
        "path": path,
        "frenet": frenet.unwrap_or(false),
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_loft(
    app: tauri::AppHandle,
    sections: Value,
    ruled: Option<bool>,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "loft",
        "sections": sections,
        "ruled": ruled.unwrap_or(true),
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_shell(
    app: tauri::AppHandle,
    outer_radius: f64,
    height: f64,
    wall: f64,
    bottom: f64,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "shell",
        "outer_radius": outer_radius,
        "height": height,
        "wall": wall,
        "bottom": bottom,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_draft_prism(
    app: tauri::AppHandle,
    width: f64,
    depth: f64,
    height: f64,
    angle: f64,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "draft_prism",
        "width": width,
        "depth": depth,
        "height": height,
        "angle": angle,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_rib(
    app: tauri::AppHandle,
    base_length: f64,
    base_width: f64,
    base_thickness: f64,
    rib_length: f64,
    rib_height: f64,
    rib_width: f64,
    overlap: f64,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "rib",
        "base_length": base_length,
        "base_width": base_width,
        "base_thickness": base_thickness,
        "rib_length": rib_length,
        "rib_height": rib_height,
        "rib_width": rib_width,
        "overlap": overlap,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_fit_pocket(
    app: tauri::AppHandle,
    fixture_id: String,
    fixture_version: Option<String>,
    body_length: f64,
    body_width: f64,
    body_height: f64,
    clearance: f64,
    clearance_mode: String,
    pocket_depth: Option<f64>,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    let mut operation = json!({
        "op": "fit_pocket",
        "fixture_id": fixture_id,
        "fixture_version": fixture_version.unwrap_or_else(|| "1".into()),
        "body_length": body_length,
        "body_width": body_width,
        "body_height": body_height,
        "clearance": clearance,
        "clearance_mode": clearance_mode,
        "result_id": result_id,
        "name": name,
    });
    if let Some(value) = pocket_depth {
        operation["pocket_depth"] = json!(value);
    }
    apply_op(&app, operation).await
}

#[tauri::command]
async fn doc_vector_extrude(
    app: tauri::AppHandle,
    path: String,
    format: String,
    height: f64,
    unit_scale: Option<f64>,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    let source_text = std::fs::read_to_string(&path)
        .map_err(|error| geo_err("file_read_failed", &format!("Не удалось прочитать векторный файл: {error}")))?;
    let mut operation = json!({
        "op": "vector_extrude",
        "format": format,
        "source_text": source_text,
        "height": height,
        "result_id": result_id,
        "name": name,
    });
    if let Some(value) = unit_scale {
        operation["unit_scale"] = json!(value);
    }
    apply_op(&app, operation).await
}

#[tauri::command]
async fn doc_text_relief(
    app: tauri::AppHandle,
    text: String,
    font_size: f64,
    relief_height: f64,
    body_length: f64,
    body_width: f64,
    body_height: f64,
    mode: String,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "text_relief",
        "text": text,
        "font_size": font_size,
        "relief_height": relief_height,
        "body_length": body_length,
        "body_width": body_width,
        "body_height": body_height,
        "mode": mode,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_thread_pair(
    app: tauri::AppHandle,
    profile_version: Option<String>,
    major_diameter: f64,
    pitch: f64,
    length: f64,
    hand: String,
    starts: u32,
    clearance: f64,
    nut_height: f64,
    nut_across_flats: f64,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "thread_pair",
        "profile_version": profile_version.unwrap_or_else(|| "metric-60-v1".into()),
        "major_diameter": major_diameter,
        "pitch": pitch,
        "length": length,
        "hand": hand,
        "starts": starts,
        "clearance": clearance,
        "nut_height": nut_height,
        "nut_across_flats": nut_across_flats,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_clearance_calibration(
    app: tauri::AppHandle,
    values: Value,
    nominal_diameter: f64,
    coupon_length: f64,
    coupon_width: f64,
    thickness: f64,
    spacing: f64,
    font_size: f64,
    label_height: f64,
    profile_name: Option<String>,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "clearance_calibration",
        "values": values,
        "nominal_diameter": nominal_diameter,
        "coupon_length": coupon_length,
        "coupon_width": coupon_width,
        "thickness": thickness,
        "spacing": spacing,
        "font_size": font_size,
        "label_height": label_height,
        "profile_name": profile_name,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_split_connector_pair(
    app: tauri::AppHandle,
    length: f64,
    width: f64,
    height: f64,
    pin_radius: f64,
    pin_length: f64,
    radial_clearance: f64,
    print_separation: f64,
    result_id: Option<String>,
    name: Option<String>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "split_connector_pair",
        "length": length,
        "width": width,
        "height": height,
        "pin_radius": pin_radius,
        "pin_length": pin_length,
        "radial_clearance": radial_clearance,
        "print_separation": print_separation,
        "result_id": result_id,
        "name": name,
    })).await
}

#[tauri::command]
async fn doc_resize_body(
    app: tauri::AppHandle,
    target_id: String,
    size: [f64; 3],
    anchor: [i8; 3],
) -> Result<Value, String> {
    if size.iter().any(|value| !value.is_finite() || *value <= 0.0)
        || anchor.iter().any(|value| *value != -1 && *value != 1)
    {
        return Err(geo_err("bad_params", "Укажите положительные размеры и неподвижный угол тела."));
    }
    apply_atomic_op(&app, json!({
        "op": "resize_body", "target_id": target_id, "size": size, "anchor": anchor,
    })).await
}

#[tauri::command]
async fn doc_designer_action(
    app: tauri::AppHandle,
    action: Value,
    expected_revision: u64,
    expected_instance: Value,
    preview: bool,
) -> Result<Value, String> {
    let _task = DocumentTask::begin();
    let (slot, mut candidate) = with_store(|store| {
        if CLOSE_CONFIRMED.load(std::sync::atomic::Ordering::SeqCst) {
            return Err(geo_err("application_closing", "Приложение закрывается."));
        }
        let slot = store.active.clone();
        let document = active_doc(store);
        if document.revision != expected_revision || json!(document.document_instance_id) != expected_instance {
            return Err(geo_err("document_changed", "Документ изменился. Выберите область заново."));
        }
        Ok((slot, document.candidate(document.snap.clone())))
    }).await?;
    let prepared = worker_call(&app, "designer_action", json!({
        "document": candidate.build_params(), "action": action,
    }), expected_revision).await?;
    candidate.snap.parts = serde_json::from_value(prepared["parts"].clone())
        .map_err(|error| geo_err("bad_params", error.to_string()))?;
    candidate.snap.operations = serde_json::from_value(prepared["operations"].clone())
        .map_err(|error| geo_err("bad_params", error.to_string()))?;
    if candidate.snap.parts.is_empty() { candidate.snap.expressions.clear(); }
    rebuild(&app, &mut candidate).await;
    if preview {
        if let Some(error) = candidate.error { return Err(error.to_string()); }
        return with_store(|store| {
            let active_slot = store.active.clone();
            let document = active_doc(store);
            if active_slot != slot || document.revision != expected_revision || json!(document.document_instance_id) != expected_instance {
                return Err(geo_err("document_changed", "Preview устарел: документ изменился."));
            }
            Ok(json!({"stats": candidate.stats, "mesh": candidate.mesh,
                "base_revision": expected_revision, "document_instance_id": expected_instance}))
        }).await;
    }
    with_store(|store| {
        if store.active != slot { return Err(geo_err("document_changed", "Активный документ изменился.")); }
        let document = active_doc(store);
        document.apply_built_candidate(candidate)?;
        Ok(document.state(&slot))
    }).await
}

#[tauri::command]
async fn doc_face_offset(
    app: tauri::AppHandle,
    target_id: String,
    face_ref: Value,
    distance: f64,
) -> Result<Value, String> {
    if !distance.is_finite() || distance.abs() < 1e-6 {
        return Err(geo_err(
            "bad_params",
            "Введите ненулевое смещение грани в миллиметрах.",
        ));
    }
    apply_atomic_op(&app, json!({
        "op": "face_offset",
        "target_id": target_id,
        "face_ref": face_ref,
        "distance": distance,
    })).await
}

#[tauri::command]
async fn doc_face_feature(
    app: tauri::AppHandle,
    target_id: String,
    mode: String,
    face_ref: Value,
    profile: Value,
    depth: Value,
) -> Result<Value, String> {
    if mode != "add" && mode != "cut" {
        return Err(geo_err(
            "bad_params",
            "Режим элемента должен быть add или cut.",
        ));
    }
    apply_op(
        &app,
        json!({
            "op": "face_feature",
            "target_id": target_id,
            "mode": mode,
            "face_ref": face_ref,
            "profile": profile,
            "depth": depth,
        }),
    )
    .await
}

#[tauri::command]
async fn doc_face_dome(
    app: tauri::AppHandle,
    target_id: String,
    mode: String,
    face_ref: Value,
    center: Value,
    diameter: f64,
    height: f64,
) -> Result<Value, String> {
    if mode != "add" && mode != "cut" {
        return Err(geo_err(
            "bad_params",
            "Режим сферического сегмента должен быть add или cut.",
        ));
    }
    apply_op(
        &app,
        json!({
            "op": "face_dome",
            "target_id": target_id,
            "mode": mode,
            "face_ref": face_ref,
            "center": center,
            "diameter": diameter,
            "height": height,
        }),
    )
    .await
}

#[tauri::command]
async fn doc_sheet_bend(
    app: tauri::AppHandle,
    target_id: String,
    face_ref: Value,
    bend_axis: String,
    position: f64,
    angle: f64,
    inside_radius: f64,
    moving_side: i32,
    direction: i32,
) -> Result<Value, String> {
    apply_op(
        &app,
        json!({
            "op": "sheet_bend",
            "target_id": target_id,
            "face_ref": face_ref,
            "bend_axis": bend_axis,
            "position": position,
            "angle": angle,
            "inside_radius": inside_radius,
            "moving_side": moving_side,
            "direction": direction,
        }),
    )
    .await
}

fn mode_is_cut(op: &Value) -> bool {
    op.get("mode").and_then(Value::as_str) == Some("cut")
}

#[tauri::command]
async fn doc_array_circular(
    app: tauri::AppHandle,
    part_id: String,
    count: u32,
    angle: Option<f64>,
    center: Option<Vec<f64>>,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "array_circular", "part_id": part_id, "count": count,
        "angle": angle.unwrap_or(360.0),
        "center": center.unwrap_or(vec![0.0, 0.0, 0.0]),
    })).await
}

#[tauri::command]
async fn doc_align(
    app: tauri::AppHandle,
    part_id: String,
    axis: String,
    align: String,
    value: f64,
) -> Result<Value, String> {
    apply_op(&app, json!({
        "op": "align", "part_id": part_id, "axis": axis,
        "align": align, "value": value,
    })).await
}

#[tauri::command]
async fn measure(app: tauri::AppHandle, measure_type: String, extra: Option<Value>) -> Result<Value, String> {
    let (params, revision) = with_store(|s| {
        let doc = active_doc(s);
        (doc.build_params(), doc.revision)
    }).await;
    if params["template"].is_null() && params["parts"].is_null() {
        return Err(geo_err("no_model", "Сначала создайте деталь."));
    }
    let mut call = params;
    call["type"] = json!(measure_type);
    if let Some(e) = extra {
        if let Some(obj) = e.as_object() {
            for (k, v) in obj { call[k] = v.clone(); }
        }
    }
    worker_call(&app, "measure", call, revision).await
}

fn apply_plan_ops(snap: &mut Snapshot, ops: &[Value]) -> Result<(), String> {
    for op in ops {
        let cid = op.get("command_id").and_then(Value::as_str).unwrap_or("");
        let params = op.get("parameters").and_then(Value::as_object)
            .ok_or_else(|| geo_err("plan_invalid", "В операции нет parameters."))?;
        match cid {
            "part.create.from_template" => {
                let template = params.get("template").and_then(Value::as_str).unwrap_or("");
                if !TEMPLATES.contains(&template) {
                    return Err(geo_err("plan_invalid", "Неизвестный шаблон в AI-плане."));
                }
                let mut pmap = BTreeMap::new();
                if let Some(obj) = params.get("params").and_then(Value::as_object) {
                    for (k, v) in obj {
                        if let Some(n) = v.as_f64() {
                            pmap.insert(k.clone(), n);
                        }
                    }
                }
                snap.parts = vec![make_part(1, template, pmap)];
                snap.part_n = 1;
                snap.operations = vec![];
                snap.expressions = BTreeMap::new();
            }
            "parameter.set" => {
                let tid = op.get("target_id").and_then(Value::as_str).unwrap_or("");
                let name = params.get("name").and_then(Value::as_str).unwrap_or("");
                let value = params.get("value").and_then(Value::as_f64).unwrap_or(0.0);
                let part = snap.parts.iter_mut().find(|p| {
                    p.get("part_id").and_then(Value::as_str) == Some(tid)
                }).ok_or_else(|| geo_err("plan_invalid", "Целевая деталь не существует."))?;
                part["params"][name] = json!(value);
                snap.expressions.remove(&format!("{tid}.{name}"));
            }
            "op.fillet" => {
                let radius = params.get("radius").and_then(Value::as_f64).unwrap_or(0.0);
                snap.operations.retain(|o| o.get("op") != Some(&json!("fillet")));
                let tid = op.get("target_id").and_then(Value::as_str)
                    .or_else(|| snap.parts.first().and_then(|p| p.get("part_id")).and_then(Value::as_str));
                snap.operations.push(json!({
                    "op": "fillet", "radius": radius,
                    "edge_ref": params.get("edge_ref"),
                    "part_id": tid,
                }));
            }
            _ => return Err(geo_err("plan_forbidden", "Команда не разрешена для AI.")),
        }
    }
    Ok(())
}

#[tauri::command]
async fn doc_transaction(
    app: tauri::AppHandle,
    operations: Vec<Value>,
    base_revision: Option<u64>,
    document_instance_id: Option<u64>,
    plan_hash: Option<String>,
    action_id: Option<String>,
    mode: Option<String>,
) -> Result<Value, String> {
    let _task = DocumentTask::begin();
    let (doc_id, instance_id, revision, snap) = with_store(|s| {
        let doc = active_doc(s);
        (doc.doc_id, doc.document_instance_id, doc.revision, doc.snap.clone())
    })
    .await;
    if operations.is_empty() {
        return Err(geo_err("plan_invalid", "Пустой набор операций."));
    }
    if document_instance_id.unwrap_or(instance_id) != instance_id {
        return Err(geo_err("plan_stale", "План относится к другому открытию документа."));
    }
    let base = base_revision.unwrap_or(revision);
    let expected_hash = ai::plan_hash(doc_id, instance_id, base, &operations);
    if plan_hash.as_deref().is_some_and(|value| value != expected_hash) {
        return Err(geo_err(
            "plan_conflict",
            "План изменён после предпросмотра; пересчитайте его.",
        ));
    }
    if let Some(action) = action_id.as_ref() {
        let replay = with_store(|s| -> Result<Option<Value>, String> {
            let slot = s.active.clone();
            let doc = active_doc(s);
            if let Some(previous_hash) = doc.applied_actions.get(action) {
                if previous_hash != &expected_hash {
                    return Err(geo_err(
                        "action_conflict",
                        "action_id уже использован для другого плана.",
                    ));
                }
                let mut state = doc.state(&slot);
                state["idempotent_replay"] = json!(true);
                return Ok(Some(state));
            }
            Ok(None)
        })
        .await?;
        if let Some(state) = replay {
            return Ok(state);
        }
    }
    if base != revision {
        return Err(geo_err(
            "plan_stale",
            "Документ изменился, пока формировалось предложение. Пересчитайте.",
        ));
    }
    let mut candidate = snap;
    apply_plan_ops(&mut candidate, &operations)?;
    let mut tmp = Document {
        doc_id,
        document_instance_id: instance_id,
        snap: candidate.clone(),
        history: vec![],
        index: 0,
        dirty: false,
        path: None,
        revision: base,
        stats: None,
        mesh: None,
        error: None,
        applied_actions: HashMap::new(),
    };
    rebuild(&app, &mut tmp).await;
    if mode.as_deref() == Some("apply") {
        if let Some(error) = tmp.error {
            return Err(error.to_string());
        }
        return with_store(|s| -> Result<Value, String> {
            let slot = s.active.clone();
            let doc = active_doc(s);
            if doc.doc_id != doc_id
                || doc.document_instance_id != instance_id
                || doc.revision != base
            {
                return Err(geo_err("plan_stale", "Документ изменился перед применением плана."));
            }
            if let Some(action) = action_id.as_ref() {
                if let Some(previous_hash) = doc.applied_actions.get(action) {
                    if previous_hash != &expected_hash {
                        return Err(geo_err(
                            "action_conflict",
                            "action_id уже использован для другого плана.",
                        ));
                    }
                    let mut state = doc.state(&slot);
                    state["idempotent_replay"] = json!(true);
                    return Ok(state);
                }
            }
            doc.commit(tmp.snap);
            doc.revision = tmp.revision;
            doc.stats = tmp.stats;
            doc.mesh = tmp.mesh;
            doc.error = None;
            if let Some(action) = action_id {
                doc.applied_actions.insert(action, expected_hash);
            }
            Ok(doc.state(&slot))
        })
        .await;
    }
    Ok(json!({
        "mode": "preview",
        "stats": tmp.stats,
        "error": tmp.error,
        "parts": tmp.snap.parts,
        "plan_hash": expected_hash,
        "base_revision": base,
        "document_instance_id": instance_id,
    }))
}

#[tauri::command]
async fn ai_providers() -> Result<Value, String> {
    Ok(ai::provider_info())
}

#[tauri::command]
async fn ai_configure(
    app: tauri::AppHandle,
    provider: String,
    base_url: String,
    model: String,
    api_key: Option<String>,
    clear_api_key: Option<bool>,
) -> Result<Value, String> {
    let config_dir = app.path().app_config_dir().map_err(|error| error.to_string())?;
    ai::configure(
        &config_dir,
        provider,
        base_url,
        model,
        api_key,
        clear_api_key.unwrap_or(false),
    )
    .map_err(|message| geo_err("ai_settings_invalid", message))
}

#[tauri::command]
async fn ai_test_connection() -> Result<Value, String> {
    ai::test_connection()
        .await
        .map_err(|message| geo_err("ai_connection_failed", message))
}

async fn build_ai_plan(app: tauri::AppHandle, text: String) -> Result<Value, String> {
    let info = ai::provider_info();
    if info["provider"] == "disabled" {
        return Err(geo_err("ai_disabled", "AI-помощник выключен в настройках."));
    }
    if text.trim().is_empty() {
        return Err(geo_err("bad_request", "Пустой запрос."));
    }
    let (doc_id, instance_id, revision, parts, part_ids) = with_store(|s| {
        let doc = active_doc(s);
        let ids: Vec<String> = doc.snap.parts.iter()
            .filter_map(|p| p.get("part_id").and_then(Value::as_str).map(String::from))
            .collect();
        (
            doc.doc_id,
            doc.document_instance_id,
            doc.revision,
            doc.snap.parts.clone(),
            ids,
        )
    })
    .await;
    let plan = if info["scripted"] == true {
        ai::scripted_plan(&text, doc_id, instance_id, revision, &parts)
    } else {
        ai::llm_plan(
            &text,
            doc_id,
            instance_id,
            revision,
            &parts,
            &part_ids,
        )
        .await?
    };
    if let Some(err) = ai::validate_plan(&plan, doc_id, instance_id, revision, &part_ids) {
        return Err(err.to_string());
    }
    let ops = plan.get("operations").and_then(Value::as_array).cloned().unwrap_or_default();
    let plan_hash = ai::plan_hash(doc_id, instance_id, revision, &ops);
    let preview = if ops.is_empty() {
        Value::Null
    } else {
        doc_transaction(
            app,
            ops,
            Some(revision),
            Some(instance_id),
            Some(plan_hash.clone()),
            None,
            None,
        )
        .await?
    };
    static NEXT_ACTION_ID: std::sync::atomic::AtomicU64 =
        std::sync::atomic::AtomicU64::new(1);
    let action_id = format!(
        "ai-{}-{}",
        instance_id,
        NEXT_ACTION_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
    );
    Ok(json!({
        "plan": plan,
        "preview": preview,
        "plan_hash": plan_hash,
        "action_id": action_id,
    }))
}

#[tauri::command]
async fn ai_plan(app: tauri::AppHandle, text: String, task_id: String) -> Result<Value, String> {
    let mut cancelled =
        ai::register_task(&task_id).map_err(|message| geo_err("ai_task_conflict", message))?;
    let result = tokio::select! {
        biased;
        changed = cancelled.changed() => {
            let _ = changed;
            Err(geo_err("ai_cancelled", "AI-запрос отменён пользователем."))
        }
        result = build_ai_plan(app, text) => result,
    };
    ai::finish_task(&task_id);
    result
}

#[tauri::command]
async fn ai_cancel(task_id: String) -> Result<Value, String> {
    let cancelled = ai::cancel_task(&task_id);
    let geometry_cancelled = if cancelled {
        request_geometry_cancel()?
    } else {
        false
    };
    if geometry_cancelled {
        stop_geo_worker().await;
    }
    Ok(json!({
        "task_id": task_id,
        "cancelled": cancelled,
        "geometry_cancelled": geometry_cancelled,
    }))
}

#[tauri::command]
async fn ai_chat(messages: Value, want_json: Option<bool>) -> Result<Value, String> {
    let info = ai::provider_info();
    if info["provider"] == "disabled" {
        return Err(geo_err("ai_disabled", "AI-помощник выключен в настройках."));
    }
    if info["scripted"] == true {
        return Err(geo_err("ai_scripted_only",
            "Включён детерминированный планировщик (не LLM): используйте «Предложить план»."));
    }
    let content = ai::http_chat(messages, want_json.unwrap_or(false)).await?;
    Ok(json!({"content": content}))
}

#[tauri::command]
async fn doc_clear_error() -> Result<Value, String> {
    with_store(|s| active_doc(s).error = None).await;
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_undo(app: tauri::AppHandle) -> Result<Value, String> {
    restore_history(&app, false).await
}

#[tauri::command]
async fn doc_redo(app: tauri::AppHandle) -> Result<Value, String> {
    restore_history(&app, true).await
}

fn apply_history_candidate(document: &mut Document, candidate: Document, index: usize) -> Result<(), String> {
    if document.document_instance_id != candidate.document_instance_id || document.revision + 1 != candidate.revision {
        return Err(geo_err("document_changed", "Документ изменился во время отмены или повтора."));
    }
    if candidate.error.is_some() {
        document.error = candidate.error;
        return Ok(());
    }
    document.snap = candidate.snap;
    document.index = index;
    document.revision = candidate.revision;
    document.stats = candidate.stats;
    document.mesh = candidate.mesh;
    document.error = None;
    document.dirty = true;
    Ok(())
}

async fn restore_history(app: &tauri::AppHandle, redo: bool) -> Result<Value, String> {
    let _task = DocumentTask::begin();
    let pending = with_store(|store| {
        let slot = store.active.clone();
        let document = active_doc(store);
        let index = if redo {
            (document.index + 1 < document.history.len()).then_some(document.index + 1)
        } else {
            document.index.checked_sub(1)
        }?;
        Some((slot, index, document.candidate(document.history[index].clone())))
    }).await;
    let Some((slot, index, mut candidate)) = pending else {
        return Ok(current_state().await);
    };
    rebuild(app, &mut candidate).await;
    with_store(|store| {
        if store.active != slot {
            return Err(geo_err("document_changed", "Активный документ изменился во время отмены или повтора."));
        }
        let document = active_doc(store);
        apply_history_candidate(document, candidate, index)?;
        Ok(document.state(&slot))
    }).await
}

#[tauri::command]
async fn doc_get_state() -> Result<Value, String> {
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_get_mesh() -> Result<Value, String> {
    let mesh_resource = with_store(|s| {
        let doc = active_doc(s);
        doc.mesh.clone()
    })
    .await;
    let resource = mesh_resource.ok_or_else(|| geo_err("no_model", "модель ещё не построена"))?;
    let path = resource
        .get("path")
        .and_then(Value::as_str)
        .ok_or_else(|| geo_err("mesh_invalid", "ресурс сетки не содержит путь"))?;
    let mut mesh = read_mesh_resource(path, None)?;
    mesh["face_ranges"] = resource
        .get("face_ranges")
        .cloned()
        .unwrap_or_else(|| json!([]));
    Ok(mesh)
}

fn mesh_layout(data: &[u8]) -> Result<(usize, usize), String> {
    if data.len() < 8 {
        return Err(geo_err(
            "mesh_invalid",
            "ресурс сетки короче обязательного заголовка",
        ));
    }
    let nv = u32::from_le_bytes(data[0..4].try_into().unwrap()) as usize;
    let nt = u32::from_le_bytes(data[4..8].try_into().unwrap()) as usize;
    let position_bytes = nv
        .checked_mul(3)
        .and_then(|count| count.checked_mul(std::mem::size_of::<f32>()))
        .ok_or_else(|| geo_err("mesh_invalid", "размер массива вершин переполнен"))?;
    let index_bytes = nt
        .checked_mul(3)
        .and_then(|count| count.checked_mul(std::mem::size_of::<u32>()))
        .ok_or_else(|| geo_err("mesh_invalid", "размер массива индексов переполнен"))?;
    let expected_len = 8usize
        .checked_add(position_bytes)
        .and_then(|size| size.checked_add(index_bytes))
        .ok_or_else(|| geo_err("mesh_invalid", "размер ресурса сетки переполнен"))?;
    if data.len() != expected_len {
        return Err(geo_err(
            "mesh_invalid",
            format!(
                "длина ресурса сетки не совпадает с заголовком: {} вместо {expected_len}",
                data.len()
            ),
        ));
    }
    Ok((nv, nt))
}

fn mesh_sha256(data: &[u8]) -> String {
    format!("{:x}", Sha256::digest(data))
}

fn validate_mesh_sha256(data: &[u8], expected_sha256: &str) -> Result<(), String> {
    if mesh_sha256(data) != expected_sha256 {
        return Err(geo_err(
            "mesh_hash_mismatch",
            "ресурс сетки изменился или повреждён",
        ));
    }
    Ok(())
}

fn read_mesh_bytes(path: &str, expected_sha256: Option<&str>) -> Result<Vec<u8>, String> {
    let data = std::fs::read(path)
        .map_err(|e| geo_err("mesh_unavailable", format!("чтение сетки: {e}")))?;
    mesh_layout(&data)?;
    if let Some(expected) = expected_sha256 {
        validate_mesh_sha256(&data, expected)?;
    }
    Ok(data)
}

fn mesh_json(data: &[u8]) -> Result<Value, String> {
    let (nv, nt) = mesh_layout(data)?;
    let mut positions = Vec::with_capacity(nv * 3);
    let mut off = 8;
    for _ in 0..nv * 3 {
        positions.push(f32::from_le_bytes(data[off..off + 4].try_into().unwrap()));
        off += 4;
    }
    let mut indices = Vec::with_capacity(nt * 3);
    for _ in 0..nt * 3 {
        indices.push(u32::from_le_bytes(data[off..off + 4].try_into().unwrap()));
        off += 4;
    }
    Ok(json!({
        "vertex_count": nv, "triangle_count": nt,
        "positions": positions, "indices": indices,
    }))
}

fn read_mesh_resource(path: &str, expected_sha256: Option<&str>) -> Result<Value, String> {
    let data = read_mesh_bytes(path, expected_sha256)?;
    mesh_json(&data)
}

fn mesh_resource_metadata(resource: &Value) -> Result<Value, String> {
    let path = resource
        .get("path")
        .and_then(Value::as_str)
        .ok_or_else(|| geo_err("mesh_invalid", "ресурс сетки не содержит путь"))?;
    let sha256 = resource
        .get("sha256")
        .and_then(Value::as_str)
        .filter(|value| value.len() == 64 && value.bytes().all(|byte| byte.is_ascii_hexdigit()))
        .ok_or_else(|| geo_err("mesh_invalid", "ресурс сетки не содержит корректный sha256"))?;
    let bytes = resource
        .get("bytes")
        .and_then(Value::as_u64)
        .ok_or_else(|| geo_err("mesh_invalid", "ресурс сетки не содержит размер"))?;
    let vertex_count = resource
        .get("vertex_count")
        .and_then(Value::as_u64)
        .ok_or_else(|| geo_err("mesh_invalid", "ресурс сетки не содержит число вершин"))?;
    let triangle_count = resource
        .get("triangle_count")
        .and_then(Value::as_u64)
        .ok_or_else(|| geo_err("mesh_invalid", "ресурс сетки не содержит число треугольников"))?;
    let face_ranges = resource
        .get("face_ranges")
        .cloned()
        .unwrap_or_else(|| json!([]));
    if !face_ranges.is_array() {
        return Err(geo_err(
            "mesh_invalid",
            "ресурс сетки содержит некорректные диапазоны граней",
        ));
    }
    Ok(json!({
        "path": path,
        "bytes": bytes,
        "sha256": sha256,
        "vertex_count": vertex_count,
        "triangle_count": triangle_count,
        "face_ranges": face_ranges,
    }))
}

fn validate_mesh_resource(resource: &Value, data: &[u8]) -> Result<(), String> {
    let metadata = mesh_resource_metadata(resource)?;
    let (vertex_count, triangle_count) = mesh_layout(data)?;
    let metadata_bytes = metadata["bytes"].as_u64().unwrap();
    let metadata_vertices = metadata["vertex_count"].as_u64().unwrap();
    let metadata_triangles = metadata["triangle_count"].as_u64().unwrap();
    if metadata_bytes != data.len() as u64
        || metadata_vertices != vertex_count as u64
        || metadata_triangles != triangle_count as u64
    {
        return Err(geo_err(
            "mesh_invalid",
            "метаданные ресурса сетки не совпадают с бинарным содержимым",
        ));
    }
    Ok(())
}

#[tauri::command]
async fn doc_get_mesh_meta() -> Result<Value, String> {
    let resource = with_store(|s| active_doc(s).mesh.clone())
        .await
        .ok_or_else(|| geo_err("no_model", "модель ещё не построена"))?;
    let mut metadata = mesh_resource_metadata(&resource)?;
    metadata
        .as_object_mut()
        .expect("metadata is an object")
        .remove("path");
    Ok(metadata)
}

#[tauri::command]
async fn doc_get_mesh_binary(expected_sha256: String) -> Result<tauri::ipc::Response, String> {
    let resource = with_store(|s| active_doc(s).mesh.clone())
        .await
        .ok_or_else(|| geo_err("no_model", "модель ещё не построена"))?;
    let metadata = mesh_resource_metadata(&resource)?;
    let current_sha256 = metadata["sha256"].as_str().unwrap();
    if current_sha256 != expected_sha256 {
        return Err(geo_err(
            "mesh_stale",
            "модель изменилась до загрузки сетки; запросите актуальные метаданные",
        ));
    }
    let path = metadata["path"].as_str().unwrap();
    let data = read_mesh_bytes(path, Some(&expected_sha256))?;
    validate_mesh_resource(&resource, &data)?;
    Ok(tauri::ipc::Response::new(data))
}

#[tauri::command]
async fn doc_get_imported_mesh(path: String) -> Result<Value, String> {
    let mut mesh = read_mesh_resource(&path, None)?;
    mesh["face_ranges"] = json!([]);
    Ok(mesh)
}

#[tauri::command]
async fn doc_get_imported_mesh_binary(
    path: String,
    expected_sha256: String,
) -> Result<tauri::ipc::Response, String> {
    let data = read_mesh_bytes(&path, Some(&expected_sha256))?;
    Ok(tauri::ipc::Response::new(data))
}

fn document_schema_version(doc: &Document) -> u32 {
    if doc.snap.operations.iter().any(|operation| {
        matches!(operation["op"].as_str(), Some("resize_body" | "resize_parametric" | "mesh_deform"))
            || operation.get("enabled").is_some()
            || (operation["op"] == "transform" && (operation.get("rotate_deg").is_some() || operation.get("pivot").is_some()))
            || (operation["op"] == "mesh_transform" && operation.get("pivot").is_some())
    }) { return 6; }
    if doc.snap.operations.iter().any(|operation| operation["op"] == "step_source") {
        return 5;
    }
    if doc.snap.parts.iter().any(|part| {
        matches!(part.get("template").and_then(Value::as_str), Some("box" | "cylinder" | "sphere"))
    }) || doc.snap.operations.iter().any(|operation| {
        operation.get("op").and_then(Value::as_str) == Some("face_offset")
            || (operation.get("op").and_then(Value::as_str) == Some("split")
                && operation.get("separate").and_then(Value::as_bool) == Some(true))
    }) {
        4
    } else {
        3
    }
}

fn save_document(doc: &Document, target: &PathBuf) -> Result<(), String> {
    let tmp = target.with_extension("printforge.tmp");
    let schema_version = document_schema_version(doc);
    let manifest = json!({
        "schema_version": schema_version, "app": "PrintForge",
        "app_version": APP_VERSION, "units": "mm", "kernel": "build123d/OCP",
    });
    let document = json!({
        "schema_version": schema_version, "units": "mm",
        "document_id": doc.doc_id,
        "template": doc.snap.parts.first().and_then(|p| p.get("template")),
        "parts": doc.snap.parts,
        "parameters": doc.snap.parts.first().and_then(|p| p.get("params")).cloned().unwrap_or(json!({})),
        "expressions": doc.snap.expressions,
        "operations": doc.snap.operations,
    });
    {
        let file = std::fs::File::create(&tmp)
            .map_err(|e| format!("не удалось создать файл: {e}"))?;
        let mut zip = zip::ZipWriter::new(file);
        let opts = zip::write::SimpleFileOptions::default()
            .compression_method(zip::CompressionMethod::Deflated);
        zip.start_file("manifest.json", opts).map_err(|e| e.to_string())?;
        zip.write_all(manifest.to_string().as_bytes()).map_err(|e| e.to_string())?;
        zip.start_file("document.json", opts).map_err(|e| e.to_string())?;
        zip.write_all(document.to_string().as_bytes()).map_err(|e| e.to_string())?;
        zip.finish().map_err(|e| e.to_string())?;
    }
    std::fs::rename(&tmp, target).map_err(|e| format!("замена файла: {e}"))
}

#[tauri::command]
async fn doc_save(path: String) -> Result<Value, String> {
    let _task = DocumentTask::begin();
    let target = PathBuf::from(&path);
    with_store(|s| {
        let doc = active_doc(s);
        save_document(doc, &target)?;
        doc.path = Some(target.clone());
        doc.dirty = false;
        Ok::<(), String>(())
    })
    .await?;
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_save_main(path: String) -> Result<Value, String> {
    let _task = DocumentTask::begin();
    with_store(|store| {
        let document = &mut store.main;
        let target = PathBuf::from(path);
        save_document(document, &target)?;
        document.path = Some(target);
        document.dirty = false;
        Ok(document.state("main"))
    }).await
}

fn document_is_busy() -> bool {
    DOCUMENT_TASKS.load(std::sync::atomic::Ordering::SeqCst) > 0
        || GEOMETRY_TASK.lock().map(|task| task.is_some()).unwrap_or(true)
        || ai::has_active_tasks()
}

fn confirm_close_document(
    document: &Document,
    expected_instance: u64,
    expected_revision: u64,
    discard: bool,
    busy: bool,
) -> Result<(), String> {
    if busy {
        return Err(geo_err("document_busy", "Дождитесь завершения или отмените текущее вычисление перед закрытием."));
    }
    if document.document_instance_id != expected_instance || document.revision != expected_revision {
        return Err(geo_err("document_changed", "Документ изменился. Повторите закрытие после проверки изменений."));
    }
    if document.dirty && !discard {
        return Err(geo_err("document_unsaved", "Сначала сохраните текущий документ."));
    }
    Ok(())
}

#[tauri::command]
async fn doc_confirm_close(
    app: tauri::AppHandle,
    expected_document_instance_id: u64,
    expected_revision: u64,
    discard: bool,
) -> Result<(), String> {
    with_store(|store| {
        confirm_close_document(
            &store.main, expected_document_instance_id, expected_revision, discard, document_is_busy(),
        )?;
        CLOSE_CONFIRMED.store(true, std::sync::atomic::Ordering::SeqCst);
        Ok::<(), String>(())
    }).await?;
    app.exit(0);
    Ok(())
}

fn request_application_close(app: tauri::AppHandle) {
    tauri::async_runtime::spawn(async move {
        if document_is_busy() {
            let _ = app.emit("printforge-close-blocked", json!({
                "message": "Дождитесь завершения или отмените текущее вычисление перед закрытием.",
            }));
            return;
        }
        let pending = with_store(|store| {
            if document_is_busy() {
                return Err(geo_err("document_busy", "Дождитесь завершения или отмените текущее вычисление перед закрытием."));
            }
            if store.main.dirty {
                Ok(Some(store.main.state("main")))
            } else {
                CLOSE_CONFIRMED.store(true, std::sync::atomic::Ordering::SeqCst);
                Ok(None)
            }
        }).await;
        match pending {
            Ok(Some(document)) => { let _ = app.emit("printforge-close-requested", document); }
            Ok(None) => app.exit(0),
            Err(error) => {
                let detail: Value = serde_json::from_str(&error).unwrap_or_else(|_| json!({"message": error}));
                let _ = app.emit("printforge-close-blocked", json!({"message": detail["message"]}));
            }
        }
    });
}

fn replace_built_document(
    current: &mut Document,
    mut candidate: Document,
    expected_instance: u64,
    expected_revision: u64,
) -> Result<(), String> {
    if current.document_instance_id != expected_instance || current.revision != expected_revision {
        return Err(geo_err("document_changed", "Документ изменился во время открытия файла."));
    }
    if let Some(error) = candidate.error.as_ref() {
        return Err(error.to_string());
    }
    candidate.commit(candidate.snap.clone());
    candidate.dirty = false;
    *current = candidate;
    Ok(())
}

#[tauri::command]
async fn doc_open(app: tauri::AppHandle, path: String) -> Result<Value, String> {
    let _task = DocumentTask::begin();
    let file = std::fs::File::open(&path).map_err(|e| format!("открытие файла: {e}"))?;
    let mut zip = zip::ZipArchive::new(file)
        .map_err(|_| geo_err("bad_file", "Это не файл проекта PrintForge."))?;
    let mut buf = String::new();
    zip.by_name("document.json")
        .map_err(|_| geo_err("bad_file", "В проекте нет document.json."))?
        .read_to_string(&mut buf)
        .map_err(|e| e.to_string())?;
    let doc_json: Value = serde_json::from_str(&buf)
        .map_err(|_| geo_err("bad_file", "document.json повреждён."))?;
    let schema_version = doc_json
        .get("schema_version")
        .and_then(Value::as_u64)
        .unwrap_or(1);
    if schema_version > u64::from(SCHEMA_VERSION) {
        return Err(geo_err(
            "unsupported_project_version",
            &format!(
                "Проект создан в более новой версии формата ({schema_version}). Обновите PrintForge."
            ),
        ));
    }
    let document_id = doc_json.get("document_id").and_then(Value::as_u64);
    const TEMPLATES: [&str; 7] = [
        "box", "cylinder", "sphere", "plate_with_holes", "washer", "bracket_l", "case_with_lid",
    ];
    let template = doc_json.get("template").and_then(Value::as_str).map(String::from);
    if template.as_deref().is_some_and(|value| !TEMPLATES.contains(&value)) {
        return Err(geo_err(
            "bad_file",
            format!("Неизвестный шаблон в проекте: {}", template.as_deref().unwrap()),
        ));
    }
    let mut snap = Snapshot {
        parts: vec![],
        expressions: BTreeMap::new(),
        operations: doc_json.get("operations").and_then(Value::as_array).cloned().unwrap_or_default(),
        part_n: 0,
    };
    if let Some(parts) = doc_json.get("parts").and_then(Value::as_array) {
        snap.parts = parts.clone();
        snap.part_n = parts.iter().filter_map(|part| {
            part["part_id"].as_str()?.strip_prefix("part-")?.parse::<u64>().ok()
        }).max().unwrap_or(parts.len() as u64);
    }
    if snap.parts.is_empty() && snap.operations.is_empty() && template.is_some() {
        let mut params = BTreeMap::new();
        if let Some(obj) = doc_json.get("parameters").and_then(Value::as_object) {
            for (k, v) in obj {
                if let Some(n) = v.as_f64() {
                    params.insert(k.clone(), n);
                }
            }
        }
        snap.part_n = 1;
        snap.parts.push(make_part(1, template.as_deref().unwrap(), params));
    }
    if let Some(obj) = doc_json.get("expressions").and_then(Value::as_object) {
        for (k, v) in obj {
            if let Some(sv) = v.as_str() {
                snap.expressions.insert(k.clone(), sv.to_string());
            }
        }
    }
    let (slot, expected_instance, expected_revision) = with_store(|store| {
        let slot = store.active.clone();
        let document = active_doc(store);
        (slot, document.document_instance_id, document.revision)
    }).await;
    let mut candidate = document_id.map(Document::with_document_id).unwrap_or_else(Document::new);
    candidate.snap = snap;
    candidate.path = Some(PathBuf::from(path));
    rebuild(&app, &mut candidate).await;
    with_store(|store| {
        if store.active != slot {
            return Err(geo_err("document_changed", "Активный документ изменился во время открытия файла."));
        }
        let document = active_doc(store);
        replace_built_document(document, candidate, expected_instance, expected_revision)?;
        Ok(document.state(&slot))
    }).await
}

#[tauri::command]
async fn doc_export(
    app: tauri::AppHandle,
    path: String,
    format: String,
    linear_deflection: Option<f64>,
) -> Result<Value, String> {
    let (params, revision) = with_store(|s| {
        let doc = active_doc(s);
        (doc.build_params(), doc.revision)
    })
    .await;
    if params["template"].is_null() && params["parts"].is_null() {
        return Err(geo_err("no_model", "нет модели для экспорта"));
    }
    let mut call = params;
    call["format"] = json!(format);
    call["path"] = json!(path);
    if let Some(t) = linear_deflection {
        call["linear_deflection"] = json!(t);
    }
    worker_call(&app, "export", call, revision).await
}

#[tauri::command]
async fn doc_export_stl(
    app: tauri::AppHandle,
    path: String,
    linear_deflection: Option<f64>,
) -> Result<Value, String> {
    doc_export(app, path, "stl".into(), linear_deflection).await
}

#[tauri::command]
async fn doc_import(
    app: tauri::AppHandle,
    path: String,
    format: String,
    unit_scale: Option<f64>,
) -> Result<Value, String> {
    if format.eq_ignore_ascii_case("step") {
        let _task = DocumentTask::begin();
        let source_path = PathBuf::from(&path);
        let metadata = std::fs::metadata(&source_path)
            .map_err(|error| geo_err("file_read_failed", format!("Не удалось прочитать STEP: {error}")))?;
        if metadata.len() > 25 * 1024 * 1024 {
            return Err(geo_err("step_too_large", "STEP source превышает лимит 25 MiB."));
        }
        let source = std::fs::read(&source_path)
            .map_err(|error| geo_err("file_read_failed", format!("Не удалось прочитать STEP: {error}")))?;
        if source.len() > 25 * 1024 * 1024 {
            return Err(geo_err("step_too_large", "STEP source превышает лимит 25 MiB."));
        }
        let source_name = source_path.file_name().map(|value| value.to_string_lossy().into_owned())
            .unwrap_or_else(|| "import.step".into());
        let operation = json!({
            "op": "step_source",
            "source_sha256": mesh_sha256(&source),
            "source_base64": BASE64_STANDARD.encode(source),
            "source_name": source_name,
        });
        let (slot, expected_instance, expected_revision) = with_store(|store| {
            let slot = store.active.clone();
            let document = active_doc(store);
            (slot, document.document_instance_id, document.revision)
        }).await;
        let mut candidate = Document::new();
        candidate.snap.operations.push(operation);
        rebuild(&app, &mut candidate).await;
        return with_store(|store| {
            if store.active != slot {
                return Err(geo_err("document_changed", "Активный документ изменился во время импорта STEP."));
            }
            let document = active_doc(store);
            replace_built_document(document, candidate, expected_instance, expected_revision)?;
            document.dirty = true;
            Ok(json!({
                "mode": "brep", "stats": document.stats, "mesh": document.mesh,
                "document": document.state(&slot),
            }))
        }).await;
    }
    let revision = with_store(|s| active_doc(s).revision).await;
    let mut call = json!({"path": path, "format": format});
    if let Some(sc) = unit_scale {
        call["unit_scale"] = json!(sc);
    }
    worker_call(&app, "import", call, revision).await
}

fn is_mesh_snapshot(snapshot: &Snapshot) -> bool {
    matches!(snapshot.operations.first()
        .and_then(|operation| operation.get("op"))
        .and_then(Value::as_str), Some("mesh_source" | "image_relief_source"))
}

#[tauri::command]
async fn doc_mesh_import_apply(
    app: tauri::AppHandle,
    path: String,
    format: String,
    unit_scale: Option<f64>,
) -> Result<Value, String> {
    let mesh_format = format.to_lowercase();
    if !["stl", "obj", "ply"].contains(&mesh_format.as_str()) {
        return Err(geo_err("bad_params", format!(
            "Mesh workflow не поддерживает формат {mesh_format}.")));
    }
    let source_path = PathBuf::from(&path);
    let metadata = std::fs::metadata(&source_path)
        .map_err(|error| geo_err("file_read_failed", format!("Не удалось прочитать mesh: {error}")))?;
    if metadata.len() > 25 * 1024 * 1024 {
        return Err(geo_err("mesh_too_large", "Mesh source превышает лимит 25 MiB."));
    }
    let source = std::fs::read(&source_path)
        .map_err(|error| geo_err("file_read_failed", format!("Не удалось прочитать mesh: {error}")))?;
    let source_name = source_path.file_name()
        .map(|value| value.to_string_lossy().to_string())
        .unwrap_or_else(|| "mesh".into());
    let operation = json!({
        "op": "mesh_source",
        "format": mesh_format,
        "source_base64": BASE64_STANDARD.encode(source),
        "unit_scale": unit_scale.unwrap_or(1.0),
        "source_name": source_name,
    });
    edit_snapshot(&app, |snapshot| {
        *snapshot = Snapshot {
            parts: vec![],
            expressions: BTreeMap::new(),
            operations: vec![operation],
            part_n: 0,
        };
        Ok(())
    }).await
}

async fn apply_mesh_op(app: &tauri::AppHandle, operation: Value) -> Result<Value, String> {
    let is_mesh = with_store(|store| is_mesh_snapshot(&active_doc(store).snap)).await;
    if !is_mesh {
        return Err(geo_err("mesh_source_missing", "Сначала примените STL как mesh-документ."));
    }
    apply_op(app, operation).await
}

#[tauri::command]
async fn doc_mesh_transform(
    app: tauri::AppHandle,
    translate: Vec<f64>,
    rotate_deg: Vec<f64>,
    scale: Value,
) -> Result<Value, String> {
    apply_mesh_op(&app, json!({
        "op": "mesh_transform", "translate": translate,
        "rotate_deg": rotate_deg, "scale": scale,
    })).await
}

#[tauri::command]
async fn doc_mesh_repair(app: tauri::AppHandle, action: Option<String>) -> Result<Value, String> {
    apply_mesh_op(&app, json!({
        "op": "mesh_repair", "action": action.unwrap_or_else(|| "fill_holes".into()),
    })).await
}

#[tauri::command]
async fn doc_mesh_decimate(
    app: tauri::AppHandle,
    target_ratio: f64,
    minimum_ratio: Option<f64>,
    maximum_ratio: Option<f64>,
    volume_tolerance: Option<f64>,
) -> Result<Value, String> {
    let mut operation = json!({"op": "mesh_decimate", "target_ratio": target_ratio});
    if let Some(value) = minimum_ratio { operation["minimum_ratio"] = json!(value); }
    if let Some(value) = maximum_ratio { operation["maximum_ratio"] = json!(value); }
    if let Some(value) = volume_tolerance { operation["volume_tolerance"] = json!(value); }
    apply_mesh_op(&app, operation).await
}

fn image_relief_operation(
    path: &str,
    model: &str,
    seed: i64,
    width_mm: f64,
    relief_height: f64,
    base_thickness: f64,
    samples: u32,
    noise_strength: f64,
    invert: bool,
    expected_sha256: Option<&str>,
) -> Result<(Value, String), String> {
    let source_path = PathBuf::from(path);
    let metadata = std::fs::metadata(&source_path)
        .map_err(|error| geo_err("file_read_failed", format!("Не удалось прочитать изображение: {error}")))?;
    if metadata.len() > 8 * 1024 * 1024 {
        return Err(geo_err("image_too_large", "Изображение превышает лимит 8 MiB."));
    }
    let source = std::fs::read(&source_path)
        .map_err(|error| geo_err("file_read_failed", format!("Не удалось прочитать изображение: {error}")))?;
    let source_sha256 = format!("{:x}", Sha256::digest(&source));
    if expected_sha256.is_some_and(|expected| expected != source_sha256) {
        return Err(geo_err(
            "image_changed",
            "Изображение изменилось после preview. Выполните preview повторно.",
        ));
    }
    let image_format = source_path.extension()
        .map(|value| value.to_string_lossy().to_lowercase())
        .map(|value| if value == "jpg" { "jpeg".into() } else { value })
        .unwrap_or_else(|| "image".into());
    let source_name = source_path.file_name()
        .map(|value| value.to_string_lossy().to_string())
        .unwrap_or_else(|| "image".into());
    Ok((json!({
        "op": "image_relief_source",
        "format": image_format,
        "source_base64": BASE64_STANDARD.encode(source),
        "source_name": source_name,
        "model": model,
        "seed": seed,
        "width_mm": width_mm,
        "relief_height": relief_height,
        "base_thickness": base_thickness,
        "samples": samples,
        "noise_strength": noise_strength,
        "invert": invert,
    }), source_sha256))
}

async fn image_settings_sha256(
    app: &tauri::AppHandle,
    path: &str,
    operation: &Value,
    source_sha256: &str,
    revision: u64,
) -> Result<String, String> {
    let mut settings = operation.as_object().cloned().unwrap_or_default();
    for key in ["op", "format", "source_base64", "source_name"] {
        settings.remove(key);
    }
    settings.insert("path".into(), json!(path));
    settings.insert("source_sha256".into(), json!(source_sha256));
    let result = worker_call(app, "image_relief_settings_hash", Value::Object(settings), revision).await?;
    result["settings_sha256"].as_str().map(String::from)
        .ok_or_else(|| geo_err("image_preview_invalid", "Не удалось проверить настройки предпросмотра."))
}

fn validate_image_settings_hash(expected: &str, actual: &str) -> Result<(), String> {
    if expected.is_empty() || expected != actual {
        return Err(geo_err("image_settings_changed", "Настройки изменились после preview. Выполните preview повторно."));
    }
    Ok(())
}

#[tauri::command]
async fn image_relief_preview(
    app: tauri::AppHandle,
    path: String,
    model: String,
    seed: i64,
    width_mm: f64,
    relief_height: f64,
    base_thickness: f64,
    samples: u32,
    noise_strength: f64,
    invert: bool,
) -> Result<Value, String> {
    let (operation, source_sha256) = image_relief_operation(
        &path, &model, seed, width_mm, relief_height, base_thickness,
        samples, noise_strength, invert, None)?;
    let revision = with_store(|store| active_doc(store).revision).await;
    let settings_sha256 = image_settings_sha256(&app, &path, &operation, &source_sha256, revision).await?;
    let mut params = operation.as_object().cloned().unwrap_or_default();
    params.remove("op");
    let mut result = worker_call(&app, "image_relief_preview", Value::Object(params), revision).await?;
    result["source_sha256"] = json!(source_sha256);
    result["settings_sha256"] = json!(settings_sha256);
    Ok(result)
}

#[tauri::command]
async fn doc_image_relief_apply(
    app: tauri::AppHandle,
    path: String,
    model: String,
    seed: i64,
    width_mm: f64,
    relief_height: f64,
    base_thickness: f64,
    samples: u32,
    noise_strength: f64,
    invert: bool,
    expected_sha256: String,
    expected_settings_sha256: String,
) -> Result<Value, String> {
    let (operation, source_sha256) = image_relief_operation(
        &path, &model, seed, width_mm, relief_height, base_thickness,
        samples, noise_strength, invert, Some(&expected_sha256))?;
    let revision = with_store(|store| active_doc(store).revision).await;
    let actual_settings_sha256 = image_settings_sha256(&app, &path, &operation, &source_sha256, revision).await?;
    validate_image_settings_hash(&expected_settings_sha256, &actual_settings_sha256)?;
    edit_snapshot(&app, |snapshot| {
        *snapshot = Snapshot {
            parts: vec![],
            expressions: BTreeMap::new(),
            operations: vec![operation],
            part_n: 0,
        };
        Ok(())
    }).await
}

#[tauri::command]
async fn print_check(app: tauri::AppHandle, printer: Value) -> Result<Value, String> {
    let (params, revision) = with_store(|s| {
        let doc = active_doc(s);
        (doc.build_params(), doc.revision)
    })
    .await;
    if params["template"].is_null() && params["parts"].is_null() {
        return Err(geo_err("no_model", "Сначала создайте деталь."));
    }
    let mut call = params;
    call["printer"] = printer;
    worker_call(&app, "print_check", call, revision).await
}

#[tauri::command]
async fn doc_switch_slot(slot: String) -> Result<Value, String> {
    if slot != "main" && slot != "tutorial" {
        return Err(geo_err("bad_slot", "неизвестный слот документа"));
    }
    with_store(|s| s.active = slot).await;
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_new_tutorial() -> Result<Value, String> {
    with_store(|s| {
        s.tutorial = Document::new();
        s.active = "tutorial".into();
    })
    .await;
    Ok(current_state().await)
}

// ---------- файловые диалоги ----------

#[tauri::command]
async fn dialog_save_path(
    app: tauri::AppHandle,
    default_name: String,
    filter_name: String,
    extensions: Vec<String>,
) -> Result<Option<String>, String> {
    let exts: Vec<&str> = extensions.iter().map(String::as_str).collect();
    let result = app
        .dialog()
        .file()
        .set_file_name(&default_name)
        .add_filter(&filter_name, &exts)
        .blocking_save_file();
    Ok(result.and_then(|p| p.into_path().ok().map(|p| p.to_string_lossy().into_owned())))
}

#[tauri::command]
async fn dialog_open_path(
    app: tauri::AppHandle,
    filter_name: String,
    extensions: Vec<String>,
) -> Result<Option<String>, String> {
    let exts: Vec<&str> = extensions.iter().map(String::as_str).collect();
    let result = app
        .dialog()
        .file()
        .add_filter(&filter_name, &exts)
        .blocking_pick_file();
    Ok(result.and_then(|p| p.into_path().ok().map(|p| p.to_string_lossy().into_owned())))
}

fn write_performance_report(path: Option<PathBuf>, payload: &Value) -> Result<bool, String> {
    let Some(path) = path else {
        return Ok(false);
    };
    if !path.is_absolute() {
        return Err("PF_PERF_REPORT должен содержать абсолютный путь".into());
    }
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent).map_err(|error| error.to_string())?;
    }
    let temporary = path.with_extension("json.tmp");
    let report = json!({
        "pid": std::process::id(),
        "payload": payload,
    });
    std::fs::write(&temporary, report.to_string()).map_err(|error| error.to_string())?;
    std::fs::rename(&temporary, &path).map_err(|error| error.to_string())?;
    Ok(true)
}

#[tauri::command]
fn performance_config() -> Value {
    let mode = std::env::var("PF_PERF_MODE").unwrap_or_default();
    let report_path = std::env::var_os("PF_PERF_REPORT");
    let enabled = report_path.is_some() && matches!(mode.as_str(), "startup" | "workload");
    json!({
        "enabled": enabled,
        "mode": mode,
        "project_path": std::env::var("PF_PERF_PROJECT").ok(),
        "duration_ms": std::env::var("PF_PERF_DURATION_MS")
            .ok()
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or(3000),
    })
}

#[tauri::command]
fn performance_report(payload: Value) -> Result<bool, String> {
    write_performance_report(std::env::var_os("PF_PERF_REPORT").map(PathBuf::from), &payload)
}

#[tauri::command]
fn native_e2e_config() -> Value {
    let mode = std::env::var("PF_E2E_MODE").unwrap_or_default();
    let report_path = std::env::var_os("PF_E2E_REPORT");
    let enabled = report_path.is_some() && matches!(mode.as_str(), "ai-http-cancel" | "ai-cad-cancel");
    json!({
        "enabled": enabled,
        "mode": mode,
        "cancel_delay_ms": std::env::var("PF_E2E_CANCEL_DELAY_MS")
            .ok()
            .and_then(|value| value.parse::<u64>().ok())
            .unwrap_or(800),
    })
}

#[tauri::command]
fn native_e2e_report(payload: Value) -> Result<bool, String> {
    write_performance_report(std::env::var_os("PF_E2E_REPORT").map(PathBuf::from), &payload)
}

// ---------- автосохранение (DOC-007) ----------

fn spawn_autosave() {
    tauri::async_runtime::spawn(async {
        let mut interval = tokio::time::interval(std::time::Duration::from_secs(30));
        loop {
            interval.tick().await;
            let _ = with_store(|s| {
                for doc in [&mut s.main] {
                    if doc.dirty {
                        if let Some(path) = doc.path.clone() {
                            if save_document(doc, &path).is_ok() {
                                doc.dirty = false;
                            }
                        }
                    }
                }
            })
            .await;
        }
    });
}

fn main() {
    tauri::Builder::default()
        .menu(application_menu)
        .on_menu_event(|app, event| {
            if event.id().as_ref() == QUIT_MENU_ID {
                request_application_close(app.clone());
            }
        })
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_process::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if window.label() == "main" && !CLOSE_CONFIRMED.load(std::sync::atomic::Ordering::SeqCst) {
                    api.prevent_close();
                    request_application_close(window.app_handle().clone());
                }
            }
        })
        .setup(|app| {
            if let Ok(config_dir) = app.path().app_config_dir() {
                ai::initialize(&config_dir);
            }
            spawn_autosave();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            doc_create,
            doc_create_plate,
            doc_add_part,
            doc_boolean,
            doc_array,
            doc_mirror,
            doc_split,
            doc_transform,
            doc_profile_extrude,
            doc_sketch_extrude,
            sketch_solve,
            doc_constrained_sketch_extrude,
            doc_revolve,
            doc_sweep,
            doc_loft,
            doc_shell,
            doc_draft_prism,
            doc_rib,
            doc_fit_pocket,
            doc_vector_extrude,
            doc_text_relief,
            doc_thread_pair,
            doc_clearance_calibration,
            doc_split_connector_pair,
            doc_resize_body,
            doc_designer_action,
            doc_face_offset,
            doc_face_feature,
            doc_face_dome,
            doc_sheet_bend,
            doc_array_circular,
            doc_align,
            measure,
            doc_transaction,
            ai_providers,
            ai_configure,
            ai_test_connection,
            ai_plan,
            ai_cancel,
            geometry_cancel,
            ai_chat,
            doc_set_parameter,
            doc_fillet,
            doc_chamfer,
            doc_clear_error,
            doc_undo,
            doc_redo,
            doc_get_state,
            doc_get_mesh,
            doc_get_mesh_meta,
            doc_get_mesh_binary,
            doc_get_imported_mesh,
            doc_get_imported_mesh_binary,
            doc_save,
            doc_save_main,
            doc_confirm_close,
            doc_open,
            doc_export,
            doc_export_stl,
            doc_import,
            doc_mesh_import_apply,
            doc_mesh_transform,
            doc_mesh_repair,
            doc_mesh_decimate,
            image_relief_preview,
            doc_image_relief_apply,
            print_check,
            doc_switch_slot,
            doc_new_tutorial,
            dialog_save_path,
            dialog_open_path,
            performance_config,
            performance_report,
            native_e2e_config,
            native_e2e_report,
        ])
        .build(tauri::generate_context!())
        .expect("ошибка запуска PrintForge")
        .run(|app, event| {
            if let tauri::RunEvent::ExitRequested { api, .. } = event {
                if !CLOSE_CONFIRMED.load(std::sync::atomic::Ordering::SeqCst) {
                    api.prevent_exit();
                    request_application_close(app.clone());
                }
            }
        });
}

#[cfg(test)]
mod mesh_tests {
    use super::*;

    fn sample_mesh() -> Vec<u8> {
        let mut data = Vec::new();
        data.extend_from_slice(&3u32.to_le_bytes());
        data.extend_from_slice(&1u32.to_le_bytes());
        for value in [0.0f32, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0] {
            data.extend_from_slice(&value.to_le_bytes());
        }
        for index in [0u32, 1, 2] {
            data.extend_from_slice(&index.to_le_bytes());
        }
        data
    }

    #[test]
    fn mesh_binary_layout_and_json_decode_are_exact() {
        let data = sample_mesh();
        assert_eq!(mesh_layout(&data).unwrap(), (3, 1));
        let decoded = mesh_json(&data).unwrap();
        assert_eq!(decoded["vertex_count"], 3);
        assert_eq!(decoded["triangle_count"], 1);
        assert_eq!(decoded["indices"], json!([0, 1, 2]));
    }

    #[test]
    fn mesh_binary_rejects_truncated_and_trailing_bytes() {
        let data = sample_mesh();
        assert!(mesh_layout(&data[..data.len() - 1]).is_err());
        let mut trailing = data;
        trailing.push(0);
        assert!(mesh_layout(&trailing).is_err());
    }

    #[test]
    fn mesh_binary_hash_binds_resource_content() {
        let data = sample_mesh();
        let digest = mesh_sha256(&data);
        assert_eq!(digest.len(), 64);
        assert!(validate_mesh_sha256(&data, &digest).is_ok());
        let error = validate_mesh_sha256(&data[..data.len() - 1], &digest).unwrap_err();
        assert!(error.contains("mesh_hash_mismatch"));
    }

    #[test]
    fn geometry_task_cancel_signal_is_bounded_and_timeout_is_method_specific() {
        let (mut receiver, registration) = register_geometry_task().unwrap();
        assert_eq!(worker_request_timeout("build"), Duration::from_secs(120));
        assert_eq!(worker_request_timeout("import"), Duration::from_secs(300));
        assert!(request_geometry_cancel().unwrap());
        assert!(receiver.has_changed().unwrap());
        assert!(*receiver.borrow_and_update());
        drop(registration);
        assert!(!request_geometry_cancel().unwrap());
    }

    #[test]
    fn every_failed_candidate_preserves_redo_and_saved_state() {
        let mut document = Document::new();
        let mut confirmed = Snapshot::default();
        confirmed.parts.push(json!({"part_id": "part-1", "params": {"length": 80}}));
        confirmed.part_n = 1;
        document.commit(confirmed);

        document.commit(document.snap.clone());
        document.index -= 1;
        document.snap = document.history[document.index].clone();
        document.dirty = false;
        document.revision = 7;
        document.path = Some(PathBuf::from("confirmed.printforge"));
        document.stats = Some(json!({"volume": 24000}));
        document.mesh = Some(json!({"path": "confirmed.mesh"}));
        for operation in ["vector_extrude", "mesh_repair", "mesh_decimate", "profile_extrude", "transform", "parameter.set"] {
            document.error = None;
            let before = document.state("main");
            let mut candidate = document.candidate(document.snap.clone());
            candidate.snap.operations.push(json!({"op": operation}));
            candidate.revision += 1;
            candidate.error = Some(json!({"code": "geometry_error"}));
            document.apply_built_candidate(candidate).unwrap();
            let mut after = document.state("main");
            after["error"] = Value::Null;
            assert_eq!(after, before, "{operation}");
            assert_eq!(document.history.len(), 3);
            assert_eq!(document.index, 1);
        }
    }

    #[test]
    fn opening_invalid_geometry_is_atomic_and_valid_open_changes_instance() {
        let mut document = Document::new();
        document.snap.parts.push(json!({"part_id": "part-1", "params": {"length": 55}}));
        document.commit(document.snap.clone());
        document.revision = 9;
        document.stats = Some(json!({"volume": 33000}));
        let before = document.state("main");
        let instance = document.document_instance_id;
        let mut invalid = Document::new();
        invalid.snap.parts.push(json!({"params": {"length": -10}}));
        invalid.error = Some(json!({"code": "bad_params"}));
        assert!(replace_built_document(&mut document, invalid, instance, 9).is_err());
        assert_eq!(document.state("main"), before);
        let mut valid = Document::new();
        valid.snap.parts.push(json!({"params": {"length": 40}}));
        valid.stats = Some(json!({"volume": 24000}));
        valid.revision = 1;
        valid.path = Some(PathBuf::from("opened.printforge"));
        replace_built_document(&mut document, valid, instance, 9).unwrap();
        assert_ne!(document.document_instance_id, instance);
        assert!(!document.dirty);
        assert_eq!(document.stats.unwrap()["volume"], 24000);
    }

    #[test]
    fn close_confirmation_requires_saved_or_explicit_discard_and_current_identity() {
        let mut document = Document::new();
        document.dirty = true;
        let instance = document.document_instance_id;
        assert!(confirm_close_document(&document, instance, 0, false, false).unwrap_err().contains("document_unsaved"));
        assert!(confirm_close_document(&document, instance, 0, true, false).is_ok());
        assert!(confirm_close_document(&document, instance + 1, 0, true, false).is_err());
        assert!(confirm_close_document(&document, instance, 1, true, false).is_err());
        assert!(confirm_close_document(&document, instance, 0, true, true).unwrap_err().contains("document_busy"));
        document.dirty = false;
        assert!(confirm_close_document(&document, instance, 0, false, false).is_ok());
        assert!(confirm_close_document(&document, instance, 0, false, true).unwrap_err().contains("document_busy"));
    }

    #[test]
    fn image_apply_requires_the_actual_preview_settings_hash() {
        assert!(validate_image_settings_hash("", "current").is_err());
        assert!(validate_image_settings_hash("old", "current").unwrap_err().contains("image_settings_changed"));
        assert!(validate_image_settings_hash("current", "current").is_ok());
    }

    #[test]
    fn failed_undo_preserves_history_and_successful_undo_keeps_redo_branch() {
        let mut document = Document::new();
        let mut snapshot = Snapshot::default();
        snapshot.parts.push(json!({"part_id": "part-1", "params": {"length": 40}}));
        document.commit(snapshot);
        document.revision = 3;
        document.dirty = false;
        document.stats = Some(json!({"volume": 24000}));
        let before = document.state("main");
        let mut failed = document.candidate(document.history[0].clone());
        failed.revision = 4;
        failed.error = Some(json!({"code": "geometry_cancelled"}));
        apply_history_candidate(&mut document, failed, 0).unwrap();
        let mut after = document.state("main");
        after["error"] = Value::Null;
        assert_eq!(after, before);
        let mut valid = document.candidate(document.history[0].clone());
        valid.revision = 4;
        valid.stats = None;
        valid.mesh = None;
        apply_history_candidate(&mut document, valid, 0).unwrap();
        assert_eq!(document.index, 0);
        assert_eq!(document.history.len(), 2);
        assert_eq!(document.state("main")["can_redo"], true);
        assert_eq!(document.revision, 4);
    }

    #[test]
    fn direct_edit_projects_require_schema_four_and_legacy_projects_remain_three() {
        let mut document = Document::new();
        document.snap.parts.push(json!({"part_id": "part-1", "template": "washer"}));
        assert_eq!(document_schema_version(&document), 3);
        document.snap.operations.push(json!({"op": "split"}));
        assert_eq!(document_schema_version(&document), 3);
        document.snap.operations[0]["separate"] = json!(false);
        assert_eq!(document_schema_version(&document), 3);
        document.snap.operations[0]["separate"] = json!(true);
        assert_eq!(document_schema_version(&document), 4);
        document.snap.operations = vec![json!({"op": "face_offset"})];
        assert_eq!(document_schema_version(&document), 4);
        document.snap.operations.clear();
        for template in ["box", "cylinder", "sphere"] {
            document.snap.parts[0]["template"] = json!(template);
            assert_eq!(document_schema_version(&document), 4);
        }
        document.snap.operations.push(json!({"op": "step_source"}));
        assert_eq!(document_schema_version(&document), 5);
        for operation in [json!({"op": "resize_body"}), json!({"op": "resize_parametric"}),
            json!({"op": "mesh_deform"}), json!({"op": "fillet", "enabled": false}),
            json!({"op": "transform", "rotate_deg": [0, 0, 30]}), json!({"op": "mesh_transform", "pivot": [1, 2, 3]})] {
            document.snap.operations = vec![operation];
            assert_eq!(document_schema_version(&document), 6);
        }
    }

    #[test]
    fn failed_face_offset_candidate_preserves_redo_and_saved_document_state() {
        let mut document = Document::new();
        let mut first = Snapshot::default();
        first.parts.push(json!({"part_id": "part-1", "params": {"height": 20}}));
        first.part_n = 1;
        document.commit(first);
        let mut next = document.snap.clone();
        next.operations.push(json!({"op": "transform", "translate": [5, 0, 0]}));
        document.commit(next);
        document.index -= 1;
        document.snap = document.history[document.index].clone();
        document.dirty = false;
        document.revision = 7;
        document.stats = Some(json!({"volume": 24000}));
        document.mesh = Some(json!({"path": "confirmed.mesh"}));
        let before = document.state("main");
        let redo = document.history[document.index + 1].clone();

        let mut candidate = Document::with_document_id(document.doc_id);
        candidate.document_instance_id = document.document_instance_id;
        candidate.snap = document.snap.clone();
        candidate.snap.operations.push(json!({"op": "face_offset", "distance": -100}));
        candidate.revision = 8;
        candidate.error = Some(json!({"code": "face_offset_failed"}));
        document.apply_built_candidate(candidate).unwrap();

        let mut after = document.state("main");
        assert_eq!(after["error"]["code"], "face_offset_failed");
        after["error"] = Value::Null;
        assert_eq!(after, before);
        assert_eq!(document.history[document.index + 1].parts, redo.parts);
        assert_eq!(document.history[document.index + 1].operations, redo.operations);
        assert_eq!(document.mesh.as_ref().unwrap()["path"], "confirmed.mesh");
    }

    #[test]
    fn successful_face_offset_candidate_replaces_redo_once_and_rejects_stale_commit() {
        let mut document = Document::new();
        document.commit(Snapshot::default());
        document.commit(Snapshot::default());
        document.index -= 1;
        document.snap = document.history[document.index].clone();
        document.revision = 7;

        let mut candidate = Document::with_document_id(document.doc_id);
        candidate.document_instance_id = document.document_instance_id;
        candidate.snap = document.snap.clone();
        candidate.snap.operations.push(json!({"op": "face_offset", "distance": 3}));
        candidate.revision = 8;
        candidate.stats = Some(json!({"volume": 27600}));
        document.apply_built_candidate(candidate).unwrap();

        assert_eq!(document.revision, 8);
        assert_eq!(document.index, 2);
        assert_eq!(document.history.len(), 3);
        assert_eq!(document.snap.operations.len(), 1);
        assert_eq!(document.snap.operations[0]["op"], "face_offset");
        assert!(document.dirty);
        assert_eq!(document.stats.as_ref().unwrap()["volume"], 27600);

        let before = document.state("main");
        let stale = Document::with_document_id(document.doc_id);
        assert!(document.apply_built_candidate(stale).unwrap_err().contains("document_changed"));
        assert_eq!(document.state("main"), before);
    }

    #[test]
    fn performance_report_is_disabled_without_env_path_and_atomic_with_path() {
        assert!(!write_performance_report(None, &json!({"mode": "startup"})).unwrap());
        let path = std::env::temp_dir().join(format!(
            "printforge-perf-report-{}-{}.json",
            std::process::id(),
            std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_nanos()
        ));
        assert!(write_performance_report(Some(path.clone()), &json!({"fps": 60})).unwrap());
        let report: Value = serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
        assert_eq!(report["pid"], std::process::id());
        assert_eq!(report["payload"]["fps"], 60);
        std::fs::remove_file(path).unwrap();
    }
}
