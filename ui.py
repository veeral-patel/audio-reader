from __future__ import annotations

import os
import queue
import threading

import streamlit as st
from streamlit_audio_queue_player import audio_player

from cartesia_tts import TTSConfig, start_stream

APP_VERSION = os.environ.get("CARTESIA_VERSION", "2025-04-16")
APP_MODEL_ID = os.environ.get("CARTESIA_MODEL_ID", "sonic-2")
APP_VOICE_ID = os.environ.get("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091")
APP_SAMPLE_RATE = int(os.environ.get("CARTESIA_SAMPLE_RATE", "44100"))

PASSAGES = {
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


def render_app() -> None:
    st.set_page_config(page_title="Cartesia Streamlit Reader", layout="wide")
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

    st.title("Cartesia Streamlit Reader")

    col_left, col_right = st.columns([2.2, 1])

    with col_left:
        selection = st.selectbox("Passage", list(PASSAGES.keys()))
        text = PASSAGES[selection]
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
                    st.session_state.tts_thread = start_stream(
                        text,
                        TTSConfig(
                            api_key=api_key,
                            version=APP_VERSION,
                            model_id=APP_MODEL_ID,
                            voice_id=APP_VOICE_ID,
                            sample_rate=APP_SAMPLE_RATE,
                        ),
                        st.session_state.tts_queue,
                        st.session_state.tts_status,
                        st.session_state.tts_stop,
                    )

        audio_b64 = None
        try:
            audio_b64 = st.session_state.tts_queue.get_nowait()
        except queue.Empty:
            audio_b64 = None

        audio_player(
            audio_b64,
            format="audio/wav",
            clear_key=st.session_state.clear_key,
            key="audio_player",
        )
        try:
            status = st.session_state.tts_status.get_nowait()
            if status in {"done", "stopped"}:
                st.session_state.tts_running = False
            elif isinstance(status, str) and status.startswith("error"):
                st.session_state.tts_running = False
                st.error(status)
        except queue.Empty:
            pass
