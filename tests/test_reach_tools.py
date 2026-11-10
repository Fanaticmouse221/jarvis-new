from __future__ import annotations

import asyncio
import os
import zipfile
from pathlib import Path

import httpx
import pytest

from jarvis.tools.base import ToolContext, ToolError
from jarvis.tools import file_tools as files, system_tools as systems, utility_tools as utilities, web_tools as web


@pytest.fixture
def ctx(runtime):
    runtime.settings.workspace.mkdir(parents=True, exist_ok=True)
    return ToolContext(None, "test", {"settings": runtime.settings, "prefs": runtime.prefs})


@pytest.mark.parametrize(("expression", "expected"), [
    ("2 + 3 * 4", 14), ("sqrt(81)", 9), ("sin(pi / 2)", 1),
    ("round(10 / 3, 2)", 3.33), ("2**10", 1024), ("-5 % 3", 1),
])
def test_calculator(expression, expected):
    assert utilities.evaluate(expression) == pytest.approx(expected)


@pytest.mark.parametrize("expression", [
    "__import__('os').system('anything')", "(1).__class__", "[1][0]", "True", "2**1000000",
    "9**9**9", "sqrt(-1)", "1/0", "exp(999999)", "1e999", "round(1, 1e100)", "sum([1,2])",
])
def test_calculator_refuses_code_or_unbounded_work(expression):
    with pytest.raises(ToolError):
        utilities.evaluate(expression)


def test_pc_controls_are_injected_and_report_limits(ctx):
    calls = []

    class Controller:
        def perform(self, action, value):
            calls.append((action, value))

    ctx.services["pc_controller"] = Controller()
    result = asyncio.run(utilities.pc_control({"action": "set_volume", "value": 35}, ctx))
    assert calls == [("set_volume", 35)]
    assert "cannot read the level back" in result.text
    with pytest.raises(ToolError):
        asyncio.run(utilities.pc_control({"action": "set_volume"}, ctx))


@pytest.mark.parametrize("path", ["../outside.txt", ".env", ".env.local", ".git/config", ".ssh/id_ed25519", "server.key", "api_keys.json", "credentials.json", "note.txt:hidden", "//server/share/a.txt", "CON.txt", "NUL", "COM1.log"])
def test_files_refuse_escapes_and_secrets(ctx, path):
    with pytest.raises(ToolError):
        files.approved_path(path, ctx)


def test_file_creation_append_and_overwrite(ctx):
    workspace = ctx.services["settings"].workspace
    asyncio.run(files.write_file({"path": "note.txt", "content": "hello", "mode": "create"}, ctx))
    with pytest.raises(ToolError, match="already exists"):
        asyncio.run(files.write_file({"path": "note.txt", "content": "destroy", "mode": "create"}, ctx))
    assert (workspace / "note.txt").read_text() == "hello"
    asyncio.run(files.write_file({"path": "note.txt", "content": " world", "mode": "append"}, ctx))
    assert (workspace / "note.txt").read_text() == "hello world"
    assert files.write_risk({"mode": "overwrite"}, ctx) == "sensitive"
    assert files.write_risk({"mode": "create"}, ctx) == "act"
    asyncio.run(files.write_file({"path": "note.txt", "content": "replacement", "mode": "overwrite"}, ctx))
    assert (workspace / "note.txt").read_text() == "replacement"


def test_move_and_delete_files_are_bounded_to_approved_roots(ctx, tmp_path):
    workspace = ctx.services["settings"].workspace
    destination = workspace / "archive"
    destination.mkdir()
    source = workspace / "move-me.txt"
    source.write_text("hello", encoding="utf-8")
    moved = asyncio.run(files.move_file({"source": "move-me.txt", "destination": str(destination / "moved.txt")}, ctx))
    assert moved.ok and not source.exists() and (destination / "moved.txt").read_text() == "hello"
    deleted = asyncio.run(files.delete_file({"path": str(destination / "moved.txt")}, ctx))
    assert deleted.ok and not (destination / "moved.txt").exists()
    outside = tmp_path / "outside.txt"
    outside.write_text("private", encoding="utf-8")
    with pytest.raises(ToolError):
        asyncio.run(files.delete_file({"path": str(outside)}, ctx))
    with pytest.raises(ToolError):
        asyncio.run(files.move_file({"source": "missing.txt", "destination": str(destination / "x.txt")}, ctx))


def test_close_app_uses_injected_launcher(ctx):
    launcher = ctx.services["launcher"] = type("Launcher", (), {
        "find": lambda self, name: ({"name": "Notepad", "id": "notepad"}, []),
        "close": lambda self, app: ["notepad.exe"],
    })()
    result = asyncio.run(systems.close_app({"name": "Notepad"}, ctx))
    assert result.ok and "Closed Notepad" in result.text


def test_process_matching_requires_a_distinctive_name_boundary():
    assert systems._process_matches("Code.exe", {"code"})
    assert systems._process_matches("msedge.exe", {"edge"})
    assert not systems._process_matches("decoder.exe", {"code"})
    assert not systems._process_matches("app.exe", {"app"})


