use serde_json::{json, Value};
use std::path::{Path, PathBuf};
use std::sync::{Mutex, OnceLock};
use std::time::{SystemTime, UNIX_EPOCH};

static DIRECTORY: OnceLock<PathBuf> = OnceLock::new();
static CURRENT: OnceLock<PathBuf> = OnceLock::new();
static LAST_ERROR: Mutex<Option<String>> = Mutex::new(None);

pub fn initialize(root: PathBuf) -> Result<(), String> {
    let directory = root.join("recovery");
    std::fs::create_dir_all(&directory).map_err(|error| error.to_string())?;
    let timestamp = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|error| error.to_string())?.as_millis();
    let path = directory.join(format!("recovery-{timestamp}-{}.printforge", std::process::id()));
    DIRECTORY.set(directory).map_err(|_| "Recovery уже инициализирован".to_string())?;
    CURRENT.set(path).map_err(|_| "Recovery уже инициализирован".to_string())?;
    Ok(())
}

pub fn current() -> Option<&'static PathBuf> { CURRENT.get() }

pub fn record_error(error: Option<String>) {
    if let Ok(mut current) = LAST_ERROR.lock() { *current = error; }
}

pub fn status() -> Value {
    let mut entries = Vec::new();
    if let Some(directory) = DIRECTORY.get() {
        if let Ok(files) = std::fs::read_dir(directory) {
            for entry in files.flatten() {
                let path = entry.path();
                if CURRENT.get() == Some(&path) { continue; }
                if let Some(name) = path.file_name().and_then(|name| name.to_str()) {
                    if valid_name(name) && entry.file_type().is_ok_and(|kind| kind.is_file()) {
                        entries.push(name.to_string());
                    }
                }
            }
        }
    }
    entries.sort_by(|first, second| second.cmp(first));
    json!({"available": entries, "error": LAST_ERROR.lock().ok().and_then(|error| error.clone())})
}

fn valid_name(name: &str) -> bool {
    let Some(body) = name.strip_prefix("recovery-").and_then(|body| body.strip_suffix(".printforge")) else { return false; };
    let Some((timestamp, process)) = body.split_once('-') else { return false; };
    !timestamp.is_empty() && !process.is_empty() && timestamp.bytes().all(|byte| byte.is_ascii_digit())
        && process.bytes().all(|byte| byte.is_ascii_digit()) && Path::new(name).components().count() == 1
}

pub fn resolve(name: &str) -> Result<PathBuf, String> {
    if !valid_name(name) { return Err("Неверное имя recovery-копии".into()); }
    let path = DIRECTORY.get().ok_or("Recovery недоступен")?.join(name);
    if CURRENT.get() == Some(&path) { return Err("Текущую recovery-копию нельзя открыть или удалить этой командой".into()); }
    let metadata = std::fs::symlink_metadata(&path).map_err(|error| error.to_string())?;
    if !metadata.file_type().is_file() { return Err("Recovery-копия должна быть обычным файлом".into()); }
    Ok(path)
}

pub fn clear_current() {
    if let Some(path) = CURRENT.get() {
        if let Err(error) = std::fs::remove_file(path) {
            if error.kind() != std::io::ErrorKind::NotFound { record_error(Some(error.to_string())); }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn rejects_paths_and_accepts_generated_names() {
        assert!(valid_name("recovery-1234567890-123.printforge"));
        for name in ["../recovery-1.printforge", "/recovery-1.printforge", "recovery-1\\file.printforge", "project.printforge", "recovery-1.printforge.tmp"] {
            assert!(!valid_name(name), "{name}");
        }
    }
}
