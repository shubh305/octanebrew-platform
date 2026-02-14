from fastapi import Request

async def rate_limit_key(request: Request):
    """
    Returns the X-App-ID header content or 'anonymous' if not found.
    Used as the key for Rate Limiting.
    """
    return request.headers.get("X-App-ID", "anonymous")
