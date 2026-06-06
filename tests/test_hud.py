import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from gui.hud import (
    _clamp_detail,
    _weather_error_message,
    format_calendar_event_item,
    format_hud_message,
    format_voice_mode_label,
    format_voice_runtime_status,
    format_weather_status,
)


def test_format_hud_message_prefixes_user_text():
    formatted = format_hud_message("user", "open the coffee file")

    assert formatted == "USER: open the coffee file"


def test_format_hud_message_truncates_long_replies():
    text = " ".join(f"line{i}" for i in range(100))

    formatted = format_hud_message("assistant", text, max_chars=80, max_lines=3)

    assert formatted.startswith("FRIDAY: ")
    assert formatted.endswith("...")
    assert formatted.count("\n") <= 3


def test_format_voice_mode_label_handles_all_runtime_modes():
    assert format_voice_mode_label("persistent") == "PERSISTENT"
    assert format_voice_mode_label("wake-word") == "WAKE-WORD"
    assert format_voice_mode_label("on_demand") == "ON-DEMAND"
    assert format_voice_mode_label("manual") == "MANUAL"


def test_format_voice_runtime_status_exposes_gate_device_and_rejection():
    formatted = format_voice_runtime_status({
        "ui_state": "armed",
        "actively_transcribing": False,
        "wake_armed": True,
        "device_label": "Built-in Audio Analog Stereo",
        "last_rejected_reason": "wake model missing",
    })

    assert formatted == {
        "state": "ARMED",
        "gate": "ARMED",
        "device": "Built-in Audio Analog Stereo",
        "rejected": "wake model missing",
        "wake_strategy": "Wake model",
    }


def test_format_voice_runtime_status_exposes_transcript_wake_fallback():
    formatted = format_voice_runtime_status({
        "ui_state": "armed",
        "actively_transcribing": True,
        "wake_armed": True,
        "wake_transcript_fallback": True,
        "wake_strategy": "Transcript fallback",
        "last_rejected_reason": "waiting for wake word",
    })

    assert formatted["gate"] == "TRANSCRIPT WAKE"
    assert formatted["wake_strategy"] == "Transcript fallback"
    assert formatted["rejected"] == "None"


def test_format_weather_status_formats_nellore_panel_metrics():
    formatted = format_weather_status({
        "status": "success",
        "temperature_c": 31.24,
        "feels_like_c": 34.8,
        "humidity": 62,
        "wind_kmh": 11.9,
        "condition": "Partly cloudy",
    })

    assert formatted == {
        "temperature": "31.2 C",
        "condition": "Partly cloudy",
        "details": "Feels 34.8 C  |  Humidity 62%  |  Wind 12 km/h",
    }


def test_weather_error_message_is_short_and_spaced():
    # A real requests network failure carries a giant unbreakable URL token;
    # the panel must show a short, space-containing phrase instead so the
    # word-wrapped label can't stretch the left HUD column.
    class ConnectionError(Exception):
        pass

    msg = _weather_error_message(ConnectionError(
        "HTTPSConnectionPool(host='api.open-meteo.com', port=443): Max retries "
        "exceeded with url: /v1/forecast?latitude=14.4&longitude=79.9&current=..."
    ))
    assert msg == "Network unavailable"
    assert max(len(tok) for tok in msg.split(" ")) < 22


def test_clamp_detail_breaks_long_tokens_and_caps_length():
    giant = "https://api.open-meteo.com/v1/forecast?latitude=14.4&longitude=79.9&current=temperature"
    out = _clamp_detail(giant)
    assert len(out) <= 60
    # No single unbreakable token survives to balloon the label width.
    assert max(len(tok) for tok in out.split(" ")) <= 22


def test_clamp_detail_leaves_normal_text_untouched():
    assert _clamp_detail("Waiting for update") == "Waiting for update"


def test_weather_error_message_falls_back_for_unknown():
    assert _weather_error_message(ValueError("boom")) == "Weather unavailable right now"


def test_format_calendar_event_item_formats_reminder_row():
    formatted = format_calendar_event_item({
        "title": "purchase a gift",
        "remind_at": "2026-04-28T16:10:00",
    })

    assert formatted == "28 Apr 04:10 PM  purchase a gift"
