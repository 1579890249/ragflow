import importlib.util
import os
from pathlib import Path

import pytest


module_path = Path(__file__).resolve().parents[4] / "rag" / "llm" / "sequence2txt_model.py"
spec = importlib.util.spec_from_file_location("sequence2txt_model_for_test", module_path)
sequence2txt_model = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sequence2txt_model)
GPUStackSeq2txt = sequence2txt_model.GPUStackSeq2txt


@pytest.mark.parametrize(
    ("base_url", "expected_url"),
    [
        ("http://example.test", "http://example.test/v1"),
        ("http://example.test/v1", "http://example.test/v1"),
        ("http://example.test/v1/", "http://example.test/v1"),
    ],
)
def test_gpustack_transcription_normalizes_base_url(base_url, expected_url):
    model = GPUStackSeq2txt("api-key", "whisper", base_url=base_url)

    assert model.base_url == expected_url


def test_gpustack_transcription_posts_to_normalized_endpoint(monkeypatch, tmp_path):
    requested_urls = []

    class Response:
        @staticmethod
        def raise_for_status():
            return None

        @staticmethod
        def json():
            return {"text": "transcript"}

    def post(url, **kwargs):
        requested_urls.append(url)
        return Response()

    monkeypatch.setattr(sequence2txt_model.requests, "post", post)
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"audio")

    model = GPUStackSeq2txt("api-key", "whisper", base_url="http://example.test/")
    text, _ = model.transcription(os.fspath(audio_path))

    assert requested_urls == ["http://example.test/v1/audio/transcriptions"]
    assert text == "transcript"
