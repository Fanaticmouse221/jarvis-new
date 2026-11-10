"""End-to-end check of JARVIS in a real browser.

Starts a mock model provider and the real JARVIS server, then drives the real
interface with Playwright: first-run key entry, chat, real tool execution,
approvals, automatic learning, memory management, a server restart, rate-limit
fallback and the mobile layout. Screenshots are written for visual review.

Not part of the pytest suite because it needs a browser:

    pip install playwright     (uses an installed Chrome; set CHROME to its path)
    python tests/e2e/run_e2e.py [output-dir]
"""

from __future__ import annotations

import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
import tempfile
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPO = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="jarvis-e2e-")).resolve()
RUN, SHOTS, BIN = OUT / "run", OUT / "shots", OUT / "bin"
MARKER = OUT / "marker.txt"
APP, MOCK = "http://127.0.0.1:8765", "http://127.0.0.1:8799"
TELEGRAM = "http://127.0.0.1:8798"
TELEGRAM_TOKEN = "123456:telegram_e2e_fake_token_1234567890"
KEY = "gsk_e2e_valid_key_123456"
CHROME = os.environ.get("CHROME") or next((str(p) for p in (
    Path("C:/Program Files/Google/Chrome/Application/chrome.exe"),
    Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"),
    Path("/usr/bin/google-chrome"),
) if p.exists()), None)
passed: list[str] = []


def check(condition: object, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    passed.append(label)
    print(f"  ok  {label}")


def wait_http(url: str) -> None:
    for _ in range(80):
        try:
            urllib.request.urlopen(url, timeout=1)
            return
        except urllib.error.HTTPError:
            return  # the server answered; that's all we need
        except OSError:
            time.sleep(0.25)
    raise RuntimeError(f"{url} did not come up")


def start_jarvis() -> subprocess.Popen:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("JARVIS_", "TELEGRAM_")) and k not in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY")}
    env.update(
        JARVIS_GROQ_BASE_URL=f"{MOCK}/v1",
        JARVIS_TELEGRAM_API=TELEGRAM,
        JARVIS_DB_PATH=str(RUN / "jarvis.db"),
        JARVIS_WORKSPACE=str(RUN / "workspace"),
        JARVIS_E2E_MARKER=str(MARKER),
        PYTHONPATH=str(REPO),
        PATH=f"{BIN}{os.pathsep}{env['PATH']}",
    )
    log = open(OUT / "jarvis.log", "a")
    proc = subprocess.Popen(
        [sys.executable, "-m", "tests.e2e.serve_app"],
        cwd=RUN, env=env, stdout=log, stderr=subprocess.STDOUT,
    )
    wait_http(APP + "/")
    return proc


def finished(page: Page) -> int:
    return page.locator(".turn.assistant .meta .turn-actions").count()


def send(page: Page, text: str, wait: bool = True) -> None:
    before = finished(page)
    page.fill("#input", text)
    page.press("#input", "Enter")
    if wait:
        page.wait_for_function("n => document.querySelectorAll('.turn.assistant .meta .turn-actions').length > n", arg=before, timeout=30000)
        page.wait_for_timeout(120)


def last_turn(page: Page):
    return page.locator(".turn.assistant").last


def telegram_update(update: dict) -> None:
    request = urllib.request.Request(TELEGRAM + "/_updates", data=json.dumps(update).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=5).close()


def telegram_message(text: str, owner: int = 42) -> None:
    telegram_update({"message": {"chat": {"id": owner, "type": "private"}, "from": {"id": owner, "is_bot": False}, "text": text}})


def telegram_seen() -> list[dict]:
    return json.load(urllib.request.urlopen(TELEGRAM + "/_seen", timeout=5))


