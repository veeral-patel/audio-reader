from __future__ import annotations

import asyncio
import base64
import io
import queue
import threading
import uuid
import wave
from typing import AsyncIterator, Callable, List, Optional, Tuple

from cartesia_client import (
    MAX_CHARS_PER_CHUNK,
    MIN_CHUNK_SECONDS,
    CartesiaClient,
    TTSConfig,
    WebSocketLike,
    validate_config,
)


class AudioStreamer:
    """Stream Cartesia TTS audio into base64-encoded WAV chunks."""

    def __init__(self, client: CartesiaClient) -> None:
        self._client = client

    async def stream(
        self, text: str, stop_event: Optional[threading.Event] = None
    ) -> AsyncIterator[str]:
        """Yield base64 WAV chunks from a streaming TTS session."""
        validate_config(self._client._config)
        stop_event = stop_event or threading.Event()
        context_id = str(uuid.uuid4())
        pcm_buffer = bytearray()
        min_chunk_bytes = int(self._client._config.sample_rate * 2 * MIN_CHUNK_SECONDS)

        async with self._client.connect() as ws:
            await self._send_chunks(ws, text, context_id, stop_event)

            while True:
                if stop_event.is_set():
                    await self._client.cancel(ws, context_id)
                    break

                data = await self._client.recv_message(ws)
                msg_type = data.get("type")

                if msg_type == "chunk":
                    pcm = base64.b64decode(data.get("data", ""))
                    if pcm:
                        pcm_buffer.extend(pcm)
                    if len(pcm_buffer) >= min_chunk_bytes:
                        yield self._encode_and_clear(pcm_buffer)
                elif msg_type == "done":
                    if pcm_buffer:
                        yield self._encode_and_clear(pcm_buffer)
                    break
                elif msg_type == "error":
                    raise RuntimeError(data.get("error", "error"))

    async def stream_with_callbacks(
        self,
        text: str,
        on_audio: Callable[[str], None],
        on_status: Optional[Callable[[str], None]] = None,
        stop_event: Optional[threading.Event] = None,
    ) -> None:
        """Stream audio and push chunks/status via callbacks."""
        stop_event = stop_event or threading.Event()
        if on_status:
            on_status("starting")
        try:
            async for chunk in self.stream(text, stop_event=stop_event):
                if on_status:
                    on_status("streaming")
                on_audio(chunk)
            if on_status:
                on_status("done")
        except Exception as exc:
            if on_status:
                on_status(f"error: {exc}")
            else:
                raise

    def start_session(
        self,
        text: str,
        audio_queue: Optional[queue.Queue[str]] = None,
        status_queue: Optional[queue.Queue[str]] = None,
    ) -> Tuple[threading.Thread, threading.Event]:
        """Start a background session that writes chunks into queues."""
        audio_queue = audio_queue or queue.Queue()
        status_queue = status_queue or queue.Queue()
        stop_event = threading.Event()

        def on_audio(chunk: str) -> None:
            audio_queue.put(chunk)

        def on_status(status: str) -> None:
            status_queue.put(status)

        thread = threading.Thread(
            target=lambda: asyncio.run(
                self.stream_with_callbacks(text, on_audio, on_status, stop_event)
            ),
            daemon=True,
        )
        thread.start()
        return thread, stop_event

    async def _send_chunks(
        self,
        ws: WebSocketLike,
        text: str,
        context_id: str,
        stop_event: threading.Event,
    ) -> None:
        chunks = split_transcript(text, max_chars=MAX_CHARS_PER_CHUNK)
        for idx, chunk in enumerate(chunks):
            if stop_event.is_set():
                await self._client.cancel(ws, context_id)
                return
            await self._client.send_chunk(
                ws,
                chunk + (" " if idx < len(chunks) - 1 else ""),
                context_id,
                continue_flag=idx < len(chunks) - 1,
            )

    def _encode_and_clear(self, buffer: bytearray) -> str:
        wav_bytes = pcm16_to_wav_bytes(bytes(buffer), self._client._config.sample_rate)
        buffer.clear()
        return base64.b64encode(wav_bytes).decode()


def pcm16_to_wav_bytes(pcm_data: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap PCM16 audio bytes into a WAV container."""
    if len(pcm_data) % 2 != 0:
        pcm_data = pcm_data[:-1]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buffer.getvalue()


def split_transcript(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> List[str]:
    """Split text into sentence-oriented chunks of up to max_chars."""
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
