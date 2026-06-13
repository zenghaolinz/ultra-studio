import json
from pathlib import Path

from memory import manager as memory_mgr
from schemas import ChatRequest
from services.chat_documents import folder_documents
from services.chat_intents import is_folder_summary_to_docx_intent
from services.chat_paths import (
    extract_directory_path,
    format_path_resolution_card,
    nearby_path_suggestions,
)


async def summarize_folder_documents(req: ChatRequest, client, model_name: str) -> dict | None:
    if req.image_paths or not is_folder_summary_to_docx_intent(req.content):
        return None

    folder = extract_directory_path(req.content)
    if not folder and req.project_path:
        candidate = Path(req.project_path)
        if candidate.exists() and candidate.is_dir():
            folder = candidate
    if not folder:
        return {
            "needs_path": True,
            "message": format_path_resolution_card(req.content, nearby_path_suggestions(req.content)),
        }

    recursive = any(word in (req.content or "").lower() for word in ["递归", "包含子文件夹", "子目录", "recursive"])
    docs = folder_documents(folder, recursive=recursive, limit=12)
    if not docs:
        return {
            "ok": False,
            "error": f"文件夹中没有找到可读取的文档: {folder}",
        }

    sections = []
    for doc in docs:
        result = memory_mgr.handle_read_document(str(doc), 9000)
        if not result.get("ok"):
            sections.append(f"[{doc.name}]\n读取失败：{result.get('error', 'unknown error')}")
            continue
        sections.append(
            f"[文件: {result.get('name') or doc.name}]\n路径: {result.get('path') or str(doc)}\n\n{result.get('content', '')}"
        )

    output_path = folder / "资料整理报告.docx"
    system_hint = (
        "你是资料整理助手。请基于用户给定文件夹内文档内容，输出 JSON，不要 Markdown。"
        '格式为 {"title":"标题","paragraphs":["段落1","段落2"]}。'
        "要求：按文档归纳重点，合并重复信息，保留关键结论、待办事项、风险或疑问；"
        "如果某些文件读取失败，也在最后简短说明。"
    )
    user_text = (
        f"用户需求：{req.content}\n\n"
        f"文件夹：{folder}\n"
        f"已读取文档数量：{len(docs)}\n\n"
        "文档内容如下：\n\n"
        + "\n\n---\n\n".join(sections)
    )
    try:
        response = await client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": system_hint},
                {"role": "user", "content": user_text},
            ],
            response_format={"type": "json_object"},
        )
        payload = json.loads(response.choices[0].message.content or "{}")
    except Exception:
        payload = {}

    title = str(payload.get("title") or "资料整理报告").strip()
    paragraphs = payload.get("paragraphs")
    if not isinstance(paragraphs, list) or not paragraphs:
        paragraphs = [
            f"已读取文件夹：{folder}",
            f"共发现 {len(docs)} 个可读取文档。",
            "模型未能生成结构化整理内容，请重试或缩小文档范围。",
        ]

    create_result = memory_mgr.handle_create_docx_document(
        str(output_path),
        title,
        [str(item) for item in paragraphs if str(item).strip()],
        False,
    )
    if create_result.get("ok"):
        create_result["source_folder"] = str(folder)
        create_result["document_count"] = len(docs)
        create_result["documents"] = [str(doc) for doc in docs]
    return create_result
