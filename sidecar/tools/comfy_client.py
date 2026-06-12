import json
import urllib.request
import requests
import websocket
import uuid
import time
import os
import random
import glob
import copy

from tools.comfyui_manager import (
    get_comfyui_path,
    get_comfyui_code_path,
    SIDECAR_DIR,
)

CLIENT_ID = str(uuid.uuid4())

SERVER = "127.0.0.1:8188"

FLUX_FAST = "flux-2-klein-4b-Q4_K_M.gguf"
FLUX_QUALITY = "Flux-2-Klein-9B-KV-Q4_K_M.gguf"
FLUX_FAST_CLIP = "qwen_3_4b.safetensors"
FLUX_QUALITY_CLIP = "qwen_3_8b_fp8mixed.safetensors"
HY3D_MULTIVIEW_FAST_MODEL = "hunyuan3d-dit-v2-mv-fast.safetensors"
WAN_VIDEO_STANDARD_MODEL = "wan2.2_ti2v_5B_fp16.safetensors"
WAN_VIDEO_FAST_MODEL = "Wan2_2-TI2V-5B-Turbo-Q4_K_M.gguf"
WAN_VIDEO_FAST_LORA_FULL_ATTN = "Wan2_2_5B_FastWanFullAttn_lora_rank_128_bf16.safetensors"
WAN_VIDEO_FAST_LORA_TURBO = "Wan22_TI2V_5B_Turbo_lora_rank_64_fp16.safetensors"
WAN_VIDEO_STANDARD_ACCEL_LORA_STRENGTH = 0.5
WAN_VIDEO_EXPERIMENTAL_LORA_STRENGTH = 0.5
WAN_VIDEO_FAST_LORA_STRENGTH = -0.2

BACKEND_DIR = os.path.join(SIDECAR_DIR, "backend")
IMAGE_LORA_DIR = os.path.abspath(os.path.join(SIDECAR_DIR, os.pardir, "lora"))
IMAGE_LORA_EXTENSIONS = {".safetensors", ".pt", ".ckpt"}


def get_output_dir():
    cpath = get_comfyui_path()
    if cpath:
        code_path = get_comfyui_code_path(cpath)
        return os.path.join(code_path, "output")
    return ""


def get_workflows():
    return {
        "Text to 3D": os.path.join(BACKEND_DIR, "\u6587\u751f\u56fe\u7247\u751f\u6a21\u578b.json"),
        "Image to 3D": os.path.join(BACKEND_DIR, "\u56fe\u7247\u751f\u6a21\u578b.json"),
        "Dual Image Fusion": os.path.join(BACKEND_DIR, "\u53cc\u56fe\u751f\u56fe\u751f\u6a21\u578b.json"),
        "Hy3D MultiView": os.path.join(BACKEND_DIR, "多视角生模型.json"),
    }


def get_flux2_workflow():
    return os.path.join(BACKEND_DIR, "\u6539\u56fe.json")


def get_wan_video_workflow():
    return os.path.join(BACKEND_DIR, "Wan 2.2 5b TI2V\u89c6\u9891.json")


def get_wan_video_14b_workflow(has_image=False):
    filename = "\u56fe\u751f\u89c6\u9891all-in-one-14b\u56fe\u751f\u89c6\u9891.json" if has_image else "\u56fe\u751f\u89c6\u9891all-in-one-14b\u6587\u751f\u89c6\u9891.json"
    return os.path.join(BACKEND_DIR, filename)


def get_flux_lora_workflow():
    return os.path.join(BACKEND_DIR, "lora\u52a0\u8f7d.json")


def _flux_lora_family(quality):
    return "9b" if quality == "quality" else "4b"


def _is_allowed_image_lora(path):
    return os.path.splitext(path)[1].lower() in IMAGE_LORA_EXTENSIONS


def list_flux_image_loras(quality="fast"):
    family = _flux_lora_family(quality)
    family_dir = os.path.join(IMAGE_LORA_DIR, family)
    os.makedirs(family_dir, exist_ok=True)
    items = []
    paths = glob.glob(os.path.join(family_dir, "**", "*"), recursive=True)
    paths += glob.glob(os.path.join(IMAGE_LORA_DIR, "*"))
    for path in paths:
        if not os.path.isfile(path) or not _is_allowed_image_lora(path):
            continue
        relative_id = os.path.relpath(path, IMAGE_LORA_DIR).replace("\\", "/")
        is_family_file = relative_id.lower().startswith(f"{family}/")
        is_named_root_file = "/" not in relative_id and family in os.path.basename(path).lower()
        if not is_family_file and not is_named_root_file:
            continue
        items.append({
            "id": relative_id,
            "name": os.path.basename(path),
        })
    items.sort(key=lambda item: item["name"].lower())
    return {
        "qualityMode": quality,
        "family": family.upper(),
        "directory": family_dir,
        "items": items,
    }


def _resolve_flux_image_lora(quality, lora_id):
    if not lora_id:
        return None
    family = _flux_lora_family(quality)
    relative_id = str(lora_id).replace("\\", "/").strip("/")
    if not relative_id or relative_id.startswith("../") or "/../" in f"/{relative_id}/":
        raise ValueError("Invalid image LoRA path")
    root = os.path.realpath(IMAGE_LORA_DIR)
    path = os.path.realpath(os.path.join(root, relative_id.replace("/", os.sep)))
    if os.path.commonpath([root, path]) != root or not os.path.isfile(path) or not _is_allowed_image_lora(path):
        raise ValueError("Image LoRA file not found")
    relative = os.path.relpath(path, root).replace("\\", "/")
    is_family_file = relative.lower().startswith(f"{family}/")
    is_named_root_file = "/" not in relative and family in os.path.basename(path).lower()
    if not is_family_file and not is_named_root_file:
        raise ValueError(f"Selected image LoRA is not compatible with Flux {family.upper()}")
    return path, relative


def _remove_legacy_flux_image_lora_link(source_path, relative, comfy_lora_dir):
    relative_parts = relative.replace("\\", "/").split("/")
    if len(relative_parts) < 2 or relative_parts[0].lower() not in {"4b", "9b"}:
        return
    root = os.path.normcase(os.path.normpath(comfy_lora_dir))
    legacy_paths = (
        os.path.join(comfy_lora_dir, *relative_parts),
        os.path.join(comfy_lora_dir, "ultra_studio", *relative_parts),
    )
    for legacy_destination in legacy_paths:
        if not os.path.isfile(legacy_destination):
            continue
        try:
            if not os.path.samefile(source_path, legacy_destination):
                continue
        except OSError:
            continue
        os.remove(legacy_destination)
        parent = os.path.dirname(legacy_destination)
        while os.path.normcase(os.path.normpath(parent)) != root:
            try:
                os.rmdir(parent)
            except OSError:
                break
            parent = os.path.dirname(parent)


