from __future__ import annotations

from typing import List

MAX_CHARS_PER_CHUNK = 900


def split_transcript(text: str, max_chars: int = MAX_CHARS_PER_CHUNK) -> List[str]:
    """Split text into sentence-oriented chunks of up to max_chars."""
    # Normalize whitespace to keep chunking consistent.
    cleaned = " ".join(text.split())
    if len(cleaned) <= max_chars:
        # Fast path: the full text already fits in one chunk.
        return [cleaned]

    # First pass: split into sentence-like spans by punctuation.
    sentences: List[str] = []
    start = 0
    for idx, ch in enumerate(cleaned):
        if ch in ".!?":
            sentences.append(cleaned[start : idx + 1].strip())
            start = idx + 1
    tail = cleaned[start:].strip()
    if tail:
        # Add any trailing text that doesn't end in punctuation.
        sentences.append(tail)

    # Second pass: pack sentences into size-limited chunks.
    chunks: List[str] = []
    current = ""
    for sentence in sentences:
        if not sentence:
            continue
        # Try to append this sentence to the current chunk.
        pending = f"{current} {sentence}".strip() if current else sentence
        if len(pending) <= max_chars:
            current = pending
        else:
            # Current chunk is full; emit it and start a new one.
            if current:
                chunks.append(current)
            if len(sentence) <= max_chars:
                current = sentence
            else:
                # Sentence itself is too long; hard-split it by length.
                start = 0
                while start < len(sentence):
                    chunks.append(sentence[start : start + max_chars])
                    start += max_chars
                current = ""
    if current:
        # Emit the final chunk.
        chunks.append(current)

    return chunks
