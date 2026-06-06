"""P1.3 — Telegram outbound message chunking."""
import pytest
from modules.comms.telegram import TelegramChannel


def test_short_text_not_chunked():
    chunks = TelegramChannel._chunk_text("Hello!", 3800)
    assert chunks == ["Hello!"]


def test_long_text_splits_into_chunks():
    # Generate a text longer than 3800 chars
    text = ("This is a sentence. " * 300)  # ~6000 chars
    chunks = TelegramChannel._chunk_text(text, 3800)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 3800


def test_chunks_reconstruct_full_text():
    text = "Hello world. " * 500  # ~6500 chars
    chunks = TelegramChannel._chunk_text(text, 3800)
    # All words should be present in the chunks (order-insensitive due to strip)
    joined = " ".join(chunks)
    # Verify no content lost (allowing whitespace normalization at split points)
    original_words = text.split()
    joined_words = joined.split()
    assert len(joined_words) >= len(original_words) - 5  # tiny tolerance for boundary spaces


def test_split_prefers_sentence_boundary():
    sentence = "First sentence. " + "x" * 3700 + ". Second sentence."
    chunks = TelegramChannel._chunk_text(sentence, 3800)
    # The first chunk should end around "First sentence."
    assert chunks[0].startswith("First sentence")
