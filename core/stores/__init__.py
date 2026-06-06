"""Track 5.1 — domain-specific stores extracted from ContextStore.

Final state after 5.1d (this commit): five domain stores, each owning a
disjoint slice of the 16-table SQLite schema. ContextStore retains zero
tables of its own and survives only as a transitional facade for the
~30 existing callers; physical deletion happens in 5.1e once those
callers migrate.

Store map (table ownership is exclusive — write through one path only):

* `AuditStore`           — audit_events, online_permission_events, agent_messages, commitments
* `WorkflowStore`        — workflows
* `MemoryStore`          — facts, memory_items (+ owns Chroma vector index + HashEmbeddingFunction)
* `KnowledgeGraphStore`  — entities, entity_facts, entity_relationships
* `GoalStore`            — goals, goal_progress
* `SessionStore`         — sessions, turns, conversation_sessions, personas
                            (+ WorkingArtifact dataclass + ARTIFACT_SCOPE_RANK
                             + working_artifact / reference_registry helpers
                             over session_state JSON)

Reads can cross stores via raw SQL on the shared DB (e.g.
`MemoryStore._candidates_for_fallback` reads `turns` for the fallback
recall); only write-ownership is strict.

The originally-planned 5.1c MemoryStore would have owned 7 tables —
violating the Direction's "≤4 tables per store" rule — so it was split
into MemoryStore + KnowledgeGraphStore + GoalStore. Net: five stores
instead of four, but every store ≤4 tables.
"""
from core.stores.app_index_store import AppIndexStore
from core.stores.audit_store import AuditStore
from core.stores.file_index_store import FileIndexStore
from core.stores.goal_store import GoalStore
from core.stores.intent_learning_store import IntentLearningStore
from core.stores.knowledge_graph_store import KnowledgeGraphStore
from core.stores.memory_store import HashEmbeddingFunction, MemoryStore
from core.stores.session_store import (
    ARTIFACT_SCOPE_RANK,
    SessionStore,
    WorkingArtifact,
    artifact_scope_rank,
)
from core.stores.workflow_store import WorkflowStore

# Track 5.1e: the transitional facade lives here too. Imported last so
# its module-level `from core.stores.<x> import` lines resolve cleanly
# against the already-imported sibling modules above.
from core.stores.context_store import ContextStore

__all__ = [
    "ARTIFACT_SCOPE_RANK",
    "AppIndexStore",
    "AuditStore",
    "ContextStore",
    "FileIndexStore",
    "GoalStore",
    "HashEmbeddingFunction",
    "IntentLearningStore",
    "KnowledgeGraphStore",
    "MemoryStore",
    "SessionStore",
    "WorkflowStore",
    "WorkingArtifact",
    "artifact_scope_rank",
]
