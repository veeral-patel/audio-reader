from __future__ import annotations

from cartesia_tts import (
    MAX_CHARS_PER_CHUNK,
    TTSConfig,
    build_payload,
    pcm16_to_wav_bytes,
    split_transcript,
)


def test_build_payload_basic() -> None:
    config = TTSConfig(
        api_key="key",
        version="2025-04-16",
        model_id="model",
        voice_id="voice",
        sample_rate=44100,
    )
    payload = build_payload(config, "hello", "ctx", continue_flag=False)
    assert payload["model_id"] == "model"
    assert payload["voice"]["id"] == "voice"
    assert payload["output_format"]["sample_rate"] == 44100
    assert payload["context_id"] == "ctx"
    assert payload["continue"] is False


def test_split_transcript_respects_max_chars() -> None:
    text = "Sentence one. Sentence two. Sentence three."
    chunks = split_transcript(text, max_chars=12)
    assert chunks
    assert all(len(chunk) <= 12 for chunk in chunks)


def test_pcm16_to_wav_bytes_trims_odd_length() -> None:
    pcm = b"\x01\x00\x02"  # odd length
    wav_bytes = pcm16_to_wav_bytes(pcm, 16000)
    assert wav_bytes[:4] == b"RIFF"
    assert len(wav_bytes) > 44


def test_default_max_chars_constant() -> None:
    text = "A. " * (MAX_CHARS_PER_CHUNK // 2)
    chunks = split_transcript(text)
    assert chunks
    assert all(len(chunk) <= MAX_CHARS_PER_CHUNK for chunk in chunks)
