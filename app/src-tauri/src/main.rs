// PrintForge M2: ядро приложения.
// Документ (шаблон, параметры, операции, история) — authoritative в этом
// процессе; геометрия — отдельный worker-процесс (JSON Lines stdio).
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io::{Read as _, Write as _};
use std::path::PathBuf;
use tauri::async_runtime::Receiver;
use tauri_plugin_dialog::DialogExt;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::Mutex;

const SCHEMA_VERSION: u32 = 2;
const APP_VERSION: &str = "0.1.0-m2";

// ---------- геометрический worker ----------

struct GeoWorker {
    child: CommandChild,
    rx: Receiver<CommandEvent>,
    buf: String,
    next_id: u64,
}

static WORKER: Mutex<Option<GeoWorker>> = Mutex::const_new(None);

fn geo_err(code: &str, message: impl Into<String>) -> String {
    json!({"code": code, "message": message.into(), "detail": ""}).to_string()
}

async fn worker_call(
    app: &tauri::AppHandle,
    method: &str,
    params: Value,
    revision: u64,
) -> Result<Value, String> {
    let mut guard = WORKER.lock().await;
    if guard.is_none() {
        let cmd = app
            .shell()
            .sidecar("printforge-geo")
            .map_err(|e| format!("sidecar не найден: {e}"))?;
        let (rx, child) = cmd
            .spawn()
            .map_err(|e| format!("не удалось запустить геометрический процесс: {e}"))?;
        *guard = Some(GeoWorker { child, rx, buf: String::new(), next_id: 0 });
    }
    let w = guard.as_mut().ok_or("worker не инициализирован")?;
    w.next_id += 1;
    let rid = format!("r{}", w.next_id);
    let req = json!({
        "request_id": rid, "schema_version": 1,
        "document_id": "doc", "revision": revision,
        "method": method, "params": params,
    });
    w.child
        .write(format!("{req}\n").as_bytes())
        .map_err(|e| format!("запись в геометрический процесс: {e}"))?;
    loop {
        match w.rx.recv().await {
            Some(CommandEvent::Stdout(bytes)) => {
                w.buf.push_str(&String::from_utf8_lossy(&bytes));
                while let Some(pos) = w.buf.find('\n') {
                    let line: String = w.buf.drain(..=pos).collect();
                    let resp: Value = match serde_json::from_str(line.trim()) {
                        Ok(v) => v,
                        Err(_) => continue,
                    };
                    if resp.get("request_id").and_then(Value::as_str) == Some(rid.as_str()) {
                        if resp.get("ok").and_then(Value::as_bool) == Some(true) {
                            return Ok(resp.get("result").cloned().unwrap_or(Value::Null));
                        }
                        let err = resp.get("error").cloned().unwrap_or(json!({}));
                        return Err(json!({
                            "code": err.get("code").and_then(Value::as_str).unwrap_or("geometry_error"),
                            "message": err.get("message").and_then(Value::as_str).unwrap_or("ошибка геометрии"),
                            "detail": err.get("detail").and_then(Value::as_str).unwrap_or(""),
                        }).to_string());
                    }
                }
            }
            Some(CommandEvent::Terminated(_)) | None => {
                *guard = None;
                return Err(geo_err(
                    "worker_terminated",
                    "Геометрический процесс завершился. Последняя подтверждённая модель сохранена; повторите действие."));
            }
            _ => {}
        }
    }
}

// ---------- документ ----------

#[derive(Clone, Default)]
struct Snapshot {
    template: Option<String>,
    params: BTreeMap<String, f64>,
    expressions: BTreeMap<String, String>,
    operations: Vec<Value>,
}

struct Document {
    doc_id: u64,
    snap: Snapshot,
    history: Vec<Snapshot>,
    index: usize,
    dirty: bool,
    path: Option<PathBuf>,
    revision: u64,
    stats: Option<Value>,
    mesh: Option<Value>,
    error: Option<Value>,
}

impl Document {
    fn new() -> Self {
        static NEXT_ID: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(1);
        Document {
            doc_id: NEXT_ID.fetch_add(1, std::sync::atomic::Ordering::Relaxed),
            snap: Snapshot::default(),
            history: vec![Snapshot::default()],
            index: 0,
            dirty: false,
            path: None,
            revision: 0,
            stats: None,
            mesh: None,
            error: None,
        }
    }

    fn commit(&mut self, snap: Snapshot) {
        self.history.truncate(self.index + 1);
        self.history.push(snap.clone());
        self.index += 1;
        self.snap = snap;
        self.dirty = true;
    }

    fn build_params(&self) -> Value {
        json!({
            "template": self.snap.template,
            "params": self.snap.params,
            "operations": self.snap.operations,
        })
    }

