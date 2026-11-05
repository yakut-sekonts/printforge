// PrintForge M3: AI-помощник — провайдеры, декларативный план, валидация,
// транзакция (AI-004…AI-006). LLM не исполняет код: только JSON-данные,
// проверенные приложением, через тот же CommandService, что и ручной UI.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::collections::{BTreeMap, HashMap, HashSet};
use std::path::Path;
use std::sync::{Mutex, OnceLock, RwLock};
use tokio::sync::watch;

pub const MAX_PLAN_OPS: usize = 20;
const AI_SETTINGS_FILE: &str = "ai-settings.json";
const AI_KEYRING_SERVICE: &str = "dev.printforge.desktop.ai";
const AI_KEYRING_ACCOUNT: &str = "openai-compatible-api-key";
const OLLAMA_DEFAULT_BASE: &str = "http://127.0.0.1:11434/v1";

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct AiSettings {
    pub provider: String,
    pub base_url: String,
    pub model: String,
    #[serde(default)]
    pub api_key_stored: bool,
}

impl Default for AiSettings {
    fn default() -> Self {
        Self {
            provider: "disabled".into(),
            base_url: String::new(),
            model: String::new(),
            api_key_stored: false,
        }
    }
}

static AI_SETTINGS: OnceLock<RwLock<AiSettings>> = OnceLock::new();
static AI_TASKS: OnceLock<Mutex<HashMap<String, watch::Sender<bool>>>> = OnceLock::new();

fn settings_lock() -> &'static RwLock<AiSettings> {
    AI_SETTINGS.get_or_init(|| RwLock::new(settings_from_environment().unwrap_or_default()))
}

fn tasks_lock() -> &'static Mutex<HashMap<String, watch::Sender<bool>>> {
    AI_TASKS.get_or_init(|| Mutex::new(HashMap::new()))
}

pub fn register_task(task_id: &str) -> Result<watch::Receiver<bool>, String> {
    if task_id.is_empty()
        || task_id.len() > 128
        || !task_id
            .chars()
            .all(|ch| ch.is_ascii_alphanumeric() || matches!(ch, '-' | '_' | ':'))
    {
        return Err("Некорректный task_id AI-задачи.".into());
    }
    let (sender, receiver) = watch::channel(false);
    let mut tasks = tasks_lock()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    if tasks.contains_key(task_id) {
        return Err("AI-задача с таким task_id уже выполняется.".into());
    }
    tasks.insert(task_id.to_string(), sender);
    Ok(receiver)
}

pub fn cancel_task(task_id: &str) -> bool {
    let tasks = tasks_lock()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner());
    let Some(sender) = tasks.get(task_id) else {
        return false;
    };
    sender.send(true).is_ok()
}

pub fn finish_task(task_id: &str) {
    tasks_lock()
        .lock()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .remove(task_id);
}

fn current_settings() -> AiSettings {
    settings_lock()
        .read()
        .unwrap_or_else(|poisoned| poisoned.into_inner())
        .clone()
}

fn replace_settings(settings: AiSettings) {
    *settings_lock()
        .write()
        .unwrap_or_else(|poisoned| poisoned.into_inner()) = settings;
}

fn settings_from_environment() -> Option<AiSettings> {
    let provider = std::env::var("PF_AI_PROVIDER").ok()?;
    Some(AiSettings {
        provider,
        base_url: std::env::var("PF_AI_BASE").unwrap_or_default(),
        model: std::env::var("PF_AI_MODEL").unwrap_or_default(),
        api_key_stored: false,
    })
}

fn settings_path(config_dir: &Path) -> std::path::PathBuf {
    config_dir.join(AI_SETTINGS_FILE)
}

fn normalize_settings(
    mut settings: AiSettings,
    allow_scripted: bool,
) -> Result<AiSettings, String> {
    settings.provider = settings.provider.trim().to_lowercase();
    settings.model = settings.model.trim().to_string();
    settings.base_url = settings.base_url.trim().trim_end_matches('/').to_string();
    match settings.provider.as_str() {
        "disabled" => {}
        "scripted" if allow_scripted => {
            settings.base_url.clear();
            settings.model = "scripted-v1 (детерминированный, не LLM)".into();
        }
        "ollama" | "openai" => {
            if settings.provider == "ollama" && settings.base_url.is_empty() {
                settings.base_url = OLLAMA_DEFAULT_BASE.into();
            }
            if settings.base_url.is_empty() {
                return Err("Укажите URL OpenAI-совместимого endpoint.".into());
            }
            let parsed = reqwest::Url::parse(&settings.base_url)
                .map_err(|_| "Некорректный URL AI-провайдера.".to_string())?;
            if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
                return Err("URL AI-провайдера должен использовать http или https.".into());
            }
            if !parsed.username().is_empty() || parsed.password().is_some() {
                return Err(
                    "Не помещайте логин или API key в URL. Используйте отдельное поле ключа."
                        .into(),
                );
            }
            if settings.provider == "ollama" && !is_loopback_url(&parsed) {
                return Err(
                    "Профиль Ollama разрешён только для локального endpoint (localhost/127.0.0.1)."
                        .into(),
                );
            }
            if settings.model.is_empty() {
                return Err("Укажите идентификатор модели.".into());
            }
        }
        _ => return Err("Неизвестный AI-провайдер.".into()),
    }
    Ok(settings)
}

fn is_loopback_url(url: &reqwest::Url) -> bool {
    matches!(url.host_str(), Some("localhost" | "127.0.0.1" | "::1"))
}

pub fn initialize(config_dir: &Path) {
    let configured = settings_from_environment().or_else(|| {
        let bytes = std::fs::read(settings_path(config_dir)).ok()?;
        serde_json::from_slice::<AiSettings>(&bytes).ok()
    });
    let settings = configured
        .and_then(|value| normalize_settings(value, true).ok())
        .unwrap_or_default();
    replace_settings(settings);
}

