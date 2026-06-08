from __future__ import annotations

from app.models.memory import InjurySnifferSchema, WorkingMemory

CONSOLIDATION_TURN_THRESHOLD = 6


def should_consolidate(
    memory: WorkingMemory,
    *,
    force: bool = False,
    sniff: InjurySnifferSchema | None = None,
) -> bool:
    """Decide whether to run heavy Neo4j/MySQL profile consolidation."""
    if force or memory.pending_consolidation:
        return True
    if memory.turn_count >= CONSOLIDATION_TURN_THRESHOLD:
        return True
    if sniff is None:
        return False
    return bool(
        sniff.has_new_injury
        or sniff.has_new_equipment
        or sniff.has_injury_resolution
        or sniff.has_equipment_removal
    )
