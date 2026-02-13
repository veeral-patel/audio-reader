from __future__ import annotations

import logging
import os
import queue

import streamlit as st
from streamlit_audio_queue_player import audio_player
from streamlit_autorefresh import st_autorefresh

from audio_streamer import AudioStreamer
from cartesia_client import CartesiaClient, TTSConfig

APP_VERSION = os.environ.get("CARTESIA_VERSION", "2025-04-16")
APP_MODEL_ID = os.environ.get("CARTESIA_MODEL_ID", "sonic-2")
APP_VOICE_ID = os.environ.get("CARTESIA_VOICE_ID", "a0e99841-438c-4a64-b679-ae501e7d6091")
APP_SAMPLE_RATE = int(os.environ.get("CARTESIA_SAMPLE_RATE", "44100"))

PASSAGES = {
    "Harbor Notes": (
        "The library ship arrived without fanfare, a low whistle and the smell of salt. "
        "People lined up with unread letters and left with borrowed weather."
    ),
    "Harbor Notes (Extended)": (
        "The library ship arrived without fanfare, a low whistle and the smell of salt. "
        "People lined up with unread letters and left with borrowed weather. "
        "Inside, the shelves hummed. Every book carried a tide mark, and every chair faced "
        "the sea. The librarian kept a log of storms that never made landfall. "
        "She would lend you a story and ask for a memory in return. "
        "By dusk the deck lights flickered, and readers clustered near the rails, "
        "listening for pages turning across the water. "
        "At dawn the gangway lifted. The harbor kept the echo of pages long after "
        "the horizon swallowed the ship."
    ),
    "Glass Map": (
        "Nera traced the old avenues with a graphite finger, watching the city shift. "
        "Every night the map remembered a different dream."
    ),
    "Glass Map (Extended)": (
        "Nera traced the old avenues with a graphite finger, watching the city shift. "
        "Every night the map remembered a different dream. "
        "By dusk the plaza had become a river. Lanterns floated like small moons, each "
        "reflecting a route only they could see. "
        "She sketched quickly, promising to meet the alleys before morning erased them. "
        "A hinge pressed into the paper, a doorway that opened with a sigh. "
        "Beyond it was a street that never moved, anchored to a memory she did not own. "
        "She walked it anyway, listening for the city to say her name."
    ),
    "Small Machines": (
        "The kettle-bot woke the neighborhood with soft clicks, pouring warmth into cups "
        "left on windowsills."
    ),
    "Small Machines (Extended)": (
        "The kettle-bot woke the neighborhood with soft clicks, pouring warmth into cups "
        "left on windowsills. Streetlight engines climbed the poles at dusk, polishing "
        "glass with care. In winter, the machines nested in the boiler room, listening "
        "for spring. When the first thaw arrived, they carried hot stones to the doorways "
        "and left without a word. The town said thank you by keeping oil tins full."
    ),
    "Night Plaza": (
        "By dusk the plaza had become a river. Lanterns floated like small moons, "
        "each reflecting a route only they could see."
    ),
    "Night Plaza (Extended)": (
        "By dusk the plaza had become a river. Lanterns floated like small moons, "
        "each reflecting a route only they could see. "
        "Neighbors crossed in silence, trading maps drawn on the backs of receipts. "
        "A violinist played beneath the arcade, her notes drifting downstream. "
        "When the bells rang midnight, the water fell away, and the stones kept the memory "
        "of the current for another night."
    ),
}


def render_app() -> None:
    logger = logging.getLogger(__name__)
    st.set_page_config(page_title="Cartesia Streamlit Reader", layout="wide")
    if "tts_queue" not in st.session_state:
        st.session_state.tts_queue = queue.Queue()
    if "tts_status" not in st.session_state:
        st.session_state.tts_status = queue.Queue()
    if "tts_thread" not in st.session_state:
        st.session_state.tts_thread = None
    if "tts_stop" not in st.session_state:
        st.session_state.tts_stop = None
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
                    logger.error("Play clicked without API key")
                else:
                    st.session_state.tts_running = True
                    streamer = AudioStreamer(
                        client=CartesiaClient(
                            TTSConfig(
                                api_key=api_key,
                                version=APP_VERSION,
                                model_id=APP_MODEL_ID,
                                voice_id=APP_VOICE_ID,
                                sample_rate=APP_SAMPLE_RATE,
                            )
                        )
                    )
                    thread, stop_event = streamer.start_session(
                        text,
                        audio_queue=st.session_state.tts_queue,
                        status_queue=st.session_state.tts_status,
                    )
                    st.session_state.tts_thread = thread
                    st.session_state.tts_stop = stop_event
                    logger.info("Started streaming session")

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
        if st.session_state.tts_running or not st.session_state.tts_queue.empty():
            st_autorefresh(interval=800, key="tts_refresh")
        try:
            status = st.session_state.tts_status.get_nowait()
            if status in {"done", "stopped"}:
                st.session_state.tts_running = False
                logger.info("Streaming finished with status=%s", status)
            elif isinstance(status, str) and status.startswith("error"):
                st.session_state.tts_running = False
                st.error(status)
                logger.error("Streaming error: %s", status)
        except queue.Empty:
            pass