fn save_settings(config_dir: &Path, settings: &AiSettings) -> Result<(), String> {
    std::fs::create_dir_all(config_dir)
        .map_err(|error| format!("Не удалось создать каталог настроек AI: {error}"))?;
    let path = settings_path(config_dir);
    let temporary = path.with_extension(format!("json.{}.tmp", std::process::id()));
    let bytes = serde_json::to_vec_pretty(settings).map_err(|error| error.to_string())?;
    std::fs::write(&temporary, bytes)
        .map_err(|error| format!("Не удалось сохранить настройки AI: {error}"))?;
    std::fs::rename(&temporary, &path).map_err(|error| {
        let _ = std::fs::remove_file(&temporary);
        format!("Не удалось заменить настройки AI: {error}")
    })
}

#[cfg(any(target_os = "macos", target_os = "windows", target_os = "linux"))]
fn keyring_entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(AI_KEYRING_SERVICE, AI_KEYRING_ACCOUNT)
        .map_err(|error| format!("Системное хранилище секретов недоступно: {error}"))
}

#[cfg(any(target_os = "macos", target_os = "windows", target_os = "linux"))]
fn store_api_key(api_key: &str) -> Result<(), String> {
    keyring_entry()?
        .set_password(api_key)
        .map_err(|error| format!("Не удалось сохранить API key в системном хранилище: {error}"))
}

#[cfg(any(target_os = "macos", target_os = "windows", target_os = "linux"))]
fn delete_api_key() -> Result<(), String> {
    match keyring_entry()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(error) => Err(format!(
            "Не удалось удалить API key из системного хранилища: {error}"
        )),
    }
}

#[cfg(any(target_os = "macos", target_os = "windows", target_os = "linux"))]
fn stored_api_key() -> Result<String, String> {
    keyring_entry()?
        .get_password()
        .map_err(|error| format!("Не удалось прочитать API key из системного хранилища: {error}"))
}

#[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
fn store_api_key(_api_key: &str) -> Result<(), String> {
    Err("Системное хранилище секретов не поддерживается на этой платформе.".into())
}

#[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
fn delete_api_key() -> Result<(), String> {
    Err("Системное хранилище секретов не поддерживается на этой платформе.".into())
}

#[cfg(not(any(target_os = "macos", target_os = "windows", target_os = "linux")))]
fn stored_api_key() -> Result<String, String> {
    Err("Системное хранилище секретов не поддерживается на этой платформе.".into())
}

fn api_key(settings: &AiSettings) -> Result<Option<String>, String> {
    if let Ok(value) = std::env::var("PF_AI_KEY") {
        if !value.is_empty() {
            return Ok(Some(value));
        }
    }
    if settings.api_key_stored {
        return stored_api_key().map(Some);
    }
    Ok(None)
}

pub fn configure(
    config_dir: &Path,
    provider: String,
    base_url: String,
    model: String,
    api_key: Option<String>,
    clear_api_key: bool,
) -> Result<Value, String> {
    if api_key.as_ref().is_some_and(|value| !value.is_empty()) && clear_api_key {
        return Err("Нельзя одновременно сохранить и удалить API key.".into());
    }
    let mut settings = current_settings();
    settings.provider = provider;
    settings.base_url = base_url;
    settings.model = model;
    if clear_api_key {
        delete_api_key()?;
        settings.api_key_stored = false;
    } else if let Some(value) = api_key.filter(|value| !value.is_empty()) {
        store_api_key(&value)?;
        settings.api_key_stored = true;
    }
    let settings = normalize_settings(settings, false)?;
    save_settings(config_dir, &settings)?;
    replace_settings(settings);
    Ok(provider_info())
}

fn g(n: f64) -> String {
    if n.fract() == 0.0 {
        format!("{}", n as i64)
    } else {
        format!("{n}")
    }
}
const AI_TIMEOUT_SECS: u64 = 30;

pub fn provider_info() -> Value {
    let settings = current_settings();
    let provider = settings.provider.clone();
    let has_api_key =
        std::env::var("PF_AI_KEY").is_ok_and(|value| !value.is_empty()) || settings.api_key_stored;
    let local_endpoint = reqwest::Url::parse(&settings.base_url)
        .ok()
        .is_some_and(|url| is_loopback_url(&url));
    json!({
        "provider": provider,
        "available": provider != "disabled",
        "scripted": provider == "scripted",
        "model": settings.model,
        "base_url": settings.base_url,
        "has_api_key": has_api_key,
        "secret_storage": if std::env::var("PF_AI_KEY").is_ok_and(|value| !value.is_empty()) {
            "environment"
        } else {
            "system"
        },
        "local_endpoint": local_endpoint,
        "capabilities": {
            "structured_output": provider == "ollama",
            "json_object": matches!(provider.as_str(), "ollama" | "openai"),
            "tools": false,
            "images": false,
            "context_limit": if matches!(provider.as_str(), "ollama" | "openai") { 4096 } else { 0 },
        },
    })
}

fn parse_number(text: &str, default: f64) -> f64 {
    let re = regex_lite(text);
    re.unwrap_or(default)
}

fn regex_lite(text: &str) -> Option<f64> {
    let mut buf = String::new();
    let mut seen_digit = false;
    for ch in text.chars() {
        if ch.is_ascii_digit() {
            buf.push(ch);
            seen_digit = true;
        } else if (ch == '.' || ch == ',') && seen_digit && !buf.contains('.') {
            buf.push('.');
        } else if seen_digit {
            break;
        } else {
            buf.clear();
        }
    }
    if seen_digit { buf.parse().ok() } else { None }
}

