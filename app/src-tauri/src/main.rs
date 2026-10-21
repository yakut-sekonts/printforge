// PrintForge M1: ядро приложения.
// Документ (параметры, история, Undo/Redo) — в этом процессе и является
// authoritative-источником; геометрия считается отдельным worker-процессом
// (sidecar, см. backend/worker.py). Протокол worker: JSON Lines stdio.
use serde_json::{json, Value};
use std::collections::BTreeMap;
use std::io::{Read as _, Write as _};
use std::path::PathBuf;
use tauri::async_runtime::Receiver;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::Mutex;

const SCHEMA_VERSION: u32 = 1;
const APP_VERSION: &str = "0.1.0-m1";

// ---------- геометрический worker ----------

struct GeoWorker {
    child: CommandChild,
    rx: Receiver<CommandEvent>,
    buf: String,
    next_id: u64,
}

static WORKER: Mutex<Option<GeoWorker>> = Mutex::const_new(None);

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
        "request_id": rid, "schema_version": SCHEMA_VERSION,
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
                // Падение worker не роняет UI (TECH-001); следующий вызов
                // поднимет процесс заново из подтверждённой ревизии.
                *guard = None;
                return Err(json!({
                    "code": "worker_terminated",
                    "message": "Геометрический процесс завершился. Последняя подтверждённая модель сохранена; повторите действие.",
                    "detail": "",
                }).to_string());
            }
            _ => {}
        }
    }
}

// ---------- документ ----------

#[derive(Clone, Default)]
struct DocParams {
    values: BTreeMap<String, f64>,
    expressions: BTreeMap<String, String>,
}