def _register_flux_image_lora(quality, lora_id):
    resolved = _resolve_flux_image_lora(quality, lora_id)
    if not resolved:
        return ""
    source_path, relative = resolved
    comfy_path = get_comfyui_path()
    if not comfy_path:
        raise ValueError("ComfyUI not configured. Please set ComfyUI path before loading an image LoRA")
    comfy_lora_dir = os.path.join(get_comfyui_code_path(comfy_path), "models", "loras")
    family = _flux_lora_family(quality)
    destination_name = f"ultra_studio_{family}_{os.path.basename(source_path)}"
    destination = os.path.join(comfy_lora_dir, destination_name)
    os.makedirs(comfy_lora_dir, exist_ok=True)
    _remove_legacy_flux_image_lora_link(source_path, relative, comfy_lora_dir)
    if os.path.exists(destination):
        try:
            if os.path.samefile(source_path, destination):
                # ComfyUI may cache filename choices until the registered file changes.
                os.utime(destination, None)
                os.utime(comfy_lora_dir, None)
                _ensure_comfy_lora_visible(destination_name)
                return destination_name
        except OSError:
            pass
        os.remove(destination)
    try:
        os.link(source_path, destination)
    except OSError as exc:
        raise ValueError(
            "Unable to link this image LoRA into ComfyUI. Keep the project and ComfyUI on the same drive."
        ) from exc
    os.utime(comfy_lora_dir, None)
    _ensure_comfy_lora_visible(destination_name)
    return destination_name


def _ensure_comfy_lora_visible(lora_name):
    try:
        object_info = _get_object_info()
        options = (
            object_info.get("LoraLoaderModelOnly", {})
            .get("input", {})
            .get("required", {})
            .get("lora_name", [[]])[0]
        )
    except Exception as exc:
        raise ValueError("Unable to query ComfyUI image LoRA models") from exc
    if lora_name not in options:
        raise ValueError(
            "ComfyUI has not refreshed the linked image LoRA yet. Restart ComfyUI once, then try again."
        )


def _apply_flux_image_lora(workflow, quality, lora_id, model_node_id="66"):
    comfy_lora_name = _register_flux_image_lora(quality, lora_id)
    if not comfy_lora_name:
        return
    with open(get_flux_lora_workflow(), "r", encoding="utf-8") as f:
        node = copy.deepcopy(json.load(f)["2"])
    node_id = "9001"
    node["inputs"]["model"] = [model_node_id, 0]
    node["inputs"]["lora_name"] = comfy_lora_name
    node["inputs"]["strength_model"] = 1.0
    for existing in workflow.values():
        inputs = existing.get("inputs", {})
        for key, value in list(inputs.items()):
            if key == "model" and value == [model_node_id, 0]:
                inputs[key] = [node_id, 0]
    workflow[node_id] = node


def _collect_dependencies(workflow, output_node_id):
    seen = set()

    def visit(node_id):
        node_id = str(node_id)
        if node_id in seen or node_id not in workflow:
            return
        seen.add(node_id)
        inputs = workflow[node_id].get("inputs", {})
        for value in inputs.values():
            if isinstance(value, list) and value:
                visit(value[0])
            elif isinstance(value, dict):
                for item in value.values():
                    if isinstance(item, list) and item:
                        visit(item[0])

    visit(output_node_id)
    return {node_id: workflow[node_id] for node_id in seen}


def _collect_dependencies_multi(workflow, output_node_ids):
    result = {}
    for output_node_id in output_node_ids:
        result.update(_collect_dependencies(workflow, output_node_id))
    return result


def _flux_pair(quality):
    if quality == "quality":
        return FLUX_QUALITY, FLUX_QUALITY_CLIP
    return FLUX_FAST, FLUX_FAST_CLIP


def _set_clip_loader(workflow, clip_name):
    for node in workflow.values():
        if node.get("class_type") == "CLIPLoader" and "clip_name" in node.get("inputs", {}):
            node["inputs"]["clip_name"] = clip_name


def _get_object_info():
    with urllib.request.urlopen(f"http://{SERVER}/object_info", timeout=20) as resp:
        return json.loads(resp.read())


def _ui_input_names(node):
    return {item.get("name") for item in node.get("inputs", []) if item.get("name")}


def _widget_input_names(class_info):
    input_info = (class_info or {}).get("input", {})
    names = []
    for section in ("required", "optional"):
        values = input_info.get(section, {})
        if isinstance(values, dict):
            for name in values.keys():
                if name not in names:
                    names.append(name)
    return names


def _manual_widget_inputs(class_type, widgets):
    widgets = list(widgets or [])
    specs = {
        "ImageCompositeMasked": ["x", "y", "resize_source"],
        "ImageResize+": ["width", "height", "interpolation", "method", "condition", "multiple_of"],
        "Hy3DModelLoader": ["model", "attention_mode", "cublas_ops"],
        "Hy3DDiffusersSchedulerConfig": ["scheduler", "sigmas"],
        "Hy3DGenerateMeshMultiView": ["guidance_scale", "steps", "seed"],
        "Hy3DVAEDecode": ["box_v", "octree_resolution", "num_chunks", "mc_level", "mc_algo"],
        "Hy3DPostprocessMesh": [
            "remove_floaters",
            "remove_degenerate_faces",
            "reduce_faces",
            "max_facenum",
            "smooth_normals",
        ],
        "Hy3DRenderMultiView": ["render_size", "texture_size", "normal_space"],
        "Hy3DDelightImage": ["steps", "width", "height", "cfg_image", "seed"],
        "Hy3DSampleMultiView": ["view_size", "steps", "seed", None, "denoise_strength"],
        "CV2InpaintTexture": ["inpaint_radius", "inpaint_method"],
        "Hy3DExportMesh": ["filename_prefix", "file_format", "save_file"],
        "RepeatImageBatch": ["amount"],
        "Hy3DRenderSingleView": [
            "render_type",
            "render_size",
            "camera_type",
            "camera_distance",
            "pan_x",
            "pan_y",
            "ortho_scale",
            "azimuth",
            "elevation",
            "bg_color",
        ],
    }
    names = specs.get(class_type)
    if not names:
        return None
    result = {}
    for name, value in zip(names, widgets):
        if name:
            result[name] = value
    return result