pub fn scripted_plan(
    text: &str,
    doc_id: u64,
    document_instance_id: u64,
    revision: u64,
    parts: &[Value],
) -> Value {
    let t = text.to_lowercase();
    let mut plan = json!({
        "schema_version": 1,
        "document_id": doc_id,
        "document_instance_id": document_instance_id,
        "base_revision": revision,
        "units": "mm",
        "assumptions": [],
        "questions": [],
        "operations": [],
        "summary": "",
    });
    if t.contains("шайб") || t.contains("втулк") {
        let od = if t.contains("наружн") {
            parse_number(t.split("наружн").last().unwrap_or(""), 20.0)
        } else {
            parse_number(&t, 20.0)
        };
        let id = if t.contains("внутрен") {
            parse_number(t.split("внутрен").last().unwrap_or(""), 6.0)
        } else {
            6.0
        };
        let h = if t.contains("высот") {
            parse_number(t.split("высот").last().unwrap_or(""), 4.0)
        } else {
            4.0
        };
        plan["operations"] = json!([{
            "command_id": "part.create.from_template",
            "target_id": null,
            "parameters": {"template": "washer",
                           "params": {"outer_diameter": od, "inner_diameter": id, "height": h}},
        }]);
        plan["summary"] = json!(format!(
            "Создать шайбу: наружный диаметр {} мм, внутренний {} мм, высота {} мм", g(od), g(id), g(h)));
        return plan;
    }
    if t.contains("длин") && !parts.is_empty() {
        if let Some(value) = regex_lite(t.split("длин").last().unwrap_or("")) {
            let part = &parts[0];
            let pid = part.get("part_id").and_then(Value::as_str).unwrap_or("");
            let params = part.get("params").and_then(Value::as_object);
            let name = if params.map(|p| p.contains_key("length")).unwrap_or(false) {
                "length"
            } else {
                params.and_then(|p| p.keys().next()).map(String::as_str).unwrap_or("length")
            };
            plan["operations"] = json!([{
                "command_id": "parameter.set",
                "target_id": pid,
                "parameters": {"name": name, "value": value},
            }]);
            plan["summary"] = json!(format!("Изменить параметр «{name}» на {} мм", g(value)));
            return plan;
        }
    }
    if t.contains("отверсти") && t.contains("побольше") {
        if let Some(part) = parts.first() {
            let cur = part.pointer("/params/hole_diameter").and_then(Value::as_f64);
            if let Some(cur) = cur {
                let new_d = (cur * 1.5 * 10.0).round() / 10.0;
                let pid = part.get("part_id").and_then(Value::as_str).unwrap_or("");
                plan["assumptions"] = json!([format!(
                    "«Побольше» трактую как +50%: диаметр {} → {} мм (можно изменить перед применением)", g(cur), g(new_d))]);
                plan["operations"] = json!([{
                    "command_id": "parameter.set",
                    "target_id": pid,
                    "parameters": {"name": "hole_diameter", "value": new_d},
                }]);
                plan["summary"] = json!(format!("Увеличить отверстие до {} мм", g(new_d)));
                return plan;
            }
        }
        plan["questions"] = json!(["У какой детали увеличить отверстие и до какого диаметра?"]);
        plan["summary"] = json!("Нужно уточнение: деталь и диаметр не указаны");
        return plan;
    }
    plan["questions"] = json!(["Не понял запрос. Опишите деталь размерами, например: «шайба 20 на 6, высота 4»."]);
    plan["summary"] = json!("Запрос не распознан — нужны размеры");
    plan
}

const ALLOWED_COMMANDS: [&str; 3] = ["part.create.from_template", "parameter.set", "op.fillet"];
const TEMPLATES: [&str; 7] = [
    "box", "cylinder", "sphere", "plate_with_holes", "washer", "bracket_l", "case_with_lid",
];
const SIGNED_PARAMS: [&str; 19] = [
    "length", "width", "height", "diameter", "hole_diameter", "hole_offset",
    "outer_diameter", "inner_diameter", "a_length", "a_width",
    "a_thickness", "b_height", "wall", "bottom", "gap",
    "lid_thickness", "lip_height", "lip_wall", "radius",
];

fn check_number(name: &str, v: &Value) -> Option<String> {
    let Some(n) = v.as_f64() else {
        return Some(format!("параметр «{name}» не число."));
    };
    if !n.is_finite() {
        return Some(format!("параметр «{name}» не конечное число."));
    }
    if SIGNED_PARAMS.contains(&name) && n <= 0.0 {
        return Some(format!("параметр «{name}» должен быть положительным (получено {}).", g(n)));
    }
    if SIGNED_PARAMS.contains(&name) && n > 10000.0 {
        return Some(format!("параметр «{name}» вне разумного диапазона ({} мм).", g(n)));
    }
    None
}

