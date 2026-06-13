import os

from services.chat_paths import IMAGE_EXTENSIONS


def is_memory_intent(content: str) -> bool:
    text = (content or "").lower()
    if any(word in text for word in ["删除", "删了", "删掉", "移除", "理解错", "误解"]):
        return False
    return any(word in text for word in ["记住", "记一个", "remember", "别忘", "偏好"])


def is_folder_summary_to_docx_intent(content: str) -> bool:
    text = (content or "").lower()
    has_folder_word = any(word in text for word in ["文件夹", "目录", "folder", "directory"])
    has_summary_word = any(word in text for word in ["阅读", "读取", "整理", "总结", "重点", "提取", "汇总", "归纳"])
    has_output_word = any(word in text for word in ["新文档", "docx", "word", "写入", "生成文档", "输出文档", "报告"])
    return has_folder_word and has_summary_word and has_output_word


def is_open_folder_intent(content: str) -> bool:
    text = (content or "").lower()
    return any(word in text for word in ["打开", "显示", "定位", "open", "reveal"]) and any(
        word in text for word in ["文件夹", "目录", "folder", "directory", "项目"]
    )


def requests_multiview_followup(content: str) -> bool:
    text = (content or "").lower()
    return any(
        word in text
        for word in ["三视图", "三视角", "多视图", "多视角", "前左后", "正面、左侧、背面"]
    )


def is_3d_intent(content: str, image_paths: list[str] | None = None) -> bool:
    text = (content or "").lower()
    blocked_words = [
        "语言模型",
        "大模型",
        "模型配置",
        "model config",
        "llm",
    ]
    if any(word in text for word in blocked_words):
        return False

    intent_words = [
        "3d",
        "三维",
        "模型",
        "建模",
        "转3d",
        "转 3d",
        "生成模型",
    ]
    action_words = [
        "生成",
        "做",
        "给我",
        "来一个",
        "要",
        "想要",
        "创建",
        "制作",
        "转",
        "建",
        "画",
        "设计",
        "希望",
        "全新",
        "新的",
        "另一个",
        "另外一个",
        "重新来",
        "重新做",
        "从零",
        "文生",
    ]

    if image_paths:
        if not any(os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS for path in image_paths):
            return False
        return any(word in text for word in intent_words)
    return any(word in text for word in intent_words) and any(
        word in text for word in action_words
    )


def is_image_3d_intent(content: str, image_paths: list[str] | None = None) -> bool:
    return bool(image_paths) and is_3d_intent(content, image_paths)


def is_text_3d_intent(content: str, image_paths: list[str] | None = None) -> bool:
    return not image_paths and is_3d_intent(content, image_paths)


def is_image_generation_intent(content: str, image_paths: list[str] | None = None) -> bool:
    if image_paths:
        return False
    text = (content or "").lower()
    if any(word in text for word in ["3d", "3D", "三维", "模型", "建模", "glb", "obj"]):
        return False
    draw_words = [
        "画",
        "绘制",
        "绘图",
        "生图",
        "生成图片",
        "生成一张图",
        "生成图",
        "图片生成",
        "出图",
        "做一张图",
        "做张图",
        "来一张",
        "来张",
        "给我一张",
        "给我张",
        "我要一张",
        "我想要一张",
        "想要一张",
        "要一张",
        "要张",
        "帮我画",
        "画一张",
    ]
    subject_words = [
        "图",
        "图片",
        "插画",
        "海报",
        "头像",
        "概念图",
        "卡通",
        "角色",
        "狗",
        "猫",
        "产品",
        "场景",
    ]
    if "图片" in text and any(word in text for word in ["想要", "我要", "给我", "来", "做", "生成"]):
        return True
    return any(word in text for word in draw_words) and any(word in text for word in subject_words)


def is_image_edit_intent(content: str, image_paths: list[str] | None = None) -> bool:
    if not image_paths:
        return False
    if not any(os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS for path in image_paths):
        return False
    text = (content or "").lower()
    if is_3d_intent(content, image_paths):
        return False
    edit_words = [
        "改图",
        "编辑图片",
        "修改图片",
        "把图片",
        "这张图",
        "这张图片",
        "改成",
        "换成",
        "润色",
        "增强",
        "优化",
        "完整呈现",
        "呈现完整",
        "画完整",
        "补全",
        "扩图",
        "补全图片",
        "画面完整",
    ]
    return any(word in text for word in edit_words)


