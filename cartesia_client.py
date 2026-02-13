from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import json

import websockets

MIN_CHUNK_SECONDS = 1.0
WS_MAX_SIZE_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class OutputFormat:
    container: str
    encoding: str
    sample_rate: int


@dataclass(frozen=True)
class VoiceRef:
    mode: str
    id: str


@dataclass(frozen=True)
class TTSRequest:
    model_id: str
    transcript: str
    voice: VoiceRef
    language: str
    context_id: str
    output_format: OutputFormat
    add_timestamps: bool
    continue_flag: bool

    def to_json(self) -> str:
        return json.dumps(
            {
                "model_id": self.model_id,
                "transcript": self.transcript,
                "voice": {"mode": self.voice.mode, "id": self.voice.id},
                "language": self.language,
                "context_id": self.context_id,
                "output_format": {
                    "container": self.output_format.container,
                    "encoding": self.output_format.encoding,
                    "sample_rate": self.output_format.sample_rate,
                },
                "add_timestamps": self.add_timestamps,
                "continue": self.continue_flag,
            }
        )


@dataclass(frozen=True)
class TTSMessage:
    type: str
    data: Optional[str] = None
    error: Optional[str] = None

    @staticmethod
    def from_json(raw: str) -> "TTSMessage":
        payload = json.loads(raw)
        return TTSMessage(
            type=payload.get("type", ""),
            data=payload.get("data"),
            error=payload.get("error"),
        )


@dataclass(frozen=True)
class CancelMessage:
    context_id: str
    cancel: bool

    def to_json(self) -> str:
        return json.dumps({"context_id": self.context_id, "cancel": self.cancel})


@dataclass(frozen=True)
class ErrorMessage:
    type: str
    error: str

    def to_message(self) -> "TTSMessage":
        return TTSMessage(type=self.type, error=self.error)


class WebSocketLike(Protocol):
    """Minimal websocket interface used by CartesiaClient."""
    async def send(self, data: str) -> None: ...

    async def recv(self) -> str: ...


@dataclass(frozen=True)
class TTSConfig:
    """Configuration required to request Cartesia TTS audio."""
    api_key: str
    version: str
    model_id: str
    voice_id: str
    sample_rate: int
    language: str = "en"


class CartesiaClient:
    """Low-level Cartesia WebSocket client for sending text and receiving audio."""

    def __init__(self, config: TTSConfig) -> None:
        """Create a client with the given TTS configuration."""
        self._config = config
        self._logger = logging.getLogger(__name__)

    def connect(self) -> websockets.WebSocketClientProtocol:
        """Return a websocket connection context manager."""
        self._logger.debug("Opening Cartesia websocket connection")
        url = (
            "wss://api.cartesia.ai/tts/websocket"
            f"?api_key={self._config.api_key}"
            f"&cartesia_version={self._config.version}"
        )
        return websockets.connect(url, max_size=WS_MAX_SIZE_BYTES)

    async def send_chunk(
        self,
        ws: WebSocketLike,
        transcript: str,
        context_id: str,
        continue_flag: bool,
    ) -> None:
        """Send a transcript chunk to Cartesia over the websocket."""
        payload = TTSRequest(
            model_id=self._config.model_id,
            transcript=transcript,
            voice=VoiceRef(mode="id", id=self._config.voice_id),
            language=self._config.language,
            context_id=context_id,
            output_format=OutputFormat(
                container="raw",
                encoding="pcm_s16le",
                sample_rate=self._config.sample_rate,
            ),
            add_timestamps=False,
            continue_flag=continue_flag,
        )
        self._logger.debug(
            "Sending chunk (continue=%s, chars=%d)", continue_flag, len(transcript)
        )
        await ws.send(payload.to_json())

    async def recv_message(self, ws: WebSocketLike) -> "TTSMessage":
        """Receive one message from Cartesia and parse JSON."""
        raw = await ws.recv()
        try:
            return TTSMessage.from_json(raw)
        except json.JSONDecodeError:
            self._logger.error("Invalid JSON received from server")
            return ErrorMessage(type="error", error="invalid JSON from server").to_message()

    async def cancel(self, ws: WebSocketLike, context_id: str) -> None:
        """Cancel an active Cartesia streaming context."""
        self._logger.info("Canceling stream context_id=%s", context_id)
        await ws.send(CancelMessage(context_id=context_id, cancel=True).to_json())



def validate_config(config: TTSConfig) -> None:
    """Validate required config values."""
    if not config.api_key:
        logging.getLogger(__name__).error("Missing Cartesia API key")
        raise ValueError("Cartesia API key is required")
    if config.sample_rate <= 0:
        logging.getLogger(__name__).error("Invalid sample rate: %s", config.sample_rate)
        raise ValueError("Sample rate must be positive")