pub fn validate_plan(
    plan: &Value,
    doc_id: u64,
    document_instance_id: u64,
    revision: u64,
    part_ids: &[String],
) -> Option<Value> {
    let err = |code: &str, msg: String| json!({"code": code, "message": msg, "detail": ""});
    let Some(plan_object) = plan.as_object() else {
        return Some(err("plan_invalid", "Ответ AI не является планом (ожидался JSON-объект).".into()));
    };
    const PLAN_FIELDS: [&str; 9] = [
        "schema_version", "document_id", "document_instance_id", "base_revision",
        "units", "assumptions", "questions", "operations", "summary",
    ];
    let missing: Vec<&str> = PLAN_FIELDS.iter().copied()
        .filter(|field| !plan_object.contains_key(*field)).collect();
    if !missing.is_empty() {
        return Some(err("plan_invalid", format!(
            "В плане отсутствуют обязательные поля: {}.", missing.join(", "))));
    }
    let unknown: Vec<&str> = plan_object.keys().map(String::as_str)
        .filter(|field| !PLAN_FIELDS.contains(field)).collect();
    if !unknown.is_empty() {
        return Some(err("plan_invalid", format!(
            "В плане есть запрещённые поля: {}.", unknown.join(", "))));
    }
    let string_array = |field: &str| plan.get(field).and_then(Value::as_array)
        .is_some_and(|items| items.iter().all(Value::is_string));
    if !string_array("assumptions") || !string_array("questions") {
        return Some(err("plan_invalid", "assumptions и questions должны быть массивами строк.".into()));
    }
    if !plan.get("summary").is_some_and(Value::is_string) {
        return Some(err("plan_invalid", "Поле summary должно быть строкой.".into()));
    }
    if plan.get("schema_version") != Some(&json!(1)) {
        return Some(err("plan_invalid", "Неизвестная версия схемы плана.".into()));
    }
    if plan.get("units") != Some(&json!("mm")) {
        return Some(err("plan_invalid", "План не в миллиметрах — не применяется.".into()));
    }
    if plan.get("document_id") != Some(&json!(doc_id)) {
        return Some(err("plan_stale", "План относится к другому документу.".into()));
    }
    if plan.get("document_instance_id") != Some(&json!(document_instance_id)) {
        return Some(err("plan_stale", "План относится к другому открытию документа.".into()));
    }
    if plan.get("base_revision") != Some(&json!(revision)) {
        return Some(err("plan_stale",
            "Документ изменился, пока формировался план. Предложение устарело — пересчитайте.".into()));
    }
    let ops = match plan.get("operations").and_then(Value::as_array) {
        Some(o) if !o.is_empty() => o,
        _ => {
            if plan.get("questions").and_then(Value::as_array).map(|q| !q.is_empty()).unwrap_or(false) {
                return None; // законное уточнение без операций
            }
            return Some(err("plan_invalid", "В плане нет операций.".into()));
        }
    };
    if ops.len() > MAX_PLAN_OPS {
        return Some(err("plan_invalid", format!("В плане больше {MAX_PLAN_OPS} операций — отклонён.")));
    }
    for (i, op) in ops.iter().enumerate() {
        let n = i + 1;
        let Some(operation) = op.as_object() else {
            return Some(err("plan_invalid", format!("Операция {n}: ожидался объект.")));
        };
        const OPERATION_FIELDS: [&str; 3] = ["command_id", "target_id", "parameters"];
        if operation.len() != OPERATION_FIELDS.len()
            || !OPERATION_FIELDS.iter().all(|field| operation.contains_key(*field))
        {
            return Some(err("plan_invalid", format!("Операция {n}: неверный набор полей.")));
        }
        if !op.get("target_id").is_some_and(|target| target.is_null() || target.is_string()) {
            return Some(err("plan_invalid", format!(
                "Операция {n}: target_id должен быть строкой или null.")));
        }
        let cid = op.get("command_id").and_then(Value::as_str).unwrap_or("");
        if !ALLOWED_COMMANDS.contains(&cid) {
            return Some(err("plan_forbidden", format!("Операция {n}: команда «{cid}» не разрешена для AI.")));
        }
        let params = match op.get("parameters").and_then(Value::as_object) {
            Some(p) => p,
            None => return Some(err("plan_invalid", format!("Операция {n}: нет параметров."))),
        };
        match cid {
            "part.create.from_template" => {
                if params.keys().any(|key| !matches!(key.as_str(), "template" | "params")) {
                    return Some(err("plan_invalid", format!(
                        "Операция {n}: неизвестные параметры шаблона.")));
                }
                let tpl = params.get("template").and_then(Value::as_str).unwrap_or("");
                if !TEMPLATES.contains(&tpl) {
                    return Some(err("plan_invalid", format!("Операция {n}: неизвестный шаблон.")));
                }
                if params.get("params").is_some_and(|value| !value.is_object()) {
                    return Some(err("plan_invalid", format!(
                        "Операция {n}: params должен быть объектом.")));
                }
                if let Some(pp) = params.get("params").and_then(Value::as_object) {
                    for (k, v) in pp {
                        if let Some(bad) = check_number(k, v) {
                            return Some(err("plan_invalid", format!("Операция {n}: {bad}")));
                        }
                    }
                }
            }
            "parameter.set" => {
                if params.len() != 2 || !params.contains_key("name") || !params.contains_key("value") {
                    return Some(err("plan_invalid", format!(
                        "Операция {n}: неверные параметры parameter.set.")));
                }
                let tid = op.get("target_id").and_then(Value::as_str).unwrap_or("");
                if !part_ids.iter().any(|p| p == tid) {
                    return Some(err("plan_invalid", format!("Операция {n}: деталь «{tid}» не существует в документе.")));
                }
                let name = params.get("name").and_then(Value::as_str).unwrap_or("");
                let value = params.get("value").cloned().unwrap_or(Value::Null);
                if let Some(bad) = check_number(name, &value) {
                    return Some(err("plan_invalid", format!("Операция {n}: {bad}")));
                }
            }
            "op.fillet" => {
                if params.keys().any(|key| !matches!(key.as_str(), "radius" | "edge_ref")) {
                    return Some(err("plan_invalid", format!(
                        "Операция {n}: неизвестные параметры скругления.")));
                }
                let radius = params.get("radius").cloned().unwrap_or(Value::Null);
                if let Some(bad) = check_number("radius", &radius) {
                    return Some(err("plan_invalid", format!("Операция {n}: {bad}")));
                }
                if let Some(tid) = op.get("target_id").and_then(Value::as_str) {
                    if !part_ids.iter().any(|p| p == tid) {
                        return Some(err("plan_invalid", format!("Операция {n}: деталь «{tid}» не существует.")));
                    }
                }
            }
            _ => unreachable!(),
        }
    }
    None
}

pub fn doc_summary(
    doc_id: u64,
    document_instance_id: u64,
    revision: u64,
    parts: &[Value],
) -> String {
    json!({
        "document_id": doc_id,
        "document_instance_id": document_instance_id,
        "revision": revision,
        "units": "mm",
        "parts": parts,
    })
    .to_string()
}

fn extract_json(raw: &str) -> Result<Value, String> {
    let mut s = raw.trim();
    if let Some(stripped) = s.strip_prefix("```") {
        s = stripped.trim_start_matches(|c: char| c.is_alphabetic()).trim_start();
        if let Some(end) = s.rfind("```") {
            s = &s[..end];
        }
    }
    let start = s.find('{').ok_or("в ответе нет JSON")?;
    let end = s.rfind('}').ok_or("в ответе нет JSON")?;
    serde_json::from_str(&s[start..=end]).map_err(|e| format!("невалидный JSON: {e}"))
}