def _ui_workflow_to_api(ui_workflow):
    """Convert a ComfyUI UI workflow JSON to the API prompt format.

    The multi-view workflow is saved in UI format. Runtime object metadata tells
    us which widget values map to API input names, so this stays compatible with
    custom Hy3D nodes without hard-coding every widget.
    """
    object_info = _get_object_info()
    nodes = {str(node["id"]): node for node in ui_workflow.get("nodes", [])}
    links = {link[0]: link for link in ui_workflow.get("links", [])}

    def resolve_link(link_id):
        link = links.get(link_id)
        if not link:
            return None
        origin_id = str(link[1])
        origin_slot = link[2]
        origin = nodes.get(origin_id)
        if not origin:
            return None
        if origin.get("type") == "Reroute":
            reroute_link = (origin.get("inputs") or [{}])[0].get("link")
            return resolve_link(reroute_link) if reroute_link is not None else None
        if origin.get("type") == "PrimitiveNode":
            values = origin.get("widgets_values") or []
            return values[0] if values else None
        return [origin_id, origin_slot]

    api = {}
    for node_id, node in nodes.items():
        class_type = node.get("type")
        if not class_type or class_type in {"Note", "Reroute", "PrimitiveNode"}:
            continue

        inputs = {}
        for item in node.get("inputs", []):
            name = item.get("name")
            link_id = item.get("link")
            if not name or link_id is None:
                continue
            value = resolve_link(link_id)
            if value is not None:
                inputs[name] = value

        linked_input_names = _ui_input_names(node)
        manual_inputs = _manual_widget_inputs(class_type, node.get("widgets_values") or [])
        if manual_inputs is not None:
            for name, value in manual_inputs.items():
                if name not in linked_input_names:
                    inputs.setdefault(name, value)
        else:
            class_info = object_info.get(class_type, {})
            widget_names = _widget_input_names(class_info)
            for name, value in zip(widget_names, node.get("widgets_values") or []):
                if name not in linked_input_names:
                    inputs.setdefault(name, value)

        api[node_id] = {
            "class_type": class_type,
            "inputs": inputs,
            "_meta": {"title": node.get("title") or node.get("properties", {}).get("Node name for S&R", class_type)},
        }

    return api


def _remove_ui_control_values(workflow):
    for node in workflow.values():
        inputs = node.get("inputs", {})
        for key, value in list(inputs.items()):
            if value == "fixed":
                inputs.pop(key, None)


def _set_node_input(workflow, node_id, key, value):
    node = workflow.get(str(node_id))
    if node is None:
        raise ValueError(f"Workflow node {node_id} not found")
    node.setdefault("inputs", {})[key] = value


def upload_image(path):
    with open(path, "rb") as f:
        r = requests.post(f"http://{SERVER}/upload/image", files={"image": f})
    if r.status_code != 200:
        raise Exception(f"Upload failed: {r.text}")
    return r.json()["name"]


