// PrintForge M0: пробная интеграция sidecar (упакованный Python-backend).
// Протокол: JSON Lines через stdin/stdout worker'а (см. backend/worker.py).
// Запись: CommandChild::write; чтение: события Stdout из Receiver.
use serde_json::{json, Value};
use tauri::async_runtime::Receiver;
use tauri_plugin_shell::process::{CommandChild, CommandEvent};
use tauri_plugin_shell::ShellExt;
use tokio::sync::Mutex;

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
) -> Result<Value, String> {
    let mut guard = WORKER.lock().await;
    if guard.is_none() {
        let cmd = app
            .shell()
            .sidecar("printforge-geo")
            .map_err(|e| format!("sidecar не найден: {e}"))?;
        let (rx, child) = cmd
            .spawn()
            .map_err(|e| format!("не удалось запустить sidecar: {e}"))?;
        *guard = Some(GeoWorker {
            child,
            rx,
            buf: String::new(),
            next_id: 0,
        });
    }
    let w = guard.as_mut().ok_or("worker не инициализирован")?;
    w.next_id += 1;
    let rid = format!("r{}", w.next_id);
    let req = json!({
        "request_id": rid,
        "schema_version": 1,
        "document_id": "trial",
        "revision": w.next_id,
        "method": method,
        "params": params,
    });
    w.child
        .write(format!("{req}\n").as_bytes())
        .map_err(|e| format!("запись в sidecar: {e}"))?;
    // Ждём строку ответа с нашим request_id.
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
                        return Err(resp
                            .get("error")
                            .and_then(|e| e.get("message"))
                            .and_then(Value::as_str)
                            .unwrap_or("ошибка геометрии")
                            .to_string());
                    }
                }
            }
            Some(CommandEvent::Terminated(_)) | None => {
                // Падение worker не роняет UI (TECH-001); следующий вызов
                // поднимет новый процесс из последней ревизии (TECH-002).
                *guard = None;
                return Err("геометрический процесс завершился; последняя подтверждённая модель сохранена".into());
            }
            _ => {}
        }
    }
}

#[tauri::command]
async fn build_plate(app: tauri::AppHandle, length: f64) -> Result<Value, String> {
    worker_call(&app, "build_plate", json!({ "length": length })).await
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .invoke_handler(tauri::generate_handler![build_plate])
        .run(tauri::generate_context!())
        .expect("ошибка запуска PrintForge");
}