fn chat_request_body(
    settings: &AiSettings,
    messages: Value,
    want_json: bool,
    json_schema: Option<Value>,
) -> Value {
    let mut body = json!({"model": settings.model, "messages": messages, "temperature": 0});
    if settings.provider == "ollama" {
        body["reasoning_effort"] = json!("none");
    }
    if let Some(schema) = json_schema.filter(|_| settings.provider == "ollama") {
        body["response_format"] = json!({
            "type": "json_schema",
            "json_schema": {
                "name": "printforge_plan",
                "strict": true,
                "schema": schema,
            },
        });
    } else if want_json {
        body["response_format"] = json!({"type": "json_object"});
    }
    body
}

async fn http_chat_request(
    messages: Value,
    want_json: bool,
    json_schema: Option<Value>,
) -> Result<String, String> {
    let settings = current_settings();
    if !matches!(settings.provider.as_str(), "ollama" | "openai") {
        return Err("Для сетевого запроса не настроен AI-провайдер.".into());
    }
    let key = api_key(&settings)?;
    let body = chat_request_body(&settings, messages, want_json, json_schema);
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(AI_TIMEOUT_SECS))
        .build()
        .map_err(|e| e.to_string())?;
    let mut request = client
        .post(format!("{}/chat/completions", settings.base_url))
        .json(&body);
    if let Some(key) = key {
        request = request.bearer_auth(key);
    }
    let resp = request
        .send()
        .await
        .map_err(|e| format!("провайдер AI недоступен: {e}"))?;
    let status = resp.status();
    let data: Value = resp.json().await.map_err(|e| e.to_string())?;
    if !status.is_success() {
        return Err(format!("провайдер вернул {status}: {data}"));
    }
    data.pointer("/choices/0/message/content")
        .and_then(Value::as_str)
        .map(String::from)
        .ok_or_else(|| "пустой ответ провайдера".into())
}

pub async fn http_chat(messages: Value, want_json: bool) -> Result<String, String> {
    http_chat_request(messages, want_json, None).await
}

pub async fn test_connection() -> Result<Value, String> {
    let settings = current_settings();
    if settings.provider == "disabled" {
        return Err("AI-помощник выключен.".into());
    }
    if settings.provider == "scripted" {
        return Ok(json!({
            "ok": true,
            "message": "Детерминированный планировщик доступен локально; сетевой запрос не выполнялся.",
            "model_found": true,
        }));
    }
    if !matches!(settings.provider.as_str(), "ollama" | "openai") {
        return Err("Неизвестный AI-провайдер.".into());
    }
    let key = api_key(&settings)?;
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(10))
        .build()
        .map_err(|error| error.to_string())?;
    let mut request = client.get(format!("{}/models", settings.base_url));
    if let Some(key) = key {
        request = request.bearer_auth(key);
    }
    let response = request
        .send()
        .await
        .map_err(|error| format!("Провайдер AI недоступен: {error}"))?;
    let status = response.status();
    let data: Value = response
        .json()
        .await
        .map_err(|error| format!("Провайдер вернул не-JSON ответ на /models: {error}"))?;
    if !status.is_success() {
        return Err(format!("Провайдер вернул {status} при проверке /models."));
    }
    let models: Vec<String> = data
        .get("data")
        .and_then(Value::as_array)
        .into_iter()
        .flatten()
        .filter_map(|item| item.get("id").and_then(Value::as_str).map(String::from))
        .take(20)
        .collect();
    let model_found = models.is_empty() || models.iter().any(|model| model == &settings.model);
    let message = if model_found {
        format!(
            "Соединение установлено. Модель «{}» доступна.",
            settings.model
        )
    } else {
        format!(
            "Соединение установлено, но модель «{}» отсутствует в ответе /models.",
            settings.model
        )
    };
    Ok(json!({
        "ok": true,
        "message": message,
        "model_found": model_found,
        "models": models,
    }))
}

pub fn system_prompt(
    doc_id: u64,
    document_instance_id: u64,
    revision: u64,
    parts: &[Value],
) -> String {
    let document_rule = if parts.is_empty() {
        "Документ пуст: для явного запроса создать деталь используй part.create.from_template. "
            .to_string()
    } else {
        let existing = parts
            .iter()
            .map(|part| {
                let part_id = part.get("part_id").and_then(Value::as_str).unwrap_or("");
                let template = part.get("template").and_then(Value::as_str).unwrap_or("");
                let mut parameters: Vec<&str> = part
                    .get("params")
                    .and_then(Value::as_object)
                    .into_iter()
                    .flatten()
                    .map(|(name, _)| name.as_str())
                    .collect();
                parameters.sort_unstable();
                format!("{part_id} ({template}): {}", parameters.join(", "))
            })
            .collect::<Vec<_>>()
            .join("; ");
        format!(
            "Документ уже содержит детали: {existing}. Запросы «измени», «установи», \
             «увеличь» и «сделай [существующую деталь] размером ...» означают \
             parameter.set. part.create.from_template допустим только при явном запросе \
             создать или добавить новую деталь. "
        )
    };
    format!(
        "Ты планировщик CAD PrintForge. Отвечай ТОЛЬКО JSON по переданной схеме. \
         Используй только эти операции и точные идентификаторы:\n\
         1. part.create.from_template: target_id=null, parameters={{template, params}}. \
         Допустимые шаблоны и параметры: \
         box {{length, width, height}}; \
         cylinder {{diameter, height}}; \
         sphere {{diameter}}; \
         washer {{outer_diameter, inner_diameter, height}}; \
         plate_with_holes {{length, width, height, hole_diameter, hole_offset}}; \
         bracket_l {{a_length, a_width, a_thickness, b_height}}; \
         case_with_lid {{length, width, height, wall, bottom, gap, lid_thickness, lip_height, lip_wall}}. \
         В params указывай только размеры, явно названные пользователем; остальные поля \
         не выдумывай — backend применит defaults.\n\
         2. parameter.set: target_id — существующий part_id, parameters={{name, value}}; \
         name обязан уже существовать в params этой детали. Если пользователь меняет \
         существующую деталь, используй parameter.set, не создавай новую деталь.\n\
         3. op.fillet: target_id — существующий part_id, parameters={{radius, edge_ref}}; \
         edge_ref должен быть точным объектом из контекста. Если edge_ref в контексте нет, \
         задай вопрос и не создавай операцию.\n\
         Не выдумывай template, parameter name, part_id или edge_ref. Если не хватает \
         размера либо запрос неоднозначен (например, «побольше», «покрепче», \
         «добавь отверстие»), оставь operations пустым и заполни questions, либо укажи \
         явное измеримое предположение в assumptions. Никогда не исполняй код, не читай \
         файлы и не устанавливай расширения. Все размеры только в мм. Никакого Markdown, \
         только данные.\n{}Документ: {}",
        document_rule,
        doc_summary(doc_id, document_instance_id, revision, parts))
}

