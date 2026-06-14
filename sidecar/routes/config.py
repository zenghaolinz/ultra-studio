from fastapi import APIRouter, HTTPException
from db.sqlite import get_db
from db.sqlite import DB_PATH
from schemas import ModelConfigCreate, EmbeddingConfigCreate
from services.model_context import context_spec_from_provider_config
import uuid
import datetime
import httpx
from pathlib import Path

router = APIRouter()

LOCAL_PROBES = [
    {
        "name": "Ollama",
        "base_url": "http://localhost:11434/v1",
        "check_urls": [
            "http://localhost:11434/api/tags",
            "http://localhost:11434/v1/models",
        ],
        "model_path": "models[*].name",
    },
    {
        "name": "LM Studio",
        "base_url": "http://localhost:1234/v1",
        "check_urls": [
            "http://localhost:1234/v1/models",
        ],
        "model_path": "data[*].id",
    },
    {
        "name": "llama.cpp",
        "base_url": "http://localhost:8080/v1",
        "check_urls": [
            "http://localhost:8080/v1/models",
            "http://localhost:8080/health",
        ],
        "model_path": "data[*].id",
    },
]


def _masked_api_key(api_key: str | None) -> str:
    if not api_key:
        return ""
    if len(api_key) <= 8:
        return "********"
    return f"{api_key[:4]}...{api_key[-4:]}"


def _extract_models(data: dict, path: str) -> list[dict]:
    parts = path.replace("[*]", "").split(".")
    result = data
    for part in parts:
        if part == "" or result is None:
            continue
        if isinstance(result, list):
            items = []
            for item in result:
                if isinstance(item, dict) and part in item:
                    items.append(item[part])
            return [{"id": str(i), "name": str(i) if i else ""} for i in items if i]
        elif isinstance(result, dict):
            result = result.get(part)
        else:
            return []
    if isinstance(result, list):
        return [{"id": str(i), "name": str(i) if i else ""} for i in result if i]
    return []


def _diagnostic_item(
    item_id: str,
    label: str,
    status: str,
    detail: str,
    action: str = "",
) -> dict:
    return {
        "id": item_id,
        "label": label,
        "status": status,
        "detail": detail,
        "action": action,
    }


