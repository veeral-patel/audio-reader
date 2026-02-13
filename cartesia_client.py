from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

import websockets

MAX_CHARS_PER_CHUNK = 900
MIN_CHUNK_SECONDS = 1.0
WS_MAX_SIZE_BYTES = 8 * 1024 * 1024


class WebSocketLike(Protocol):
    async def send(self, data: str) -> None: ...

    async def recv(self) -> str: ...


@dataclass(frozen=True)
class TTSConfig:
    api_key: str
    version: str
    model_id: str
    voice_id: str
    sample_rate: int
    language: str = "en"


class CartesiaClient:
    """Low-level Cartesia WebSocket client for sending text and receiving audio."""

    def __init__(self, config: TTSConfig) -> None:
        self._config = config

    @property
    def config(self) -> TTSConfig:
        return self._config

    def connect(self):
        return websockets.connect(self._build_ws_url(), max_size=WS_MAX_SIZE_BYTES)

    async def send_chunk(
        self,
        ws: WebSocketLike,
        transcript: str,
        context_id: str,
        continue_flag: bool,
    ) -> None:
        payload = self._build_payload(transcript, context_id, continue_flag)
        await ws.send(json.dumps(payload))

    async def recv_message(self, ws: WebSocketLike) -> dict:
        raw = await ws.recv()
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"type": "error", "error": "invalid JSON from server"}

    async def cancel(self, ws: WebSocketLike, context_id: str) -> None:
        await ws.send(json.dumps({"context_id": context_id, "cancel": True}))

    def _build_ws_url(self) -> str:
        """Build the Cartesia WebSocket URL with auth and version."""
        return (
            "wss://api.cartesia.ai/tts/websocket"
            f"?api_key={self._config.api_key}"
            f"&cartesia_version={self._config.version}"
        )

    def _build_payload(
        self, transcript: str, context_id: str, continue_flag: bool
    ) -> dict:
        """Build a single Cartesia TTS payload for a transcript chunk."""
        return {
            "model_id": self._config.model_id,
            "transcript": transcript,
            "voice": {"mode": "id", "id": self._config.voice_id},
            "language": self._config.language,
            "context_id": context_id,
            "output_format": {
                "container": "raw",
                "encoding": "pcm_s16le",
                "sample_rate": self._config.sample_rate,
            },
            "add_timestamps": False,
            "continue": continue_flag,
        }


def validate_config(config: TTSConfig) -> None:
    """Validate required config values."""
    if not config.api_key:
        raise ValueError("Cartesia API key is required")
    if config.sample_rate <= 0:
        raise ValueError("Sample rate must be positive")