def queue_prompt(workflow):
    payload = {
        "prompt": workflow,
        "client_id": CLIENT_ID,
        "extra_data": {"extra_pnginfo": {"ts": str(time.time())}},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(f"http://{SERVER}/prompt", data=data)
    try:
        resp = urllib.request.urlopen(req)
        result = json.loads(resp.read())
        if "error" in result and result["error"]:
            error_msg = result.get("error", {})
            if isinstance(error_msg, dict):
                error_msg = error_msg.get("message", str(error_msg))
            raise Exception(f"ComfyUI error: {error_msg}")
        if "node_errors" in result and result["node_errors"]:
            node_errors = result["node_errors"]
            error_details = []
            for node_id, errs in node_errors.items():
                if isinstance(errs, list):
                    for e in errs:
                        error_details.append(f"Node {node_id}: {e.get('message', str(e))}")
                else:
                    error_details.append(f"Node {node_id}: {errs}")
            raise Exception(f"ComfyUI node errors:\n" + "\n".join(error_details))
        if "prompt_id" not in result:
            raise Exception(f"ComfyUI unexpected response: {result}")
        return result
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise Exception(f"ComfyUI HTTP {e.code}: {body[:500]}")


def get_history(pid):
    with urllib.request.urlopen(f"http://{SERVER}/history/{pid}") as resp:
        return json.loads(resp.read())


def find_file(prefix, subfolder=""):
    output_dir = get_output_dir()
    search_dir = os.path.join(output_dir, subfolder) if subfolder else output_dir
    if not search_dir or not os.path.exists(search_dir):
        return None
    pattern = os.path.join(search_dir, f"{prefix}*")
    files = glob.glob(pattern)
    return max(files, key=os.path.getmtime) if files else None


def clear_vram():
    try:
        requests.post(
            f"http://{SERVER}/free",
            json={"unload_models": True, "free_memory": True},
            timeout=10,
        )
    except Exception:
        pass
    try:
        urllib.request.urlopen(f"http://{SERVER}/memory/free", timeout=10)
    except Exception:
        pass


def extract_file(history, node_id):
    if node_id not in history.get("outputs", {}):
        return None

    out = history["outputs"][node_id]
    for field in ["images", "files", "result"]:
        if field not in out:
            continue
        data = out[field]

        if isinstance(data, list) and len(data) > 0:
            if field == "result" and isinstance(data[0], str):
                path = os.path.join(get_output_dir(), data[0].replace("\\", "/"))
                return path if os.path.exists(path) else None

            for item in data:
                if isinstance(item, dict) and "filename" in item:
                    sub = item.get("subfolder", "")
                    path = os.path.join(get_output_dir(), sub, item["filename"])
                    if os.path.exists(path):
                        return path
    return None


def run_pipeline(mode, quality, prompt, img1, img2=None, progress_callback=None):
    output_dir = get_output_dir()
    if not output_dir:
        raise Exception("ComfyUI not configured. Please set ComfyUI path in sidecar/config.ini")

    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    if progress_callback:
        progress_callback({
            "type": "status",
            "description": "正在释放上一轮模型显存，准备启动 3D 工作流...",
        })
    clear_vram()
    time.sleep(1.0)

    ts = int(time.time())
    prefix = f"UI_{ts}"

    flux_model, clip_model = _flux_pair(quality)

    workflows = get_workflows()
    if mode not in workflows:
        raise ValueError(f"Unknown mode: {mode}")

    with open(workflows[mode], "r", encoding="utf-8") as f:
        wf = json.load(f)

    _set_clip_loader(wf, clip_model)

    node_map = {}

    if mode == "Text to 3D":
        if not prompt:
            raise ValueError("Prompt required")
        wf["64"]["inputs"]["text"] = prompt
        wf["63"]["inputs"]["noise_seed"] = random.randint(1, 10000000)
        wf["66"]["inputs"]["unet_name"] = flux_model
        wf["62"]["inputs"]["filename_prefix"] = f"{prefix}_Flux"
        wf["18"]["inputs"]["filename_prefix"] = f"3D/{prefix}_White"
        wf["34"]["inputs"]["filename_prefix"] = f"3D/{prefix}_Textured"

        wf["998"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"{prefix}_RemBG", "images": ["1", 0]},
        }
        wf["997"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"{prefix}_Normal", "images": ["42", 0]},
        }
        wf["996"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"{prefix}_Texture", "images": ["35", 0]},
        }

        node_map = {"62": "2d", "998": "2d", "997": "normal", "996": "uv", "47": "model"}

    elif mode == "Image to 3D":
        if not img1:
            raise ValueError("Image required")

        from PIL import Image
        with Image.open(img1) as im:
            img_w, img_h = im.size

        uploaded = upload_image(img1)
        wf["71"]["inputs"]["image"] = uploaded
        wf["24"]["inputs"]["width"] = img_w
        wf["24"]["inputs"]["height"] = img_h
        wf["25"]["inputs"]["width"] = img_w
        wf["25"]["inputs"]["height"] = img_h

        wf["18"]["inputs"]["filename_prefix"] = f"3D/{prefix}_White"
        wf["34"]["inputs"]["filename_prefix"] = f"3D/{prefix}_Textured"

        wf["998"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"{prefix}_RemBG", "images": ["1", 0]},
        }
        wf["997"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"{prefix}_Normal", "images": ["42", 0]},
        }
        wf["996"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"{prefix}_Texture", "images": ["35", 0]},
        }

        node_map = {"998": "2d", "997": "normal", "996": "uv", "47": "model"}

    elif mode == "Dual Image Fusion":
        if not prompt:
            raise ValueError("Prompt required")
        if not img1 or not img2:
            raise ValueError("Both images required")

        up1 = upload_image(img1)
        up2 = upload_image(img2)
        wf["74"]["inputs"]["image"] = up1
        wf["75"]["inputs"]["image"] = up2
        wf["73"]["inputs"]["text"] = prompt
        wf["72"]["inputs"]["noise_seed"] = random.randint(1, 10000000)
        wf["76"]["inputs"]["unet_name"] = flux_model
        wf["63"]["inputs"]["filename_prefix"] = f"{prefix}_Flux"
        wf["18"]["inputs"]["filename_prefix"] = f"3D/{prefix}_White"
        wf["34"]["inputs"]["filename_prefix"] = f"3D/{prefix}_Textured"

        wf["998"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"{prefix}_RemBG", "images": ["1", 0]},
        }
        wf["997"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"{prefix}_Normal", "images": ["42", 0]},
        }
        wf["996"] = {
            "class_type": "SaveImage",
            "inputs": {"filename_prefix": f"{prefix}_Texture", "images": ["35", 0]},
        }

        node_map = {"63": "2d", "998": "2d", "997": "normal", "996": "uv", "47": "model"}

    ws = websocket.WebSocket()
    ws.settimeout(20)
    ws.connect(f"ws://{SERVER}/ws?clientId={CLIENT_ID}")

    pid = queue_prompt(wf)["prompt_id"]

    node_progress_map = {}
    last_message_at = time.time()
    last_status_at = 0.0

    while True:
        try:
            msg = ws.recv()
        except websocket.WebSocketTimeoutException:
            now = time.time()
            if progress_callback and now - last_status_at >= 20:
                last_status_at = now
                progress_callback({
                    "type": "status",
                    "description": "3D 节点仍在运行中；若长时间停在同一步，通常是在等待显存或 Hunyuan3D 采样。",
                })
            if now - last_message_at > 900:
                raise Exception("3D workflow timed out: no ComfyUI websocket updates for 15 minutes")
            continue
        last_message_at = time.time()
        if isinstance(msg, str):
            data = json.loads(msg)

            if data.get("type") == "progress":
                d = data.get("data", {})
                node_id = data.get("node", "")
                value = d.get("value", 0)
                max_val = d.get("max", 1)
                if progress_callback:
                    progress_callback({
                        "type": "progress",
                        "value": value / max_val if max_val > 0 else 0,
                        "node": node_id,
                        "description": f"执行节点中... ({value}/{max_val})",
                    })

            elif data.get("type") == "execution_start":
                d = data.get("data", {})
                if progress_callback:
                    progress_callback({
                        "type": "status",
                        "description": "开始执行工作流...",
                    })

            elif data.get("type") == "execution_cached":
                d = data.get("data", {})
                if progress_callback:
                    nodes = d.get("nodes", [])
                    progress_callback({
                        "type": "status",
                        "description": f"使用缓存 ({len(nodes)} 个节点已缓存)",
                    })

            elif data.get("type") == "executing":
                d = data["data"]
                node = d.get("node")
                if node is not None and progress_callback:
                    progress_callback({
                        "type": "node_started",
                        "node": str(node),
                        "description": f"执行节点: {node}",
                    })
                elif d.get("node") is None and d.get("prompt_id") == pid:
                    break

            elif data.get("type") == "execution_error":
                d = data.get("data", {})
                exception_msg = d.get("exception_message", "Unknown error")
                node_id = d.get("node_id", "")
                node_type = d.get("node_type", "")
                err_parts = [f"ComfyUI execution error: {exception_msg}"]
                if node_id:
                    err_parts.append(f"Node {node_id} ({node_type})")
                raise Exception("\n".join(err_parts))

    try:
        ws.close()
    except Exception:
        pass

    clear_vram()
    time.sleep(1.0)

    result_2d = find_file(f"{prefix}_Flux") or find_file(f"{prefix}_RemBG")
    result_normal = find_file(f"{prefix}_Normal")
    result_uv = find_file(f"{prefix}_Texture")
    result_model = find_file(f"{prefix}_Textured", "3D") or find_file(f"{prefix}_White", "3D")

    if mode == "Image to 3D":
        result_2d = img1

    return result_2d, result_normal, result_uv, result_model


