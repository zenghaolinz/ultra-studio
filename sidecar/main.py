import sys
import os
import threading
import time
from contextlib import asynccontextmanager

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from db.sqlite import init_db, close_db
from routes import chat, memory, config, persona, asset_3d


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()

    def start_comfy():
        try:
            from tools.comfyui_manager import start_comfyui
            start_comfyui()
        except Exception as e:
            print(f"[main] ComfyUI auto-start failed: {e}")

    threading.Thread(target=start_comfy, daemon=True).start()

    yield

    try:
        from tools.comfyui_manager import stop_comfyui
        stop_comfyui()
    except Exception:
        pass

    await close_db()


app = FastAPI(title="Ultra Studio Sidecar", version="0.5.6", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "https://tauri.localhost",
    ],
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(chat.router, prefix="/api/chat", tags=["chat"])
app.include_router(memory.router, prefix="/api/memory", tags=["memory"])
app.include_router(config.router, prefix="/api/config", tags=["config"])
app.include_router(persona.router, prefix="/api/config", tags=["persona"])
app.include_router(asset_3d.router)


@app.get("/api/comfyui/status")
async def comfyui_status():
    try:
        from tools.comfyui_manager import get_status
        return get_status()
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/comfyui/start")
async def comfyui_start():
    try:
        from tools.comfyui_manager import start_comfyui, get_status
        ok = start_comfyui()
        return {"started": ok, **get_status()}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/comfyui/stop")
async def comfyui_stop():
    try:
        from tools.comfyui_manager import stop_comfyui, get_status
        stop_comfyui()
        return {"stopped": True, **get_status()}
    except Exception as e:
        return {"error": str(e)}


@app.post("/api/app/shutdown")
async def app_shutdown():
    def shutdown_later():
        try:
            from tools.comfyui_manager import stop_comfyui
            stop_comfyui()
        except Exception as e:
            print(f"[main] ComfyUI shutdown failed: {e}")
        time.sleep(0.5)
        os._exit(0)

    threading.Thread(target=shutdown_later, daemon=True).start()
    return {"ok": True, "message": "shutdown scheduled"}


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"detail": str(exc), "type": type(exc).__name__},
    )


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9257, access_log=False)
