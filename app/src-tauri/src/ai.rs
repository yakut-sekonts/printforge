// PrintForge M3: AI-помощник — провайдеры, декларативный план, валидация,
// транзакция (AI-004…AI-006). LLM не исполняет код: только JSON-данные,
// проверенные приложением, через тот же CommandService, что и ручной UI.
use serde_json::{json, Value};

pub const MAX_PLAN_OPS: usize = 20;

fn g(n: f64) -> String {
    if n.fract() == 0.0 { format!("{}", n as i64) } else { format!("{n}") }
}
const AI_TIMEOUT_SECS: u64 = 30;

pub fn provider_info() -> Value {
    let provider = std::env::var("PF_AI_PROVIDER").unwrap_or_else(|_| "scripted".into());
    json!({
        "provider": provider,
        "available": provider != "disabled",
        "scripted": provider == "scripted",
        "model": if provider == "scripted" {
            "scripted-v1 (детерминированный, не LLM)".to_string()
        } else {
            std::env::var("PF_AI_MODEL").unwrap_or_else(|_| "-".into())
        },
        "base_url": if provider == "openai" {
            std::env::var("PF_AI_BASE").unwrap_or_default()
        } else {
            String::new()
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

pub fn scripted_plan(text: &str, doc_id: u64, revision: u64, parts: &[Value]) -> Value {
    let t = text.to_lowercase();
    let mut plan = json!({
        "schema_version": 1,
        "document_id": doc_id,
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
const TEMPLATES: [&str; 4] = ["plate_with_holes", "washer", "bracket_l", "case_with_lid"];
const SIGNED_PARAMS: [&str; 16] = [
    "length", "width", "height", "hole_diameter", "hole_offset",
    "outer_diameter", "inner_diameter", "a_length", "a_width",
    "a_thickness", "b_height", "wall", "bottom", "gap",
    "lid_thickness", "lip_wall",
];

fn check_number(name: &str, v: &Value) -> Option<String> {
    let n = v.as_f64()?;
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

pub fn validate_plan(plan: &Value, doc_id: u64, revision: u64, part_ids: &[String]) -> Option<Value> {
    let err = |code: &str, msg: String| json!({"code": code, "message": msg, "detail": ""});
    if !plan.is_object() {
        return Some(err("plan_invalid", "Ответ AI не является планом (ожидался JSON-объект).".into()));
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
                let tpl = params.get("template").and_then(Value::as_str).unwrap_or("");
                if !TEMPLATES.contains(&tpl) {
                    return Some(err("plan_invalid", format!("Операция {n}: неизвестный шаблон.")));
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

pub fn doc_summary(doc_id: u64, revision: u64, parts: &[Value]) -> String {
    json!({
        "document_id": doc_id, "revision": revision, "units": "mm", "parts": parts,
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

pub async fn http_chat(messages: Value, want_json: bool) -> Result<String, String> {
    let base = std::env::var("PF_AI_BASE").unwrap_or_default().trim_end_matches('/').to_string();
    let key = std::env::var("PF_AI_KEY").unwrap_or_default();
    let model = std::env::var("PF_AI_MODEL").unwrap_or_else(|_| "auto".into());
    let mut body = json!({"model": model, "messages": messages, "temperature": 0});
    if want_json {
        body["response_format"] = json!({"type": "json_object"});
    }
    let client = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(AI_TIMEOUT_SECS))
        .build()
        .map_err(|e| e.to_string())?;
    let resp = client
        .post(format!("{base}/chat/completions"))
        .bearer_auth(key)
        .json(&body)
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

pub fn system_prompt(doc_id: u64, revision: u64, parts: &[Value]) -> String {
    format!(
        "Ты планировщик CAD PrintForge. Отвечай ТОЛЬКО JSON по схеме: \
         {{schema_version:1, document_id, base_revision, units:\"mm\", \
         assumptions:[], questions:[], operations:[{{command_id, target_id, parameters}}], summary}}. \
         Разрешённые command_id: part.create.from_template {{template, params}}, \
         parameter.set {{name, value}}, op.fillet {{radius, edge_ref}}. \
         Никакого кода, только данные.\nДокумент: {}",
        doc_summary(doc_id, revision, parts))
}

pub async fn llm_plan(text: &str, doc_id: u64, revision: u64, parts: &[Value]) -> Result<Value, String> {
    let sys = system_prompt(doc_id, revision, parts);
    let messages = json!([
        {"role": "system", "content": sys},
        {"role": "user", "content": text},
    ]);
    let raw = http_chat(messages, true).await?;
    match extract_json(&raw) {
        Ok(plan) => Ok(plan),
        Err(_) => {
            // одна автоматическая попытка исправления (AI-006)
            let retry = json!([
                {"role": "system", "content": sys},
                {"role": "user", "content": text},
                {"role": "assistant", "content": raw},
                {"role": "user", "content": "Это не валидный JSON по схеме. Исправь, ответь только JSON."},
            ]);
            let raw2 = http_chat(retry, true).await?;
            extract_json(&raw2)
        }
    }
}
