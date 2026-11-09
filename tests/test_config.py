from pathlib import Path

import pytest

from jarvis.config import Settings, parse_model_list


def test_parse_model_list_basic():
    specs = parse_model_list("groq:openai/gpt-oss-120b, gemini:gemini-3.8-flash")
    assert [s.label for s in specs] == ["groq:openai/gpt-oss-120b", "gemini:gemini-3.8-flash"]


def test_parse_model_list_keeps_colons_in_model_ids():
    (spec,) = parse_model_list("openrouter:openai/gpt-oss-120b:free")
    assert spec.provider == "openrouter"
    assert spec.model == "openai/gpt-oss-120b:free"


def test_parse_model_list_ignores_blanks_and_normalises_provider():
    specs = parse_model_list(" , GROQ:llama-3.1-8b-instant ,, ")
    assert [s.label for s in specs] == ["groq:llama-3.1-8b-instant"]


@pytest.mark.parametrize("bad", ["groq", "groq:", ":model"])
def test_parse_model_list_rejects_bad_entries(bad):
    with pytest.raises(ValueError):
        parse_model_list(bad)


def test_from_env_reads_keys_and_defaults(tmp_path: Path, monkeypatch):
    # delenv records each variable so monkeypatch restores it after load_dotenv sets it.
    for name in ("GROQ_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY", "JARVIS_MODELS",
                 "JARVIS_PORT", "JARVIS_USER_TITLE"):
        monkeypatch.delenv(name, raising=False)
    env_file = tmp_path / ".env"
    env_file.write_text("GROQ_API_KEY=abc123\nJARVIS_PORT=9001\nJARVIS_USER_TITLE=\n")
    monkeypatch.chdir(tmp_path)
    settings = Settings.from_env(env_file)
    assert settings.api_keys == {"GROQ_API_KEY": "abc123"}
    assert settings.port == 9001
    assert settings.host == "127.0.0.1"
    assert settings.models[0].label == "groq:openai/gpt-oss-120b"
    assert settings.db_path == Path.cwd() / "data" / "jarvis.db"
    assert settings.user_title == ""