def wait_telegram(predicate, timeout: float = 20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = predicate(telegram_seen())
        if result:
            return result
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for Telegram mock outcome")


def main() -> None:
    if RUN.exists():
        raise RuntimeError("Choose a fresh output directory; browser checks never delete an existing run.")
    for folder in (RUN, SHOTS, BIN):
        folder.mkdir(parents=True)
    app_script = BIN / "e2e-marker-app"  # a real program for JARVIS to launch
    app_script.write_text(f"#!/bin/sh\necho launched > {MARKER}\nsleep 4\n")
    app_script.chmod(app_script.stat().st_mode | stat.S_IEXEC)

    mock = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e.mock_openai:app", "--port", "8799", "--log-level", "warning"],
        cwd=REPO, stdout=open(OUT / "mock.log", "w"), stderr=subprocess.STDOUT,
    )
    wait_http(MOCK + "/_seen")
    telegram = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e.mock_telegram:app", "--port", "8798", "--log-level", "warning"],
        cwd=REPO, stdout=open(OUT / "telegram.log", "w"), stderr=subprocess.STDOUT,
    )
    wait_http(TELEGRAM + "/_seen")
    jarvis = start_jarvis()
    errors: list[str] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
            page = browser.new_page(viewport={"width": 1360, "height": 880})
            # "Failed to load resource" lines are the browser noting HTTP failures this run causes on
            # purpose (a rejected key, the restart, the token probe). Everything else must be clean.
            page.on("console", lambda m: errors.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") and "Failed to load resource" not in m.text else None)
            page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
            shot = lambda name: page.screenshot(path=str(SHOTS / f"{name}.png"))

            print("First run: connecting a model")
            page.goto(APP + "/")
            page.wait_for_selector(".setup")
            check(page.locator("#voiceBtn").count() == 1, "the chat composer exposes a microphone button")
            check(page.locator("#voiceStatus").count() == 1, "the chat composer exposes voice status feedback")
            check(page.locator("a[data-nav='todos']").count() == 1, "the rail exposes the To-dos page")
            check("Connect a model" in page.inner_text(".setup"), "first run shows the setup panel, not a dead chat box")
            check("warn" in page.get_attribute("#railStatus .dot", "class"), "status light is amber while no model is ready")
            shot("01-first-run")
            page.fill(".setup input", "gsk_wrong_key_000000")
            page.click(".setup button[type=submit]")
            page.wait_for_function("document.querySelector('.setup .hint:not([hidden])')?.textContent.includes('rejected')")
            check(not (RUN / ".env").exists() or KEY not in (RUN / ".env").read_text(), "a rejected key is not saved")
            page.fill(".setup input", KEY)
            page.click(".setup button[type=submit]")
            page.wait_for_selector(".starters")
            check(f"GROQ_API_KEY={KEY}" in (RUN / ".env").read_text(), "the accepted key is saved to .env")
            check("ok" in page.get_attribute("#railStatus .dot", "class"), "status light turns green")
            check(page.locator("#modelSelect option").count() == 4, "three models were selected automatically from the account's list")
            shot("02-welcome")

            print("To-dos: add, complete and reopen")
            page.click(".rail-item[data-nav=todos]")
            page.wait_for_selector("h1:has-text('To-dos')")
            check("No to-dos yet." in page.inner_text(".page"), "the To-dos page starts empty")
            page.fill("input[aria-label='To-do title']", "Book chemistry revision")
            page.fill("input[aria-label='To-do details']", "Review the practice questions")
            page.click("button:has-text('Add to-do')")
            page.locator(".row", has_text="Book chemistry revision").wait_for()
            check("Review the practice questions" in page.inner_text(".row"), "a to-do is added through the protected API")
            page.locator(".row", has_text="Book chemistry revision").get_by_role("button", name=re.compile("Complete")).click()
            page.locator(".group-heading", has_text="Completed").wait_for()
            check("Book chemistry revision" in page.inner_text(".group-heading + .row"), "a to-do can be completed")
            page.locator(".row", has_text="Book chemistry revision").get_by_role("button", name=re.compile("Reopen")).click()
            page.locator(".row", has_text="Book chemistry revision").get_by_role("button", name=re.compile("Complete")).wait_for()
            check(page.locator(".group-heading", has_text="Completed").count() == 0, "a completed to-do can be reopened")
            page.click(".rail-item[data-nav=chat]")
            page.wait_for_selector("#input")

            print("Memory: told, learned, and visible")
            send(page, "Remember that I prefer worked solutions step by step")
            check("Saved to memory" in last_turn(page).locator(".step[data-status=ok] .step-title").inner_text(), "remember ran as a real tool step")
            send(page, "I'm studying chemistry for my exam next week")
            page.wait_for_selector(".learned", timeout=15000)
            check("chemistry" in page.inner_text(".learned"), "JARVIS learned a fact on its own and showed it")
            shot("03-learned")

            print("Actions: real, verified, and honest about failure")
            send(page, "open e2e-marker-app")
            check(MARKER.exists(), "open_app really started the program (it wrote its marker file)")
            check("e2e-marker-app" in last_turn(page).locator(".step[data-status=ok] .step-title").inner_text(), "the step reports the accepted launch request")
            send(page, "open definitely-not-an-app")
            check(last_turn(page).locator(".step[data-status=error]").count() == 1, "a failed action is shown as failed")
            check("didn't work" in last_turn(page).inner_text(), "JARVIS says it failed instead of pretending")
            send(page, "show me a formatting demo")
            check(last_turn(page).locator(".katex").count() >= 2, "maths renders")
            check(last_turn(page).locator(".code-block .hljs-keyword").count() >= 1, "code is highlighted")
            check(last_turn(page).locator("table").count() == 1, "tables render")
            check("hidden reasoning" not in page.inner_text("#thread"), "the model's private reasoning is not shown")
            shot("04-formatting")

            print("Settings: personality and permissions")
            page.click(".rail-item[data-nav=settings]")
            page.wait_for_selector(".page h2:has-text('System status')")
            shot("05-settings")
            check("Folders and home city" in page.inner_text(".page"), "settings show approved folders and home city")
            check(page.locator("textarea[aria-label='Approved folders']").count() == 1, "approved folders have a dedicated setting")
            check(page.locator("input[placeholder='Brisbane, Australia']").count() == 1, "home city has a dedicated setting")
            check("Reminders" in page.inner_text(".page") and "No pending reminders." in page.inner_text(".page"), "settings show the reminders list")
            page.select_option("select[aria-label='Permission for Open an app']", "ask")
            page.click(".segmented[aria-label='Humour'] button:has-text('Off')")
            page.click(".segmented[aria-label='Answer length'] button:has-text('Brief')")
            page.fill("input[placeholder='Your first name']", "Jack")
            page.press("input[placeholder='Your first name']", "Tab")
            page.wait_for_timeout(600)

            print("Approvals")
            page.click(".rail-item[data-nav=chat]")
            page.wait_for_selector(".welcome")
            MARKER.unlink()
            send(page, "open e2e-marker-app", wait=False)
            page.wait_for_selector(".approval")
            page.wait_for_timeout(400)
            check(not MARKER.exists(), "an ask-first action does not run before approval")
            check("Allow JARVIS to open e2e-marker-app?" in page.inner_text(".approval"), "the approval request says exactly what will happen")
            shot("06-approval")
            before = finished(page)
            page.click(".approval button:has-text('Allow')")
            page.wait_for_function("n => document.querySelectorAll('.turn.assistant .meta .turn-actions').length > n", arg=before, timeout=30000)
            check(MARKER.exists(), "after approval it runs for real")
            MARKER.unlink()
            send(page, "open e2e-marker-app", wait=False)
            page.wait_for_selector(".approval")
            before = finished(page)
            page.click(".approval button:has-text(\"Don't allow\")")
            page.wait_for_function("n => document.querySelectorAll('.turn.assistant .meta .turn-actions').length > n", arg=before, timeout=30000)
            check(not MARKER.exists() and last_turn(page).locator(".step[data-status=denied]").count() == 1, "a declined action never runs")

            seen = json.load(urllib.request.urlopen(MOCK + "/_seen"))
            system = next(r for r in reversed(seen) if r.get("tools"))["messages"][0]["content"]
            check("No humour" in system and "as short as accuracy allows" in system, "personality dials reached the model")
            check("Jack's personal AI assistant" in system, "the model is told who it works for")
            check("[#1]" in system and "chemistry" in system, "memories are sent to the model with every message")
            tool_names = [t["function"]["name"] for t in seen[-1].get("tools") or next(r for r in reversed(seen) if r.get("tools"))["tools"]]
            check({"remember", "recall", "open_app"} <= set(tool_names), "real tool definitions are sent to the model")

            print("Memory screen")
            page.click(".rail-item[data-nav=memory]")
            page.wait_for_selector(".memory")
            check(page.locator(".memory").count() == 2, "both memories are listed")
            page.click("button:has-text('Add a memory')")
            page.fill(".memory-form textarea", "Is left-handed.")
            page.select_option(".memory-form select", "personal")
            page.click(".memory-form button:has-text('Add memory')")
            page.wait_for_function("document.querySelectorAll('.memory').length === 3")
            page.locator(".memory", has_text="left-handed").locator("button[title^='Pin']").click()
            page.wait_for_selector(".memory.pinned")
            shot("07-memory")
            page.fill("input[aria-label='Search memory']", "left")
            page.wait_for_function("document.querySelectorAll('.memory').length === 1")
            check("left-handed" in page.inner_text(".memory"), "memory search finds the right entry")

            print("Restart: does it remember?")
            jarvis.terminate()
            jarvis.wait(timeout=15)
            jarvis = start_jarvis()
            page.goto(APP + "/#/")
            page.reload()
            page.wait_for_selector(".starters")
            check("3 memories on file" in page.inner_text(".welcome"), "memories survived the restart")
            check("Continue:" in page.inner_text(".welcome"), "JARVIS offers to pick up the last conversation")
            check(page.locator(".conv").count() == 2, "conversations survived the restart")
            shot("08-after-restart")
            send(page, "What do you know about me?")
            reply = last_turn(page).inner_text()
            check(all(word in reply for word in ("chemistry", "left-handed", "worked solutions")), "after a restart JARVIS recalls what it was told, learned and given")

            print("Rate limits and fallback")
            send(page, "rate limit test please")
            check("gpt-oss-20b" in last_turn(page).locator(".meta").inner_text(), "when the first model is rate-limited the next one answers")
            page.click(".rail-item[data-nav=settings]")
            page.wait_for_selector(".page h2:has-text('System status')")
            check("Resting" in page.inner_text(".model-list"), "the rate-limited model is shown as resting")
            check("Left today" in page.inner_text(".model-list"), "remaining allowance from the provider is shown")
            page.click("button:has-text('Test models now')")
            page.wait_for_selector(".result-list .badge")
            shot("09-status")

            print("Activity log")
            page.click(".rail-item[data-nav=activity]")
            page.wait_for_selector(".log-item")
            log_text = page.inner_text(".log")
            check("Learned:" in log_text and "Declined by you" in log_text and "Approved by you" in log_text, "the log records learning, approvals and refusals")
            shot("10-activity")

            print("Conversation tools")
            page.click(".rail-item[data-nav=chat]")
            page.fill("#searchInput", "formatting")
            page.wait_for_function("document.querySelectorAll('.conv').length === 1")
            page.click(".conv-open")
            page.wait_for_selector(".turn.user")
            check(page.locator(".step").count() >= 3, "tool steps are shown again when a conversation is reopened")
            count = page.locator(".turn.assistant").count()
            before = finished(page)
            last_turn(page).locator("button[title='Try again']").click()
            page.wait_for_function("n => document.querySelectorAll('.turn.assistant .meta .turn-actions').length >= n", arg=before, timeout=30000)
            page.wait_for_timeout(300)
            check(page.locator(".turn.assistant").count() == count, "try again replaces the last reply")
            status = page.evaluate("fetch('/api/bootstrap').then(r => r.status)")
            check(status == 401, "the API rejects requests that don't carry the session token")

            print("Telegram phone link: setup, owner chat, and approval buttons")
            page.click(".rail-item[data-nav=settings]")
            page.wait_for_selector("input[aria-label='Telegram bot token']")
            phone_section = page.locator(".section", has=page.locator("input[aria-label='Telegram bot token']"))
            token_input = page.locator("input[aria-label='Telegram bot token']")
            check(token_input.get_attribute("type") == "password", "the Telegram token entry is masked")
            token_input.fill("654321:rejected_telegram_token_1234567890")
            page.get_by_role("button", name="Connect bot", exact=True).click()
            page.wait_for_selector(".toast.error:has-text('rejected')")
            check("TELEGRAM_BOT_TOKEN=" not in (RUN / ".env").read_text(), "a rejected Telegram token is not saved")
            token_input.fill(TELEGRAM_TOKEN)
            page.get_by_role("button", name="Connect bot", exact=True).click()
            page.wait_for_selector(".pairing-code")
            check(token_input.input_value() == "" and "7890" in token_input.get_attribute("placeholder"), "connected bot shows only the token ending")
            check("not end-to-end encrypted" in page.inner_text(".page"), "phone setup explains Telegram privacy and the running-PC requirement")
            code = page.inner_text(".pairing-code")
            telegram_message(code)
            page.wait_for_selector(".phone-state strong:has-text('Phone linked')", timeout=15000)
            check(not page.locator(".pairing-code").count(), "successful pairing hides the pairing code")
            page.get_by_role("button", name="Send test message", exact=True).click()
            wait_telegram(lambda rows: any("Systems online" in row["body"].get("text", "") for row in rows))
            check(True, "the Phone test button sends through the real HTTP client to the Telegram stand-in")
            shot("13-phone-linked")
            before_stranger = len(telegram_seen())
            telegram_message("Open everything", owner=99)
            time.sleep(0.6)
            check(len(telegram_seen()) == before_stranger, "an unpaired stranger is silently ignored")
            telegram_message("What do you know about me?")
            wait_telegram(lambda rows: any(all(word in row["body"].get("text", "") for word in ("chemistry", "left-handed", "worked solutions")) for row in rows))
            check(True, "a Telegram reply uses the same saved memories")
            if MARKER.exists():
                MARKER.unlink()
            telegram_message("open e2e-marker-app")
            approval = wait_telegram(lambda rows: next((row["body"] for row in reversed(rows) if "reply_markup" in row["body"]), None))
            check(not MARKER.exists(), "a phone action waits for its inline approval button")
            callback_data = approval["reply_markup"]["inline_keyboard"][0][0]["callback_data"]
            # The mock gives monotonically increasing ids to every successful sendMessage.
            approval_message_id = sum(row["method"] == "sendMessage" for row in telegram_seen())
            telegram_update({"callback_query": {"id": "e2e-approval", "from": {"id": 42}, "data": callback_data, "message": {"message_id": approval_message_id, "chat": {"id": 42, "type": "private"}}}})
            wait_telegram(lambda rows: any(row["method"] == "editMessageText" and row["body"].get("text") == "Allowed." for row in rows))
            wait_telegram(lambda rows: MARKER.exists())
            check(MARKER.exists(), "the Telegram approval button releases the real marker-program launch")
            telegram_message("/new")
            wait_telegram(lambda rows: any("Fresh conversation" in row["body"].get("text", "") for row in rows))
            check(True, "/new starts a fresh Telegram conversation")
            page.goto(APP + "/#/")
            page.reload()
            page.wait_for_selector(".conv-open:has-text('📱')")
            check(page.locator(".conv-open:has-text('📱')").count() == 1, "Telegram conversations appear with a phone icon in the PC sidebar")
            page.locator(".conv-open:has-text('📱')").click()
            page.wait_for_selector(".turn.user")
            shot("14-phone-conversation")

            print("Mobile layout")
            phone = browser.new_page(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            phone.on("pageerror", lambda e: errors.append(f"mobile pageerror: {e}"))
            phone.goto(page.url)
            phone.wait_for_selector(".turn.user")
            phone.screenshot(path=str(SHOTS / "11-mobile-chat.png"))
            phone.goto(APP + "/#/memory")
            phone.wait_for_selector(".memory")
            phone.screenshot(path=str(SHOTS / "12-mobile-memory.png"))
            overflow = phone.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
            check(not overflow, "no sideways scrolling on a phone-sized screen")
            browser.close()
        check(not errors, f"no browser errors or warnings ({errors[:3]})")
    finally:
        jarvis.terminate()
        mock.terminate()
        telegram.terminate()
        jarvis.wait(timeout=15)
        mock.wait(timeout=15)
        telegram.wait(timeout=15)
    print(f"\n{len(passed)} checks passed. Screenshots: {SHOTS}")


if __name__ == "__main__":
    main()