def test_file_reads_are_paginated_and_untrusted(ctx):
    workspace = ctx.services["settings"].workspace
    (workspace / "long.txt").write_text("A" * 2600 + "ENDING", encoding="utf-8")
    first = asyncio.run(files.read_file({"path": "long.txt"}, ctx))
    second = asyncio.run(files.read_file({"path": "long.txt", "offset": 2600}, ctx))
    assert len(first.text) <= 2800 and "Continue at offset 2600" in first.text
    assert second.text == "ENDING" and first.untrusted
    with pytest.raises(ToolError):
        asyncio.run(files.read_file({"path": "long.txt", "offset": -1}, ctx))


def test_file_listing_roots_filter_and_secrets(ctx, tmp_path):
    workspace = ctx.services["settings"].workspace
    for name in ("note.txt", "report.txt", ".env", "server.key"):
        (workspace / name).write_text("text")
    assert str(workspace) in asyncio.run(files.list_files({}, ctx)).text
    listing = asyncio.run(files.list_files({"folder": str(workspace)}, ctx))
    assert "note.txt" in listing.text and ".env" not in listing.text and "server.key" not in listing.text
    assert "report.txt" not in asyncio.run(files.list_files({"folder": str(workspace), "search": "note"}, ctx)).text
    extra = tmp_path / "approved"
    extra.mkdir()
    ctx.services["prefs"].update({"allowed_folders": [str(extra)]})
    assert files.approved_path(str(extra / "school.txt"), ctx).parent == extra


def test_files_refuse_symlink_and_hardlink_escape(ctx, tmp_path):
    workspace = ctx.services["settings"].workspace
    outside = tmp_path / "outside.txt"
    outside.write_text("private")
    linked = workspace / "link.txt"
    try:
        linked.symlink_to(outside)
    except OSError:
        pass  # Windows without developer mode still exercises hard-link protection below.
    else:
        with pytest.raises(ToolError):
            files.approved_path(str(linked), ctx)
    alias = workspace / "alias.txt"
    os.link(outside, alias)
    with pytest.raises(ToolError, match="hard links"):
        files.approved_path(str(alias), ctx)


@pytest.mark.parametrize("suffix, member, content", [
    (".docx", "word/document.xml", '<w:document xmlns:w="word"><w:p><w:r><w:t>School report</w:t></w:r></w:p></w:document>'),
    (".pptx", "ppt/slides/slide1.xml", '<p:sld xmlns:p="slide" xmlns:a="drawing"><a:p><a:r><a:t>First slide</a:t></a:r></a:p></p:sld>'),
])
def test_office_text(ctx, suffix, member, content):
    path = ctx.services["settings"].workspace / ("document" + suffix)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(member, content)
    assert asyncio.run(files.read_file({"path": str(path)}, ctx)).text in ("School report", "First slide")


def test_office_rejects_entity_declarations(ctx):
    path = ctx.services["settings"].workspace / "document.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", '<!DOCTYPE x [<!ENTITY y "boom">]><x>&y;</x>')
    with pytest.raises(ToolError, match="XML"):
        asyncio.run(files.read_file({"path": str(path)}, ctx))


def test_pdf_text_and_blank_page(ctx):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 20 100 Td (A real PDF sentence) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
    path = ctx.services["settings"].workspace / "report.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    assert "A real PDF sentence" in asyncio.run(files.read_file({"path": str(path)}, ctx)).text
    blank = PdfWriter()
    blank.add_blank_page(width=200, height=200)
    with path.open("wb") as handle:
        blank.write(handle)
    assert "OCR" in asyncio.run(files.read_file({"path": str(path)}, ctx)).text


def test_unsupported_and_oversized_files(ctx):
    workspace = ctx.services["settings"].workspace
    (workspace / "binary.exe").write_bytes(b"hello")
    with pytest.raises(ToolError, match="Supported files"):
        asyncio.run(files.read_file({"path": "binary.exe"}, ctx))
    (workspace / "huge.txt").write_bytes(b"x" * (files.MAX_BYTES + 1))
    with pytest.raises(ToolError, match="5 MB"):
        asyncio.run(files.read_file({"path": "huge.txt"}, ctx))
    (workspace / "binary.txt").write_bytes(b"a\x00b")
    with pytest.raises(ToolError, match="binary"):
        asyncio.run(files.read_file({"path": "binary.txt"}, ctx))


def test_pdf_decompression_is_bounded(ctx):
    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

    writer = PdfWriter()
    page = writer.add_blank_page(width=200, height=200)
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(b" " * 4_000_001)
    page[NameObject("/Contents")] = writer._add_object(stream.flate_encode())
    path = ctx.services["settings"].workspace / "compressed.pdf"
    with path.open("wb") as handle:
        writer.write(handle)
    assert path.stat().st_size < 10_000
    with pytest.raises(ToolError, match="safe reading limits"):
        asyncio.run(files.read_file({"path": str(path)}, ctx))


