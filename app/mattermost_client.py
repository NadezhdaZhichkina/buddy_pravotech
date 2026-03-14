from typing import Optional

import httpx

from .config import get_settings


async def post_message(
    channel_id: str,
    text: str,
    root_id: Optional[str] = None,
) -> str:
    """
    Post a message as the bot to a Mattermost channel.
    Returns created post id.
    """
    settings = get_settings()
    if not settings.mattermost_bot_token:
        # For local demo without Mattermost just return a fake id.
        return "demo-post-id"

    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{settings.mattermost_base_url}/api/v4/posts",
            headers={
                "Authorization": f"Bearer {settings.mattermost_bot_token}",
                "Content-Type": "application/json",
            },
            json={
                "channel_id": channel_id,
                "message": text,
                **({"root_id": root_id} if root_id else {}),
            },
        )
        resp.raise_for_status()
        data = resp.json()
        return data["id"]