def run_multiview_pipeline(image_paths, quality="fast", progress_callback=None):
    image_paths = list(image_paths or [])
    if len(image_paths) == 3:
        image_paths = [image_paths[0], image_paths[1], "", image_paths[2]]
    while len(image_paths) < 4:
        image_paths.append("")

    required = {
        "front": image_paths[0],
        "left": image_paths[1],
        "back": image_paths[3],
    }
    for label, path in required.items():
        if not path or not os.path.exists(path):
            raise ValueError(f"{label} image file not found: {path}")
    if image_paths[2] and not os.path.exists(image_paths[2]):
        raise ValueError(f"right image file not found: {image_paths[2]}")

    output_dir = get_output_dir()
    if not output_dir:
        raise Exception("ComfyUI not configured. Please set ComfyUI path in sidecar/config.ini")
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    if progress_callback:
        progress_callback({
            "type": "status",
            "description": "正在释放显存，准备启动 Hy3D 多视角工作流...",
        })
    clear_vram()
    time.sleep(1.0)

    workflow_path = get_workflows()["Hy3D MultiView"]
    if not os.path.exists(workflow_path):
        raise ValueError("Hy3D multiview workflow not found")

    with open(workflow_path, "r", encoding="utf-8") as f:
        api_wf = json.load(f)

    uploaded = [upload_image(path) if path else "" for path in image_paths[:4]]
    run_ts = int(time.time())

    _set_node_input(api_wf, "157", "image", uploaded[0])  # Front
    _set_node_input(api_wf, "160", "image", uploaded[1])  # Left
    _set_node_input(api_wf, "159", "image", uploaded[3])  # Back
    if uploaded[2]:
        api_wf["167"] = {
            "class_type": "LoadImage",
            "inputs": {"image": uploaded[2]},
            "_meta": {"title": "Load Image: Right"},
        }
        api_wf["172"] = {
            "class_type": "ImageResize+",
            "inputs": {
                "width": 518,
                "height": 518,
                "interpolation": "lanczos",
                "method": "pad",
                "condition": "always",
                "multiple_of": 2,
                "image": ["167", 0],
            },
            "_meta": {"title": "Right Resize"},
        }
        api_wf["173"] = {
            "class_type": "ImageRemoveBackground+",
            "inputs": {"rembg_session": ["55", 0], "image": ["172", 0]},
            "_meta": {"title": "Right Remove Background"},
        }
        api_wf["200"] = {
            "class_type": "InvertMask",
            "inputs": {"mask": ["173", 1]},
            "_meta": {"title": "Right Alpha"},
        }
        api_wf["197"] = {
            "class_type": "JoinImageWithAlpha",
            "inputs": {"image": ["172", 0], "alpha": ["200", 0]},
            "_meta": {"title": "Right Join Alpha"},
        }
        _set_node_input(api_wf, "166", "right", ["197", 0])
    else:
        api_wf.get("166", {}).setdefault("inputs", {}).pop("right", None)

    _set_node_input(api_wf, "10", "model", HY3D_MULTIVIEW_FAST_MODEL)
    _set_node_input(api_wf, "166", "seed", random.randint(1, 1000000000000000))
    _set_node_input(api_wf, "17", "filename_prefix", f"3D/UI_MV_{run_ts}_White")
    _set_node_input(api_wf, "99", "filename_prefix", f"3D/UI_MV_{run_ts}_Textured")

    preview_prefix = f"UI_MV_{run_ts}"
    api_wf["990"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": f"{preview_prefix}_MeshPreview", "images": ["166", 1]},
    }
    api_wf["991"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": f"{preview_prefix}_MultiView", "images": ["88", 0]},
    }
    api_wf["992"] = {
        "class_type": "SaveImage",
        "inputs": {"filename_prefix": f"{preview_prefix}_Texture", "images": ["129", 0]},
    }

    ws = websocket.WebSocket()
    ws.settimeout(20)
    ws.connect(f"ws://{SERVER}/ws?clientId={CLIENT_ID}")

    pid = queue_prompt(api_wf)["prompt_id"]
    last_message_at = time.time()
    last_status_at = 0.0

    while True:
        try:
            msg = ws.recv()
        except websocket.WebSocketTimeoutException:
            now = time.time()
            if progress_callback and now - last_status_at >= 20:
                last_status_at = now
                progress_callback({
                    "type": "status",
                    "description": "Hy3D 多视角节点仍在运行中，模型加载、采样和纹理烘焙可能需要较长时间...",
                })
            if now - last_message_at > 1200:
                raise Exception("Hy3D multiview workflow timed out: no ComfyUI websocket updates for 20 minutes")
            continue
        last_message_at = time.time()
        if isinstance(msg, str):
            data = json.loads(msg)
            if data.get("type") == "progress":
                d = data.get("data", {})
                value = d.get("value", 0)
                max_val = d.get("max", 1)
                if progress_callback:
                    progress_callback({
                        "type": "progress",
                        "value": value / max_val if max_val > 0 else 0,
                        "description": f"执行 Hy3D 多视角节点... ({value}/{max_val})",
                    })
            elif data.get("type") == "execution_start" and progress_callback:
                progress_callback({"type": "status", "description": "开始执行 Hy3D 多视角工作流..."})
            elif data.get("type") == "execution_cached" and progress_callback:
                nodes = data.get("data", {}).get("nodes", [])
                progress_callback({"type": "status", "description": f"使用缓存 ({len(nodes)} 个节点已缓存)"})
            elif data.get("type") == "executing":
                d = data.get("data", {})
                node = d.get("node")
                if node is not None and progress_callback:
                    progress_callback({
                        "type": "node_started",
                        "node": str(node),
                        "description": f"执行 Hy3D 节点: {node}",
                    })
                elif node is None and d.get("prompt_id") == pid:
                    break
            elif data.get("type") == "execution_error":
                d = data.get("data", {})
                exception_msg = d.get("exception_message", "Unknown error")
                node_id = d.get("node_id", "")
                node_type = d.get("node_type", "")
                err_parts = [f"ComfyUI execution error: {exception_msg}"]
                if node_id:
                    err_parts.append(f"Node {node_id} ({node_type})")
                raise Exception("\n".join(err_parts))

    try:
        ws.close()
    except Exception:
        pass

    clear_vram()
    time.sleep(1.0)

    result_preview = find_file(f"{preview_prefix}_MeshPreview")
    result_multiview = find_file(f"{preview_prefix}_MultiView")
    result_texture = find_file(f"{preview_prefix}_Texture")
    result_model = find_file(f"UI_MV_{run_ts}_Textured", "3D") or find_file(f"UI_MV_{run_ts}_White", "3D")

    return result_preview or image_paths[0], result_multiview, result_texture, result_model


def improve_image_with_flux2klein(original_image_path, improvement_prompt, quality="fast", image_lora_id=None):

    if not original_image_path or not os.path.exists(original_image_path):
        raise ValueError("Original image path does not exist")

    ts = int(time.time())
    prefix = f"IMPROVED_{ts}"

    workflow_path = get_flux2_workflow()
    if not os.path.exists(workflow_path):
        raise ValueError("Flux2 improvement workflow not found")

    with open(workflow_path, "r", encoding="utf-8") as f:
        wf = json.load(f)

    flux_model, clip_model = _flux_pair(quality)
    _set_clip_loader(wf, clip_model)

    uploaded = upload_image(original_image_path)
    wf["18"]["inputs"]["image"] = uploaded
    wf["16"]["inputs"]["text"] = improvement_prompt
    wf["17"]["inputs"]["unet_name"] = flux_model
    wf["13"]["inputs"]["noise_seed"] = random.randint(1, 10000000)
    wf["19"]["inputs"]["filename_prefix"] = prefix
    _apply_flux_image_lora(wf, quality, image_lora_id, model_node_id="17")

    ws = websocket.WebSocket()
    ws.settimeout(20)
    ws.connect(f"ws://{SERVER}/ws?clientId={CLIENT_ID}")

    pid = queue_prompt(wf)["prompt_id"]
    last_message_at = time.time()

    while True:
        try:
            msg = ws.recv()
        except websocket.WebSocketTimeoutException:
            improved_image = find_file(prefix)
            if improved_image:
                break
            if time.time() - last_message_at > 900:
                raise Exception("Flux2 improvement timed out: no ComfyUI websocket updates for 15 minutes")
            continue
        last_message_at = time.time()
        if isinstance(msg, str):
            data = json.loads(msg)

            if data.get("type") == "progress":
                pass

            elif data.get("type") == "execution_error":
                d = data.get("data", {})
                exception_msg = d.get("exception_message", "Unknown error")
                raise Exception(f"Flux2 execution error: {exception_msg}")

            elif data.get("type") == "executing":
                d = data["data"]
                if d.get("node") is None and d.get("prompt_id") == pid:
                    break

    try:
        ws.close()
    except Exception:
        pass

    clear_vram()
    time.sleep(1.0)

    improved_image = find_file(prefix)
    if not improved_image:
        raise Exception("Flux2 improvement failed, no output file found")

    return improved_image


