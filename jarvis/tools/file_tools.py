"""Document access confined to the user's explicitly approved folders."""

from __future__ import annotations

import asyncio
import io
import os
import re
import shutil
import sys
import zipfile
from pathlib import Path, PureWindowsPath
from typing import Any
from xml.etree import ElementTree

from jarvis.tools.base import RISK_ACT, RISK_READ, RISK_SENSITIVE, Tool, ToolContext, ToolError, ToolResult, obj

MAX_BYTES = 5 * 1024 * 1024
MAX_TEXT = 1_000_000
PAGE_CHARS = 2600
TEXT_TYPES = {".txt", ".md", ".csv", ".tsv", ".json", ".xml", ".yaml", ".yml", ".log", ".rst", ".tex", ".py", ".js", ".css", ".html"}
DOCUMENT_TYPES = {".docx", ".pptx", ".pdf"}
OPEN_TYPES = {".txt", ".md", ".csv", ".tsv", ".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".webp"}
_PRIVATE_NAMES = {".git", ".ssh", ".aws", ".azure", ".gnupg", ".kube", "credentials", "credentials.json", "secrets", "secrets.json", "secrets.toml", "token.json", "tokens.json", "id_rsa", "id_ed25519", "id_ecdsa", "id_dsa"}
_PRIVATE_EXTENSIONS = {".pem", ".key", ".p12", ".pfx", ".kdbx", ".keystore"}


def _blocked(path: Path) -> bool:
    for part in path.parts:
        name = part.casefold().rstrip(". ")
        if PureWindowsPath(part).is_reserved():
            return True
        if name in _PRIVATE_NAMES or name.startswith(".env") or name.endswith(tuple(_PRIVATE_EXTENSIONS)):
            return True
        if re.search(r"(?:^|[_. -])(?:api[_-]?keys?|private[_-]?keys?|secrets?|credentials|passwords?|tokens?)(?:[_. -]|$)", name):
            return True
    return False


def roots(ctx: ToolContext) -> list[Path]:
    settings = ctx.services["settings"]
    prefs = ctx.services["prefs"].all()
    return list(dict.fromkeys(Path(p).expanduser().resolve() for p in [settings.workspace, *prefs.get("allowed_folders", [])]))


def approved_path(raw: str, ctx: ToolContext) -> Path:
    if not isinstance(raw, str) or not raw.strip() or "\x00" in raw:
        raise ToolError("Provide a file or folder path.")
    raw = raw.strip()
    # Reject Windows device paths, UNC shares, alternate streams and ambiguous names.
    if raw.startswith(("\\\\", "//")) or re.search(r":", raw[2:] if re.match(r"^[A-Za-z]:", raw) else raw):
        raise ToolError("Network paths, device paths and alternate file streams are not allowed.")
    supplied = Path(raw).expanduser()
    if _blocked(supplied):
        raise ToolError("Credentials, private keys and internal folders are not accessible.")
    allowed = roots(ctx)
    if not supplied.is_absolute():
        supplied = allowed[0] / supplied
    try:
        resolved = supplied.resolve()
    except (OSError, RuntimeError) as exc:
        raise ToolError("That path cannot be resolved safely.") from exc
    if _blocked(resolved) or not any(resolved.is_relative_to(root) for root in allowed):
        raise ToolError("That path is outside the approved folders, or contains protected files.")
    # Hard links can otherwise make a file outside a root writable through an inside alias.
    if resolved.is_file() and resolved.stat().st_nlink > 1:
        raise ToolError("Files with multiple hard links are not accessible.")
    return resolved


async def list_files(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if not args.get("folder"):
        allowed = roots(ctx)
        return ToolResult(True, "Approved folders:\n" + "\n".join(str(p) for p in allowed), data={"folders": [str(p) for p in allowed]})
    folder = approved_path(args["folder"], ctx)
    if not folder.is_dir():
        raise ToolError("That folder does not exist.")
    search = args.get("search", "").casefold()

    def collect() -> str:
        entries: list[str] = []
        # One directory per call: no unbounded recursive walks or hidden traversal.
        with os.scandir(folder) as children:
            for index, item in enumerate(children):
                if index >= 1000 or len(entries) >= 50:
                    entries.append("[More files exist; narrow the search.]")
                    break
                if search not in item.name.casefold():
                    continue
                try:
                    path = approved_path(str(folder / item.name), ctx)
                except (ToolError, OSError):
                    continue
                entries.append(("[folder] " if path.is_dir() else "") + item.name)
        return "\n".join(sorted(entries))[:2400] or "No matching files."

    return ToolResult(True, await asyncio.to_thread(collect), summary=f"Listed {folder.name}", untrusted=True)


def _office_text(data: bytes, suffix: str) -> str:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        infos = archive.infolist()
        if len(infos) > 1500 or sum(info.file_size for info in infos) > 20 * 1024 * 1024:
            raise ToolError("This document is too large to unpack safely.")
        names = (["word/document.xml"] if suffix == ".docx" else
                 sorted((i.filename for i in infos if re.fullmatch(r"ppt/slides/slide\d+\.xml", i.filename)),
                        key=lambda name: int(re.search(r"slide(\d+)", name).group(1))))
        if len(names) > 200:
            raise ToolError("This presentation has too many slides (limit 200).")
        chunks: list[str] = []
        for name in names:
            content = archive.read(name)
            if len(content) > 4 * 1024 * 1024 or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
                raise ToolError("This document contains unsupported or oversized XML.")
            root = ElementTree.fromstring(content)
            for paragraph in root.iter():
                if paragraph.tag.rsplit("}", 1)[-1] == "p":
                    chunks.append("".join(node.text or "" for node in paragraph.iter() if node.tag.rsplit("}", 1)[-1] == "t"))
            if sum(map(len, chunks)) > MAX_TEXT:
                raise ToolError("This document contains too much text (limit one million characters).")
        return "\n".join(chunks)


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader, apply_configuration
    from pypdf.errors import PyPdfError

    try:
        # Per-extraction limits, not process-wide changes. A tiny compressed PDF
        # can otherwise expand to hundreds of megabytes before text is bounded.
        with apply_configuration(
            maximum_declared_stream_length=MAX_BYTES,
            array_based_stream_maximum_output_length=4_000_000,
            zlib_maximum_output_length=4_000_000,
            lzw_maximum_output_length=4_000_000,
            run_length_maximum_output_length=4_000_000,
            brotli_maximum_output_length=4_000_000,
            stream_decoding_work_maximum_length=16_000_000,
            stream_parsing_work_maximum_count=100_000,
            page_tree_maximum_entries=500,
            xform_maximum_invocations_per_extraction=100,
            jbig2dec_binary=None,
        ):
            reader = PdfReader(io.BytesIO(data), root_object_recovery_limit=1000)
            if reader.is_encrypted:
                raise ToolError("Password-protected PDFs are not supported.")
            if len(reader.pages) > 100:
                raise ToolError("PDF is too long (limit 100 pages).")
            chunks = []
            for page in reader.pages:
                chunks.append(page.extract_text() or "")
                if sum(map(len, chunks)) > MAX_TEXT:
                    raise ToolError("PDF contains too much text.")
            return "\n".join(chunks)
    except PyPdfError as exc:
        raise ToolError("This PDF is malformed, unsupported or exceeds safe reading limits.") from exc


def extract_text(path: Path) -> str:
    if path.suffix.casefold() not in TEXT_TYPES | DOCUMENT_TYPES:
        raise ToolError("Supported files: text, .docx, .pptx and .pdf. Other formats cannot be read yet.")
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ToolError("File is too large (limit 5 MB).")
    suffix = path.suffix.casefold()
    try:
        if suffix in (".docx", ".pptx"):
            text = _office_text(data, suffix)
        elif suffix == ".pdf":
            text = _pdf_text(data)
        else:
            encoding = "utf-16" if data.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
            text = data.decode(encoding)
            if "\x00" in text:
                raise ToolError("This appears to be a binary file, not text.")
    except ToolError:
        raise
    except (UnicodeError, ValueError, OSError, KeyError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
        raise ToolError("The file could not be read as a supported text document.") from exc
    if len(text) > MAX_TEXT:
        raise ToolError("File contains too much text (limit one million characters).")
    return text


async def read_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = approved_path(args["path"], ctx)
    if not path.is_file():
        raise ToolError("That file does not exist.")
    offset = args.get("offset", 0)
    if type(offset) is not int or offset < 0:
        raise ToolError("Offset must be a non-negative whole number.")
    text = await asyncio.to_thread(extract_text, path)
    body = text[offset:offset + PAGE_CHARS]
    if not text.strip():
        body = "No text could be extracted. Scanned pages and images need OCR, which is not supported yet."
    elif offset >= len(text):
        body = "End of file."
    elif offset + PAGE_CHARS < len(text):
        body += f"\n[Continue at offset {offset + PAGE_CHARS}.]"
    return ToolResult(True, body, summary=f"Read {path.name}", untrusted=True)


def write_risk(args: dict[str, Any], ctx: ToolContext) -> str:
    return RISK_SENSITIVE if args.get("mode") == "overwrite" else RISK_ACT


async def write_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = approved_path(args["path"], ctx)
    mode = args.get("mode", "create")
    if mode not in ("create", "append", "overwrite"):
        raise ToolError("Mode must be create, append or overwrite.")
    if path.suffix.casefold() not in TEXT_TYPES:
        raise ToolError("Only text files can be written. Word, PowerPoint and PDF creation are not supported yet.")
    content = args["content"]
    if not isinstance(content, str) or len(content) > 20_000 or "\x00" in content:
        raise ToolError("Content must be text of at most 20,000 characters.")
    if not path.parent.is_dir():
        # Only the built-in workspace is created automatically; no broad mkdir trees.
        if path.parent == roots(ctx)[0]:
            path.parent.mkdir(parents=True, exist_ok=True)
        else:
            raise ToolError("The parent folder must already exist.")

    def write() -> None:
        approved_path(str(path), ctx)  # recheck immediately before opening
        try:
            with path.open({"create": "x", "append": "a", "overwrite": "w"}[mode], encoding="utf-8", newline="") as handle:
                handle.write(content)
        except FileExistsError as exc:
            raise ToolError("That file already exists. Use overwrite, which always asks for approval, or append.") from exc
        except OSError as exc:
            raise ToolError(f"Windows could not write the file: {exc.strerror or 'access denied'}.") from exc

    await asyncio.to_thread(write)
    return ToolResult(True, f"Saved {len(content)} characters to {path} ({mode}).", summary=f"Saved {path.name}")


async def open_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = approved_path(args["path"], ctx)
    if not path.is_file():
        raise ToolError("That file does not exist.")
    if path.suffix.casefold() not in OPEN_TYPES:
        raise ToolError("Only documents and images can be opened; scripts, shortcuts and programs are not allowed.")
    opener = ctx.services.get("open_file")
    if opener is None:
        if sys.platform != "win32":
            raise ToolError("Opening files is only available on Windows.")
        opener = os.startfile
    await asyncio.to_thread(opener, str(path))
    return ToolResult(True, f"Asked Windows to open {path.name}; the application opening could not be confirmed.")


async def move_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    source = approved_path(args["source"], ctx)
    destination = approved_path(args["destination"], ctx)
    if not source.is_file():
        raise ToolError("The source file does not exist.")
    if destination.exists():
        raise ToolError("The destination already exists; move it somewhere else first.")
    if not destination.parent.is_dir():
        raise ToolError("The destination folder does not exist.")

    def move() -> None:
        approved_path(str(source), ctx)
        approved_path(str(destination), ctx)
        try:
            shutil.move(str(source), str(destination))
        except OSError as exc:
            raise ToolError(f"Windows could not move the file: {exc.strerror or exc}.") from exc

    await asyncio.to_thread(move)
    return ToolResult(True, f"Moved {source.name} to {destination}.", summary=f"Moved {source.name}")


async def delete_file(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    path = approved_path(args["path"], ctx)
    if not path.is_file():
        raise ToolError("That file does not exist.")

    def remove() -> None:
        approved_path(str(path), ctx)
        try:
            path.unlink()
        except OSError as exc:
            raise ToolError(f"Windows could not delete the file: {exc.strerror or exc}.") from exc

    await asyncio.to_thread(remove)
    return ToolResult(True, f"Deleted {path.name}.", summary=f"Deleted {path.name}")


_PATH = {"type": "string", "maxLength": 500}
TOOLS = [
    Tool("list_files", "files", "List files", "List an approved folder; omit folder to see roots. Search matches names.",
         obj({"folder": _PATH, "search": {"type": "string", "maxLength": 100}}), RISK_READ, list_files,
         lambda a: "List approved files", untrusted_output=True),
    Tool("read_file", "files", "Read a file", "Read text, Word, PowerPoint or PDF in approved folders; paginate with offset.",
         obj({"path": _PATH, "offset": {"type": "integer", "minimum": 0}}, ["path"]), RISK_READ, read_file,
         lambda a: f"Read {a.get('path', 'file')}", untrusted_output=True),
    Tool("write_file", "files", "Write a file", "Write a text file in approved folders. Overwrite always requires approval.",
         obj({"path": _PATH, "content": {"type": "string", "maxLength": 20_000, "preserveWhitespace": True},
              "mode": {"type": "string", "enum": ["create", "append", "overwrite"]}}, ["path", "content", "mode"]),
         RISK_ACT, write_file, lambda a: f"{a.get('mode', 'create').title()} {a.get('path', 'file')}", risk_for=write_risk),
    Tool("open_file", "files", "Open a file", "Open an approved document or image in its Windows app.",
         obj({"path": _PATH}, ["path"]), RISK_ACT, open_file, lambda a: f"Open {a.get('path', 'file')}"),
    Tool("move_file", "files", "Move a file", "Move an approved file to another approved folder. Never overwrites an existing destination.",
         obj({"source": _PATH, "destination": _PATH}, ["source", "destination"]), RISK_SENSITIVE, move_file,
         lambda a: f"Move {a.get('source', 'file')} to {a.get('destination', 'folder')}"),
    Tool("delete_file", "files", "Delete a file", "Delete one approved file. Folders and protected files are never deleted.",
         obj({"path": _PATH}, ["path"]), RISK_SENSITIVE, delete_file,
         lambda a: f"Delete {a.get('path', 'file')}"),
]
