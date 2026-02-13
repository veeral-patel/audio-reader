from __future__ import annotations

import asyncio
import base64
import io
import json
import queue
import threading
import uuid
import wave
from dataclasses import dataclass
from typing import Iterable, List

import websockets


@dataclass(frozen=True)
class TTSConfig:
    api_key: str
    version: str
    model_id: str
    voice_id: str
    sample_rate: int
    language: str = "en"


class CartesiaStreamer:
    def __init__(
        self,
        config: TTSConfig,
        audio_queue: queue.Queue,
        status_queue: queue.Queue,
        stop_event: threading.Event,
    ) -> None:
        self._config = config
        self._audio_queue = audio_queue
        self._status_queue = status_queue
        self._stop_event = stop_event

    def start(self, text: str) -> threading.Thread:
        thread = threading.Thread(target=self._run, args=(text,), daemon=True)
        thread.start()
        return thread

    def _run(self, text: str) -> None:
        asyncio.run(self._stream(text))

    async def _stream(self, text: str) -> None:
        url = (
            "wss://api.cartesia.ai/tts/websocket"
            f"?api_key={self._config.api_key}"
            f"&cartesia_version={self._config.version}"
        )
        context_id = str(uuid.uuid4())
        min_chunk_bytes = int(self._config.sample_rate * 2 * 1.0)
        pcm_buffer = bytearray()

        try:
            async with websockets.connect(url, max_size=8 * 1024 * 1024) as ws:
                chunks = split_transcript(text, max_chars=900)
                for idx, chunk in enumerate(chunks):
                    if self._stop_event.is_set():
                        await ws.send(
                            json.dumps({"context_id": context_id, "cancel": True})
                        )
                        self._status_queue.put("stopped")
                        return

                    payload = {
                        "model_id": self._config.model_id,
                        "transcript": chunk + (" " if idx < len(chunks) - 1 else ""),
                        "voice": {"mode": "id", "id": self._config.voice_id},
                        "language": self._config.language,
                        "context_id": context_id,
                        "output_format": {
                            "container": "raw",
                            "encoding": "pcm_s16le",
                            "sample_rate": self._config.sample_rate,
                        },
                        "add_timestamps": False,
                        "continue": idx < len(chunks) - 1,
                    }
                    await ws.send(json.dumps(payload))

                while True:
                    if self._stop_event.is_set():
                        await ws.send(
                            json.dumps({"context_id": context_id, "cancel": True})
                        )
                        self._status_queue.put("stopped")
                        break

                    raw = await ws.recv()
                    data = json.loads(raw)
                    msg_type = data.get("type")

                    if msg_type == "chunk":
                        pcm = base64.b64decode(data.get("data", ""))
                        if pcm:
                            pcm_buffer.extend(pcm)
                        if len(pcm_buffer) >= min_chunk_bytes:
                            self._enqueue_pcm(bytes(pcm_buffer))
                            pcm_buffer.clear()
                    elif msg_type == "done":
                        if pcm_buffer:
                            self._enqueue_pcm(bytes(pcm_buffer))
                            pcm_buffer.clear()
                        self._status_queue.put("done")
                        break
                    elif msg_type == "error":
                        self._status_queue.put(data.get("error", "error"))
                        break
        except Exception as exc:
            self._status_queue.put(f"error: {exc}")

    def _enqueue_pcm(self, pcm_data: bytes) -> None:
        wav_bytes = pcm16_to_wav_bytes(pcm_data, self._config.sample_rate)
        self._audio_queue.put(base64.b64encode(wav_bytes).decode())


def start_stream(
    text: str,
    config: TTSConfig,
    audio_queue: queue.Queue,
    status_queue: queue.Queue,
    stop_event: threading.Event,
) -> threading.Thread:
    streamer = CartesiaStreamer(config, audio_queue, status_queue, stop_event)
    return streamer.start(text)


def pcm16_to_wav_bytes(pcm_data: bytes, sample_rate: int, channels: int = 1) -> bytes:
    if len(pcm_data) % 2 != 0:
        pcm_data = pcm_data[:-1]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buffer.getvalue()


def split_transcript(text: str, max_chars: int = 900) -> List[str]:
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        return [cleaned]

    sentences: List[str] = []
    start = 0
    for idx, ch in enumerate(cleaned):
        if ch in ".!?":
            sentences.append(cleaned[start : idx + 1].strip())
            start = idx + 1
    tail = cleaned[start:].strip()
    if tail:
        sentences.append(tail)

    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        pending = f"{current} {sentence}".strip() if current else sentence
        if len(pending) <= max_chars:
            current = pending
        else:
            if current:
                chunks.append(current)
            if len(sentence) <= max_chars:
                current = sentence
            else:
                start = 0
                while start < len(sentence):
                    chunks.append(sentence[start : start + max_chars])
                    start += max_chars
                current = ""
    if current:
        chunks.append(current)

    return chunks


def drain_queue(q: queue.Queue) -> Iterable:
    while True:
        try:
            yield q.get_nowait()
        except queue.Empty:
            return
