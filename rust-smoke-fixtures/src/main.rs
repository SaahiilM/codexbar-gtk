use codexbar_core::preferences::default_values;
use serde_json::{json, Value};
use std::{
    env, fs,
    io::{Read, Write},
    net::TcpListener,
};

fn read_json(path: &str) -> Result<Value, String> {
    let data = fs::read_to_string(path).map_err(|e| format!("read {path}: {e}"))?;
    serde_json::from_str(&data).map_err(|e| format!("parse {path}: {e}"))
}

fn py_scalar(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(v) => if *v { "True" } else { "False" }.into(),
        Value::String(v) => v.clone(),
        other => other.to_string(),
    }
}

fn selected_value<'a>(root: &'a Value, key: &str, index: Option<usize>) -> Option<&'a Value> {
    let value = root.get(key)?;
    match index {
        Some(index) => value.as_array()?.get(index),
        None => Some(value),
    }
}

fn json_get(args: &[String]) -> Result<(), String> {
    if !(3..=4).contains(&args.len()) {
        return Err("json-get FILE KEY [INDEX]".into());
    }
    let root = read_json(&args[1])?;
    let index = if let Some(index) = args.get(3) {
        Some(
            index
                .parse()
                .map_err(|_| "index must be an unsigned integer")?,
        )
    } else {
        None
    };
    let selected = selected_value(&root, &args[2], index);
    if let Some(v) = selected {
        println!("{}", py_scalar(v));
    } else if args.len() == 4 {
        println!();
    } else {
        println!("None");
    }
    Ok(())
}

fn fixture_settings(args: &[String]) -> Result<(), String> {
    if args.len() != 3 {
        return Err("settings-fixtures IMPORT_FILE EMPTY_IMPORT_FILE".into());
    }
    let import = json!({"version":1,"preferences":{"preferredCurrencyCode":"EUR","refreshFrequency":"2m","launchAtLogin":false,"futureSyntheticPreference":"ignored"}});
    let empty = json!({"version":1,"preferences":{}});
    fs::write(&args[1], serde_json::to_vec(&import).unwrap()).map_err(|e| e.to_string())?;
    fs::write(&args[2], serde_json::to_vec(&empty).unwrap()).map_err(|e| e.to_string())?;
    Ok(())
}

fn validate_export(args: &[String]) -> Result<(), String> {
    if args.len() != 3 {
        return Err("validate-export FILE SECRET_SENTINEL".into());
    }
    let doc = read_json(&args[1])?;
    validate_export_value(&doc, &args[2])
}

fn validate_export_value(doc: &Value, secret: &str) -> Result<(), String> {
    if doc.get("version").and_then(Value::as_i64) != Some(1) {
        return Err("portable export version was not 1".into());
    }
    let prefs = doc
        .get("preferences")
        .and_then(Value::as_object)
        .ok_or("portable export preferences must be an object")?;
    if prefs.get("refreshFrequency").and_then(Value::as_str) != Some("5m") {
        return Err("portable refreshFrequency was not 5m".into());
    }
    if prefs.get("preferredCurrencyCode").and_then(Value::as_str) != Some("USD") {
        return Err("portable preferredCurrencyCode was not USD".into());
    }
    if serde_json::to_string(doc).unwrap().contains(secret) {
        return Err("secret sentinel appeared in portable export".into());
    }
    Ok(())
}

fn validate_import(args: &[String]) -> Result<(), String> {
    if args.len() != 2 {
        return Err("validate-import FILE".into());
    }
    let prefs = read_json(&args[1])?;
    validate_import_value(&prefs)
}

fn assert_json_equal(args: &[String]) -> Result<(), String> {
    if args.len() != 3 {
        return Err("assert-json-equal EXPECTED ACTUAL".into());
    }
    let expected = read_json(&args[1])?;
    let actual = read_json(&args[2])?;
    if expected != actual {
        return Err(format!(
            "complete JSON maps differ: expected {} got {}",
            expected, actual
        ));
    }
    Ok(())
}

