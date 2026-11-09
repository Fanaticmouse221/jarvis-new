"""An offline stand-in model for tests and demos (no internet or API key needed).

Models:
  fake:echo   replies with a short canned answer that quotes the last message
  fake:demo   slowly streams a formatting showcase (for trying the interface)
  fake:fail   always fails (used to test fallback)
  fake:empty  returns nothing (used to test fallback)
"""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from jarvis.llm.base import ChatMessage, LLMError

DEMO_REPLY = """\
Offline demo mode, sir. No model is being called, but the interface is fully operational.

## What I can render
- **Bold**, *italic* and `inline code`
- Numbered steps:
  1. First
  2. Second

| System | Status |
|---|---|
| Interface | Online |
| Language model | Simulated |

```python
def greet(name: str) -> str:
    return f"Good evening, {name}."
```

> Set a real model in `.env` and run `uv run jarvis check` when ready.
"""


class FakeProvider:
    def __init__(self, model: str = "echo", delay: float = 0.0):
        self.model = model
        self.delay = delay
        self.label = f"fake:{model}"
        self.calls: list[list[ChatMessage]] = []

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncIterator[str]:
        self.calls.append(list(messages))
        if self.model == "fail":
            raise LLMError("fake:fail always fails.", status=503)
        if self.model == "empty":
            return
        if self.model == "demo":
            for index in range(0, len(DEMO_REPLY), 6):
                await asyncio.sleep(self.delay or 0.02)
                yield DEMO_REPLY[index : index + 6]
            return
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        reply = f"Offline test mode. You said: **{last_user}**"
        for word in reply.split(" "):
            if self.delay:
                await asyncio.sleep(self.delay)
            yield word + " "

    async def list_models(self) -> list[str]:
        return ["echo", "demo", "fail", "empty"]
