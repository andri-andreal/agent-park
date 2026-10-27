// Agent Park 3D: a window onto the same park the terminal screensaver shows.
//
// Agent detection stays in Python (one source of truth): this app runs
// `python3 park_state.py`, which prints the park's state as one JSON object
// per line, and forwards every line to the page as a "park-state" event.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;

use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// The state script: $PARK_STATE if set, else the one in the repo next to this app.
fn state_script() -> PathBuf {
    std::env::var_os("PARK_STATE")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../park_state.py"))
}

/// Starts the state script and streams its lines to the page; the page shows
/// "no data" by itself if this fails (no python3, script moved, ...).
fn spawn_state(app: tauri::AppHandle) -> Option<Child> {
    let script = state_script();
    let mut child = Command::new("python3")
        .arg(&script)
        .stdout(Stdio::piped())
        .stderr(Stdio::inherit())
        .spawn()
        .map_err(|error| eprintln!("park3d: cannot run {}: {error}", script.display()))
        .ok()?;
    let stdout = child.stdout.take()?;
    thread::spawn(move || {
        for line in BufReader::new(stdout).lines().map_while(Result::ok) {
            let _ = app.emit("park-state", line);
        }
    });
    Some(child)
}

struct StateProcess(Mutex<Option<Child>>);

/// `park3d --low --cap=20` becomes the page's `?low&cap=20`.
fn page_options() -> String {
    let options: Vec<String> = std::env::args()
        .skip(1)
        .filter_map(|arg| arg.strip_prefix("--").map(str::to_owned))
        .collect();
    if options.is_empty() {
        String::new()
    } else {
        format!("?{}", options.join("&"))
    }
}

fn main() {
    // WebKitGTK's DMA-BUF renderer leaves WebGL black on some Wayland setups.
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
    tauri::Builder::default()
        .setup(|app| {
            let page = format!("index.html{}", page_options());
            WebviewWindowBuilder::new(app, "main", WebviewUrl::App(page.into()))
                .title("Agent Park 3D")
                .inner_size(1280.0, 800.0)
                .build()?;
            let child = spawn_state(app.handle().clone());
            app.manage(StateProcess(Mutex::new(child)));
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building park3d")
        .run(|app, event| {
            if let RunEvent::Exit = event {
                if let Some(mut child) = app.state::<StateProcess>().0.lock().unwrap().take() {
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        });
}