fn assert_import_overlay(args: &[String]) -> Result<(), String> {
    if args.len() != 3 {
        return Err("assert-import-overlay BASELINE ACTUAL".into());
    }
    let mut expected = read_json(&args[1])?;
    let prefs = expected
        .as_object_mut()
        .ok_or("baseline preference map must be a JSON object")?;
    prefs.insert("preferredCurrencyCode".into(), json!("EUR"));
    prefs.insert("refreshFrequency".into(), json!("2m"));
    prefs.insert("launchAtLogin".into(), json!(false));
    prefs.remove("futureSyntheticPreference");
    let actual = read_json(&args[2])?;
    if expected != actual {
        return Err(format!(
            "complete imported preference map differs: expected {} got {}",
            expected, actual
        ));
    }
    Ok(())
}

fn assert_default_map(args: &[String]) -> Result<(), String> {
    if args.len() != 2 {
        return Err("assert-default-map ACTUAL".into());
    }
    let expected = Value::Object(default_values());
    let actual = read_json(&args[1])?;
    if expected != actual {
        return Err(format!(
            "complete reset preference map differs from Rust defaults: expected {} got {}",
            expected, actual
        ));
    }
    Ok(())
}

fn validate_import_value(prefs: &Value) -> Result<(), String> {
    if prefs.get("usageBarsShowUsed").and_then(Value::as_bool) != Some(false) {
        return Err("usageBarsShowUsed was not false after import".into());
    }
    if prefs.get("futureSyntheticPreference").is_some() {
        return Err("unknown synthetic preference was retained".into());
    }
    Ok(())
}

fn random_token() -> Result<(), String> {
    let mut bytes = [0u8; 16];
    fs::File::open("/dev/urandom")
        .and_then(|mut f| f.read_exact(&mut bytes))
        .map_err(|e| format!("system random source: {e}"))?;
    for b in bytes {
        print!("{b:02x}");
    }
    println!();
    Ok(())
}

async fn update_server(args: &[String]) -> Result<(), String> {
    if args.len() != 4 {
        return Err("update-server PORT_FILE REQUEST_LOG VERSION_FILE".into());
    }
    let listener = TcpListener::bind("127.0.0.1:0").map_err(|e| e.to_string())?;
    let port = listener.local_addr().map_err(|e| e.to_string())?.port();
    fs::write(&args[1], port.to_string()).map_err(|e| e.to_string())?;
    for incoming in listener.incoming() {
        let mut stream = incoming.map_err(|e| e.to_string())?;
        let mut request = [0u8; 2048];
        let size = stream.read(&mut request).map_err(|e| e.to_string())?;
        let line = String::from_utf8_lossy(&request[..size])
            .lines()
            .next()
            .unwrap_or("")
            .to_owned();
        if line.starts_with("GET /VERSION ") {
            let raw = fs::read_to_string(&args[3]).map_err(|e| e.to_string())?;
            let mut marketing = None;
            let mut build = None;
            for line in raw.lines() {
                if let Some(v) = line.strip_prefix("MARKETING_VERSION=") {
                    marketing = Some(v.trim());
                }
                if let Some(v) = line.strip_prefix("CURRENT_PROJECT_VERSION=") {
                    build = v.trim().parse::<u64>().ok();
                }
            }
            let marketing = marketing.ok_or("VERSION missing MARKETING_VERSION")?;
            let build = build.ok_or("VERSION missing numeric CURRENT_PROJECT_VERSION")? + 1;
            fs::OpenOptions::new()
                .create(true)
                .append(true)
                .open(&args[2])
                .and_then(|mut f| writeln!(f, "VERSION"))
                .map_err(|e| e.to_string())?;
            let body = format!("MARKETING_VERSION={marketing}\nCURRENT_PROJECT_VERSION={build}\n");
            let response = format!("HTTP/1.1 200 OK\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{body}", body.len());
            stream
                .write_all(response.as_bytes())
                .map_err(|e| e.to_string())?;
        } else {
            stream
                .write_all(
                    b"HTTP/1.1 404 Not Found\r\nContent-Length: 0\r\nConnection: close\r\n\r\n",
                )
                .map_err(|e| e.to_string())?;
        }
    }
    Ok(())
}

struct NotificationService {
    log: String,
    next_id: std::sync::Mutex<u32>,
}

