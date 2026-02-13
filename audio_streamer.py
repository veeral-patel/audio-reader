from __future__ import annotations

import asyncio
import base64
import io
import queue
import threading
import uuid
import wave
from typing import List

from cartesia_client import (
    MAX_CHARS_PER_CHUNK,
    MIN_CHUNK_SECONDS,
    CartesiaClient,
    TTSConfig,
    WebSocketLike,
    validate_config,
)


def start_stream(
    text: str,
    config: TTSConfig,
    audio_queue: queue.Queue[str],
    status_queue: queue.Queue[str],
    stop_event: threading.Event,
) -> threading.Thread:
    """Convenience entrypoint for starting a stream in a thread."""
    validate_config(config)
    streamer = AudioStreamer(
        CartesiaClient(config), audio_queue, status_queue, stop_event
    )
    return streamer.start(text)


class AudioStreamer:
    """Stream Cartesia TTS audio into a queue of base64-encoded WAV chunks."""

    def __init__(
        self,
        client: CartesiaClient,
        audio_queue: queue.Queue[str],
        status_queue: queue.Queue[str],
        stop_event: threading.Event,
    ) -> None:
        self._client = client
        self._audio_queue = audio_queue
        self._status_queue = status_queue
        self._stop_event = stop_event

    def start(self, text: str) -> threading.Thread:
        """Start streaming in a background thread and return the thread."""
        thread = threading.Thread(target=self._run, args=(text,), daemon=True)
        thread.start()
        return thread

    def _run(self, text: str) -> None:
        asyncio.run(self._stream(text))

    async def _stream(self, text: str) -> None:
        """Open a websocket, send chunks, and stream audio back."""
        try:
            validate_config(self._client.config)
            context_id = str(uuid.uuid4())
            self._pcm_buffer = bytearray()
            self._min_chunk_bytes_per_flush = int(
                self._client.config.sample_rate * 2 * MIN_CHUNK_SECONDS
            )
            async with self._client.connect() as ws:
                await self._send_chunks(ws, text, context_id)
                await self._recv_loop(ws, context_id)
        except Exception as exc:
            self._status_queue.put(f"error: {exc}")

    async def _send_chunks(self, ws: WebSocketLike, text: str, context_id: str) -> None:
        """Split text and send each chunk to the websocket."""
        chunks = split_transcript(text, max_chars=MAX_CHARS_PER_CHUNK)
        for idx, chunk in enumerate(chunks):
            if self._stop_event.is_set():
                await self._client.cancel(ws, context_id)
                self._status_queue.put("stopped")
                return
            await self._client.send_chunk(
                ws,
                chunk + (" " if idx < len(chunks) - 1 else ""),
                context_id,
                continue_flag=idx < len(chunks) - 1,
            )

    async def _recv_loop(self, ws: WebSocketLike, context_id: str) -> None:
        """Receive audio chunks from the websocket and enqueue WAV data."""
        while True:
            if self._stop_event.is_set():
                await self._client.cancel(ws, context_id)
                self._status_queue.put("stopped")
                break

            data = await self._client.recv_message(ws)
            msg_type = data.get("type")

            if msg_type == "chunk":
                pcm = base64.b64decode(data.get("data", ""))
                if pcm:
                    self._handle_chunk(pcm)
            elif msg_type == "done":
                self._flush_buffer()
                self._status_queue.put("done")
                break
            elif msg_type == "error":
                self._status_queue.put(data.get("error", "error"))
                break

    def _handle_chunk(self, pcm: bytes) -> None:
        """Buffer PCM until threshold then flush as WAV."""
        self._pcm_buffer.extend(pcm)
        if len(self._pcm_buffer) >= self._min_chunk_bytes_per_flush:
            self._flush_buffer()

    def _flush_buffer(self) -> None:
        """Convert buffered PCM to WAV and enqueue it."""
        if not self._pcm_buffer:
            return
        wav_bytes = pcm16_to_wav_bytes(
            bytes(self._pcm_buffer), self._client.config.sample_rate
        )
        self._audio_queue.put(base64.b64encode(wav_bytes).decode())
        self._pcm_buffer.clear()


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
