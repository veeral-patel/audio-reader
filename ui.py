from __future__ import annotations

import os
import queue
import threading
from dataclasses import dataclass
from typing import Dict

import streamlit as st
from streamlit_audio_queue_player import audio_player
from streamlit_autorefresh import st_autorefresh

from cartesia_tts import CartesiaStreamer, TTSConfig, drain_queue


@dataclass(frozen=True)
class AppConfig:
    version: str
    model_id: str
    voice_id: str
    sample_rate: int


def load_app_config() -> AppConfig:
    return AppConfig(
        version=os.environ.get("CARTESIA_VERSION", "2025-04-16"),
        model_id=os.environ.get("CARTESIA_MODEL_ID", "sonic-2"),
        voice_id=os.environ.get(
            "CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091"
        ),
        sample_rate=int(os.environ.get("CARTESIA_SAMPLE_RATE", "44100")),
    )


def builtin_passages() -> Dict[str, str]:
    return {
        "Harbor Notes": (
            "The library ship arrived without fanfare, a low whistle and the smell of salt. "
            "People lined up with unread letters and left with borrowed weather."
        ),
        "Glass Map": (
            "Nera traced the old avenues with a graphite finger, watching the city shift. "
            "Every night the map remembered a different dream."
        ),
        "Small Machines": (
            "The kettle-bot woke the neighborhood with soft clicks, pouring warmth into cups "
            "left on windowsills."
        ),
        "Night Plaza": (
            "By dusk the plaza had become a river. Lanterns floated like small moons, "
            "each reflecting a route only they could see."
        ),
    }


def init_state() -> None:
    if "tts_queue" not in st.session_state:
        st.session_state.tts_queue = queue.Queue()
    if "tts_status" not in st.session_state:
        st.session_state.tts_status = queue.Queue()
    if "tts_thread" not in st.session_state:
        st.session_state.tts_thread = None
    if "tts_stop" not in st.session_state:
        st.session_state.tts_stop = threading.Event()
    if "tts_running" not in st.session_state:
        st.session_state.tts_running = False
    if "clear_key" not in st.session_state:
        st.session_state.clear_key = 0


def render_app() -> None:
    st.set_page_config(page_title="Cartesia Streamlit Reader", layout="wide")
    init_state()

    st.title("Cartesia Streamlit Reader")
    st.caption("Choose a passage and stream audio with Cartesia TTS.")

    passages = builtin_passages()
    config = load_app_config()

    col_left, col_right = st.columns([2.2, 1])

    with col_left:
        selection = st.selectbox("Passage", list(passages.keys()))
        text = passages[selection]
        st.write(text)

    with col_right:
        st.subheader("Text-to-Speech")
        api_key = st.text_input("Cartesia API key", type="password")

        if st.session_state.tts_running:
            st.button("Playing...", disabled=True)
        else:
            if st.button("Play"):
                if not api_key:
                    st.error("Enter your Cartesia API key.")
                else:
                    st.session_state.tts_stop.clear()
                    st.session_state.tts_running = True
                    streamer = CartesiaStreamer(
                        TTSConfig(
                            api_key=api_key,
                            version=config.version,
                            model_id=config.model_id,
                            voice_id=config.voice_id,
                            sample_rate=config.sample_rate,
                        ),
                        st.session_state.tts_queue,
                        st.session_state.tts_status,
                        st.session_state.tts_stop,
                    )
                    st.session_state.tts_thread = streamer.start(text)

        audio_b64 = None
        for item in drain_queue(st.session_state.tts_queue):
            audio_b64 = item

        audio_player(
            audio_b64,
            format="audio/wav",
            clear_key=st.session_state.clear_key,
            key="audio_player",
        )

        if st.session_state.tts_running:
            st.caption("Streaming audio...")
            st_autorefresh(interval=800, key="tts_refresh")

        for status in drain_queue(st.session_state.tts_status):
            if status in {"done", "stopped"}:
                st.session_state.tts_running = False
            elif isinstance(status, str) and status.startswith("error"):
                st.session_state.tts_running = False
                st.error(status)

