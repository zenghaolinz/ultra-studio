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
