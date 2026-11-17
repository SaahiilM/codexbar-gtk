use std::{
    fs,
    io::{Read, Write},
    net::TcpStream,
    process::{Command, Stdio},
    thread,
    time::{Duration, Instant},
};

#[test]
fn loopback_update_fixture_serves_synthetic_version_and_reaps() {
    let root = std::env::temp_dir().join(format!("codexbar-smoke-fixtures-{}", std::process::id()));
    let _ = fs::remove_dir_all(&root);
    fs::create_dir_all(&root).unwrap();
    let port_file = root.join("port");
    let requests = root.join("requests");
    let version = root.join("VERSION");
    fs::write(
        &version,
        "MARKETING_VERSION=0.82.0\nCURRENT_PROJECT_VERSION=118\n",
    )
    .unwrap();
    let mut child = Command::new(env!("CARGO_BIN_EXE_codexbar-smoke-fixtures"))
        .args([
            "update-server",
            port_file.to_str().unwrap(),
            requests.to_str().unwrap(),
            version.to_str().unwrap(),
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .spawn()
        .unwrap();
    let deadline = Instant::now() + Duration::from_secs(5);
    while !port_file.exists() && Instant::now() < deadline {
        thread::sleep(Duration::from_millis(10));
    }
    assert!(port_file.exists(), "fixture did not publish its port");
    let port = fs::read_to_string(&port_file).unwrap();
    let mut stream = TcpStream::connect(format!("127.0.0.1:{}", port.trim())).unwrap();
    stream
        .write_all(b"GET /VERSION HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        .unwrap();
    let mut response = String::new();
    stream.read_to_string(&mut response).unwrap();
    assert!(response.contains("200 OK"));
    assert!(response.contains("CURRENT_PROJECT_VERSION=119"));
    assert_eq!(fs::read_to_string(&requests).unwrap(), "VERSION\n");
    child.kill().unwrap();
    assert!(
        !child.wait().unwrap().success(),
        "killed fixture unexpectedly returned success"
    );
    fs::remove_dir_all(root).unwrap();
}
