from services.chat_paths import format_path_resolution_card


def format_image_response(tool_name: str, result: dict) -> str:
    status = result.get("status")
    task_id = result.get("task_id") or result.get("taskId")
    if status == "queued" and task_id:
        label = {
            "generate_multiview_images_from_image": "三视图生成",
            "edit_image": "图片编辑",
            "modify_image_with_flux": "图片编辑",
        }.get(tool_name, "图片生成")
        return "\n".join(
            [
                f"{label}任务已加入队列。",
                "",
                f"任务 ID: `{task_id}`",
                "",
                "你可以继续发送新的聊天或生成任务；完成后会出现在生成历史里。",
            ]
        )
    if tool_name == "generate_multiview_images_from_image":
        front = result.get("front_path") or result.get("frontPath")
        left = result.get("left_path") or result.get("leftPath")
        back = result.get("back_path") or result.get("backPath")
        if status == "success" and front and left and back:
            return "\n".join(
                [
                    "三视图已生成。",
                    "",
                    f"正面: `{front}`",
                    f"左侧: `{left}`",
                    f"背面: `{back}`",
                    "",
                    "可以继续要求我用这三张已知视角图片生成 3D 模型。",
                ]
            )
        message = result.get("message") or "没有返回完整三视图"
        return f"三视图生成失败。\n\n原因: {message}"

    image_path = (
        result.get("image_path")
        or result.get("imagePath")
        or result.get("improved_image_path")
        or result.get("modelPath")
    )
    if status == "success" and image_path:
        label = "编辑后图片" if tool_name == "edit_image" else "生成图片"
        lines = [f"{label}已完成。", "", f"{label}: `{image_path}`"]
        source_prompt = result.get("source_prompt")
        if source_prompt:
            lines.extend(["", f"使用提示词: `{source_prompt}`"])
        return "\n".join(lines)
    message = result.get("message") or "没有返回图片文件"
    return f"图片任务失败。\n\n原因: {message}"


def format_video_response(result: dict) -> str:
    status = result.get("status")
    task_id = result.get("task_id") or result.get("taskId")
    video_path = result.get("videoPath") or result.get("video_path")
    if status == "queued" and task_id:
        return "\n".join(
            [
                "视频生成任务已加入队列。",
                "",
                f"任务 ID: `{task_id}`",
                "",
                "你可以继续发送新的聊天或生成任务；视频完成后会出现在生成历史里。",
            ]
        )
    if status == "success" and video_path:
        return "\n".join(["视频生成已完成。", "", f"视频: `{video_path}`"])
    message = result.get("message") or "视频生成任务没有返回结果"
    return f"视频任务失败。\n\n原因: {message}"


def format_3d_response(tool_name: str, result: dict) -> str:
    mode_label = {
        "generate_3d_from_text": "文生 3D",
        "generate_3d_from_image": "图片转 3D",
        "generate_3d_fusion": "双图融合 3D",
        "modify_previous_3d": "修改后 3D",
    }.get(tool_name, "3D 生成")

    status = result.get("status")
    task_id = result.get("task_id") or result.get("taskId")
    if status == "queued" and task_id:
        return "\n".join(
            [
                f"{mode_label} 任务已加入队列。",
                "",
                f"任务 ID: `{task_id}`",
                "",
                "你可以继续发送新的聊天或生成任务；完成后会出现在生成历史里。",
            ]
        )
    model_path = result.get("model_path") or result.get("modelPath")
    image_2d = result.get("image_2d") or result.get("image2D")
    image_normal = result.get("image_normal") or result.get("imageNormal")
    image_uv = result.get("image_uv") or result.get("imageUV")

    if status == "success" and model_path:
        lines = [f"{mode_label} 已完成。", "", f"3D 模型: `{model_path}`"]
        if image_2d:
            lines.append(f"预览图: `{image_2d}`")
        if image_normal:
            lines.append(f"法线图: `{image_normal}`")
        if image_uv:
            lines.append(f"UV 贴图: `{image_uv}`")
        source1 = result.get("image1_path") or result.get("image1Path")
        source2 = result.get("image2_path") or result.get("image2Path")
        if source1:
            lines.append(f"源图1: `{source1}`")
        if source2:
            lines.append(f"源图2: `{source2}`")
        front = result.get("front_path") or result.get("frontPath")
        left = result.get("left_path") or result.get("leftPath")
        back = result.get("back_path") or result.get("backPath")
        if front and left and back:
            lines.extend([f"正面: `{front}`", f"左侧: `{left}`", f"背面: `{back}`"])
        return "\n".join(lines)

    message = result.get("message") or "未返回 3D 模型文件"
    lines = [f"{mode_label} 失败。", "", f"原因: {message}"]
    front = result.get("front_path") or result.get("frontPath")
    left = result.get("left_path") or result.get("leftPath")
    back = result.get("back_path") or result.get("backPath")
    if front and left and back:
        lines.extend(["", "已完成的中间产物："])
        lines.extend([f"正面: `{front}`", f"左侧: `{left}`", f"背面: `{back}`"])
    if "mat1 and mat2 shapes cannot be multiplied" in message:
        lines.extend(
            [
                "",
                "这个错误通常表示当前 ComfyUI 工作流里的 Flux2 模型和文本编码器维度不匹配。请检查工作流中 UNet/GGUF 模型与 Qwen/CLIP 文本编码器是否来自同一套 Flux2 配置。",
            ]
        )
    return "\n".join(lines)


