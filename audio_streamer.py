from __future__ import annotations

import asyncio
import base64
import io
import queue
import threading
import uuid
import wave
from typing import AsyncIterator, Callable, Optional, Tuple

from cartesia_client import MIN_CHUNK_SECONDS, CartesiaClient, WebSocketLike, validate_config
from text_utils import split_transcript


class AudioStreamer:
    """Stream Cartesia TTS audio into base64-encoded WAV chunks."""

    def __init__(self, client: CartesiaClient) -> None:
        """Create a streamer that uses the provided Cartesia client."""
        self._client = client

    async def stream(
        self, text: str, stop_event: Optional[threading.Event] = None
    ) -> AsyncIterator[str]:
        """Yield base64 WAV chunks from a streaming TTS session."""
        validate_config(self._client._config)
        sample_rate = self._client._config.sample_rate
        stop_event = stop_event or threading.Event()
        context_id = str(uuid.uuid4())
        pcm_buffer = bytearray()
        min_chunk_bytes = int(sample_rate * 2 * MIN_CHUNK_SECONDS)

        async with self._client.connect() as ws:
            # Send all text chunks to the service first, then consume audio.
            await self._send_chunks(ws, text, context_id, stop_event)

            while True:
                if stop_event.is_set():
                    # Request cancel so the server stops generating audio.
                    await self._client.cancel(ws, context_id)
                    break

                message = await self._client.recv_message(ws)
                msg_type = message.type

                if msg_type == "chunk":
                    # Buffer raw PCM until we have enough for a smooth WAV chunk.
                    pcm = base64.b64decode(message.data or "")
                    if pcm:
                        pcm_buffer.extend(pcm)
                    if len(pcm_buffer) >= min_chunk_bytes:
                        yield self._encode_and_clear(pcm_buffer, sample_rate)
                elif msg_type == "done":
                    # Flush any remaining audio and exit.
                    if pcm_buffer:
                        yield self._encode_and_clear(pcm_buffer, sample_rate)
                    break
                elif msg_type == "error":
                    # Surface server error to the caller.
                    raise RuntimeError(message.error or "error")

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
            # Push each WAV chunk into the queue for UI consumption.
            audio_queue.put(chunk)

        def on_status(status: str) -> None:
            # Report status changes to the UI.
            status_queue.put(status)

        # Run the async stream in a background thread.
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
        """Split text and send each chunk to Cartesia."""
        chunks = split_transcript(text)
        total = len(chunks)
        for idx, chunk in enumerate(chunks):
            continue_flag = idx < total - 1
            if stop_event.is_set():
                await self._client.cancel(ws, context_id)
                return
            await self._client.send_chunk(
                ws,
                chunk + (" " if continue_flag else ""),
                context_id,
                continue_flag=continue_flag,
            )

    def _encode_and_clear(self, buffer: bytearray, sample_rate: int) -> str:
        """Convert PCM buffer to WAV, clear it, and return base64 WAV."""
        wav_bytes = pcm16_to_wav_bytes(bytes(buffer), sample_rate)
        buffer.clear()
        return base64.b64encode(wav_bytes).decode()


def pcm16_to_wav_bytes(pcm_data: bytes, sample_rate: int, channels: int = 1) -> bytes:
    """Wrap PCM16 audio bytes into a WAV container."""
    if len(pcm_data) % 2 != 0:
        # Trim odd byte to keep PCM frame alignment.
        pcm_data = pcm_data[:-1]
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm_data)
    return buffer.getvalue()
