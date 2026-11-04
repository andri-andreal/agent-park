// Agent Park 3D: a window onto the same park the terminal screensaver shows.
//
// Agent detection stays in Python (one source of truth): this app runs
// `python3 park_state.py` (`python` on Windows), which prints the park's state as one
// JSON object per line, and forwards every line to the page as a "park-state" event.
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::io::{BufRead, BufReader};
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;
use std::thread;

use tauri::{Emitter, Manager, RunEvent, WebviewUrl, WebviewWindowBuilder};

/// The state script: $PARK_STATE if set, else the one in the repo next to this app.
fn state_script(app: &tauri::AppHandle) -> PathBuf {
    std::env::var_os("PARK_STATE")
        .map(PathBuf::from)
        .unwrap_or_else(|| {
            let bundled = app
                .path()
                .resource_dir()
                .ok()
                .map(|path| path.join("backend/park_state.py"));
            bundled.filter(|path| path.exists()).unwrap_or_else(|| {
                PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("../../park_state.py")
            })
        })
}

/// Keeps a child's console window from flashing up when this is a GUI app on Windows.
#[cfg(windows)]
fn hide_window(command: &mut Command) {
    use std::os::windows::process::CommandExt;
    command.creation_flags(0x0800_0000); // CREATE_NO_WINDOW
}

#[cfg(not(windows))]
fn hide_window(_command: &mut Command) {}

/// The interpreter on Windows: the first of `python` and `py -3` that really runs. (A bare
/// `python.exe` can be the Microsoft Store stub, which fails when Python is not installed.)
#[cfg(windows)]
fn default_python() -> Command {
    for (program, args) in [("python", &[][..]), ("py", &["-3"][..])] {
        let mut probe = Command::new(program);
        probe
            .args(args)
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null());
        hide_window(&mut probe);
        if probe
            .status()
            .map(|status| status.success())
            .unwrap_or(false)
        {
            let mut command = Command::new(program);
            command.args(args);
            return command;
        }
    }
    Command::new("python")
}

#[cfg(not(windows))]
fn default_python() -> Command {
    Command::new("python3")
}

/// Python for the backend scripts: $AGENT_PARK_PYTHON if set, else the OS's usual name.
fn python() -> Command {
    let mut command = match std::env::var_os("AGENT_PARK_PYTHON") {
        Some(path) => Command::new(path),
        None => default_python(),
    };
    // Windows pipes default to a legacy code page; the scripts speak UTF-8.
    command.env("PYTHONUTF8", "1");
    hide_window(&mut command);
    // linuxdeploy's AppRun points Python and the dynamic linker at the AppImage,
    // which does not contain a Python standard library. Use system Python's
    // normal environment for this child while keeping the app's own libraries.
    if std::env::var_os("APPIMAGE").is_some() {
        command
            .env_remove("PYTHONHOME")
            .env_remove("PYTHONPATH")
            .env_remove("LD_LIBRARY_PATH");
    }
    command
}

/// Starts the state script and streams its lines to the page; the page shows
/// "no data" by itself if this fails (no Python, script moved, ...).
fn spawn_state(app: tauri::AppHandle) -> Option<Child> {
    let script = state_script(&app);
    let mut child = python()
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

#[cfg(target_os = "linux")]
#[tauri::command]
fn notify_attention(name: String) -> Result<(), String> {
    let status = Command::new("notify-send")
        .arg("Agent Park")
        .arg(format!("{name} needs your attention"))
        .status()
        .map_err(|error| format!("Cannot send notification: {error}"))?;
    if status.success() {
        Ok(())
    } else {
        Err("Desktop notification failed".into())
    }
}

#[cfg(not(target_os = "linux"))]
#[tauri::command]
fn notify_attention(app: tauri::AppHandle, name: String) -> Result<(), String> {
    use tauri_plugin_notification::NotificationExt;
    app.notification()
        .builder()
        .title("Agent Park")
        .body(format!("{name} needs your attention"))
        .show()
        .map_err(|error| format!("Cannot send notification: {error}"))
}

#[tauri::command]
fn integration_setup(app: tauri::AppHandle, agents: Option<Vec<String>>) -> Result<String, String> {
    let script = state_script(&app).with_file_name("agent_park.py");
    let mut command = python();
    command.arg(script);
    match agents {
        None => {
            command.arg("onboarding-status");
        }
        Some(names) => {
            if names.is_empty()
                || names.iter().any(|name| {
                    !["claude", "codex", "opencode", "pi", "mcode"].contains(&name.as_str())
                })
            {
                return Err("Select at least one supported integration".into());
            }
            command.arg("onboarding-setup").args(names);
        }
    }
    let output = command
        .output()
        .map_err(|error| format!("Cannot run setup: {error}"))?;
    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    if output.status.success() {
        Ok(stdout)
    } else {
        Err(format!(
            "{}{}",
            stdout,
            String::from_utf8_lossy(&output.stderr)
        ))
    }
}

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
    #[cfg(target_os = "linux")]
    if std::env::var_os("WEBKIT_DISABLE_DMABUF_RENDERER").is_none() {
        std::env::set_var("WEBKIT_DISABLE_DMABUF_RENDERER", "1");
    }
    let builder = tauri::Builder::default();
    // Linux notifies through notify-send; the other systems through the notification plugin.
    #[cfg(not(target_os = "linux"))]
    let builder = builder.plugin(tauri_plugin_notification::init());
    builder
        .invoke_handler(tauri::generate_handler![
            notify_attention,
            integration_setup
        ])
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