def generate_multiview_images_with_flux(source_image_path, object_prompt="", quality="fast"):
    if not source_image_path or not os.path.exists(source_image_path):
        raise ValueError("Source image path does not exist")

    subject = (object_prompt or "").strip()
    subject_line = f"Subject description: {subject}. " if subject else ""
    common = (
        f"{subject_line}Create a clean 3D modeling reference view of the same subject. "
        "Keep identity, proportions, colors, costume/materials, and silhouette consistent. "
        "Use a single centered full-body/object composition, orthographic camera, white background, "
        "no shadows, no labels, no extra objects, no collage."
    )
    view_prompts = [
        (
            "front",
            f"{common} Convert the source into the exact FRONT view, symmetrical, facing camera.",
        ),
        (
            "left",
            f"{common} Convert the source into a clean side profile reference. The final required output is the LEFT side view: the face, nose, chest, and body direction must point to the RIGHT side of the image. Same scale as front view. Do not create a right side view, turnaround sheet, collage, or multiple subjects.",
        ),
        (
            "back",
            f"{common} Convert the source into the exact BACK view, rear-facing, same scale as front view.",
        ),
    ]

    results = {}
    for view, prompt in view_prompts:
        output = improve_image_with_flux2klein(source_image_path, prompt, quality)
        results[view] = output

    return results


def generate_image_with_flux(prompt, quality="fast", progress_callback=None, image_lora_id=None):
    if not prompt:
        raise ValueError("Prompt required")

    output_dir = get_output_dir()
    if not output_dir:
        raise Exception("ComfyUI not configured. Please set ComfyUI path in sidecar/config.ini")

    workflow_path = get_workflows()["Text to 3D"]
    if not os.path.exists(workflow_path):
        raise ValueError("Text-to-image workflow not found")

    with open(workflow_path, "r", encoding="utf-8") as f:
        full_wf = json.load(f)

    ts = int(time.time())
    prefix = f"IMG_{ts}_Flux"
    flux_model, clip_model = _flux_pair(quality)

    full_wf["64"]["inputs"]["text"] = prompt
    full_wf["63"]["inputs"]["noise_seed"] = random.randint(1, 10000000)
    full_wf["66"]["inputs"]["unet_name"] = flux_model
    _set_clip_loader(full_wf, clip_model)
    full_wf["62"]["inputs"]["filename_prefix"] = prefix
    _apply_flux_image_lora(full_wf, quality, image_lora_id)

    wf = _collect_dependencies(full_wf, "62")

    ws = websocket.WebSocket()
    ws.connect(f"ws://{SERVER}/ws?clientId={CLIENT_ID}")

    pid = queue_prompt(wf)["prompt_id"]

    while True:
        msg = ws.recv()
        if isinstance(msg, str):
            data = json.loads(msg)

            if data.get("type") == "progress" and progress_callback:
                d = data.get("data", {})
                value = d.get("value", 0)
                max_val = d.get("max", 1)
                progress_callback({
                    "type": "progress",
                    "value": value / max_val if max_val > 0 else 0,
                    "description": f"Generating image... ({value}/{max_val})",
                })

            elif data.get("type") == "execution_start" and progress_callback:
                progress_callback({"type": "status", "description": "Starting Flux image workflow..."})

            elif data.get("type") == "execution_error":
                d = data.get("data", {})
                exception_msg = d.get("exception_message", "Unknown error")
                node_id = d.get("node_id", "")
                node_type = d.get("node_type", "")
                err_parts = [f"ComfyUI execution error: {exception_msg}"]
                if node_id:
                    err_parts.append(f"Node {node_id} ({node_type})")
                raise Exception("\n".join(err_parts))

            elif data.get("type") == "executing":
                d = data["data"]
                if d.get("node") is None and d.get("prompt_id") == pid:
                    break

    clear_vram()
    time.sleep(1.0)

    image_path = find_file(prefix)
    if not image_path:
        raise Exception("Flux image generation failed, no output file found")

    return image_path


def _set_wan_sampler(wf, steps, cfg, sampler_name, scheduler):
    _set_node_input(wf, "63", "steps", steps)
    _set_node_input(wf, "63", "cfg", cfg)
    _set_node_input(wf, "63", "sampler_name", sampler_name)
    _set_node_input(wf, "63", "scheduler", scheduler)


def _set_wan_video_model(wf, quality, lora_acceleration=False):
    if quality == "fast":
        _set_node_input(wf, "99", "unet_name", WAN_VIDEO_FAST_MODEL)
        _set_node_input(wf, "92", "model", ["99", 0])
        _set_node_input(wf, "92", "lora_name", WAN_VIDEO_FAST_LORA_TURBO)
        _set_node_input(wf, "92", "strength_model", WAN_VIDEO_FAST_LORA_STRENGTH)
        _set_node_input(wf, "48", "model", ["92", 0])
        _set_wan_sampler(wf, steps=5, cfg=1, sampler_name="euler", scheduler="simple")
        wf.pop("37", None)
        wf.pop("91", None)
        return

    _set_node_input(wf, "37", "unet_name", WAN_VIDEO_STANDARD_MODEL)
    if quality == "experimental":
        _set_node_input(wf, "91", "model", ["37", 0])
        _set_node_input(wf, "91", "lora_name", WAN_VIDEO_FAST_LORA_FULL_ATTN)
        _set_node_input(wf, "91", "strength_model", WAN_VIDEO_EXPERIMENTAL_LORA_STRENGTH)
        _set_node_input(wf, "92", "model", ["91", 0])
        _set_node_input(wf, "92", "lora_name", WAN_VIDEO_FAST_LORA_TURBO)
        _set_node_input(wf, "92", "strength_model", WAN_VIDEO_EXPERIMENTAL_LORA_STRENGTH)
        _set_node_input(wf, "48", "model", ["92", 0])
        _set_wan_sampler(wf, steps=4, cfg=1, sampler_name="sa_solver", scheduler="beta")
    elif lora_acceleration:
        _set_node_input(wf, "91", "model", ["37", 0])
        _set_node_input(wf, "91", "lora_name", WAN_VIDEO_FAST_LORA_FULL_ATTN)
        _set_node_input(wf, "91", "strength_model", WAN_VIDEO_STANDARD_ACCEL_LORA_STRENGTH)
        _set_node_input(wf, "48", "model", ["91", 0])
        _set_wan_sampler(wf, steps=8, cfg=1, sampler_name="euler", scheduler="simple")
    else:
        _set_node_input(wf, "48", "model", ["37", 0])
        _set_wan_sampler(wf, steps=20, cfg=4, sampler_name="uni_pc", scheduler="simple")
        wf.pop("91", None)
    wf.pop("99", None)
    if quality != "experimental":
        wf.pop("92", None)


