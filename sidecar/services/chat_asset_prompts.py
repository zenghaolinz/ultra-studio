import re


def document_requirement_text(document_sections: list[str]) -> str:
    chunks: list[str] = []
    for section in document_sections:
        _, _, body = section.partition("\n")
        chunks.append(body or section)
    text = "\n".join(chunks)
    text = re.sub(r"(?i)\b(requirements?|prompt)\s*[:：]", "", text)
    text = re.sub(r"要求\s*[:：]", "", text)
    text = re.sub(r"\s+", " ", text).strip(" \n\r\t,，。；;")
    return text


def contains_any(text: str, words: list[str]) -> bool:
    lowered = text.lower()
    return any(word.lower() in lowered for word in words)


def deterministic_asset_prompt(requirement_text: str, target: str) -> str:
    text = requirement_text.strip()
    color = ""
    if contains_any(text, ["白色", "white"]):
        color = "white"
    elif contains_any(text, ["黑色", "black"]):
        color = "black"
    elif contains_any(text, ["棕色", "brown"]):
        color = "brown"

    cute = contains_any(text, ["可爱", "cute", "adorable"])
    subject = ""
    if contains_any(text, ["狗", "小狗", "犬", "dog", "puppy"]):
        subject = "puppy dog" if cute else "dog"
    elif contains_any(text, ["猫", "小猫", "cat", "kitten"]):
        subject = "kitten cat" if cute else "cat"
    elif contains_any(text, ["兔", "rabbit", "bunny"]):
        subject = "bunny rabbit" if cute else "rabbit"

    if subject:
        parts = ["a single"]
        if cute:
            parts.append("cute adorable")
        if color:
            parts.append(color)
        parts.append(subject)
        core = " ".join(parts)
    else:
        core = text

    if target == "3d":
        return (
            f"{core}, stylized 3D asset, full body, clear silhouette, clean topology-friendly shape, "
            "simple neutral background, no humans, no text, no watermark"
        )
    return (
        f"{core}, full body, centered composition, soft fluffy fur, clean simple background, "
        "high quality cute illustration, no humans, no people, no portrait, no text, no watermark"
    )