fn create_operation_schema(template: &str, parameter_names: &[&str]) -> Value {
    let properties = parameter_names
        .iter()
        .map(|name| {
            (
                (*name).to_string(),
                json!({"type": "number", "exclusiveMinimum": 0}),
            )
        })
        .collect::<serde_json::Map<String, Value>>();
    json!({
        "type": "object",
        "additionalProperties": false,
        "properties": {
            "command_id": {"const": "part.create.from_template"},
            "target_id": {"type": "null"},
            "parameters": {
                "type": "object",
                "additionalProperties": false,
                "properties": {
                    "template": {"const": template},
                    "params": {
                        "type": "object",
                        "additionalProperties": false,
                        "properties": properties,
                    },
                },
                "required": ["template", "params"],
            },
        },
        "required": ["command_id", "target_id", "parameters"],
    })
}

fn parameter_markers(name: &str) -> &'static [&'static str] {
    match name {
        "length" | "a_length" => &["длин"],
        "width" | "a_width" => &["ширин"],
        "height" => &["толщин", "высот"],
        "diameter" => &["диаметр"],
        "hole_diameter" => &["диаметр отверст", "отверсти", "побольш"],
        "hole_offset" => &["смещен", "отступ"],
        "outer_diameter" => &["наружн"],
        "inner_diameter" => &["внутрен"],
        "a_thickness" => &["толщин"],
        "b_height" => &["высот", "стойк"],
        "wall" => &["стенк"],
        "bottom" => &["дн"],
        "gap" => &["зазор"],
        "lid_thickness" => &["толщин крыш"],
        "lip_height" => &["высот бортик"],
        "lip_wall" => &["толщин бортик"],
        _ => &[],
    }
}

fn request_operation_scope(
    parts: &[Value],
    text: Option<&str>,
) -> (Option<HashSet<String>>, bool, bool) {
    let Some(text) = text else {
        return (None, false, false);
    };
    let normalized = text.to_lowercase().replace('ё', "е");
    let has_negative_number = normalized
        .as_bytes()
        .windows(2)
        .any(|pair| pair[0] == b'-' && pair[1].is_ascii_digit());
    let has_nan = normalized
        .split(|character: char| !character.is_alphanumeric())
        .any(|token| token == "nan");
    let unsafe_or_invalid = has_negative_number
        || has_nan
        || [
            "python",
            "/etc/",
            "прочитай файл",
            "открой файл",
            "установи расширение",
            "запусти код",
        ]
        .iter()
        .any(|marker| normalized.contains(marker));
    if unsafe_or_invalid {
        return (Some(HashSet::new()), false, true);
    }

    let mut requested_templates = Vec::new();
    for (template, markers) in [
        ("box", &["параллелеп", "куб", "брусок"][..]),
        ("cylinder", &["цилиндр"][..]),
        ("sphere", &["сфер", "шар"][..]),
        ("washer", &["шайб", "втулк"][..]),
        ("plate_with_holes", &["пластин"][..]),
        ("bracket_l", &["кроншт"][..]),
        ("case_with_lid", &["корпус", "крышк"][..]),
    ] {
        if markers.iter().any(|marker| normalized.contains(marker)) {
            requested_templates.push(template);
        }
    }

    let mut scope = HashSet::new();
    let explicit_create = parts.is_empty()
        || normalized.contains("созд")
        || normalized.contains("добавь деталь");
    if explicit_create {
        for template in requested_templates {
            scope.insert(format!("create:{template}"));
        }
    }
    for part in parts {
        let Some(part_id) = part.get("part_id").and_then(Value::as_str) else {
            continue;
        };
        if let Some(parameters) = part.get("params").and_then(Value::as_object) {
            for name in parameters.keys() {
                if parameter_markers(name)
                    .iter()
                    .any(|marker| normalized.contains(marker))
                {
                    scope.insert(format!("parameter:{part_id}:{name}"));
                }
            }
        }
        if normalized.contains("скруг") || normalized.contains("радиус") {
            scope.insert(format!("fillet:{part_id}"));
        }
    }
    let requires_assumption = normalized.contains("побольш") && !scope.is_empty();
    let requires_question = scope.is_empty();
    (Some(scope), requires_assumption, requires_question)
}