def _configure_wan_14b_video(wf, image_path, prompt_text, duration, width, height):
    has_image = bool(image_path)
    fps = 16
    frame_count = duration * fps + 1
    ts = int(time.time())
    prefix = f"Wan22_14b_{'i2v' if has_image else 't2v'}_{ts}"

    _set_node_input(wf, "9", "text", prompt_text)
    _set_node_input(wf, "58", "value", frame_count)

    if has_image:
        uploaded = upload_image(image_path)
        _set_node_input(wf, "16", "image", uploaded)
        _set_node_input(wf, "54", "width", width)
        _set_node_input(wf, "54", "height", height)
        _set_node_input(wf, "55", "seed", random.randint(1, 1000000000000000))
        _set_node_input(wf, "57", "frame_rate", fps)
        _set_node_input(wf, "57", "filename_prefix", prefix)
        return prefix, "57"

    _set_node_input(wf, "28", "width", width)
    _set_node_input(wf, "28", "height", height)
    _set_node_input(wf, "8", "seed", random.randint(1, 1000000000000000))
    _set_node_input(wf, "39", "frame_rate", fps)
    _set_node_input(wf, "39", "filename_prefix", prefix)
    return prefix, "39"


def _run_wan_video_workflow(wf, prefix, output_node_id, progress_callback=None, timeout_seconds=1800):
    ws = websocket.WebSocket()
    ws.settimeout(20)
    ws.connect(f"ws://{SERVER}/ws?clientId={CLIENT_ID}")

    pid = queue_prompt(wf)["prompt_id"]
    last_message_at = time.time()
    last_status_at = 0.0

    while True:
        try:
            msg = ws.recv()
        except websocket.WebSocketTimeoutException:
            now = time.time()
            if progress_callback and now - last_status_at >= 20:
                last_status_at = now
                progress_callback({
                    "type": "status",
                    "description": "Wan video workflow is still running; video sampling can take several minutes.",
                })
            if now - last_message_at > timeout_seconds:
                raise Exception("Wan video workflow timed out: no ComfyUI websocket updates for 30 minutes")
            continue
        last_message_at = time.time()
        if isinstance(msg, str):
            data = json.loads(msg)
            if data.get("type") == "progress" and progress_callback:
                d = data.get("data", {})
                value = d.get("value", 0)
                max_val = d.get("max", 1)
                progress_callback({
                    "type": "progress",
                    "value": value / max_val if max_val > 0 else 0,
                    "description": f"Generating video... ({value}/{max_val})",
                })
            elif data.get("type") == "execution_start" and progress_callback:
                progress_callback({"type": "status", "description": "Starting Wan video workflow..."})
            elif data.get("type") == "execution_error":
                d = data.get("data", {})
                exception_msg = d.get("exception_message", "Unknown error")
                node_id = d.get("node_id", "")
                node_type = d.get("node_type", "")
                err_parts = [f"ComfyUI execution error: {exception_msg}"]
                if node_id:
                    err_parts.append(f"Node {node_id} ({node_type})")
                raise Exception("\n".join(err_parts))
            elif data.get("type") == "executing":
                d = data.get("data", {})
                if d.get("node") is None and d.get("prompt_id") == pid:
                    break

    try:
        ws.close()
    except Exception:
        pass

    clear_vram()
    time.sleep(1.0)

    history = get_history(pid)
    video_path = extract_file(history, output_node_id) or find_file(prefix)
    if not video_path:
        raise Exception("Wan video generation failed, no output file found")

    return video_path


def generate_video_with_wan(
    image_path=None,
    prompt="",
    quality="quality",
    progress_callback=None,
    duration_seconds=4,
    width=1024,
    height=576,
    lora_acceleration=False,
    standard_model="5b",
):
    if image_path and not os.path.exists(image_path):
        raise ValueError("Source image path does not exist")

    prompt_text = (prompt or "").strip()
    if not prompt_text:
        raise ValueError("Prompt required")

    output_dir = get_output_dir()
    if not output_dir:
        raise Exception("ComfyUI not configured. Please set ComfyUI path in sidecar/config.ini")

    duration = max(1, min(int(duration_seconds or 4), 5))
    safe_width = max(256, min(int(width or 1024), 1280))
    safe_height = max(256, min(int(height or 576), 1280))

    if quality == "quality" and str(standard_model).lower() == "14b":
        workflow_path = get_wan_video_14b_workflow(bool(image_path))
        if not os.path.exists(workflow_path):
            raise ValueError("Wan 14B video workflow not found")
        with open(workflow_path, "r", encoding="utf-8") as f:
            wf = json.load(f)
        prefix, output_node_id = _configure_wan_14b_video(
            wf,
            image_path,
            prompt_text,
            duration,
            safe_width,
            safe_height,
        )
        return _run_wan_video_workflow(wf, prefix, output_node_id, progress_callback)

    workflow_path = get_wan_video_workflow()
    if not os.path.exists(workflow_path):
        raise ValueError("Wan video workflow not found")

    with open(workflow_path, "r", encoding="utf-8") as f:
        wf = json.load(f)

    ts = int(time.time())
    prefix = f"Wan22_5b_{quality}_{ts}"
    fps = 24
    frame_count = duration * fps + 1

    _set_wan_video_model(wf, quality, lora_acceleration)
    _set_node_input(wf, "55", "width", safe_width)
    _set_node_input(wf, "55", "height", safe_height)
    _set_node_input(wf, "55", "length", frame_count)
    _set_node_input(wf, "64", "frame_rate", fps)
    if image_path:
        uploaded = upload_image(image_path)
        _set_node_input(wf, "56", "image", uploaded)
        _set_node_input(wf, "55", "start_image", ["56", 0])
    else:
        wf.pop("56", None)
        wf.get("55", {}).setdefault("inputs", {}).pop("start_image", None)
    _set_node_input(wf, "6", "text", prompt_text)
    _set_node_input(wf, "63", "noise_seed", random.randint(1, 1000000000000000))
    _set_node_input(wf, "64", "filename_prefix", prefix)

    ws = websocket.WebSocket()
    ws.settimeout(20)
    ws.connect(f"ws://{SERVER}/ws?clientId={CLIENT_ID}")

    pid = queue_prompt(wf)["prompt_id"]
    last_message_at = time.time()
    last_status_at = 0.0

    while True:
        try:
            msg = ws.recv()
        except websocket.WebSocketTimeoutException:
            now = time.time()
            if progress_callback and now - last_status_at >= 20:
                last_status_at = now
                progress_callback({
                    "type": "status",
                    "description": "Wan video workflow is still running; video sampling can take several minutes.",
                })
            if now - last_message_at > 1800:
                raise Exception("Wan video workflow timed out: no ComfyUI websocket updates for 30 minutes")
            continue
        last_message_at = time.time()
        if isinstance(msg, str):
            data = json.loads(msg)
            if data.get("type") == "progress" and progress_callback:
                d = data.get("data", {})
                value = d.get("value", 0)
                max_val = d.get("max", 1)
                progress_callback({
                    "type": "progress",
                    "value": value / max_val if max_val > 0 else 0,
                    "description": f"Generating video... ({value}/{max_val})",
                })
            elif data.get("type") == "execution_start" and progress_callback:
                progress_callback({"type": "status", "description": "Starting Wan video workflow..."})
            elif data.get("type") == "execution_error":
                d = data.get("data", {})
                exception_msg = d.get("exception_message", "Unknown error")
                node_id = d.get("node_id", "")
                node_type = d.get("node_type", "")
                err_parts = [f"ComfyUI execution error: {exception_msg}"]
                if node_id:
                    err_parts.append(f"Node {node_id} ({node_type})")
                raise Exception("\n".join(err_parts))
            elif data.get("type") == "executing":
                d = data.get("data", {})
                if d.get("node") is None and d.get("prompt_id") == pid:
                    break

    try:
        ws.close()
    except Exception:
        pass

    clear_vram()
    time.sleep(1.0)

    history = get_history(pid)
    video_path = extract_file(history, "64") or find_file(prefix)
    if not video_path:
        raise Exception("Wan video generation failed, no output file found")

    return video_path


