"""Local Telegram wire-protocol stand-in. Never use this server outside tests.

    uv run uvicorn tests.e2e.mock_telegram:app --host 127.0.0.1 --port 8798

POST /_updates accepts a Telegram update; GET /_seen returns outbound requests.
The test bot token is intentionally fake and must never work against Telegram.
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

VALID_TOKEN = "123456:telegram_e2e_fake_token_1234567890"
app = FastAPI()
seen: list[dict] = []
updates: list[dict] = []
next_update = 0
next_message = 0


@app.get("/_seen")
def requests_seen():
    return seen


@app.post("/_updates")
async def add_update(request: Request):
    global next_update
    update = await request.json()
    next_update += 1
    update["update_id"] = next_update
    updates.append(update)
    return {"ok": True, "update_id": next_update}


@app.post("/_reset")
def reset():
    seen.clear()
    updates.clear()
    return {"ok": True}


@app.post("/bot{token}/{method}")
async def api(token: str, method: str, request: Request):
    global next_message
    if token != VALID_TOKEN:
        return JSONResponse({"ok": False, "error_code": 401, "description": "Unauthorised"}, status_code=401)
    body = await request.json()
    if method != "getUpdates":
        seen.append({"method": method, "body": body})
    if method == "getMe":
        result = {"id": 123456, "is_bot": True, "username": "jarvis_e2e_bot", "first_name": "JARVIS"}
    elif method == "getUpdates":
        offset = body.get("offset", 0)
        for _ in range(50):
            result = [update for update in updates if update["update_id"] >= offset]
            if result:
                break
            await asyncio.sleep(0.1)
    elif method == "sendMessage":
        next_message += 1
        result = {"message_id": next_message, "chat": {"id": body["chat_id"], "type": "private"}, "text": body["text"]}
    elif method in ("sendChatAction", "answerCallbackQuery", "editMessageText"):
        result = True
    else:
        return JSONResponse({"ok": False, "error_code": 400, "description": "Unsupported test method"}, status_code=400)
    return {"ok": True, "result": result}