struct Document {
    doc_id: u64,
    params: DocParams,
    history: Vec<DocParams>,
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
            params: DocParams::default(),
            history: vec![DocParams::default()],
            index: 0,
            dirty: false,
            path: None,
            revision: 0,
            stats: None,
            mesh: None,
            error: None,
        }
    }

    fn state(&self, slot: &str) -> Value {
        json!({
            "doc_id": self.doc_id,
            "revision": self.revision,
            "dirty": self.dirty,
            "path": self.path.as_ref().map(|p| p.to_string_lossy()),
            "slot": slot,
            "params": self.params.values,
            "expressions": self.params.expressions,
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
    active: String, // "main" | "tutorial"
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
    if store.active == "tutorial" {
        &mut store.tutorial
    } else {
        &mut store.main
    }
}

async fn rebuild(app: &tauri::AppHandle, doc: &mut Document) {
    doc.revision += 1;
    let params = json!({
        "length": doc.params.values.get("length").copied().unwrap_or(80.0),
        "width": doc.params.values.get("width").copied().unwrap_or(40.0),
        "height": doc.params.values.get("height").copied().unwrap_or(6.0),
        "hole_diameter": doc.params.values.get("hole_diameter").copied().unwrap_or(4.0),
        "hole_offset": doc.params.values.get("hole_offset").copied().unwrap_or(10.0),
    });
    match worker_call(app, "build_plate", params, doc.revision).await {
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

fn commit_params(doc: &mut Document, next: DocParams) {
    doc.history.truncate(doc.index + 1);
    doc.history.push(next.clone());
    doc.index += 1;
    doc.params = next;
    doc.dirty = true;
}

// ---------- команды IPC ----------

#[tauri::command]
async fn doc_create_plate(
    app: tauri::AppHandle,
    length: f64,
    width: f64,
    height: f64,
    hole_diameter: f64,
    hole_offset: f64,
) -> Result<Value, String> {
    let mut next = DocParams::default();
    for (k, v) in [
        ("length", length), ("width", width), ("height", height),
        ("hole_diameter", hole_diameter), ("hole_offset", hole_offset),
    ] {
        next.values.insert(k.into(), v);
    }
    with_store(|s| {
        let doc = active_doc(s);
        commit_params(doc, next);
    })
    .await;
    rebuild_for_active(&app).await;
    Ok(current_state().await)
}

async fn rebuild_for_active(app: &tauri::AppHandle) {
    let mut guard = STORE.lock().await;
    if let Some(store) = guard.as_mut() {
        let doc = active_doc(store);
        rebuild(app, doc).await;
    }
}

async fn current_state() -> Value {
    with_store(|s| {
        let slot = s.active.clone();
        active_doc(s).state(&slot)
    })
    .await
}

#[tauri::command]
async fn doc_set_parameter(
    app: tauri::AppHandle,
    name: String,
    value: f64,
    expression: Option<String>,
) -> Result<Value, String> {
    if !value.is_finite() || value <= 0.0 {
        return Err(json!({
            "code": "bad_value",
            "message": format!("Значение параметра «{name}» должно быть положительным числом."),
            "detail": "",
        }).to_string());
    }
    with_store(|s| {
        let doc = active_doc(s);
        let mut next = doc.params.clone();
        next.values.insert(name.clone(), value);
        match &expression {
            Some(e) if !e.trim().is_empty() => {
                next.expressions.insert(name.clone(), e.clone());
            }
            _ => {
                next.expressions.remove(&name);
            }
        }
        commit_params(doc, next);
    })
    .await;
    rebuild_for_active(&app).await;
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_undo(app: tauri::AppHandle) -> Result<Value, String> {
    let changed = with_store(|s| {
        let doc = active_doc(s);
        if doc.index > 0 {
            doc.index -= 1;
            doc.params = doc.history[doc.index].clone();
            doc.dirty = true;
            true
        } else {
            false
        }
    })
    .await;
    if changed {
        rebuild_for_active(&app).await;
    }
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_redo(app: tauri::AppHandle) -> Result<Value, String> {
    let changed = with_store(|s| {
        let doc = active_doc(s);
        if doc.index + 1 < doc.history.len() {
            doc.index += 1;
            doc.params = doc.history[doc.index].clone();
            doc.dirty = true;
            true
        } else {
            false
        }
    })
    .await;
    if changed {
        rebuild_for_active(&app).await;
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
    let path = mesh_path.ok_or("модель ещё не построена")?;
    let data = std::fs::read(&path).map_err(|e| format!("чтение сетки: {e}"))?;
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
    let face_ranges = with_store(|s| {
        let doc = active_doc(s);
        doc.mesh
            .as_ref()
            .and_then(|m| m.get("face_ranges"))
            .cloned()
            .unwrap_or(json!([]))
    })
    .await;
    Ok(json!({
        "vertex_count": nv, "triangle_count": nt,
        "positions": positions, "indices": indices,
        "face_ranges": face_ranges,
    }))
}

#[tauri::command]
async fn doc_save(path: String) -> Result<Value, String> {
    let (params, exprs) = with_store(|s| {
        let doc = active_doc(s);
        (doc.params.values.clone(), doc.params.expressions.clone())
    })
    .await;
    let target = PathBuf::from(&path);
    let tmp = target.with_extension("printforge.tmp");
    let manifest = json!({
        "schema_version": SCHEMA_VERSION,
        "app": "PrintForge",
        "app_version": APP_VERSION,
        "units": "mm",
        "kernel": "build123d/OCP",
    });
    let document = json!({
        "schema_version": SCHEMA_VERSION,
        "units": "mm",
        "parameters": params,
        "expressions": exprs,
        "operations": [{"op": "plate_with_holes"}],
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
    // Атомарная замена (DOC-007)
    std::fs::rename(&tmp, &target).map_err(|e| format!("замена файла: {e}"))?;
    with_store(|s| {
        let doc = active_doc(s);
        doc.path = Some(target.clone());
        doc.dirty = false;
    })
    .await;
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_open(app: tauri::AppHandle, path: String) -> Result<Value, String> {
    let file = std::fs::File::open(&path).map_err(|e| format!("открытие файла: {e}"))?;
    let mut zip = zip::ZipArchive::new(file).map_err(|_| "это не файл проекта PrintForge".to_string())?;
    let mut buf = String::new();
    zip.by_name("document.json")
        .map_err(|_| "в проекте нет document.json".to_string())?
        .read_to_string(&mut buf)
        .map_err(|e| e.to_string())?;
    let doc_json: Value =
        serde_json::from_str(&buf).map_err(|_| "document.json повреждён".to_string())?;
    let mut next = DocParams::default();
    if let Some(obj) = doc_json.get("parameters").and_then(Value::as_object) {
        for (k, v) in obj {
            if let Some(n) = v.as_f64() {
                next.values.insert(k.clone(), n);
            }
        }
    }
    if let Some(obj) = doc_json.get("expressions").and_then(Value::as_object) {
        for (k, v) in obj {
            if let Some(sv) = v.as_str() {
                next.expressions.insert(k.clone(), sv.to_string());
            }
        }
    }
    if next.values.is_empty() {
        return Err("в проекте нет параметров модели".into());
    }
    let p = PathBuf::from(&path);
    with_store(|s| {
        let doc = active_doc(s);
        *doc = Document::new();
        commit_params(doc, next);
        doc.path = Some(p);
        doc.dirty = false;
    })
    .await;
    rebuild_for_active(&app).await;
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_export_stl(
    app: tauri::AppHandle,
    path: String,
    linear_deflection: Option<f64>,
) -> Result<Value, String> {
    let (params, revision) = with_store(|s| {
        let doc = active_doc(s);
        (doc.params.values.clone(), doc.revision)
    })
    .await;
    if params.is_empty() {
        return Err("нет модели для экспорта".into());
    }
    let mut call_params = json!({
        "length": params.get("length").copied().unwrap_or(80.0),
        "width": params.get("width").copied().unwrap_or(40.0),
        "height": params.get("height").copied().unwrap_or(6.0),
        "hole_diameter": params.get("hole_diameter").copied().unwrap_or(4.0),
        "hole_offset": params.get("hole_offset").copied().unwrap_or(10.0),
        "path": path,
    });
    if let Some(t) = linear_deflection {
        call_params["linear_deflection"] = json!(t);
    }
    let result = worker_call(&app, "export_stl", call_params, revision).await?;
    Ok(result)
}

#[tauri::command]
async fn doc_switch_slot(slot: String) -> Result<Value, String> {
    if slot != "main" && slot != "tutorial" {
        return Err("неизвестный слот документа".into());
    }
    with_store(|s| s.active = slot).await;
    Ok(current_state().await)
}

#[tauri::command]
async fn doc_new_tutorial(app: tauri::AppHandle) -> Result<Value, String> {
    with_store(|s| {
        s.tutorial = Document::new();
        s.active = "tutorial".into();
    })
    .await;
    let _ = app;
    Ok(current_state().await)
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![
            doc_create_plate,
            doc_set_parameter,
            doc_undo,
            doc_redo,
            doc_get_state,
            doc_get_mesh,
            doc_save,
            doc_open,
            doc_export_stl,
            doc_switch_slot,
            doc_new_tutorial,
        ])
        .run(tauri::generate_context!())
        .expect("ошибка запуска PrintForge");
}
