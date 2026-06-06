mod commands;

use commands::sidecar::SidecarState;
use reqwest::Client;
use std::fs::{create_dir_all, OpenOptions};
use std::io::Write;
use std::net::{SocketAddr, TcpStream};
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::time::Duration;
use tauri::WindowEvent;
use tokio::sync::Mutex;

fn log_path(base_dir: &Path) -> PathBuf {
    base_dir.join("logs").join("ultra-studio-sidecar.log")
}

fn append_log(path: &Path, message: impl AsRef<str>) {
    if let Some(parent) = path.parent() {
        let _ = create_dir_all(parent);
    }
    if let Ok(mut file) = OpenOptions::new().create(true).append(true).open(path) {
        let _ = writeln!(file, "{}", message.as_ref());
    }
}

fn find_project_dir() -> PathBuf {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Ok(current_dir) = std::env::current_dir() {
        candidates.push(current_dir);
    }

    if let Ok(exe) = std::env::current_exe() {
        if let Some(exe_dir) = exe.parent() {
            let mut dir = Some(exe_dir);
            while let Some(current) = dir {
                candidates.push(current.to_path_buf());
                dir = current.parent();
            }
        }
    }

    for candidate in candidates {
        if candidate.join("sidecar").join("main.py").exists() {
            return candidate;
        }
    }

    std::env::current_dir().unwrap_or_else(|_| PathBuf::from("."))
}

fn sidecar_port_ready() -> bool {
    let addr: SocketAddr = match "127.0.0.1:9257".parse() {
        Ok(addr) => addr,
        Err(_) => return false,
    };
    TcpStream::connect_timeout(&addr, Duration::from_millis(450)).is_ok()
}

fn start_python_sidecar() {
    let project_dir = find_project_dir();
    let log_file = log_path(&project_dir);
    let sidecar_main = project_dir.join("sidecar").join("main.py");
    let venv_python = project_dir
        .join("sidecar")
        .join(".venv")
        .join("Scripts")
        .join("python.exe");
    let python = if venv_python.exists() {
        venv_python
    } else {
        PathBuf::from("python")
    };

    append_log(&log_file, "");
    append_log(&log_file, "================ Ultra Studio sidecar startup ================");
    append_log(&log_file, format!("current_dir={:?}", std::env::current_dir().ok()));
    append_log(&log_file, format!("current_exe={:?}", std::env::current_exe().ok()));
    append_log(&log_file, format!("project_dir={}", project_dir.display()));
    append_log(&log_file, format!("python={}", python.display()));
    append_log(&log_file, format!("sidecar_main={}", sidecar_main.display()));
    append_log(&log_file, format!("sidecar_exists={}", sidecar_main.exists()));

    if sidecar_port_ready() {
        append_log(&log_file, "sidecar port 9257 is already available; skip spawning a new backend process.");
        return;
    }

    if !sidecar_main.exists() {
        append_log(&log_file, "ERROR: sidecar/main.py was not found. The exe is probably not being launched from the project root or the sidecar folder is not bundled.");
        return;
    }

    let sidecar_stdout = OpenOptions::new()
        .create(true)
        .append(true)
        .open(project_dir.join("logs").join("sidecar-stdout.log"))
        .ok();
    let sidecar_stderr = OpenOptions::new()
        .create(true)
        .append(true)
        .open(project_dir.join("logs").join("sidecar-stderr.log"))
        .ok();

    let mut command = Command::new(&python);
    command
        .arg(&sidecar_main)
        .current_dir(&project_dir)
        .env("ULTRA_STUDIO_PROJECT_DIR", &project_dir)
        .stdin(Stdio::null());

    if let Some(file) = sidecar_stdout {
        command.stdout(Stdio::from(file));
    } else {
        command.stdout(Stdio::null());
    }
    if let Some(file) = sidecar_stderr {
        command.stderr(Stdio::from(file));
    } else {
        command.stderr(Stdio::null());
    }

    let spawn_result = command.spawn();

    match spawn_result {
        Ok(mut child) => {
            append_log(&log_file, format!("spawned sidecar pid={}", child.id()));

            let wait_log = log_file.clone();
            std::thread::spawn(move || match child.wait() {
                Ok(status) => append_log(&wait_log, format!("sidecar exited: {}", status)),
                Err(e) => append_log(&wait_log, format!("sidecar wait error: {}", e)),
            });
        }
        Err(e) => {
            append_log(&log_file, format!("ERROR: failed to spawn sidecar: {}", e));
        }
    }
}

