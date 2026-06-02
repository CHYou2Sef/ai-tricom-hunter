"""
smart_wait.py — State-based browser waiting utilities.
Replaces all time.sleep() / asyncio.sleep() with observable DOM conditions.
"""
import asyncio
import time
from typing import Optional, Callable, Any

async def wait_until(
    condition: Callable[[], Any],
    timeout: float = 30.0,
    poll_interval: float = 0.5,
    description: str = "condition",
) -> Optional[Any]:
    """
    Poll `condition()` every `poll_interval` seconds until it returns
    a truthy value or `timeout` expires.

    Returns the truthy result or None on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = await condition() if asyncio.iscoroutinefunction(condition) else condition()
            if result:
                return result
        except Exception:
            pass
        await asyncio.sleep(poll_interval)
    return None

async def wait_for_json_in_text(
    get_text_fn: Callable,
    timeout: float = 30.0,
    poll_interval: float = 0.8,
) -> Optional[str]:
    """
    Wait until the page text contains a JSON object (opening brace detected).
    Returns the text when JSON appears, or None on timeout.
    """
    async def check():
        text = await get_text_fn() if asyncio.iscoroutinefunction(get_text_fn) else get_text_fn()
        if text and "{" in text and "}" in text:
            return text
        return None
    return await wait_until(check, timeout=timeout, poll_interval=poll_interval,
                             description="json_in_response")

async def wait_for_element_disappear(
    check_fn: Callable,
    timeout: float = 25.0,
    poll_interval: float = 0.5,
) -> bool:
    """
    Wait until a 'loading' spinner / typing indicator disappears.
    Returns True when gone, False on timeout.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = await check_fn() if asyncio.iscoroutinefunction(check_fn) else check_fn()
            if not result:
                return True
        except Exception:
            return True  # Element gone → safe
        await asyncio.sleep(poll_interval)
    return False