fn plan_json_schema(
    doc_id: u64,
    document_instance_id: u64,
    revision: u64,
    parts: &[Value],
    text: Option<&str>,
) -> Value {
    let mut available_variants = BTreeMap::new();
    available_variants.insert(
        "create:box".to_string(),
        create_operation_schema("box", &["length", "width", "height"]),
    );
    available_variants.insert(
        "create:cylinder".to_string(),
        create_operation_schema("cylinder", &["diameter", "height"]),
    );
    available_variants.insert(
        "create:sphere".to_string(),
        create_operation_schema("sphere", &["diameter"]),
    );
    available_variants.insert(
        "create:washer".to_string(),
        create_operation_schema("washer", &["outer_diameter", "inner_diameter", "height"]),
    );
    available_variants.insert(
        "create:plate_with_holes".to_string(),
        create_operation_schema(
            "plate_with_holes",
            &["length", "width", "height", "hole_diameter", "hole_offset"],
        ),
    );
    available_variants.insert(
        "create:bracket_l".to_string(),
        create_operation_schema(
            "bracket_l",
            &["a_length", "a_width", "a_thickness", "b_height"],
        ),
    );
    available_variants.insert(
        "create:case_with_lid".to_string(),
        create_operation_schema(
            "case_with_lid",
            &[
                "length", "width", "height", "wall", "bottom", "gap",
                "lid_thickness", "lip_height", "lip_wall",
            ],
        ),
    );
    for part in parts {
        let Some(part_id) = part.get("part_id").and_then(Value::as_str) else {
            continue;
        };
        if let Some(parameters) = part.get("params").and_then(Value::as_object) {
            let mut parameter_names: Vec<&String> = parameters.keys().collect();
            parameter_names.sort_unstable();
            for name in parameter_names {
                available_variants.insert(format!("parameter:{part_id}:{name}"), json!({
                    "type": "object",
                    "additionalProperties": false,
                    "properties": {
                        "command_id": {"const": "parameter.set"},
                        "target_id": {"const": part_id},
                        "parameters": {
                            "type": "object",
                            "additionalProperties": false,
                            "properties": {
                                "name": {"const": name},
                                "value": {"type": "number", "exclusiveMinimum": 0},
                            },
                            "required": ["name", "value"],
                        },
                    },
                    "required": ["command_id", "target_id", "parameters"],
                }));
            }
        }
        available_variants.insert(format!("fillet:{part_id}"), json!({
            "type": "object",
            "additionalProperties": false,
            "properties": {
                "command_id": {"const": "op.fillet"},
                "target_id": {"const": part_id},
                "parameters": {
                    "type": "object",
                    "additionalProperties": false,
                    "properties": {
                        "radius": {"type": "number", "exclusiveMinimum": 0},
                        "edge_ref": {"type": "object"},
                    },
                    "required": ["radius", "edge_ref"],
                },
            },
            "required": ["command_id", "target_id", "parameters"],
        }));
    }
    let (scope, requires_assumption, requires_question) =
        request_operation_scope(parts, text);
    let operation_variants: Vec<Value> = match scope {
        None => available_variants.into_values().collect(),
        Some(scope) => available_variants
            .into_iter()
            .filter_map(|(key, value)| scope.contains(&key).then_some(value))
            .collect(),
    };
    let assumptions_schema = if requires_assumption {
        json!({"type": "array", "minItems": 1, "items": {"type": "string"}})
    } else {
        json!({"type": "array", "items": {"type": "string"}})
    };
    let questions_schema = if requires_question {
        json!({"type": "array", "minItems": 1, "items": {"type": "string"}})
    } else {
        json!({"type": "array", "items": {"type": "string"}})
    };
    let operations_schema = if operation_variants.is_empty() {
        json!({"type": "array", "maxItems": 0})
    } else {
        json!({
            "type": "array",
            "maxItems": MAX_PLAN_OPS,
            "items": {"oneOf": operation_variants},
        })
    };
    json!({
        "type": "object",
        "additionalProperties": false,
        "properties": {
            "schema_version": {"type": "integer", "const": 1},
            "document_id": {"type": "integer", "const": doc_id},
            "document_instance_id": {"type": "integer", "const": document_instance_id},
            "base_revision": {"type": "integer", "const": revision},
            "units": {"type": "string", "const": "mm"},
            "assumptions": assumptions_schema,
            "questions": questions_schema,
            "operations": operations_schema,
            "summary": {"type": "string"},
        },
        "required": [
            "schema_version", "document_id", "document_instance_id",
            "base_revision", "units",
            "assumptions", "questions", "operations", "summary"
        ],
    })
}

pub async fn llm_plan(
    text: &str,
    doc_id: u64,
    document_instance_id: u64,
    revision: u64,
    parts: &[Value],
    part_ids: &[String],
) -> Result<Value, String> {
    let sys = system_prompt(doc_id, document_instance_id, revision, parts);
    let messages = json!([
        {"role": "system", "content": sys},
        {"role": "user", "content": text},
    ]);
    let schema = plan_json_schema(
        doc_id,
        document_instance_id,
        revision,
        parts,
        Some(text),
    );
    let raw = http_chat_request(messages, true, Some(schema.clone())).await?;
    let first = extract_json(&raw);
    let validation_error = first.as_ref().ok().and_then(|plan| {
        validate_plan(plan, doc_id, document_instance_id, revision, part_ids)
    });
    match (first, validation_error) {
        (Ok(plan), None) => Ok(plan),
        (first_result, validation_error) => {
            // одна автоматическая попытка исправления (AI-006)
            let reason = validation_error
                .and_then(|error| error.get("message").and_then(Value::as_str).map(String::from))
                .or_else(|| first_result.err())
                .unwrap_or_else(|| "план не прошёл проверку".into());
            let retry = json!([
                {"role": "system", "content": sys},
                {"role": "user", "content": text},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": format!(
                    "Ответ не прошёл проверку JSON-схемы: {reason}. Исправь, ответь только JSON.")},
            ]);
            let raw2 = http_chat_request(retry, true, Some(schema)).await?;
            let plan = extract_json(&raw2)?;
            if let Some(error) = validate_plan(
                &plan, doc_id, document_instance_id, revision, part_ids,
            ) {
                return Err(error.to_string());
            }
            Ok(plan)
        }
    }
}