fn request_sidecar_shutdown() {
    let project_dir = find_project_dir();
    let log_file = log_path(&project_dir);
    append_log(&log_file, "Tauri window is closing; requesting sidecar shutdown");

    let client = match reqwest::blocking::Client::builder()
        .timeout(Duration::from_secs(8))
        .build()
    {
        Ok(client) => client,
        Err(e) => {
            append_log(&log_file, format!("ERROR: failed to create blocking shutdown client: {}", e));
            return;
        }
    };

    match client.post("http://127.0.0.1:9257/api/app/shutdown").send() {
        Ok(resp) => append_log(&log_file, format!("sidecar shutdown response: {}", resp.status())),
        Err(e) => append_log(&log_file, format!("sidecar shutdown request failed: {}", e)),
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    start_python_sidecar();

    let client = Client::builder()
        .timeout(Duration::from_secs(600))
        .connect_timeout(Duration::from_secs(10))
        .build()
        .expect("Failed to create HTTP client");

    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarState {
            client,
            ready: Mutex::new(false),
        })
        .invoke_handler(tauri::generate_handler![
            commands::sidecar::init_sidecar,
            commands::sidecar::list_projects,
            commands::sidecar::create_project,
            commands::sidecar::delete_project,
            commands::sidecar::list_project_files,
            commands::sidecar::list_conversations,
            commands::sidecar::create_conversation,
            commands::sidecar::delete_conversation,
            commands::sidecar::get_messages,
            commands::sidecar::send_message,
            commands::sidecar::send_stream_start,
            commands::sidecar::update_conversation_title,
            commands::sidecar::detect_local_models,
            commands::sidecar::get_diagnostics,
            commands::sidecar::get_comfyui_status,
            commands::sidecar::list_comfyui_profiles,
            commands::sidecar::save_comfyui_profile,
            commands::sidecar::select_comfyui_profile,
            commands::sidecar::start_comfyui,
            commands::sidecar::stop_comfyui,
            commands::sidecar::get_persona,
            commands::sidecar::update_persona,
            commands::sidecar::list_model_configs,
            commands::sidecar::add_model_config,
            commands::sidecar::remove_model_config,
            commands::sidecar::set_default_model_config,
            commands::sidecar::list_embedding_configs,
            commands::sidecar::add_embedding_config,
            commands::sidecar::remove_embedding_config,
            commands::sidecar::remember_memory,
            commands::sidecar::generate_3d_text,
            commands::sidecar::generate_3d_image,
            commands::sidecar::generate_3d_fusion,
            commands::sidecar::generate_3d_multiview,
            commands::sidecar::generate_3d_improve_image,
            commands::sidecar::generate_flux_image,
            commands::sidecar::list_image_loras,
            commands::sidecar::generate_flux_multiview_images,
            commands::sidecar::generate_wan_video,
            commands::sidecar::create_showcase_materials,
            commands::sidecar::list_generation_tasks,
            commands::sidecar::generate_3d_text_stream,
            commands::sidecar::generate_3d_image_stream,
            commands::sidecar::generate_3d_fusion_stream,
            commands::sidecar::generate_3d_multiview_stream,
            commands::sidecar::cancel_3d_generation,
            commands::sidecar::get_3d_output_file,
            commands::sidecar::export_3d_model,
            commands::sidecar::reveal_path,
        ])
        .on_window_event(|_window, event| {
            if let WindowEvent::CloseRequested { .. } = event {
                request_sidecar_shutdown();
            }
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