#[zbus::interface(name = "org.freedesktop.Notifications")]
impl NotificationService {
    fn get_capabilities(&self) -> Vec<&'static str> {
        vec!["body"]
    }
    fn get_server_information(&self) -> (&'static str, &'static str, &'static str, &'static str) {
        ("Synthetic", "CodexBar GTK fixture", "1.0", "1.2")
    }
    #[allow(clippy::too_many_arguments)]
    fn notify(
        &self,
        app_name: &str,
        _replaces_id: u32,
        _app_icon: &str,
        summary: &str,
        body: &str,
        _actions: Vec<String>,
        _hints: std::collections::HashMap<String, zbus::zvariant::OwnedValue>,
        _expire_timeout: i32,
    ) -> u32 {
        if let Ok(mut output) = fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.log)
        {
            let _ = writeln!(output, "{app_name}\t{summary}\t{body}");
        }
        let mut next = self.next_id.lock().unwrap();
        *next += 1;
        *next
    }
    fn close_notification(&self, _notification_id: u32) {}
}

async fn notification_service(args: &[String]) -> Result<(), String> {
    if args.len() != 2 {
        return Err("mock-notifications LOG_FILE".into());
    }
    let service = NotificationService {
        log: args[1].clone(),
        next_id: std::sync::Mutex::new(1),
    };
    let _connection = zbus::connection::Builder::session()
        .map_err(|e| e.to_string())?
        .name("org.freedesktop.Notifications")
        .map_err(|e| e.to_string())?
        .serve_at("/org/freedesktop/Notifications", service)
        .map_err(|e| e.to_string())?
        .build()
        .await
        .map_err(|e| e.to_string())?;
    std::future::pending::<()>().await;
    Ok(())
}

#[tokio::main]
async fn main() {
    let mut args: Vec<String> = env::args().collect();
    if args.len() < 2 {
        eprintln!("usage: codexbar-smoke-fixtures COMMAND ...");
        std::process::exit(2);
    }
    let command = args.remove(1);
    let rest = &args[..];
    let result = match command.as_str() {
        "json-get" => json_get(rest),
        "settings-fixtures" => fixture_settings(rest),
        "validate-export" => validate_export(rest),
        "validate-import" => validate_import(rest),
        "assert-json-equal" => assert_json_equal(rest),
        "assert-import-overlay" => assert_import_overlay(rest),
        "assert-default-map" => assert_default_map(rest),
        "random-token" => random_token(),
        "update-server" => update_server(rest).await,
        "mock-notifications" => notification_service(rest).await,
        _ => Err(format!("unknown command: {command}")),
    };
    if let Err(error) = result {
        eprintln!("{error}");
        std::process::exit(1);
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn scalar_format_preserves_shell_contract() {
        assert_eq!(py_scalar(&json!(false)), "False");
        assert_eq!(py_scalar(&json!("5m")), "5m");
        assert_eq!(py_scalar(&Value::Null), "None");
    }
    #[test]
    fn json_lookup_supports_top_level_keys_and_array_indices() {
        let fixture = json!({"refreshFrequency":"5m","providers":["codex","claude"]});
        assert_eq!(
            selected_value(&fixture, "refreshFrequency", None),
            Some(&json!("5m"))
        );
        assert_eq!(
            selected_value(&fixture, "providers", Some(1)),
            Some(&json!("claude"))
        );
        assert_eq!(selected_value(&fixture, "providers", Some(2)), None);
    }
    #[test]
    fn import_fixture_ignores_future_key_only_after_application() {
        let prefs = json!({"usageBarsShowUsed":false});
        assert!(validate_import_value(&prefs).is_ok());
        let with_future = json!({"usageBarsShowUsed":false,"futureSyntheticPreference":"ignored"});
        assert!(validate_import_value(&with_future).is_err());
    }
    #[test]
    fn exported_preferences_require_expected_values_and_secret_redaction() {
        let doc = json!({"version":1,"preferences":{"refreshFrequency":"5m","preferredCurrencyCode":"USD"}});
        assert!(validate_export_value(&doc, "synthetic-secret").is_ok());
        let leaked = json!({"version":1,"preferences":{"refreshFrequency":"5m","preferredCurrencyCode":"USD","apiKey":"synthetic-secret"}});
        assert!(validate_export_value(&leaked, "synthetic-secret").is_err());
    }
    #[test]
    fn rejects_wrong_export_preferences() {
        let doc = json!({"version":1,"preferences":{"refreshFrequency":"2m","preferredCurrencyCode":"USD"}});
        assert!(validate_export_value(&doc, "secret").is_err());
    }
}
