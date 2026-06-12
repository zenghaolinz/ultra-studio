from openai import AsyncOpenAI


async def get_provider_client(db, model_id: str | None = None):
    config_row = []
    if model_id:
        config_row = await db.execute_fetchall(
            "SELECT provider, model_name, api_key, base_url FROM model_configs WHERE id = ? LIMIT 1",
            (model_id,),
        )
    if not config_row:
        config_row = await db.execute_fetchall(
            "SELECT provider, model_name, api_key, base_url FROM model_configs WHERE is_default = 1 LIMIT 1"
        )
    if not config_row:
        config_row = await db.execute_fetchall(
            "SELECT provider, model_name, api_key, base_url FROM model_configs ORDER BY created_at DESC LIMIT 1"
        )
    if not config_row:
        return None, None

    provider_config = config_row[0]
    client = AsyncOpenAI(
        api_key=provider_config[2] or "sk-placeholder",
        base_url=provider_config[3],
    )
    return client, provider_config
