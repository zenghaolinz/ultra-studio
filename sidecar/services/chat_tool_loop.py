import asyncio
import json
from pathlib import Path

from memory import manager as memory_mgr
from memory import stm as memory_stm
from services.chat_generation_context import inject_3d_context, inject_image_context
from services.model_context import fit_messages_to_context
from services.chat_tool_results import first_tool_result


MAX_TOOL_CALL_ROUNDS = 6


async def run_tool_calls(
    client,
    model_name,
    messages,
    tools,
    conversation_id: str = "",
    permission_mode: str = "standard",
    force_file_action: bool = False,
    status_callback=None,
    provider_config=None,
):
    saved_memories = []
    tool_results = []
    read_file_paths: set[str] = set()
    context_provider_config = provider_config or ("", model_name, "", "", None)
    for _ in range(MAX_TOOL_CALL_ROUNDS):
        if force_file_action and not first_tool_result(tool_results, "delete_file"):
            messages.append({
                "role": "system",
                "content": (
                    "当前任务是本地文件删除。必须通过工具完成，不能用普通文本回答。"
                    "如果目标在文件夹中，先 list_directory；目录列表返回后，选择精确子文件 path 调用 delete_file。"
                    "标准模式 confirmed=false；自主模式可以 confirmed=true。"
                ),
            })
        response = await client.chat.completions.create(
            model=model_name,
            messages=fit_messages_to_context(messages, context_provider_config, tools),
            tools=tools,
            tool_choice="auto",
        )

        choice = response.choices[0]
        message = choice.message

        if not message.tool_calls:
            if force_file_action and not first_tool_result(tool_results, "delete_file"):
                messages.append({
                    "role": "system",
                    "content": (
                        "用户请求的是本地文件删除任务。不能用普通文本回答无法访问。"
                        "你必须继续使用工具完成：如果还没有定位目标，调用 list_directory；"
                        "如果已经从目录列表中看到了匹配的文本文件，调用 delete_file。"
                        "标准权限下 delete_file confirmed=false 以触发确认卡片；自主模式可以直接删除。"
                    ),
                })
                continue
            return messages, tool_results, saved_memories

        messages.append(message.model_dump())

        for tool_call in message.tool_calls:
            if status_callback:
                await status_callback(tool_call.function.name)
                await asyncio.sleep(0)
            if tool_call.function.name == "recall_memory":
                try:
                    args = json.loads(tool_call.function.arguments)
                    branch_path = args.get("branch_path", "")
                    results = memory_mgr.handle_recall_memory(branch_path)
                except Exception as e:
                    results = [{"error": str(e)}]

                tool_results.append({"tool": tool_call.function.name, "result": results})

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(results, ensure_ascii=False),
                    }
                )
            elif tool_call.function.name == "save_memory":
                try:
                    args = json.loads(tool_call.function.arguments)
                    content = args.get("content", "")
                    branch_path = args.get("branch_path", "个人/喜好偏好")
                    tags = args.get("tags", [])
                    save_result = memory_mgr.handle_save_memory(
                        content, branch_path, tags
                    )
                except Exception as e:
                    save_result = {"ok": False, "error": str(e)}

                if save_result.get("ok"):
                    saved_memories.append(content)
                tool_results.append({"tool": tool_call.function.name, "result": save_result})

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(save_result, ensure_ascii=False),
                    }
                )
            elif tool_call.function.name == "generate_image":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_image(
                        args.get("prompt", ""),
                        args.get("quality_mode", "fast"),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await inject_image_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_video":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_video(
                        args.get("prompt", ""),
                        args.get("image_path") or None,
                        args.get("quality_mode", "quality"),
                        int(args.get("duration_seconds", 4)),
                        int(args.get("width", 1024)),
                        int(args.get("height", 576)),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "generate_3d_from_text":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_3d_from_text(
                        args.get("prompt", ""),
                        args.get("quality_mode", "fast"),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await inject_3d_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_3d_from_image":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_3d_from_image(
                        args.get("image_path", ""),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        parts = []
                        if result.get("image_2d"):
                            parts.append(f"[System Context: 活跃生成图片路径=\"{result['image_2d']}\"]")
                        if result.get("model_path"):
                            parts.append(f"[System Context: 活跃模型路径=\"{result['model_path']}\"]")
                        if parts:
                            await memory_stm.inject_system_context(conversation_id, "\n".join(parts))
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_3d_fusion":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_3d_fusion(
                        args.get("image1_path", ""),
                        args.get("image2_path", ""),
                        args.get("prompt", ""),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await inject_3d_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_multiview_images_from_image":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_multiview_images_from_image(
                        args.get("image_path", ""),
                        args.get("quality_mode", "fast"),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await inject_3d_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "generate_3d_from_generated_multiview":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_generate_3d_from_generated_multiview(
                        args.get("front_path", ""),
                        args.get("left_path", ""),
                        args.get("back_path", ""),
                        args.get("quality_mode", "fast"),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success":
                    try:
                        await inject_3d_context(conversation_id, result)
                    except Exception:
                        pass
            elif tool_call.function.name == "modify_image_with_flux":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_modify_image(
                        args.get("source_path", ""),
                        args.get("modification_prompt", ""),
                        args.get("denoise_strength", 0.5),
                        conversation_id,
                    )
                except Exception as e:
                    result = {"status": "error", "message": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("status") == "success" and result.get("improved_image_path"):
                    try:
                        ctx_msg = f"[System Context: 活跃图像路径=\"{result['improved_image_path']}\"]"
                        await memory_stm.inject_system_context(conversation_id, ctx_msg)
                    except Exception:
                        pass
            elif tool_call.function.name == "read_document":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_read_document(
                        args.get("file_path", ""),
                        int(args.get("max_chars", 12000)),
                    )
                    if result.get("ok") and result.get("path"):
                        read_file_paths.add(str(Path(result["path"]).resolve()).lower())
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "read_many_files":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_read_many_files(
                        args.get("file_paths", []),
                        int(args.get("max_chars_per_file", 8000)),
                        int(args.get("max_files", 12)),
                    )
                    for item in result.get("files") or []:
                        if isinstance(item, dict) and item.get("path"):
                            read_file_paths.add(str(Path(item["path"]).resolve()).lower())
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "web_search":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_web_search(
                        args.get("query", ""),
                        int(args.get("max_results", 5)),
                        args.get("recency_days"),
                        args.get("domains", []),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e), "results": []}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "web_fetch":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_web_fetch(
                        args.get("url", ""),
                        int(args.get("max_chars", 12000)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "list_directory":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_list_directory(
                        args.get("directory_path", ""),
                        bool(args.get("recursive", False)),
                        int(args.get("max_items", 120)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if force_file_action:
                    messages.append({
                        "role": "system",
                        "content": (
                            "上面是目录列表。若用户要求删除文件夹里的文本文档，请从 items 中选择 .txt/.md 等文本文件的精确 path，"
                            "然后调用 delete_file，target_type=file，recursive=false。不要删除父文件夹，也不要回答没有权限。"
                        ),
                    })
            elif tool_call.function.name == "search_files":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_search_files(
                        args.get("directory_path", ""),
                        args.get("query", ""),
                        args.get("file_glob", "*"),
                        bool(args.get("recursive", True)),
                        bool(args.get("search_content", True)),
                        int(args.get("max_matches", 80)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "organize_files":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_organize_files(
                        args.get("directory_path", ""),
                        args.get("strategy", "by_type"),
                        bool(args.get("apply_changes", False)),
                        bool(args.get("recursive", False)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "edit_text_file":
                try:
                    args = json.loads(tool_call.function.arguments)
                    file_path = str(Path(args.get("file_path", "")).resolve()).lower()
                    if file_path not in read_file_paths:
                        result = {
                            "ok": False,
                            "error": "修改已有文本文件前必须先调用 read_document 或 read_many_files 读取该文件内容。",
                            "path": args.get("file_path", ""),
                            "needs_read": True,
                        }
                    else:
                        result = memory_mgr.handle_edit_text_file(
                            args.get("file_path", ""),
                            args.get("action", ""),
                            args.get("text", ""),
                            args.get("find", ""),
                            args.get("replace", ""),
                            bool(args.get("use_regex", False)),
                            bool(args.get("backup", False)),
                        )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if (
                    not result.get("ok")
                    and "未找到要替换的内容" in str(result.get("error") or "")
                ):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "刚才 edit_text_file 的精确 replace 没有命中。不要把失败直接返回给用户。"
                                "请先用 read_document 读取该文件确认当前内容，然后用 write_many_files 写回完整更新后的文件，"
                                "或用更可靠的 edit_text_file 参数重试。用户要的是完成修改文件。"
                            ),
                        }
                    )
                elif result.get("needs_read"):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "刚才 edit_text_file 被拦截，因为还没有读取目标文件。"
                                "请先调用 read_document 读取同一路径，再基于读取到的真实内容调用 edit_text_file。"
                                "不要改用创建新文件或删除旧文件。"
                            ),
                        }
                    )
            elif tool_call.function.name == "write_many_files":
                try:
                    args = json.loads(tool_call.function.arguments)
                    root_path = Path(args.get("root_path", "")).resolve()
                    files = args.get("files", [])
                    overwrite = bool(args.get("overwrite", False))
                    unread_existing = []
                    if overwrite:
                        for item in files or []:
                            if not isinstance(item, dict):
                                continue
                            raw_name = str(item.get("path") or item.get("filename") or item.get("name") or "").replace("\\", "/")
                            parts = [part for part in raw_name.lstrip("/").split("/") if part not in {"", ".", ".."}]
                            if not parts:
                                continue
                            target = (root_path / Path(*parts)).resolve()
                            if target.exists() and str(target).lower() not in read_file_paths:
                                unread_existing.append(str(target))
                    if unread_existing:
                        result = {
                            "ok": False,
                            "error": "覆盖已有文本/代码文件前必须先读取原文件内容。",
                            "paths": unread_existing,
                            "needs_read": True,
                        }
                    else:
                        result = memory_mgr.handle_write_many_files(
                            args.get("root_path", ""),
                            files,
                            overwrite,
                        )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("needs_read"):
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "刚才 write_many_files 覆盖已有文件被拦截，因为还没有读取原文件。"
                                "请先调用 read_document 或 read_many_files 读取 paths 中的目标文件，"
                                "再选择 edit_text_file 精确修改，或在确实需要整文件写回时 overwrite=true 写回同一路径。"
                            ),
                        }
                    )
            elif tool_call.function.name == "run_command":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_run_command(
                        args.get("command", ""),
                        args.get("cwd", ""),
                        args.get("shell", "powershell"),
                        int(args.get("timeout_seconds", 60)),
                        bool(args.get("confirmed", False)),
                        permission_mode,
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("needs_confirmation"):
                    return messages, tool_results, saved_memories
            elif tool_call.function.name == "run_project_check":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_run_project_check(
                        args.get("project_path", ""),
                        args.get("check_type", "auto"),
                        int(args.get("timeout_seconds", 180)),
                        bool(args.get("confirmed", False)),
                        permission_mode,
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                if result.get("needs_confirmation"):
                    return messages, tool_results, saved_memories
            elif tool_call.function.name == "delete_file":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_delete_path(
                        args.get("target_path", ""),
                        args.get("target_type", "auto"),
                        bool(args.get("recursive", False)),
                        bool(args.get("confirmed", False)),
                        permission_mode,
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
                return messages, tool_results, saved_memories
            elif tool_call.function.name == "create_docx_document":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_create_docx_document(
                        args.get("file_path", ""),
                        args.get("title", ""),
                        args.get("paragraphs", []),
                        bool(args.get("overwrite", False)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            elif tool_call.function.name == "edit_docx_document":
                try:
                    args = json.loads(tool_call.function.arguments)
                    result = memory_mgr.handle_edit_docx_document(
                        args.get("file_path", ""),
                        args.get("action", ""),
                        args.get("text", ""),
                        args.get("find", ""),
                        args.get("replace", ""),
                        bool(args.get("backup", False)),
                    )
                except Exception as e:
                    result = {"ok": False, "error": str(e)}
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
                tool_results.append({"tool": tool_call.function.name, "result": result})
            else:
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": "Unknown function"}),
                    }
                )

    return messages, tool_results, saved_memories
