def test_transcribe_route_passes_audio_to_runtime(client):
    seen = {}

    async def fake_transcribe(audio: bytes, filename: str, content_type: str) -> str:
        seen.update(audio=audio, filename=filename, content_type=content_type)
        return "remember this"

    client.runtime.transcribe_audio = fake_transcribe
    response = client.post(
        "/api/transcribe",
        content=b"fake audio",
        headers={"Content-Type": "audio/webm", "X-Jarvis-Filename": "voice.webm"},
    )

    assert response.status_code == 200
    assert response.json() == {"text": "remember this"}
    assert seen == {"audio": b"fake audio", "filename": "voice.webm", "content_type": "audio/webm"}


def test_transcribe_rejects_empty_audio(client):
    async def fake_transcribe(audio: bytes, filename: str, content_type: str) -> str:
        raise ValueError("The recording was empty.")

    client.runtime.transcribe_audio = fake_transcribe
    response = client.post("/api/transcribe", content=b"", headers={"Content-Type": "audio/webm"})

    assert response.status_code == 422
    assert response.json()["detail"] == "The recording was empty."