@router.get("/diagnostics")
async def get_diagnostics():
    items: list[dict] = []

    items.append(
        _diagnostic_item(
            "sidecar",
            "Python Sidecar",
            "ok",
            "后端服务已响应。",
        )
    )

    db_path = Path(DB_PATH).resolve()
    try:
      db = await get_db()
      await db.execute_fetchall("SELECT 1")
      conv_count = (await db.execute_fetchall("SELECT COUNT(*) FROM conversations"))[0][0]
      model_count = (await db.execute_fetchall("SELECT COUNT(*) FROM model_configs"))[0][0]
      items.append(
          _diagnostic_item(
              "database",
              "本地数据库",
              "ok",
              f"SQLite 可读写，路径：{db_path}，会话 {conv_count} 个，模型配置 {model_count} 个。",
          )
      )
    except Exception as e:
        items.append(
            _diagnostic_item(
                "database",
                "本地数据库",
                "error",
                f"SQLite 检查失败：{e}",
                "确认 sidecar/data 目录可写，必要时备份后重建 agent.db。",
            )
        )

    try:
        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT COUNT(*), SUM(CASE WHEN is_default = 1 THEN 1 ELSE 0 END) FROM model_configs"
        )
        total, defaults = rows[0][0], rows[0][1] or 0
        if total <= 0:
            status = "warn"
            detail = "尚未配置聊天模型。"
            action = "到设置 - 聊天中添加 OpenAI/Qwen/GLM 或本地模型。"
        elif defaults <= 0:
            status = "warn"
            detail = f"已有 {total} 个聊天模型，但没有默认模型。"
            action = "在模型列表中选择一个默认模型。"
        else:
            status = "ok"
            detail = f"已配置 {total} 个聊天模型，默认模型可用。"
            action = ""
        items.append(_diagnostic_item("chat-model", "聊天模型", status, detail, action))
    except Exception as e:
        items.append(_diagnostic_item("chat-model", "聊天模型", "error", f"模型配置读取失败：{e}"))

    try:
        db = await get_db()
        rows = await db.execute_fetchall(
            "SELECT COUNT(*), SUM(CASE WHEN is_default = 1 THEN 1 ELSE 0 END) FROM embedding_configs"
        )
        total, defaults = rows[0][0], rows[0][1] or 0
        if total <= 0:
            items.append(
                _diagnostic_item(
                    "embedding-model",
                    "Embedding 模型",
                    "warn",
                    "尚未配置 Embedding 模型，长期记忆检索质量可能受影响。",
                    "如需记忆检索，添加一个 Embedding 模型并设为默认。",
                )
            )
        elif defaults <= 0:
            items.append(
                _diagnostic_item(
                    "embedding-model",
                    "Embedding 模型",
                    "warn",
                    f"已有 {total} 个 Embedding 模型，但没有默认模型。",
                    "选择一个默认 Embedding 模型。",
                )
            )
        else:
            items.append(_diagnostic_item("embedding-model", "Embedding 模型", "ok", f"已配置 {total} 个 Embedding 模型。"))
    except Exception as e:
        items.append(_diagnostic_item("embedding-model", "Embedding 模型", "error", f"Embedding 配置读取失败：{e}"))

    config_path = Path(__file__).resolve().parents[1] / "config.ini"
    if not config_path.exists():
        items.append(
            _diagnostic_item(
                "config-file",
                "本地配置文件",
                "warn",
                "sidecar/config.ini 不存在。",
                "运行 start.ps1 自动生成，或从 sidecar/config.example.ini 复制一份。",
            )
        )
    else:
        items.append(_diagnostic_item("config-file", "本地配置文件", "ok", f"配置文件存在：{config_path}"))

    try:
        from tools.comfyui_manager import get_comfyui_path, get_status, is_valid_comfyui_path

        comfy_path = get_comfyui_path()
        comfy_status = get_status()
        if not comfy_path:
            items.append(
                _diagnostic_item(
                    "comfyui-config",
                    "ComfyUI 路径",
                    "warn",
                    "尚未配置 ComfyUI 路径。",
                    "编辑 sidecar/config.ini 的 [ComfyUI] path。",
                )
            )
        elif not is_valid_comfyui_path(comfy_path):
            items.append(
                _diagnostic_item(
                    "comfyui-config",
                    "ComfyUI 路径",
                    "error",
                    f"路径无效：{comfy_path}",
                    "确认该目录包含 ComfyUI/main.py 或 main.py。",
                )
            )
        else:
            items.append(_diagnostic_item("comfyui-config", "ComfyUI 路径", "ok", f"路径有效：{comfy_path}"))

        if comfy_status.get("ready"):
            items.append(_diagnostic_item("comfyui-runtime", "ComfyUI 运行状态", "ok", "ComfyUI 已就绪。"))
        elif comfy_status.get("running"):
            items.append(
                _diagnostic_item(
                    "comfyui-runtime",
                    "ComfyUI 运行状态",
                    "warn",
                    "端口已监听，但程序未确认完全就绪。",
                    "稍等片刻后刷新，或查看 ComfyUI 日志。",
                )
            )
        else:
            items.append(
                _diagnostic_item(
                    "comfyui-runtime",
                    "ComfyUI 运行状态",
                    "warn",
                    "ComfyUI 未运行，图片/3D 生成不可用。",
                    "点击 ComfyUI 状态按钮启动，或手动启动 ComfyUI。",
                )
            )
    except Exception as e:
        items.append(_diagnostic_item("comfyui-runtime", "ComfyUI", "error", f"ComfyUI 检查失败：{e}"))

    try:
        from tools.comfy_client import get_output_dir

        output_dir = get_output_dir()
        if output_dir and Path(output_dir).exists():
            items.append(_diagnostic_item("output-dir", "生成输出目录", "ok", f"输出目录可访问：{output_dir}"))
        else:
            items.append(
                _diagnostic_item(
                    "output-dir",
                    "生成输出目录",
                    "warn",
                    "暂未检测到 ComfyUI 输出目录。",
                    "启动 ComfyUI 并完成一次生成后再刷新。",
                )
            )
    except Exception as e:
        items.append(_diagnostic_item("output-dir", "生成输出目录", "warn", f"输出目录检查失败：{e}"))

    severity = {"ok": 0, "warn": 1, "error": 2}
    worst = max((severity.get(item["status"], 0) for item in items), default=0)
    overall = "error" if worst >= 2 else "warn" if worst == 1 else "ok"
    return {
        "overall": overall,
        "checkedAt": datetime.datetime.utcnow().isoformat(),
        "items": items,
        "summary": {
            "ok": sum(1 for item in items if item["status"] == "ok"),
            "warn": sum(1 for item in items if item["status"] == "warn"),
            "error": sum(1 for item in items if item["status"] == "error"),
        },
    }


@router.get("/detect-local")
async def detect_local_models():
    results = []
    async with httpx.AsyncClient(timeout=5.0) as client:
        for probe in LOCAL_PROBES:
            available = False
            models = []
            for check_url in probe["check_urls"]:
                try:
                    resp = await client.get(check_url)
                    if resp.status_code == 200:
                        data = resp.json()
                        available = True
                        extracted = _extract_models(data, probe["model_path"])
                        models = extracted
                        break
                except Exception:
                    continue

            results.append({
                "name": probe["name"],
                "baseUrl": probe["base_url"],
                "available": available,
                "models": models,
            })
    return results