def test_open_file_uses_injected_opener_and_refuses_programs(ctx):
    workspace = ctx.services["settings"].workspace
    (workspace / "note.txt").write_text("hello")
    (workspace / "script.py").write_text("raise SystemExit")
    opened = []
    ctx.services["open_file"] = opened.append
    result = asyncio.run(files.open_file({"path": "note.txt"}, ctx))
    assert opened == [str(workspace / "note.txt")] and "could not be confirmed" in result.text
    with pytest.raises(ToolError, match="scripts"):
        asyncio.run(files.open_file({"path": "script.py"}, ctx))


@pytest.mark.parametrize("address", ["127.0.0.1", "10.0.0.1", "169.254.169.254", "192.168.1.1", "100.64.0.1", "0.0.0.0", "224.0.0.1", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1", "2002:7f00:1::"])
def test_page_reader_rejects_non_public_addresses(ctx, address):
    ctx.services["page_resolver"] = lambda *_: [address]
    with pytest.raises(ToolError, match="blocks"):
        asyncio.run(web.pinned_url("https://example.org", ctx))


@pytest.mark.parametrize("url", ["file:///etc/passwd", "ftp://example.org", "https://user:password@example.org", "http://"])
def test_page_reader_refuses_non_web_urls(ctx, url):
    with pytest.raises(ToolError):
        asyncio.run(web.pinned_url(url, ctx))


def test_page_reader_pins_dns_and_removes_active_html(ctx):
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, text="<h1>Title</h1><script>steal()</script><p>School notes about cricket.</p><p>Other subject.</p>", headers={"Content-Type": "text/html"})

    ctx.services.update(page_resolver=lambda *_: ["93.184.216.34"], web_transport=httpx.MockTransport(respond))
    result = asyncio.run(web.read_page({"url": "https://example.org/notes", "focus": "cricket"}, ctx))
    assert requests[0].url.host == "93.184.216.34"
    assert requests[0].headers["host"] == "example.org"
    assert requests[0].extensions["sni_hostname"] == "example.org"
    assert "cricket" in result.text and "steal" not in result.text and "Other subject" not in result.text
    assert result.untrusted and len(result.text) <= 2800


def test_redirect_hop_cannot_target_localhost(ctx):
    requests = []

    def resolve(host, port):
        return ["127.0.0.1"] if host == "localhost" else ["93.184.216.34"]

    def respond(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "http://localhost/private"})

    ctx.services.update(page_resolver=resolve, web_transport=httpx.MockTransport(respond))
    with pytest.raises(ToolError, match="blocks"):
        asyncio.run(web.read_page({"url": "https://example.org"}, ctx))
    assert len(requests) == 1


def test_mixed_dns_answers_are_refused(ctx):
    ctx.services["page_resolver"] = lambda *_: ["93.184.216.34", "127.0.0.1"]
    with pytest.raises(ToolError, match="blocks"):
        asyncio.run(web.pinned_url("https://example.org", ctx))


@pytest.mark.parametrize("headers, body", [
    ({"Content-Type": "text/plain", "Content-Length": str(web.MAX_PAGE_BYTES + 1)}, b"x"),
    ({"Content-Type": "text/plain"}, b"x" * (web.MAX_PAGE_BYTES + 1)),
    ({"Content-Type": "application/octet-stream"}, b"binary"),
])
def test_page_reader_size_and_type_bounds(ctx, headers, body):
    ctx.services.update(page_resolver=lambda *_: ["93.184.216.34"],
                        web_transport=httpx.MockTransport(lambda request: httpx.Response(200, content=body, headers=headers)))
    with pytest.raises(ToolError):
        asyncio.run(web.read_page({"url": "https://example.org"}, ctx))


def test_web_search_is_bounded_and_preserves_sources(ctx):
    ctx.services["web_search"] = lambda query: [{"title": "Cricket " + str(i), "href": f"https://example.org/{i}", "body": "details " * 100} for i in range(5)]
    result = asyncio.run(web.web_search({"query": "cricket"}, ctx))
    assert result.untrusted and len(result.text) <= 900
    assert all(f"https://example.org/{i}" in result.text for i in range(5))


def test_weather_uses_home_city_and_returns_source(ctx):
    ctx.services["prefs"]._defaults["home_city"] = "Brisbane"
    requests = []

    def respond(request):
        requests.append(request)
        if "geocoding" in request.url.host:
            return httpx.Response(200, json={"results": [{"name": "Brisbane", "country": "Australia", "latitude": -27.47, "longitude": 153.03}]})
        return httpx.Response(200, json={"current": {"time": "2026-11-10T18:15", "temperature_2m": 25, "apparent_temperature": 26, "weather_code": 0, "wind_speed_10m": 10},
                                         "daily": {"temperature_2m_min": [20], "temperature_2m_max": [28], "precipitation_probability_max": [10]}})

    ctx.services["web_transport"] = httpx.MockTransport(respond)
    result = asyncio.run(web.get_weather({}, ctx))
    assert requests[0].url.params["name"] == "Brisbane"
    assert "6:15 PM" in result.text and "25 °C" in result.text and "Open-Meteo" in result.text
    assert "apikey" not in str(requests[1].url)


def test_weather_needs_a_place(ctx):
    ctx.services["prefs"]._defaults["home_city"] = ""
    with pytest.raises(ToolError, match="home city"):
        asyncio.run(web.get_weather({}, ctx))
