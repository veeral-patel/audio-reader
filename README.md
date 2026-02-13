# Cartesia Streamlit eBook Reader

A Streamlit web app that reads EPUBs, tracks reading position, stores highlights, and streams audio playback with Cartesia TTS.

## Quickstart

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export CARTESIA_API_KEY="your_key_here"
streamlit run app.py
```

## Configuration

The app reads these environment variables:

- `CARTESIA_API_KEY` (required for TTS)
- `CARTESIA_VERSION` (default: `2025-04-16`)
- `CARTESIA_MODEL_ID` (default: `sonic-2`)
- `CARTESIA_VOICE_ID` (default: `a0e99841-438c-4a64-b679-ae501e7d6091`)

You can also paste the API key directly into the sidebar UI.

## Notes

- Built-in books are small, original sample EPUBs generated locally.
- Uploaded books are stored in `data/uploads` and added to the local library.
- Reading position and highlights are persisted in `data/state.json`.
