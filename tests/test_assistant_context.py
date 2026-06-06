import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.assistant_context import AssistantContext


def test_build_chat_messages_coerces_history_to_alternating_roles():
    context = AssistantContext(max_messages=16)
    context.record_message("assistant", "Hello from FRIDAY.")
    context.record_message("assistant", "Still here.")
    context.record_message("user", "hi")
    context.record_message("user", "what is your name")

    messages = context.build_chat_messages("what is your name")
    roles = [message["role"] for message in messages]

    # Track 1.1 (Consolidation): the prompt now leads with a structured
    # system message carrying ASSISTANT_IDENTITY / USER_FACTS /
    # SESSION_CONTEXT blocks. After the system role, user/assistant must
    # still strictly alternate and end on a user turn.
    assert roles[0] == "system"
    assert roles[-1] == "user"
    for index in range(2, len(roles)):
        assert roles[index] != roles[index - 1]


def test_build_chat_messages_appends_latest_query_after_assistant_turn():
    context = AssistantContext(max_messages=16)
    context.record_message("user", "hello")
    context.record_message("assistant", "hey there")

    messages = context.build_chat_messages("tell me more")

    assert messages[-1]["role"] == "user"
    assert "tell me more" in messages[-1]["content"]


def test_assistant_identity_forbids_speaking_as_user():
    """Regression for 2026-05-23: small chat models drifted into
    impersonating the user when USER_FACTS sat next to an introspective
    question. The identity block now explicitly prohibits that mode.
    Pin the structural rule so a future prompt refactor can't silently
    drop it.
    """
    context = AssistantContext(max_messages=4)
    messages = context.build_chat_messages("what do you know about me?")
    system_content = messages[0]["content"].lower()
    assert messages[0]["role"] == "system"
    # The role guard must be present in some form — phrasings can vary
    # but "never speak as the user" carries the load-bearing instruction.
    assert "never speak as the user" in system_content
    # 2026-05-23 v2: the previous "verbatim" wording produced bullet
    # dumps + prompt-echo. We now want a natural paragraph instead, so
    # the load-bearing words shifted. Pin the two new invariants:
    #   1. the no-bullet rule (otherwise the model defaults to lists)
    #   2. the no-hallucinated-tools rule (so the LLM can't fabricate
    #      "Brightness set to 60" when no set_brightness tool exists)
    assert "do not bullet-list profile fields" in system_content
    assert "never claim to have completed an action you don't actually have a tool for" in system_content


class _FakeStore:
    """Minimal context_store exposing only get_facts_by_namespace."""

    def __init__(self, name):
        self._name = name

    def get_facts_by_namespace(self, namespace):
        if namespace == "user_profile" and self._name:
            return [{"key": "name", "value": self._name}]
        return []

    def get_workflow_summary(self, session_id):
        return ""

    def summarize_session(self, session_id, limit=4):
        return ""

    def semantic_recall(self, query, session_id, limit=2):
        return []


def test_identity_names_the_user_so_model_wont_impersonate():
    """2026-05-29: the abstract 'your name is not in USER_FACTS' guard wasn't
    enough for the 0.8B model — it called itself by the user's name (Luffy).
    The identity must now name the user explicitly and forbid that name.
    """
    context = AssistantContext(max_messages=4)
    context.context_store = _FakeStore("Luffy")
    context.session_id = "s1"
    messages = context.build_chat_messages("who are you?")
    system_content = messages[0]["content"]
    assert "The user's name is Luffy" in system_content
    assert "You are NOT Luffy" in system_content