pub fn plan_hash(
    doc_id: u64,
    document_instance_id: u64,
    base_revision: u64,
    operations: &[Value],
) -> String {
    let identity = json!({
        "schema_version": 1,
        "document_id": doc_id,
        "document_instance_id": document_instance_id,
        "base_revision": base_revision,
        "units": "mm",
        "operations": operations,
    });
    let canonical = serde_json::to_vec(&identity).expect("serializable AI plan identity");
    format!("{:x}", Sha256::digest(canonical))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn valid_plan() -> Value {
        json!({
            "schema_version": 1,
            "document_id": 7,
            "document_instance_id": 11,
            "base_revision": 3,
            "units": "mm",
            "assumptions": [],
            "questions": [],
            "operations": [{
                "command_id": "parameter.set",
                "target_id": "part-1",
                "parameters": {"name": "length", "value": 100.0},
            }],
            "summary": "Изменить длину",
        })
    }

    #[test]
    fn validates_plan_contract_and_instance() {
        let plan = valid_plan();
        assert!(validate_plan(&plan, 7, 11, 3, &["part-1".into()]).is_none());
        let error = validate_plan(&plan, 7, 12, 3, &["part-1".into()]).unwrap();
        assert_eq!(error["code"], "plan_stale");
    }

    #[test]
    fn rejects_unknown_fields_and_non_numeric_values() {
        let mut extra = valid_plan();
        extra["shell"] = json!("rm -rf /");
        assert_eq!(
            validate_plan(&extra, 7, 11, 3, &["part-1".into()]).unwrap()["code"],
            "plan_invalid",
        );

        let mut wrong_type = valid_plan();
        wrong_type["operations"][0]["parameters"]["value"] = json!("100");
        assert_eq!(
            validate_plan(&wrong_type, 7, 11, 3, &["part-1".into()]).unwrap()["code"],
            "plan_invalid",
        );
    }

    #[test]
    fn plan_hash_binds_order_and_parameters() {
        let first = vec![json!({
            "command_id": "parameter.set",
            "target_id": "part-1",
            "parameters": {"name": "length", "value": 100},
        })];
        let second = vec![json!({
            "command_id": "parameter.set",
            "target_id": "part-1",
            "parameters": {"name": "length", "value": 101},
        })];
        assert_ne!(plan_hash(7, 11, 3, &first), plan_hash(7, 11, 3, &second));
        assert_ne!(plan_hash(7, 11, 3, &first), plan_hash(7, 12, 3, &first));
    }

    #[test]
    fn ollama_disables_reasoning_without_changing_openai_requests() {
        let messages = json!([{"role": "user", "content": "test"}]);
        let schema = json!({"type": "object"});
        let ollama = AiSettings {
            provider: "ollama".into(),
            base_url: OLLAMA_DEFAULT_BASE.into(),
            model: "qwen3:4b".into(),
            api_key_stored: false,
        };
        let ollama_body = chat_request_body(
            &ollama,
            messages.clone(),
            true,
            Some(schema.clone()),
        );
        assert_eq!(ollama_body["reasoning_effort"], json!("none"));
        assert_eq!(
            ollama_body.pointer("/response_format/json_schema/schema"),
            Some(&schema),
        );

        let openai = AiSettings {
            provider: "openai".into(),
            base_url: "http://127.0.0.1:3001/v1".into(),
            model: "test-model".into(),
            api_key_stored: false,
        };
        let openai_body = chat_request_body(&openai, messages, true, None);
        assert!(openai_body.get("reasoning_effort").is_none());
        assert_eq!(openai_body["response_format"], json!({"type": "json_object"}));
    }

    #[test]
    fn system_prompt_exposes_exact_semantic_contract() {
        let prompt = system_prompt(
            7,
            11,
            3,
            &[json!({
                "part_id": "part-1",
                "template": "plate_with_holes",
                "params": {"length": 80, "width": 40},
            })],
        );
        assert!(prompt.contains("washer {outer_diameter, inner_diameter, height}"));
        assert!(prompt.contains(
            "plate_with_holes {length, width, height, hole_diameter, hole_offset}"
        ));
        assert!(prompt.contains("используй parameter.set, не создавай новую деталь"));
        assert!(prompt.contains("Не выдумывай template, parameter name, part_id или edge_ref"));
        assert!(prompt.contains("backend применит defaults"));
        assert!(prompt.contains("\"document_instance_id\":11"));
    }

    #[test]
    fn plan_schema_binds_templates_and_existing_parameters() {
        let schema = plan_json_schema(
            7,
            11,
            3,
            &[json!({
                "part_id": "part-1",
                "template": "plate_with_holes",
                "params": {"length": 80, "width": 40},
            })],
            None,
        );
        let variants = schema
            .pointer("/properties/operations/items/oneOf")
            .and_then(Value::as_array)
            .expect("operation variants");
        assert!(variants.iter().any(|variant| {
            variant.pointer("/properties/parameters/properties/template/const")
                == Some(&json!("washer"))
                && variant.pointer(
                    "/properties/parameters/properties/params/additionalProperties",
                ) == Some(&json!(false))
        }));
        assert!(variants.iter().any(|variant| {
            variant.pointer("/properties/command_id/const") == Some(&json!("parameter.set"))
                && variant.pointer("/properties/target_id/const") == Some(&json!("part-1"))
                && variant.pointer("/properties/parameters/properties/name/const")
                    == Some(&json!("length"))
        }));

        let parts = [json!({
            "part_id": "part-1",
            "template": "plate_with_holes",
            "params": {"length": 80, "width": 40},
        })];
        let edit = plan_json_schema(
            7,
            11,
            3,
            &parts,
            Some("Измени длину детали на 100 мм"),
        );
        let edit_variants = edit
            .pointer("/properties/operations/items/oneOf")
            .and_then(Value::as_array)
            .expect("edit operation variants");
        assert_eq!(edit_variants.len(), 1);
        assert_eq!(
            edit_variants[0].pointer("/properties/parameters/properties/name/const"),
            Some(&json!("length")),
        );

        let clarification = plan_json_schema(
            7,
            11,
            3,
            &[],
            Some("Сделай деталь покрепче"),
        );
        assert_eq!(
            clarification.pointer("/properties/operations/maxItems"),
            Some(&json!(0)),
        );
        assert_eq!(
            clarification.pointer("/properties/questions/minItems"),
            Some(&json!(1)),
        );
    }

    #[test]
    fn task_registry_cancels_once_and_rejects_duplicates() {
        let task_id = format!("test-task-{}", std::process::id());
        finish_task(&task_id);
        let receiver = register_task(&task_id).expect("register task");
        assert!(!*receiver.borrow());
        assert!(register_task(&task_id).is_err());
        assert!(cancel_task(&task_id));
        assert!(*receiver.borrow());
        finish_task(&task_id);
        assert!(!cancel_task(&task_id));
    }
}