def tool_generate_3d_text(prompt, quality="fast"):
    if not prompt:
        return json.dumps({"status": "error", "message": "Prompt cannot be empty"})
    try:
        res_2d, res_normal, res_uv, model_path = run_pipeline(
            mode="Text to 3D", quality=quality, prompt=prompt, img1=None
        )
        if model_path and os.path.exists(model_path):
            return json.dumps({
                "status": "success",
                "model_path": model_path,
                "image_2d": res_2d,
                "image_normal": res_normal,
                "image_uv": res_uv,
                "message": "Text-to-3D success!",
            })
        return json.dumps({"status": "error", "message": "Generation completed but model file not found"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Text-to-3D failed: {str(e)}"})


def tool_generate_3d_image(image_path, quality="fast"):
    if not image_path or not os.path.exists(image_path):
        return json.dumps({"status": "error", "message": "Image path does not exist"})
    try:
        res_2d, res_normal, res_uv, model_path = run_pipeline(
            mode="Image to 3D", quality=quality, prompt="", img1=image_path
        )
        if model_path and os.path.exists(model_path):
            return json.dumps({
                "status": "success",
                "model_path": model_path,
                "image_2d": res_2d,
                "image_normal": res_normal,
                "image_uv": res_uv,
                "message": "Image-to-3D success!",
            })
        return json.dumps({"status": "error", "message": "Generation completed but model file not found"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Image-to-3D failed: {str(e)}"})


def tool_generate_3d_dual(image1_path, image2_path, prompt, quality="fast"):
    if not image1_path or not os.path.exists(image1_path):
        return json.dumps({"status": "error", "message": "Image 1 path does not exist"})
    if not image2_path or not os.path.exists(image2_path):
        return json.dumps({"status": "error", "message": "Image 2 path does not exist"})
    if not prompt:
        return json.dumps({"status": "error", "message": "Prompt cannot be empty"})
    try:
        res_2d, res_normal, res_uv, model_path = run_pipeline(
            mode="Dual Image Fusion", quality=quality, prompt=prompt,
            img1=image1_path, img2=image2_path
        )
        if model_path and os.path.exists(model_path):
            return json.dumps({
                "status": "success",
                "model_path": model_path,
                "image_2d": res_2d,
                "image_normal": res_normal,
                "image_uv": res_uv,
                "image1_path": image1_path,
                "image2_path": image2_path,
                "message": "Dual-image fusion success!",
            })
        return json.dumps({"status": "error", "message": "Generation completed but model file not found"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Fusion failed: {str(e)}"})


def tool_generate_multiview_images(image_path, quality="fast"):
    if not image_path or not os.path.exists(image_path):
        return json.dumps({"status": "error", "message": "Image path does not exist"})
    try:
        views = generate_multiview_images_with_flux(image_path, "", quality)
        front = views.get("front")
        left = views.get("left")
        back = views.get("back")
        if front and left and back and all(os.path.exists(path) for path in [front, left, back]):
            return json.dumps({
                "status": "success",
                "front_path": front,
                "left_path": left,
                "back_path": back,
                "source_image_path": image_path,
                "message": "Multiview images generated successfully.",
            })
        return json.dumps({"status": "error", "message": "Multiview generation completed but outputs were incomplete"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Multiview image generation failed: {str(e)}"})


def tool_generate_3d_multiview(front_path, left_path, back_path, quality="fast"):
    for label, path in {"front": front_path, "left": left_path, "back": back_path}.items():
        if not path or not os.path.exists(path):
            return json.dumps({"status": "error", "message": f"{label} image path does not exist"})
    try:
        res_2d, res_normal, res_uv, model_path = run_multiview_pipeline(
            [front_path, left_path, "", back_path],
            quality,
        )
        if model_path and os.path.exists(model_path):
            return json.dumps({
                "status": "success",
                "model_path": model_path,
                "image_2d": res_2d,
                "image_normal": res_normal,
                "image_uv": res_uv,
                "front_path": front_path,
                "left_path": left_path,
                "back_path": back_path,
                "message": "Multiview-to-3D success!",
            })
        return json.dumps({"status": "error", "message": "Generation completed but model file not found"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Multiview-to-3D failed: {str(e)}"})


def tool_improve_image(image_path, improvement_prompt):
    if not image_path or not os.path.exists(image_path):
        return json.dumps({"status": "error", "message": "Image path does not exist"})
    try:
        improved_path = improve_image_with_flux2klein(image_path, improvement_prompt)
        if improved_path and os.path.exists(improved_path):
            return json.dumps({"status": "success", "improved_image_path": improved_path})
        return json.dumps({"status": "error", "message": "Improvement completed but output not found"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Improvement failed: {str(e)}"})


def tool_generate_image(prompt, quality="fast"):
    if not prompt:
        return json.dumps({"status": "error", "message": "Prompt cannot be empty"})
    try:
        image_path = generate_image_with_flux(prompt, quality)
        if image_path and os.path.exists(image_path):
            return json.dumps({
                "status": "success",
                "image_path": image_path,
                "message": "Image generation success!",
            })
        return json.dumps({"status": "error", "message": "Generation completed but image file not found"})
    except Exception as e:
        return json.dumps({"status": "error", "message": f"Image generation failed: {str(e)}"})