def format_delete_tool_response(result: dict) -> str:
    if result.get("needs_confirmation") and result.get("message"):
        return result["message"]
    if result.get("ok") and result.get("message"):
        return result["message"]
    return f"删除失败：{result.get('error') or result.get('message') or '未知错误'}"


def format_command_tool_response(result: dict) -> str:
    if result.get("needs_confirmation") and result.get("message"):
        return result["message"]
    command = result.get("command") or ""
    cwd = result.get("cwd") or result.get("path") or ""
    if result.get("timeout"):
        return f"命令执行超时：`{command}`\n\n工作目录：`{cwd}`\n\n{result.get('stderr') or result.get('stdout') or result.get('error') or ''}".strip()
    status = "成功" if result.get("ok") else "失败"
    lines = [f"命令执行{status}：`{command}`"]
    if cwd:
        lines.append(f"工作目录：`{cwd}`")
    if "returncode" in result:
        lines.append(f"退出码：{result.get('returncode')}")
    stdout = (result.get("stdout") or "").strip()
    stderr = (result.get("stderr") or "").strip()
    if stdout:
        lines.extend(["", "stdout:", "```text", stdout[-4000:], "```"])
    if stderr:
        lines.extend(["", "stderr:", "```text", stderr[-4000:], "```"])
    if not stdout and not stderr and result.get("error"):
        lines.extend(["", str(result.get("error"))])
    return "\n".join(lines)


def format_text_edit_response(result: dict) -> str:
    path = result.get("path") or ""
    if result.get("ok"):
        if result.get("changed") is False:
            return f"文件无需修改：`{path}`"
        lines = [f"已修改文件：`{path}`"]
        if result.get("action"):
            lines.append(f"操作：{result.get('action')}")
        if result.get("replacements") is not None:
            lines.append(f"替换次数：{result.get('replacements')}")
        if result.get("backup_path"):
            lines.append(f"备份：`{result.get('backup_path')}`")
        return "\n".join(lines)
    return f"修改文件失败：{result.get('error') or result.get('message') or '未知错误'}"


def format_write_many_files_response(result: dict) -> str:
    files = result.get("files") if isinstance(result, dict) else []
    errors = result.get("errors") if isinstance(result, dict) else []
    lines = []
    if result.get("ok"):
        lines.append(f"已写入 {result.get('written_count', len(files or []))} 个文件：")
    elif files:
        lines.append(f"部分文件已写入，另有 {result.get('error_count', len(errors or []))} 个错误：")
    else:
        return f"写入文件失败：{result.get('error') or '未知错误'}"
    for item in files or []:
        path = item.get("path") if isinstance(item, dict) else ""
        if path:
            lines.append(f"- `{path}`")
    for item in (errors or [])[:5]:
        if isinstance(item, dict):
            lines.append(f"- 错误：{item.get('path', '')} {item.get('error', '')}".strip())
    return "\n".join(lines)


def format_project_check_response(result: dict) -> str:
    if result.get("needs_confirmation") and result.get("message"):
        return result["message"]
    if not result.get("results"):
        return f"项目检查失败：{result.get('error', '未知错误')}"
    lines = [f"项目检查{'通过' if result.get('ok') else '失败'}：`{result.get('path')}`"]
    for item in result.get("results", []):
        lines.append("")
        lines.append(format_command_tool_response(item))
    return "\n".join(lines)


def format_folder_summary_response(result: dict) -> str:
    if result.get("needs_path"):
        return result.get("message") or format_path_resolution_card("", [])
    if result.get("ok"):
        return (
            f"已阅读文件夹中的 {result.get('document_count', 0)} 个文档，并生成整理文档：`{result.get('path')}`"
        )
    return f"整理文件夹文档失败：{result.get('error', '未知错误')}"