    fn state(&self, slot: &str) -> Value {
        json!({
            "doc_id": self.doc_id,
            "revision": self.revision,
            "dirty": self.dirty,
            "path": self.path.as_ref().map(|p| p.to_string_lossy()),
            "slot": slot,
            "template": self.snap.template,
            "params": self.snap.params,
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
    if doc.snap.template.is_none() {
        return;
    }
    doc.revision += 1;
    match worker_call(app, "build", doc.build_params(), doc.revision).await {
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

async fn rebuild_active(app: &tauri::AppHandle) {
    let mut guard = STORE.lock().await;
    if let Some(store) = guard.as_mut() {
        let doc = active_doc(store);
        rebuild(app, doc).await;
    }
}

// ---------- команды IPC ----------

#[tauri::command]
async fn doc_create(
    app: tauri::AppHandle,
    template: String,
    params: Option<BTreeMap<String, f64>>,
) -> Result<Value, String> {
    const TEMPLATES: [&str; 4] = ["plate_with_holes", "washer", "bracket_l", "case_with_lid"];
    if !TEMPLATES.contains(&template.as_str()) {
        return Err(geo_err("unknown_template", format!("Неизвестный шаблон: {template}")));
    }
    with_store(|s| {
        let doc = active_doc(s);
        doc.commit(Snapshot {
            template: Some(template.clone()),
            params: params.clone().unwrap_or_default(),
            expressions: BTreeMap::new(),
            operations: vec![],
        });
    })
    .await;
    rebuild_active(&app).await;
    Ok(current_state().await)
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
) -> Result<Value, String> {
    if !value.is_finite() || value <= 0.0 {
        return Err(geo_err("bad_value",
            format!("Значение параметра «{name}» должно быть положительным числом.")));
    }
    let has_model = with_store(|s| active_doc(s).snap.template.is_some()).await;
    if !has_model {
        return Err(geo_err("no_model", "Сначала создайте деталь."));
    }
    with_store(|s| {
        let doc = active_doc(s);
        let mut next = doc.snap.clone();
        next.params.insert(name.clone(), value);
        match &expression {
            Some(e) if !e.trim().is_empty() => {
                next.expressions.insert(name.clone(), e.clone());
            }
            _ => {
                next.expressions.remove(&name);
            }
        }
        doc.commit(next);
    })
    .await;
    rebuild_active(&app).await;
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_fillet(
    app: tauri::AppHandle,
    edge_ref: Value,
    radius: f64,
) -> Result<Value, String> {
    if !radius.is_finite() || radius <= 0.0 {
        return Err(geo_err("bad_value", "Радиус скругления должен быть больше нуля."));
    }
    with_store(|s| {
        let doc = active_doc(s);
        let mut next = doc.snap.clone();
        next.operations.retain(|op| op.get("op") != Some(&json!("fillet")));
        next.operations.push(json!({
            "op": "fillet", "radius": radius, "edge_ref": edge_ref,
        }));
        doc.commit(next);
    })
    .await;
    rebuild_active(&app).await;
    let (err, state) = with_store(|s| {
        let slot = s.active.clone();
        let doc = active_doc(s);
        (doc.error.clone(), doc.state(&slot))
    })
    .await;
    if let Some(e) = err {
        let code = e.get("code").and_then(Value::as_str).unwrap_or("");
        if code == "fillet_failed" || code == "reselect_required" || code == "bad_ref" {
            // откат транзакции: модель и история остаются прежними
            with_store(|s| {
                let doc = active_doc(s);
                if doc.index > 0 {
                    doc.history.pop();
                    doc.index -= 1;
                    doc.snap = doc.history[doc.index].clone();
                    doc.error = None;
                }
            })
            .await;
            return Err(e.to_string());
        }
    }
    Ok(state)
}

#[tauri::command]
async fn doc_clear_error() -> Result<Value, String> {
    with_store(|s| active_doc(s).error = None).await;
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_undo(app: tauri::AppHandle) -> Result<Value, String> {
    let changed = with_store(|s| {
        let doc = active_doc(s);
        if doc.index > 0 {
            doc.index -= 1;
            doc.snap = doc.history[doc.index].clone();
            doc.dirty = true;
            true
        } else {
            false
        }
    })
    .await;
    if changed {
        rebuild_active(&app).await;
    }
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_redo(app: tauri::AppHandle) -> Result<Value, String> {
    let changed = with_store(|s| {
        let doc = active_doc(s);
        if doc.index + 1 < doc.history.len() {
            doc.index += 1;
            doc.snap = doc.history[doc.index].clone();
            doc.dirty = true;
            true
        } else {
            false
        }
    })
    .await;
    if changed {
        rebuild_active(&app).await;
    }
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_get_state() -> Result<Value, String> {
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_get_mesh() -> Result<Value, String> {
    let mesh_path = with_store(|s| {
        let doc = active_doc(s);
        doc.mesh
            .as_ref()
            .and_then(|m| m.get("path"))
            .and_then(Value::as_str)
            .map(String::from)
    })
    .await;
    let path = mesh_path.ok_or_else(|| geo_err("no_model", "модель ещё не построена"))?;
    read_mesh_resource(&path)
}

fn read_mesh_resource(path: &str) -> Result<Value, String> {
    let data = std::fs::read(path).map_err(|e| format!("чтение сетки: {e}"))?;
    if data.len() < 8 {
        return Err("повреждённый ресурс сетки".into());
    }
    let nv = u32::from_le_bytes(data[0..4].try_into().unwrap()) as usize;
    let nt = u32::from_le_bytes(data[4..8].try_into().unwrap()) as usize;
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

#[tauri::command]
async fn doc_get_imported_mesh(path: String) -> Result<Value, String> {
    read_mesh_resource(&path)
}

fn save_document(doc: &Document, target: &PathBuf) -> Result<(), String> {
    let tmp = target.with_extension("printforge.tmp");
    let manifest = json!({
        "schema_version": SCHEMA_VERSION, "app": "PrintForge",
        "app_version": APP_VERSION, "units": "mm", "kernel": "build123d/OCP",
    });
    let document = json!({
        "schema_version": SCHEMA_VERSION, "units": "mm",
        "template": doc.snap.template,
        "parameters": doc.snap.params,
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
async fn doc_open(app: tauri::AppHandle, path: String) -> Result<Value, String> {
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
    const TEMPLATES: [&str; 4] = ["plate_with_holes", "washer", "bracket_l", "case_with_lid"];
    let template = doc_json
        .get("template")
        .and_then(Value::as_str)
        .unwrap_or("plate_with_holes")
        .to_string();
    if !TEMPLATES.contains(&template.as_str()) {
        return Err(geo_err("bad_file", format!("Неизвестный шаблон в проекте: {template}")));
    }
    let mut snap = Snapshot {
        template: Some(template),
        params: BTreeMap::new(),
        expressions: BTreeMap::new(),
        operations: doc_json.get("operations").and_then(Value::as_array).cloned().unwrap_or_default(),
    };
    if let Some(obj) = doc_json.get("parameters").and_then(Value::as_object) {
        for (k, v) in obj {
            if let Some(n) = v.as_f64() {
                snap.params.insert(k.clone(), n);
            }
        }
    }
    if let Some(obj) = doc_json.get("expressions").and_then(Value::as_object) {
        for (k, v) in obj {
            if let Some(sv) = v.as_str() {
                snap.expressions.insert(k.clone(), sv.to_string());
            }
        }
    }
    let p = PathBuf::from(&path);
    with_store(|s| {
        let doc = active_doc(s);
        *doc = Document::new();
        doc.commit(snap.clone());
        doc.path = Some(p.clone());
        doc.dirty = false;
    })
    .await;
    rebuild_active(&app).await;
    Ok(current_state().await)
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
    if params.get("template").is_none() || params["template"].is_null() {
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
    let revision = with_store(|s| active_doc(s).revision).await;
    let mut call = json!({"path": path, "format": format});
    if let Some(sc) = unit_scale {
        call["unit_scale"] = json!(sc);
    }
    worker_call(&app, "import", call, revision).await
}

#[tauri::command]
async fn print_check(app: tauri::AppHandle, printer: Value) -> Result<Value, String> {
    let (params, revision) = with_store(|s| {
        let doc = active_doc(s);
        (doc.build_params(), doc.revision)
    })
    .await;
    if params["template"].is_null() {
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

// ---------- автосохранение (DOC-007) ----------

fn spawn_autosave() {
    tauri::async_runtime::spawn(async {
        let mut interval = tokio::time::interval(std::time::Duration::from_secs(30));
        loop {
            interval.tick().await;
            let _ = with_store(|s| {
                for doc in [&mut s.main, &mut s.tutorial] {
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
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|_app| {
            spawn_autosave();
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            doc_create,
            doc_create_plate,
            doc_set_parameter,
            doc_fillet,
            doc_clear_error,
            doc_undo,
            doc_redo,
            doc_get_state,
            doc_get_mesh,
            doc_get_imported_mesh,
            doc_save,
            doc_open,
            doc_export,
            doc_export_stl,
            doc_import,
            print_check,
            doc_switch_slot,
            doc_new_tutorial,
            dialog_save_path,
            dialog_open_path,
        ])
        .run(tauri::generate_context!())
        .expect("ошибка запуска PrintForge");
}
