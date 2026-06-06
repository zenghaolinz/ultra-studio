from openai import AsyncOpenAI
import numpy as np


async def get_embedding(text: str, config: dict) -> list[float]:
    client = AsyncOpenAI(
        api_key=config.get("api_key") or "sk-placeholder",
        base_url=config.get("base_url", "https://api.openai.com/v1"),
    )
    response = await client.embeddings.create(
        model=config.get("model_name", "text-embedding-3-small"),
        input=text,
    )
    return response.data[0].embedding


async def get_embeddings(texts: list[str], config: dict) -> list[list[float]]:
    client = AsyncOpenAI(
        api_key=config.get("api_key") or "sk-placeholder",
        base_url=config.get("base_url", "https://api.openai.com/v1"),
    )
    response = await client.embeddings.create(
        model=config.get("model_name", "text-embedding-3-small"),
        input=texts,
    )
    return [item.embedding for item in response.data]
