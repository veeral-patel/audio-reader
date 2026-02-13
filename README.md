# Cartesia Streamlit Reader

A minimal Streamlit web app that streams text‑to‑speech audio from Cartesia’s WebSocket API and plays it in the browser.

## What this app does

1. Lets you pick a built‑in text passage.
2. Sends the passage to Cartesia in multiple chunks (if needed).
3. Receives raw PCM audio chunks over WebSocket.
4. Buffers PCM into WAV chunks and plays them progressively in the UI.

## Audio generation flow

### High‑level steps (with examples)

1) **User selects a passage** in `ui.py`.

Example UI event:
```text
selection = "Harbor Notes (Extended)"
```

2) **AudioStreamer starts a session** and opens a WebSocket via `CartesiaClient`.

Example call:
```python
streamer = AudioStreamer(CartesiaClient(config))
thread, stop_event = streamer.start_session(text, audio_queue, status_queue)
```

3) **Text is split** into manageable chunks by `split_transcript`.

Example input/output:
```text
Input text length: 1,820 chars
Chunks: ["Sentence 1...", "Sentence 2...", "Sentence 3..."]
```

4) **Chunks are sent** to Cartesia with `continue=true` on all but the last.

Example payload (one chunk):
```json
{
  "model_id": "sonic-2",
  "transcript": "Nera traced the old avenues...",
  "voice": {"mode": "id", "id": "a0e99841-438c-4a64-b679-ae501e7d6091"},
  "language": "en",
  "context_id": "<uuid>",
  "output_format": {"container": "raw", "encoding": "pcm_s16le", "sample_rate": 44100},
  "add_timestamps": false,
  "continue": true
}
```

5) **PCM audio chunks arrive** as base64 strings.

Example response:
```json
{
  "type": "chunk",
  "data": "UklGRiQAAABXQVZFZm10IBAAAA..."
}
```

6) **PCM is buffered** until it’s big enough for a smooth WAV chunk.

Example buffer logic:
```text
sample_rate=44100 → min_chunk_bytes ≈ 88200
buffered_pcm_bytes = 102400 → flush
```

7) **PCM → WAV conversion** happens in memory.

Example:
```python
wav_bytes = pcm16_to_wav_bytes(pcm_buffer, sample_rate)
```

8) **WAV chunks are base64‑encoded** and pushed to the UI.

Example:
```python
audio_queue.put(base64.b64encode(wav_bytes).decode())
```

9) **Streamlit re‑renders** and the audio player queues the new WAV data.

Example UI step:
```python
audio_b64 = tts_queue.get_nowait()
audio_player(audio_b64, format="audio/wav")
```

### Component responsibilities

- `ui.py`
  - Builds the Streamlit UI.
  - Starts streaming and feeds audio chunks to the player.
  - Triggers reruns for progressive playback.

- `audio_streamer.py`
  - Orchestrates chunk sending and audio reception.
  - Buffers PCM and converts to WAV.
  - Streams WAV chunks to the UI.

- `cartesia_client.py`
  - Handles WebSocket connection.
  - Builds and sends request payloads.
  - Parses incoming messages into dataclasses.

- `text_utils.py`
  - Splits long passages into chunks suitable for streaming.

## How chunking works

- Text is normalized (whitespace collapsed).
- It is split by sentence boundaries when possible.
- Chunks are capped at `MAX_CHARS_PER_CHUNK` (default 900).
- Very long sentences are hard‑split to stay under the limit.

## How audio buffering works

- Cartesia returns **raw PCM** chunks (base64 encoded).
- PCM is buffered until it reaches roughly `MIN_CHUNK_SECONDS` of audio.
- Buffered PCM is wrapped into a WAV container for browser playback.

## Running the app

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
export CARTESIA_API_KEY="your_key_here"
streamlit run app.py
```

## Environment variables

- `CARTESIA_API_KEY` (required in UI)
- `CARTESIA_VERSION` (default: 2025‑04‑16)
- `CARTESIA_MODEL_ID` (default: sonic‑2)
- `CARTESIA_VOICE_ID` (default: a0e99841‑438c‑4a64‑b679‑ae501e7d6091)
- `CARTESIA_SAMPLE_RATE` (default: 44100)

## Troubleshooting

- If audio cuts out, try lowering passage length or sample rate.
- If playback is muffled, increase sample rate or buffer size.
- If you see errors in the UI, check your API key and network access.

## Queue and thread flow

The app uses a background thread plus a queue to stream audio without blocking the UI.

### Step-by-step

1) `ui.py` starts a background thread via `AudioStreamer.start_session(...)`.
2) The thread runs the async streaming loop and receives audio chunks.
3) Each audio chunk is placed into a thread-safe `audio_queue`.
4) On every Streamlit rerun, the UI pulls **one** chunk from the queue.
5) The audio player queues that chunk for playback.
6) `st_autorefresh(...)` keeps the UI rerunning until the stream is done.

### Example flow (pseudo)

```text
UI thread:         Background thread:

click Play         -> open WebSocket
start_session      -> receive PCM chunk
rerun UI           -> audio_queue.put(chunk)
get_nowait()       -> receive PCM chunk
audio_player(...)  -> audio_queue.put(chunk)
rerun UI           -> ...
```

### WebSocket stream visualization

```text
Client -> Cartesia (send text chunks)

  [chunk 1] ---->
  [chunk 2] ---->
  [chunk 3] ---->  (continue=true on chunks 1..n-1)

Cartesia -> Client (receive audio chunks)

  <---- PCM #1 (base64)
  <---- PCM #2 (base64)
  <---- PCM #3 (base64)
  <---- done
```

### WAV assembly visualization

```text
PCM buffer (bytes) grows over time:

  +---------+---------+---------+
  | PCM #1  | PCM #2  | PCM #3  |
  +---------+---------+---------+

When buffer >= min_chunk_bytes:
  -> wrap PCM buffer in WAV header
  -> base64 encode WAV bytes
  -> push to UI queue
```

### Why this pattern

- Streamlit UI can’t block on network I/O.
- A queue is thread-safe for producer/consumer flow.
- Autorefresh turns the UI into a steady consumer of chunks.
