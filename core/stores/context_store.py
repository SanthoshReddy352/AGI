"""Transitional facade — Tracks 5.1d / 5.1e.

ContextStore no longer owns any SQL tables, any state, or any direct
DB connection. All persistence lives in the five domain stores under
`core.stores`:

    AuditStore, WorkflowStore, MemoryStore, KnowledgeGraphStore,
    GoalStore, SessionStore

Track 5.1e relocated this file from `core/context_store.py` to
`core/stores/context_store.py` and swept all callers to the new
import path. The class survives only as a back-compat facade for the
~30 callers that still construct or use `ContextStore`. Every method
here is either:

  (a) a single-line delegator to one of the five stores, or
  (b) a thin orchestrator that composes calls across two stores (e.g.
      `append_turn` writes the turn row via SessionStore THEN indexes
      the text via `MemoryStore.upsert_vector`).

`WorkingArtifact`, `ARTIFACT_SCOPE_RANK`, `artifact_scope_rank`, and
`HashEmbeddingFunction` are re-exported here so callers can keep using
the `from core.stores import ...` path without reaching into each
store module.

Track 5.3 / P2.2 (2026-05-22) — DB path canonicalization:
Both `data/friday.db` and `core/data/friday.db` existed because
`_project_root()` returned `core/` (one `dirname` too few). Fixed by
going three levels up from `core/stores/context_store.py`. Both old
DBs and both Chroma dirs archived to `data/_archive_2026-05-22/`.
Canonical paths are now `<project-root>/data/friday.db` and
`<project-root>/data/chroma/`. `core/data/` was deleted and added to
`.gitignore` so it cannot reappear.
"""
from __future__ import annotations

import hashlib
import os

# Direct module imports avoid a circular import — `core.stores.__init__`
# re-exports the ContextStore class for callers, and routing through it
# here would re-import this file.
from core.stores.audit_store import AuditStore
from core.stores.goal_store import GoalStore
from core.stores.knowledge_graph_store import KnowledgeGraphStore
from core.stores.memory_store import HashEmbeddingFunction, MemoryStore
from core.stores.session_store import (
    ARTIFACT_SCOPE_RANK,
    SessionStore,
    WorkingArtifact,
    artifact_scope_rank,
)
from core.stores.workflow_store import WorkflowStore


__all__ = [
    "ARTIFACT_SCOPE_RANK",
    "ContextStore",
    "HashEmbeddingFunction",
    "WorkingArtifact",
    "artifact_scope_rank",
]


def _project_root() -> str:
    # core/stores/context_store.py → core/stores → core → project root
    return os.path.dirname(os.path.dirname(os.path.dirname(__file__)))


def _default_db_path() -> str:
    return os.path.join(_project_root(), "data", "friday.db")


def _default_vector_path() -> str:
    return os.path.join(_project_root(), "data", "chroma")


