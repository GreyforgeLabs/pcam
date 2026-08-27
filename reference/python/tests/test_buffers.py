import pytest

from pcam_runtime import BufferEntry, TickInput, apply_consumption, capture_entry, expire_buffer_entries, select_entry
from pcam_runtime.errors import PCAMError


def _entry(input_id: str, sequence: int, lifetime: int = 2, priority: int = 0) -> BufferEntry:
    tick_input = TickInput(
        assigned_tick=5,
        source_entity_id=1,
        sequence=sequence,
        command_id="DODGE",
        payload={},
        input_id=input_id,
    )
    return BufferEntry.capture(tick_input, lifetime=lifetime, priority=priority)


def test_buffer_capacity_policies_are_deterministic():
    first, second = _entry("a", 1), _entry("b", 2)
    entries = capture_entry((), first, 1, "DROP_OLDEST")
    assert capture_entry(entries, second, 1, "DROP_OLDEST") == (second,)
    assert capture_entry(entries, second, 1, "DROP_NEWEST") == (first,)
    with pytest.raises(PCAMError):
        capture_entry(entries, second, 1, "FAULT")


def test_buffer_lifetime_one_is_available_only_on_capture_tick():
    entry = _entry("a", 1, lifetime=1)
    assert select_entry((entry,), "DODGE") == entry
    assert expire_buffer_entries((entry,)) == ()
    assert expire_buffer_entries((entry,), expiry_frozen=True) == (entry,)


def test_buffer_consumption_policies_distinguish_attempt_and_accept():
    entry = _entry("a", 1)
    assert apply_consumption((entry,), entry, "ON_ACCEPT", accepted=False, attempted=True) == (entry,)
    assert apply_consumption((entry,), entry, "ON_ATTEMPT", accepted=False, attempted=True) == ()
    assert apply_consumption((entry,), entry, "NEVER", accepted=True, attempted=True) == (entry,)
