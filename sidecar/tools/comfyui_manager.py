import json
import os
import re
import sys
import time
import socket
import configparser
import subprocess
import threading
from pathlib import Path
from typing import Optional, Tuple


SIDECAR_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(SIDECAR_DIR, "config.ini")
LOGS_DIR = os.path.join(SIDECAR_DIR, "logs")
COMFYUI_PORT = 8188
LAUNCH_MODE_PORTABLE = "portable"
LAUNCH_MODE_EXTERNAL = "external"
VALID_LAUNCH_MODES = {LAUNCH_MODE_PORTABLE, LAUNCH_MODE_EXTERNAL}

_process: Optional[subprocess.Popen] = None
_reader_thread: Optional[threading.Thread] = None
_ready = False
_log_lines: list[str] = []


def _log(msg: str):
    line = f"[ComfyUI] {msg}"
    _log_lines.append(line)
    if len(_log_lines) > 200:
        _log_lines.pop(0)
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(os.path.join(LOGS_DIR, "comfyui-manager.log"), "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _read_config():
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        cfg.read(CONFIG_PATH, encoding="utf-8")
    return cfg


def get_comfyui_path() -> str:
    profile = get_selected_comfyui_profile()
    if profile:
        return profile["path"]
    cfg = _read_config()
    if not cfg.has_section("ComfyUI"):
        return ""
    return cfg.get("ComfyUI", "path", fallback="").strip()


def set_comfyui_path(path: str, name: str = "Default"):
    cfg = _read_config()
    if "ComfyUI" not in cfg:
        cfg.add_section("ComfyUI")
    cfg.set("ComfyUI", "path", path)
    cfg.set("ComfyUI", "selected", "default")
    profiles = _profiles_from_config(cfg)
    profiles = [p for p in profiles if p.get("id") != "default"]
    profiles.insert(0, {"id": "default", "name": name or "Default", "path": path, "launch_mode": LAUNCH_MODE_PORTABLE})
    cfg.set("ComfyUI", "profiles", json.dumps(profiles, ensure_ascii=False))
    if not cfg.has_option("ComfyUI", "port"):
        cfg.set("ComfyUI", "port", str(COMFYUI_PORT))
    _write_config(cfg)


def _write_config(cfg):
    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        cfg.write(f)


def _slugify_profile_id(name: str, fallback: str = "comfyui") -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", name.strip().lower()).strip("-")
    return cleaned or fallback


def _profiles_from_config(cfg) -> list[dict]:
    if not cfg.has_section("ComfyUI"):
        return []

    raw = cfg.get("ComfyUI", "profiles", fallback="").strip()
    profiles: list[dict] = []
    if raw:
        try:
            payload = json.loads(raw)
            if isinstance(payload, list):
                for item in payload:
                    if not isinstance(item, dict):
                        continue
                    profile_id = str(item.get("id") or "").strip()
                    name = str(item.get("name") or profile_id or "ComfyUI").strip()
                    path = str(item.get("path") or "").strip()
                    launch_mode = _normalize_launch_mode(str(item.get("launch_mode") or item.get("launchMode") or ""))
                    if profile_id and path:
                        profiles.append({"id": profile_id, "name": name, "path": path, "launch_mode": launch_mode})
        except Exception:
            pass

    legacy_path = cfg.get("ComfyUI", "path", fallback="").strip()
    if legacy_path and not any(p["path"] == legacy_path for p in profiles):
        profiles.insert(0, {"id": "default", "name": "Default", "path": legacy_path, "launch_mode": LAUNCH_MODE_PORTABLE})
    return profiles


def _normalize_launch_mode(value: str | None) -> str:
    mode = (value or "").strip().lower()
    if mode in {"desktop", "manual", "externally_managed"}:
        return LAUNCH_MODE_EXTERNAL
    if mode in VALID_LAUNCH_MODES:
        return mode
    return LAUNCH_MODE_PORTABLE


def list_comfyui_profiles() -> list[dict]:
    cfg = _read_config()
    if not cfg.has_section("ComfyUI"):
        return []
    selected_id = cfg.get("ComfyUI", "selected", fallback="").strip()
    profiles = _profiles_from_config(cfg)
    return [
        {
            **profile,
            "selected": profile["id"] == selected_id or (not selected_id and index == 0),
            "valid": is_valid_comfyui_path(profile["path"]),
        }
        for index, profile in enumerate(profiles)
    ]


def get_selected_comfyui_profile() -> dict | None:
    cfg = _read_config()
    if not cfg.has_section("ComfyUI"):
        return None
    selected_id = cfg.get("ComfyUI", "selected", fallback="").strip()
    profiles = _profiles_from_config(cfg)
    if selected_id:
        for profile in profiles:
            if profile["id"] == selected_id:
                return profile
    return profiles[0] if profiles else None


def get_comfyui_launch_mode() -> str:
    profile = get_selected_comfyui_profile()
    if profile:
        return _normalize_launch_mode(profile.get("launch_mode"))
    return LAUNCH_MODE_PORTABLE


def save_comfyui_profile(
    name: str,
    path: str,
    profile_id: str | None = None,
    select: bool = True,
    launch_mode: str | None = None,
) -> dict:
    cfg = _read_config()
    if "ComfyUI" not in cfg:
        cfg.add_section("ComfyUI")
    profiles = _profiles_from_config(cfg)
    clean_name = (name or Path(path).name or "ComfyUI").strip()
    base_id = profile_id or _slugify_profile_id(clean_name)
    profile_id = base_id
    existing_ids = {p["id"] for p in profiles if p["id"] != profile_id}
    index = 2
    while profile_id in existing_ids:
        profile_id = f"{base_id}-{index}"
        index += 1
    profile = {
        "id": profile_id,
        "name": clean_name,
        "path": path.strip(),
        "launch_mode": _normalize_launch_mode(launch_mode),
    }
    profiles = [p for p in profiles if p["id"] != profile_id and p["path"] != profile["path"]]
    profiles.append(profile)
    cfg.set("ComfyUI", "profiles", json.dumps(profiles, ensure_ascii=False))
    if select:
        cfg.set("ComfyUI", "selected", profile_id)
        cfg.set("ComfyUI", "path", profile["path"])
    if not cfg.has_option("ComfyUI", "port"):
        cfg.set("ComfyUI", "port", str(COMFYUI_PORT))
    _write_config(cfg)
    return {**profile, "selected": select, "valid": is_valid_comfyui_path(profile["path"])}


def select_comfyui_profile(profile_id: str) -> dict | None:
    cfg = _read_config()
    profiles = _profiles_from_config(cfg)
    for profile in profiles:
        if profile["id"] == profile_id:
            if "ComfyUI" not in cfg:
                cfg.add_section("ComfyUI")
            cfg.set("ComfyUI", "selected", profile_id)
            cfg.set("ComfyUI", "path", profile["path"])
            cfg.set("ComfyUI", "profiles", json.dumps(profiles, ensure_ascii=False))
            _write_config(cfg)
            return {**profile, "selected": True, "valid": is_valid_comfyui_path(profile["path"])}
    return None


def verify_comfyui_running(host: str = "127.0.0.1", port: int = COMFYUI_PORT) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(2)
            return sock.connect_ex((host, port)) == 0
    except Exception:
        return False


def is_valid_comfyui_path(path: str) -> bool:
    if not path or not os.path.exists(path):
        return False
    main_py = os.path.join(path, "main.py")
    if os.path.exists(main_py):
        return True
    comfy_sub = os.path.join(path, "ComfyUI", "main.py")
    if os.path.exists(comfy_sub):
        return True
    return False


def get_comfyui_code_path(path: str) -> str:
    main_py = os.path.join(path, "main.py")
    if os.path.exists(main_py):
        return path
    comfy_sub = os.path.join(path, "ComfyUI", "main.py")
    if os.path.exists(comfy_sub):
        return os.path.join(path, "ComfyUI")
    return path


def get_comfyui_launch_info(path: str) -> Tuple[list[str] | str, str, str]:
    code_path = get_comfyui_code_path(path)

    if sys.platform == "win32":
        code_path = os.path.normpath(code_path)

        python_embeded = os.path.join(code_path, "python_embeded", "python.exe")
        if os.path.exists(python_embeded):
            python_embeded = os.path.normpath(python_embeded)
            main_py = os.path.normpath(os.path.join(code_path, "main.py"))
            cmd = [
                python_embeded,
                "-s",
                main_py,
                "--windows-standalone-build",
                "--disable-auto-launch",
                "--disable-dynamic-vram",
            ]
            return cmd, code_path, "python_embeded"

        parent_dir = os.path.dirname(code_path)
        parent_python = os.path.join(parent_dir, "python_embeded", "python.exe")
        if os.path.exists(parent_python):
            parent_python = os.path.normpath(parent_python)
            main_py = os.path.normpath(os.path.join(code_path, "main.py"))
            cmd = [
                parent_python,
                "-s",
                main_py,
                "--windows-standalone-build",
                "--disable-auto-launch",
                "--disable-dynamic-vram",
            ]
            return cmd, parent_dir, "python_embeded"

        bat_file = os.path.join(code_path, "run_nvidia_gpu.bat")
        if os.path.exists(bat_file):
            return os.path.normpath(bat_file), code_path, "bat"

        parent_bat = os.path.join(os.path.dirname(code_path), "run_nvidia_gpu.bat")
        if os.path.exists(parent_bat):
            return os.path.normpath(parent_bat), os.path.dirname(code_path), "bat"

    return "", code_path, ""


def auto_detect_comfyui_path() -> Optional[str]:
    cfg = _read_config()
    saved = cfg.get("ComfyUI", "path", fallback="").strip() if cfg.has_section("ComfyUI") else ""
    if saved and is_valid_comfyui_path(saved):
        _log(f"Using saved ComfyUI path: {saved}")
        return saved

    common = []
    if sys.platform == "win32":
        common = [
            r"E:\ComfyUI_windows_portable",
            r"E:\ComfyUI_windows_portable\ComfyUI",
            r"C:\ComfyUI",
            r"D:\ComfyUI",
        ]
    else:
        common = [
            os.path.join(os.path.expanduser("~"), "ComfyUI"),
            "/opt/ComfyUI",
        ]
    for p in common:
        if is_valid_comfyui_path(p):
            _log(f"Auto-detected ComfyUI at: {p}")
            set_comfyui_path(p)
            return p
    return None


def start_comfyui() -> bool:
    global _process, _reader_thread, _ready

    if verify_comfyui_running():
        if _process is not None and _process.poll() is None:
            _log("Managed ComfyUI already running on port 8188")
        else:
            _log("Detected external ComfyUI on port 8188; using it without taking process ownership")
        _ready = True
        return True

    if _process is not None and _process.poll() is None:
        _log("ComfyUI process already running")
        return True

    _ready = False

    launch_mode = get_comfyui_launch_mode()
    if launch_mode == LAUNCH_MODE_EXTERNAL:
        _log("External/Desktop ComfyUI profile selected. Start ComfyUI Desktop manually, then refresh status.")
        return False

    path = get_comfyui_path()
    if not path:
        path = auto_detect_comfyui_path()
    if not path:
        _log("ERROR: No ComfyUI path configured. Edit sidecar/config.ini [ComfyUI] path=")
        return False

    if not is_valid_comfyui_path(path):
        _log(f"ERROR: Invalid ComfyUI path: {path}")
        return False

    launch_cmd, work_dir, launch_type = get_comfyui_launch_info(path)
    if not launch_cmd:
        _log("ERROR: No valid launch method found. Check python_embeded or run_nvidia_gpu.bat")
        return False

    _log(f"Launch type: {launch_type}")
    _log(f"Working dir: {work_dir}")
    display_cmd = subprocess.list2cmdline(launch_cmd) if isinstance(launch_cmd, list) else launch_cmd
    _log(f"Command: {display_cmd}")

    try:
        if sys.platform == "win32":
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = subprocess.SW_HIDE
            cmd_list = launch_cmd if isinstance(launch_cmd, list) else ["cmd.exe", "/c", launch_cmd]
            log_path = os.path.join(LOGS_DIR, "comfyui-process.log")
            os.makedirs(LOGS_DIR, exist_ok=True)
            log_file = open(log_path, "ab", buffering=0)
            _process = subprocess.Popen(
                cmd_list,
                cwd=work_dir,
                stdin=subprocess.DEVNULL,
                stdout=log_file,
                stderr=subprocess.STDOUT,
                startupinfo=startupinfo,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        else:
            log_path = os.path.join(LOGS_DIR, "comfyui-process.log")
            os.makedirs(LOGS_DIR, exist_ok=True)
            log_file = open(log_path, "ab", buffering=0)
            _process = subprocess.Popen(
                launch_cmd, shell=True, cwd=work_dir,
                stdin=subprocess.DEVNULL, stdout=log_file, stderr=subprocess.STDOUT,
            )

        _log(f"ComfyUI started (PID: {_process.pid})")

        threading.Thread(target=_wait_for_ready, daemon=True).start()
        return True

    except Exception as e:
        _log(f"ERROR starting ComfyUI: {e}")
        _process = None
        return False


def _wait_for_ready(timeout: int = 300):
    global _ready
    _log(f"Waiting for ComfyUI to be ready (timeout: {timeout}s)...")
    start = time.time()
    last_log = 0
    while time.time() - start < timeout:
        if verify_comfyui_running():
            _ready = True
            _log("ComfyUI is ready!")
            return
        elapsed = int(time.time() - start)
        if elapsed - last_log >= 30:
            _log(f"Still waiting... ({elapsed}s)")
            last_log = elapsed
        if _process and _process.poll() is not None:
            _log("ERROR: ComfyUI process exited unexpectedly")
            return
        time.sleep(2)
    _log(f"WARNING: ComfyUI ready timeout ({timeout}s)")


def stop_comfyui():
    global _process, _reader_thread, _ready

    killed = False

    if _process is None or _process.poll() is not None:
        _process = None
        _reader_thread = None
        _ready = verify_comfyui_running()
        _log("No managed ComfyUI process to stop; external/Desktop ComfyUI was left untouched")
        return

    # Method 1: Use the tracked process
    if _process is not None and _process.poll() is None:
        _log(f"Stopping ComfyUI (PID: {_process.pid})...")
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(_process.pid)],
                    capture_output=True, timeout=10,
                )
            else:
                _process.terminate()
                _process.wait(timeout=10)
            killed = True
            _log("ComfyUI process stopped via tracked PID")
        except Exception as e:
            _log(f"Warning during managed stop: {e}")

    # Clear VRAM via ComfyUI API if the managed process is still responding.
    try:
        import urllib.request
        urllib.request.urlopen("http://127.0.0.1:8188/memory/free", timeout=5)
        _log("VRAM freed")
    except Exception:
        pass

    # Wait for port to close
    for _ in range(10):
        if not verify_comfyui_running():
            killed = True
            break
        time.sleep(1)

    if verify_comfyui_running():
        _log("Port 8188 is still active after stopping managed process; treating it as external ComfyUI")

    _process = None
    _reader_thread = None
    _ready = verify_comfyui_running()
    _log(f"ComfyUI stop complete (killed={killed})")


def _find_pid_on_port(port: int) -> int | None:
    """Find the PID of the process listening on a given port."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["netstat", "-ano"],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.strip().split()
                    if parts:
                        pid_str = parts[-1]
                        if pid_str.isdigit():
                            return int(pid_str)
        else:
            result = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True, text=True, timeout=5,
            )
            pid_str = result.stdout.strip()
            if pid_str and pid_str.isdigit():
                return int(pid_str)
    except Exception as e:
        _log(f"Port scan error: {e}")
    return None


def get_status() -> dict:
    running = verify_comfyui_running()
    profile = get_selected_comfyui_profile()
    return {
        "running": running,
        "ready": _ready or running,
        "configured_path": profile["path"] if profile else get_comfyui_path(),
        "launch_mode": profile.get("launch_mode", LAUNCH_MODE_PORTABLE) if profile else LAUNCH_MODE_PORTABLE,
        "selected_profile_id": profile.get("id") if profile else None,
        "process_alive": _process is not None and _process.poll() is None if _process else False,
        "recent_logs": _log_lines[-20:],
    }