class ContextStore:
    """Composition-over-inheritance facade over the five domain stores.

    DEPRECATED — kept for back-compat with ~30 existing callers. New
    code should reach into `app.session_store`, `app.memory_store`,
    etc. directly. Physical deletion of this class is Track 5.1e.
    """

    def __init__(self, db_path: str | None = None,
                 vector_path: str | None = None):
        self.db_path = db_path or _default_db_path()
        self.vector_path = vector_path or _default_vector_path()
        # Five domain stores, all sharing the same SQLite file.
        self._session_store = SessionStore(self.db_path)
        self._audit_store = AuditStore(self.db_path)
        self._workflow_store = WorkflowStore(self.db_path)
        self._memory_store = MemoryStore(self.db_path, self.vector_path)
        self._knowledge_graph_store = KnowledgeGraphStore(self.db_path)
        self._goal_store = GoalStore(self.db_path)

    # ------------------------------------------------------------------
    # Legacy attribute access for Chroma — some callers read these
    # directly. Exposed as properties over MemoryStore.
    # ------------------------------------------------------------------

    @property
    def _vector_collection(self):
        return self._memory_store._vector_collection

    @property
    def _vector_available(self):
        return self._memory_store._vector_available

    # ==================================================================
    # SessionStore delegators (sessions / turns / state / personas)
    # ==================================================================

    def start_session(self, metadata=None) -> str:
        return self._session_store.start_session(metadata)

    def append_turn(self, session_id: str, role: str, text: str,
                    source: str | None = None) -> None:
        """Orchestrator: SessionStore writes the turn row + bumps
        sessions.updated_at; MemoryStore indexes the text in the vector
        store so semantic_recall can return turn fragments.
        """
        if not session_id:
            return
        now = self._session_store.append_turn_row(session_id, role, text, source)
        if not now:
            return
        digest = hashlib.md5(str(text).encode("utf-8")).hexdigest()
        self._memory_store.upsert_vector(
            item_id=f"turn:{session_id}:{role}:{digest}",
            text=str(text),
            metadata={
                "session_id": session_id,
                "kind": "turn",
                "role": role,
                "source": source or role,
            },
        )

    def summarize_session(self, session_id: str, limit: int = 6) -> str:
        return self._session_store.summarize_session(session_id, limit)

    def prune_old_turns(self, session_id: str, older_than_days: int = 30) -> int:
        return self._session_store.prune_old_turns(session_id, older_than_days)

    def save_session_state(self, session_id, state):
        return self._session_store.save_session_state(session_id, state)

    def get_session_state(self, session_id):
        return self._session_store.get_session_state(session_id)

    def set_active_persona(self, session_id, persona_id):
        return self._session_store.set_active_persona(session_id, persona_id)

    def get_active_persona_id(self, session_id):
        return self._session_store.get_active_persona_id(session_id)

    def set_pending_online(self, session_id, payload):
        return self._session_store.set_pending_online(session_id, payload)

    def clear_pending_online(self, session_id):
        return self._session_store.clear_pending_online(session_id)

    def set_pending_intent(self, session_id, payload):
        return self._session_store.set_pending_intent(session_id, payload)

    def clear_pending_intent(self, session_id):
        return self._session_store.clear_pending_intent(session_id)

    def save_artifact(self, session_id: str, artifact: WorkingArtifact) -> None:
        return self._session_store.save_artifact(session_id, artifact)

    def get_artifact(self, session_id: str) -> WorkingArtifact | None:
        return self._session_store.get_artifact(session_id)

    def clear_artifact(self, session_id: str) -> None:
        return self._session_store.clear_artifact(session_id)

    def save_reference(self, session_id: str, key: str, value: str) -> None:
        return self._session_store.save_reference(session_id, key, value)

    def get_reference(self, session_id: str, key: str) -> str | None:
        return self._session_store.get_reference(session_id, key)

    def get_all_references(self, session_id: str) -> dict:
        return self._session_store.get_all_references(session_id)

    def save_persona(self, payload):
        """Orchestrator: SessionStore writes the persona row; MemoryStore
        indexes example_dialogues in the vector store so persona-style
        recall can find them.
        """
        persona_id = self._session_store.upsert_persona_row(payload or {})
        if not persona_id:
            return
        examples = (payload or {}).get("example_dialogues") or ""
        if examples:
            self._memory_store.upsert_vector(
                item_id=f"persona:{persona_id}:examples",
                text=str(examples),
                metadata={
                    "session_id": "",
                    "kind": "persona_style",
                    "persona_id": persona_id,
                },
            )

    def get_persona(self, persona_id):
        return self._session_store.get_persona(persona_id)

    def list_personas(self):
        return self._session_store.list_personas()

    # ==================================================================
    # WorkflowStore delegators + save_workflow_state orchestrator
    # ==================================================================

    def get_active_workflow(self, session_id, workflow_name=None):
        return self._workflow_store.get_active(session_id, workflow_name)

    def _mark_workflow_expired(self, session_id, workflow_name):
        return self._workflow_store.mark_expired(session_id, workflow_name)

    def expire_all_workflows(self, session_id) -> int:
        """Expire every active workflow row for *session_id*. See
        :meth:`WorkflowStore.expire_all_for_session`."""
        return self._workflow_store.expire_all_for_session(session_id)

    def save_workflow_state(self, session_id, workflow_name, state):
        """Orchestrator: WorkflowStore writes the workflow row,
        SessionStore bumps sessions.updated_at, MemoryStore indexes the
        summary text.
        """
        if not session_id or not workflow_name:
            return
        state = dict(state or {})
        now = self._workflow_store.upsert(session_id, workflow_name, state)
        if not now:
            return
        self._session_store.bump_session(session_id, now)
        summary_text = " ".join(
            part for part in [
                workflow_name.replace("_", " "),
                str(state.get("last_action") or ""),
                str(state.get("result_summary") or ""),
            ] if part
        ).strip()
        if summary_text:
            self._memory_store.upsert_vector(
                item_id=f"workflow:{session_id}:{workflow_name}",
                text=summary_text,
                metadata={
                    "session_id": session_id,
                    "kind": "workflow",
                    "workflow_name": workflow_name,
                },
            )

    def clear_workflow_state(self, session_id, workflow_name):
        active = self.get_active_workflow(session_id, workflow_name=workflow_name)
        if not active:
            return
        active["status"] = "completed"
        active["pending_slots"] = []
        self.save_workflow_state(session_id, workflow_name, active)

    def get_workflow_summary(self, session_id):
        return self._workflow_store.get_summary(session_id)

    def _row_to_workflow(self, row):
        return WorkflowStore._row_to_workflow(row)

    # ==================================================================
    # MemoryStore delegators
    # ==================================================================

    def store_fact(self, key, value, session_id=None, namespace="general"):
        return self._memory_store.store_fact(key, value, session_id or "", namespace)

    def store_memory_item(self, session_id, content, memory_type="episodic",
                          persona_id="", sensitivity="safe_auto", metadata=None):
        return self._memory_store.store_memory_item(
            session_id, content, memory_type, persona_id, sensitivity, metadata,
        )

    def recent_memory_items(self, session_id, limit=6, persona_id=None):
        return self._memory_store.recent_memory_items(session_id, limit, persona_id)

    def semantic_recall(self, query, session_id, limit=3):
        return self._memory_store.semantic_recall(query, session_id, limit)

    def delete_memory_item(self, item_id):
        return self._memory_store.delete_memory_item(item_id)

    def prune_low_confidence_memories(self, session_id, min_confidence=0.5):
        return self._memory_store.prune_low_confidence_memories(session_id, min_confidence)

    def get_facts_by_namespace(self, namespace="general"):
        return self._memory_store.get_facts_by_namespace(namespace)

    def _fallback_semantic_recall(self, query, session_id, limit=3):
        return self._memory_store._fallback_semantic_recall(query, session_id, limit)

    def _upsert_memory_item(self, item_id, text, metadata):
        return self._memory_store.upsert_vector(item_id, text, metadata)

    # ==================================================================
    # AuditStore delegators
    # ==================================================================

    def log_online_permission(self, session_id, tool_name, decision, reason=""):
        return self._audit_store.log_online_permission(
            session_id, tool_name, decision, reason
        )

    def record_commitment(self, *args, **kwargs) -> str:
        return self._audit_store.record_commitment(*args, **kwargs)

    def complete_commitment(self, commitment_id: str, result: str = "") -> bool:
        return self._audit_store.complete_commitment(commitment_id, result)

    def fail_commitment(self, commitment_id: str, result: str = "") -> bool:
        return self._audit_store.fail_commitment(commitment_id, result)

    def cancel_commitment(self, commitment_id: str) -> bool:
        return self._audit_store.cancel_commitment(commitment_id)

    def list_pending_commitments(self, session_id: str = "", limit: int = 20) -> list:
        return self._audit_store.list_pending_commitments(session_id, limit)

    def list_all_commitments(self, session_id: str = "", limit: int = 50) -> list:
        return self._audit_store.list_all_commitments(session_id, limit)

    def get_commitment(self, commitment_id: str) -> dict | None:
        return self._audit_store.get_commitment(commitment_id)

    def log_audit_event(self, *args, **kwargs) -> None:
        return self._audit_store.log_audit_event(*args, **kwargs)

    def query_audit_events(self, tool_name: str = "", limit: int = 50,
                           session_id: str = "") -> list:
        return self._audit_store.query_audit_events(tool_name, limit, session_id)

    def post_agent_message(self, *args, **kwargs) -> str:
        return self._audit_store.post_agent_message(*args, **kwargs)

    def list_agent_messages(self, to_agent: str = "", status: str = "pending") -> list:
        return self._audit_store.list_agent_messages(to_agent, status)

    def ack_agent_message(self, msg_id: str) -> bool:
        return self._audit_store.ack_agent_message(msg_id)

    # ==================================================================
    # KnowledgeGraphStore delegators
    # ==================================================================

    def upsert_entity(self, *args, **kwargs) -> str:
        return self._knowledge_graph_store.upsert_entity(*args, **kwargs)

    def _find_entity_by_name(self, name: str, entity_type: str) -> str | None:
        return self._knowledge_graph_store._find_entity_by_name(name, entity_type)

    def add_entity_fact(self, *args, **kwargs) -> str:
        return self._knowledge_graph_store.add_entity_fact(*args, **kwargs)

    def add_entity_relationship(self, *args, **kwargs) -> str:
        return self._knowledge_graph_store.add_entity_relationship(*args, **kwargs)

    def query_entity_facts(self, subject_id: str) -> list:
        return self._knowledge_graph_store.query_entity_facts(subject_id)

    def find_entities(self, name_fragment: str = "", entity_type: str = "") -> list:
        return self._knowledge_graph_store.find_entities(name_fragment, entity_type)

    # ==================================================================
    # GoalStore delegators
    # ==================================================================

    def create_goal(self, *args, **kwargs) -> str:
        return self._goal_store.create_goal(*args, **kwargs)

    def update_goal_score(self, goal_id: str, score: float, note: str = "") -> bool:
        return self._goal_store.update_goal_score(goal_id, score, note)

    def update_goal_status(self, goal_id: str, status: str) -> bool:
        return self._goal_store.update_goal_status(goal_id, status)

    def list_goals(self, session_id: str = "", status: str = "active") -> list:
        return self._goal_store.list_goals(session_id, status)

    def get_goal(self, goal_id: str) -> dict | None:
        return self._goal_store.get_goal(goal_id)

    def delete_goal(self, goal_id: str) -> bool:
        return self._goal_store.delete_goal(goal_id)
