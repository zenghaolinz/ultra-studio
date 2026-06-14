from schemas import ChatRequest
from services.chat_documents import read_document_attachments
from services.chat_paths import document_attachments
from services.chat_project_files import project_document_paths
from services.model_context import fit_messages_to_context

DOCUMENT_READ_SYSTEM_PROMPT = (
    "\u4f60\u662f\u9879\u76ee\u6587\u6863\u9605\u8bfb\u52a9\u624b\u3002"
    "\u57fa\u4e8e\u5df2\u8bfb\u53d6\u7684\u9879\u76ee\u6587\u4ef6\u5185\u5bb9"
    "\u56de\u7b54\u7528\u6237\uff0c\u4e0d\u8981\u7f16\u9020\u3002"
    "\u5982\u679c\u7528\u6237\u8981\u6c42\u603b\u7ed3\uff0c\u5c31\u6309\u8981\u70b9"
    "\u8f93\u51fa\uff1b\u5982\u679c\u7528\u6237\u8981\u6c42\u751f\u6210\u56fe\u7247/"
    "\u6a21\u578b\u63d0\u793a\u8bcd\uff0c\u5219\u5fe0\u5b9e\u63d0\u53d6"
    "\u6587\u6863\u8981\u6c42\u3002"
)


async def run_project_document_read(req: ChatRequest, client, model_name: str, provider_config=None) -> str | None:
    docs = document_attachments(req.image_paths)
    if not docs:
        docs = project_document_paths(req.project_path or "", req.content)[:5]
    if not docs:
        return None

    sections = read_document_attachments(docs, 14000)
    user_text = (
        f"\u7528\u6237\u9700\u6c42\uff1a{req.content}\n\n"
        "\u6587\u6863\u8def\u5f84\uff1a\n"
        + "\n".join(docs)
        + "\n\n\u6587\u6863\u5185\u5bb9\uff1a\n\n"
        + "\n\n---\n\n".join(sections)
    )
    response = await client.chat.completions.create(
        model=model_name,
        messages=fit_messages_to_context([
            {"role": "system", "content": DOCUMENT_READ_SYSTEM_PROMPT},
            {"role": "user", "content": user_text},
        ], provider_config or ("", model_name, "", "", None)),
    )
    return response.choices[0].message.content or ""