@router.get("/models")
async def list_model_configs():
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, provider, model_name, api_key, base_url, is_default, created_at, context_window FROM model_configs"
    )
    items = []
    for r in rows:
        spec = context_spec_from_provider_config((r[1], r[2], r[3], r[4], r[7]))
        items.append({
            "id": r[0],
            "provider": r[1],
            "modelName": r[2],
            "apiKey": _masked_api_key(r[3]),
            "baseUrl": r[4],
            "isDefault": bool(r[5]),
            "createdAt": r[6],
            "contextWindow": spec.context_window,
            "contextWindowSource": spec.source,
        })
    return items


@router.post("/models")
async def add_model_config(req: ModelConfigCreate):
    db = await get_db()
    model_id = uuid.uuid4().hex
    now = datetime.datetime.utcnow().isoformat()
    if req.is_default:
        await db.execute("UPDATE model_configs SET is_default = 0")
    await db.execute(
        "INSERT INTO model_configs (id, provider, model_name, api_key, base_url, is_default, context_window, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            model_id,
            req.provider,
            req.model_name,
            req.api_key,
            req.base_url,
            int(req.is_default),
            req.context_window,
            now,
        ),
    )
    await db.commit()
    return {
        "id": model_id,
        "provider": req.provider,
        "modelName": req.model_name,
        "apiKey": _masked_api_key(req.api_key),
        "baseUrl": req.base_url,
        "isDefault": req.is_default,
        "contextWindow": context_spec_from_provider_config(
            (req.provider, req.model_name, req.api_key, req.base_url, req.context_window)
        ).context_window,
        "contextWindowSource": "configured" if req.context_window else "inferred",
    }


@router.delete("/models/{model_id}")
async def remove_model_config(model_id: str):
    db = await get_db()
    await db.execute("DELETE FROM model_configs WHERE id = ?", (model_id,))
    await db.commit()
    return {"ok": True}


@router.put("/models/{model_id}/default")
async def set_default_model_config(model_id: str):
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, provider, model_name, api_key, base_url, is_default, created_at, context_window FROM model_configs WHERE id = ?",
        (model_id,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="model not found")
    await db.execute("UPDATE model_configs SET is_default = 0")
    await db.execute("UPDATE model_configs SET is_default = 1 WHERE id = ?", (model_id,))
    await db.commit()
    r = rows[0]
    spec = context_spec_from_provider_config((r[1], r[2], r[3], r[4], r[7]))
    return {
        "id": r[0],
        "provider": r[1],
        "modelName": r[2],
        "apiKey": _masked_api_key(r[3]),
        "baseUrl": r[4],
        "isDefault": True,
        "createdAt": r[6],
        "contextWindow": spec.context_window,
        "contextWindowSource": spec.source,
    }


@router.get("/embeddings")
async def list_embedding_configs():
    db = await get_db()
    rows = await db.execute_fetchall(
        "SELECT id, provider, model_name, dimensions, api_key, base_url, is_default FROM embedding_configs"
    )
    return [
        {
            "id": r[0],
            "provider": r[1],
            "modelName": r[2],
            "dimensions": r[3],
            "apiKey": _masked_api_key(r[4]),
            "baseUrl": r[5],
            "isDefault": bool(r[6]),
        }
        for r in rows
    ]


@router.post("/embeddings")
async def add_embedding_config(req: EmbeddingConfigCreate):
    db = await get_db()
    emb_id = uuid.uuid4().hex
    if req.is_default:
        await db.execute("UPDATE embedding_configs SET is_default = 0")
    await db.execute(
        "INSERT INTO embedding_configs (id, provider, model_name, dimensions, api_key, base_url, is_default) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (
            emb_id,
            req.provider,
            req.model_name,
            req.dimensions,
            req.api_key,
            req.base_url,
            int(req.is_default),
        ),
    )
    await db.commit()
    return {
        "id": emb_id,
        "provider": req.provider,
        "modelName": req.model_name,
        "dimensions": req.dimensions,
        "apiKey": _masked_api_key(req.api_key),
        "baseUrl": req.base_url,
        "isDefault": req.is_default,
    }


@router.delete("/embeddings/{emb_id}")
async def remove_embedding_config(emb_id: str):
    db = await get_db()
    await db.execute("DELETE FROM embedding_configs WHERE id = ?", (emb_id,))
    await db.commit()
    return {"ok": True}
