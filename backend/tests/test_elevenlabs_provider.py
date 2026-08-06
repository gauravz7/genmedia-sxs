"""Pure-function tests for the FAL-backed ElevenLabs provider.

No network: only the request-shaping helpers are exercised — the stability tier
and the multi-speaker turn parser. Those are what the Vertex→FAL migration
actually changed, and getting either wrong is silent (a clip that generates
fine but reads flat, or a dialogue that comes out in one voice).
"""

import pytest

from providers.elevenlabs_provider import (
    DIALOGUE_VOICES,
    _parse_turns,
    _stability,
    _strip_tags,
)

CREATIVE, NATURAL, ROBUST = 0.0, 0.5, 1.0


# --- stability tier ---------------------------------------------------------

@pytest.mark.parametrize("style", [
    "expressive and dramatic",
    "excited sports commentator",
    "upbeat, cheerful morning-radio host",
    "an enthusiastic product demo",
])
def test_expressive_style_notes_use_the_creative_tier(style):
    assert _stability(style) == CREATIVE


@pytest.mark.parametrize("text", [
    "[excited] The launch window opens at dawn.",
    "[whispers] Don't wake the baby.",
    "Fine. [angry] Absolutely not.",
])
def test_inline_audio_tags_alone_reach_the_creative_tier(text):
    """v3 only acts strongly on audio tags at Creative. A case tagged in the
    script but neutral in its style notes must not be read flat — this is the
    regression the first live multi-modality pass caught."""
    assert _stability(None, text) == CREATIVE
    assert _stability("warm corporate narrator", text) == CREATIVE


def test_expressive_words_in_the_script_body_are_content_not_direction():
    """Only tags are scanned. 'She was excited' is a line to read, not a
    direction to shout."""
    assert _stability(None, "She was excited about the merger.") == NATURAL


def test_meditation_still_wins_the_robust_tier():
    assert _stability("guided relaxation, soothing") == ROBUST
    assert _stability("meditation", "[excited] breathe") == ROBUST


def test_a_plain_read_stays_natural():
    assert _stability(None) == NATURAL
    assert _stability("", "") == NATURAL
    assert _stability("clear corporate narrator", "Q3 revenue rose.") == NATURAL


# --- multi-speaker turns ----------------------------------------------------

def test_each_speaker_gets_a_distinct_voice_in_order_of_appearance():
    turns = _parse_turns("Joe: Morning.\nJane: Hi Joe.\nJoe: Coffee?",
                         [{"speaker": "Joe"}, {"speaker": "Jane"}])
    assert [t["text"] for t in turns] == ["Morning.", "Hi Joe.", "Coffee?"]
    assert turns[0]["voice"] == turns[2]["voice"]      # same speaker, same voice
    assert turns[0]["voice"] != turns[1]["voice"]      # the whole point
    assert all(t["voice"] in DIALOGUE_VOICES for t in turns)


def test_turns_carry_voice_not_voice_id():
    """FAL's text-to-dialogue schema keys on `voice`; `voice_id` is silently
    ignored and every turn would come out in the default voice."""
    turns = _parse_turns("A: one\nB: two", [{"speaker": "A"}, {"speaker": "B"}])
    assert set(turns[0]) == {"text", "voice"}


def test_speaker_labels_are_not_spoken():
    turns = _parse_turns("Joe: How is the launch going?", [{"speaker": "Joe"}])
    assert "Joe:" not in turns[0]["text"]


def test_audio_tags_survive_into_dialogue_turns():
    turns = _parse_turns("Joe: Hi.\nJane: [excited] Better than we imagined!",
                         [{"speaker": "Joe"}, {"speaker": "Jane"}])
    assert "[excited]" in turns[1]["text"]


def test_an_unlabelled_line_continues_the_previous_turn():
    turns = _parse_turns("Joe: One thing.\nAnd another.\nJane: Sure.",
                         [{"speaker": "Joe"}, {"speaker": "Jane"}])
    assert turns[0]["text"] == "One thing. And another."
    assert len(turns) == 2


def test_a_script_with_no_labels_yields_no_turns():
    """Fewer than 2 turns falls through to the single-voice endpoint."""
    assert _parse_turns("Just a plain sentence.", [{"speaker": "Joe"}]) == []


def test_strip_tags_leaves_clean_text_for_engines_without_tag_support():
    assert _strip_tags("[excited] Hello   there [laughs]") == "Hello there"