def is_previous_image_edit_intent(content: str) -> bool:
    text = (content or "").lower()
    blocked_words = ["全新", "新的图片", "重新画一张", "不要基于", "不基于", "从零"]
    if any(word in text for word in blocked_words):
        return False
    previous_words = [
        "上一张",
        "上张",
        "第一张",
        "第一只",
        "第一幅",
        "第一個",
        "第一个",
        "刚才",
        "刚刚",
        "这张",
        "这个",
        "这只",
        "那只",
        "它",
        "他",
        "图片",
        "图中",
    ]
    edit_words = [
        "完整呈现",
        "呈现完整",
        "画完整",
        "补全",
        "扩图",
        "补全图片",
        "画面完整",
        "改图",
        "编辑图片",
        "修改图片",
        "润色",
        "增强",
        "优化",
        "改成",
        "换成",
        "变成",
        "变",
    ]
    attribute_words = [
        "白色",
        "黑色",
        "红色",
        "蓝色",
        "绿色",
        "黄色",
        "棕色",
        "金色",
        "灰色",
        "可爱",
        "毛茸茸",
        "小狗",
        "狗",
        "小猫",
        "猫",
        "兔子",
        "white",
        "black",
        "red",
        "blue",
        "green",
        "yellow",
        "brown",
        "dog",
        "cat",
        "rabbit",
    ]
    correction_words = [
        "我想要的是",
        "我要的是",
        "我是要",
        "我想要的其实是",
        "不是",
        "应该是",
        "要的是",
        "想要的是",
    ]
    has_previous_ref = any(word in text for word in previous_words)
    has_explicit_edit = any(word in text for word in edit_words)
    has_attribute_change = any(word in text for word in attribute_words)
    has_correction = any(word in text for word in correction_words)
    return (has_previous_ref and (has_explicit_edit or has_attribute_change)) or (
        has_correction and has_attribute_change
    )


def is_modify_previous_3d_intent(content: str, image_paths: list[str] | None = None) -> bool:
    if image_paths:
        return False

    text = (content or "").lower()
    blocked_words = [
        "语言模型",
        "大模型",
        "模型配置",
        "model config",
        "llm",
    ]
    if any(word in text for word in blocked_words):
        return False

    new_request_words = [
        "全新",
        "新的",
        "新模型",
        "另一个",
        "另外一个",
        "重新来",
        "重新做",
        "重新生成一个",
        "不要基于",
        "不基于",
        "不要沿用",
        "不要用上",
        "从零",
        "文生模型",
        "文生 3d",
    ]
    if any(word in text for word in new_request_words):
        return False

    previous_words = [
        "上一个",
        "上次",
        "之前",
        "刚才",
        "刚刚",
        "这个",
        "这只",
        "它",
        "其",
    ]
    edit_words = [
        "修改",
        "改",
        "改成",
        "换成",
        "调整",
        "优化",
        "增强",
        "润色",
        "变成",
        "变",
        "重新生成",
    ]
    attribute_words = [
        "黑色",
        "白色",
        "红色",
        "蓝色",
        "绿色",
        "黄色",
        "橙色",
        "紫色",
        "粉色",
        "灰色",
        "棕色",
        "金属",
        "木质",
        "玻璃",
        "毛绒",
        "可爱",
        "卡通",
        "风格",
        "材质",
        "颜色",
        "black",
        "white",
        "red",
        "blue",
        "green",
        "yellow",
        "metal",
        "metallic",
        "wood",
        "glass",
    ]
    preference_words = [
        "希望",
        "想",
        "想要",
        "是",
        "成为",
        "看起来",
    ]

    has_previous_ref = any(word in text for word in previous_words)
    has_explicit_edit = any(word in text for word in edit_words)
    has_attribute_change = any(word in text for word in attribute_words) and any(
        word in text for word in preference_words
    )
    return has_previous_ref and (has_explicit_edit or has_attribute_change)
