import json

from memory import manager as memory_mgr
from schemas import ChatRequest
from services.chat_confirmations import is_delete_request_text
from services.chat_router import (
    ROUTER_ACTIONS,
    model_capabilities,
    quality_mode_from_decision,
    router_safe_json,
)
from services.chat_router_context import build_router_context
from services.model_context import fit_messages_to_context


async def llm_route_request(client, model_name: str, req: ChatRequest, provider_config=None) -> dict | None:
    if is_delete_request_text(req.content):
        return {"action": "general_tools", "reason": "delete requests must use confirmed file tools"}
    if any(word in (req.content or "").lower() for word in ["cmd", "powershell", "命令", "终端", "运行", "执行", "测试", "构建", "build", "test", "npm", "git status", "git diff"]):
        return {"action": "general_tools", "reason": "system command or project verification request must use local tools"}
    if memory_mgr.infer_tool_scope(req.content, req.image_paths) == "web":
        return {"action": "general_tools", "reason": "web search requests must use web tools"}
    capabilities = model_capabilities(provider_config, req.vision_enabled)
    context = await build_router_context(req, capabilities)
    system_hint = (
        "你是 Ultra Studio 的工具路由器。只输出 JSON，不要 Markdown。"
        "根据用户请求和上下文选择一个 action。"
        "可选 action: chat, general_tools, generate_image, generate_video, edit_image, generate_3d_text, "
        "generate_3d_image, generate_3d_fusion, generate_multiview_images, generate_3d_multiview, project_document_image, project_document_3d, "
        "attachment_document_image, attachment_document_3d, read_document, create_docx, edit_docx, folder_summary_docx, create_text_file, choose_implementation。"
        "规则：如果用户要生成/画一张新图片，选 generate_image；如果用户要生成视频、短片、动画、图生视频或文生视频，选 generate_video；如果用户上传图片、引用 latest_active_image，或要求修改项目/文件夹里的图片，并要求补全、画完整、扩图、改颜色、润色、修改，选 edit_image；"
        "如果用户要求创建本地代码、脚本、网页、HTML、Markdown、TXT、JSON、CSS/JS/Python 文件、可运行 Demo、小游戏或工具，选 create_text_file；"
        "如果用户是在已有/刚生成的代码、HTML、网页、小游戏或文本文件上要求加入、添加、修改、修复、优化、美化某个功能，选 general_tools，不要选 create_text_file，也不要删除旧文件。"
        "create_text_file 支持一次请求创建多个文件，适合需要 index.html/style.css/app.js、多个脚本或项目骨架的任务。"
        "如果用户要创建可运行的软件/小游戏/工具，但没有指定实现载体，且 HTML、Python、本地脚本或 Web UI 都合理，选 choose_implementation，让界面弹出选项；"
        "如果请求已经明确指定 HTML、Python、网页、单文件、浏览器、Tkinter、Pygame 等实现方式，不要选 choose_implementation，直接选 create_text_file。"
        "不要把小游戏、脚本或网页创建误判为 Word 文档；只有用户明确说 Word/DOCX/文档报告时才选 create_docx。"
        "如果用户基于单张上传图片或 latest_active_image 要求生成三视图/前左后视图，选 generate_multiview_images；"
        "如果用户要求用已经由系统生成且上下文 latest_multiview 明确标注 front/left/back 的三视图继续生成 3D 模型，选 generate_3d_multiview；"
        "不要将用户上传的多张未标注图片交给 LLM 判断视角后选择 generate_3d_multiview。"
        "如果一个请求包含两个或更多需要依次执行、且后一步依赖前一步输出文件的操作，选 general_tools，让 Agent 使用工具结果继续规划和调用下一步；不要把多步骤请求压缩成单个生成 action。"
        "如果用户要 3D/模型/GLB，按是否有图片选择 generate_3d_image/generate_3d_fusion/generate_3d_text；"
        "如果用户说根据文档/文本/附件/项目文件夹要求生成图片或模型，优先选 project_document_image/project_document_3d 或 attachment_document_image/attachment_document_3d；"
        "如果用户要求读取、总结、分析项目文件夹内的 docx/pdf/txt/md 等文档，选 read_document 或 folder_summary_docx。"
        "如果 model_capabilities.supports_vision=false，不要声称已看懂图片内容；可以选择 edit_image 让图像工作流基于源图执行，或在无源图时选择 generate_image。"
        "如果只是问答或描述图片内容，选 chat；如果需要本地文件工具但不属于上述生成任务，选 general_tools。"
        "质量选择：如果用户明确要求高质量、更精细、慢一点但效果更好，quality_mode 选 quality；如果用户没有明确要求质量，quality_mode 必须选 fast。"
        "输出格式: {\"action\":\"...\",\"prompt\":\"可选的优化后提示词\",\"quality_mode\":\"fast|quality\",\"source\":\"latest_active_image|attached_image|project_image|document|project_document|none\",\"source_files\":[\"可选路径\"],\"reason\":\"一句话原因\"}"
    )
    user_text = json.dumps(
        {
            "user_request": req.content,
            "context": context,
        },
        ensure_ascii=False,
    )
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=fit_messages_to_context([
                {"role": "system", "content": system_hint},
                {"role": "user", "content": user_text},
            ], provider_config or ("", model_name, "", "", None)),
            response_format={"type": "json_object"},
        )
        decision = router_safe_json(response.choices[0].message.content or "{}")
    except Exception as e:
        print(f"[router] route failed: {e}")
        return None

    action = str(decision.get("action") or "chat").strip()
    if action not in ROUTER_ACTIONS:
        return None
    decision["action"] = action
    decision.setdefault("prompt", req.content)
    decision["quality_mode"] = quality_mode_from_decision(decision)
    print(f"[router] action={action} quality={decision.get('quality_mode')} source={decision.get('source')} reason={decision.get('reason')}")
    return decision
