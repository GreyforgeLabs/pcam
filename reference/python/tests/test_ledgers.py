from pcam_runtime import HitPolicy, LedgerContext, ledger_is_eligible, ledger_key, receipt_required, write_receipt


def _context(**changes) -> LedgerContext:
    values = {
        "tick": 10,
        "source_action_instance_id": 4,
        "offense_fact_id": "strike",
        "target_entity_id": 9,
        "cycle": 0,
        "predicate_entry_serials": {"ACTIVE": 1},
        "contact_partition": "body",
    }
    values.update(changes)
    return LedgerContext(**values)


def test_once_per_action_and_same_tick_duplicate_contact():
    policy = HitPolicy("ONCE_PER_ACTION_INSTANCE", "ON_IMPACT")
    context = _context()
    ledger = {}
    assert ledger_is_eligible(ledger, policy, context)
    ledger, receipt = write_receipt(ledger, policy, context, "candidate-a")
    assert receipt is not None
    assert not ledger_is_eligible(ledger, policy, context)
    assert not ledger_is_eligible(ledger, policy, _context(tick=11))


def test_cycle_and_predicate_activation_are_part_of_policy_key():
    cycle_policy = HitPolicy("ONCE_PER_CYCLE", "ON_ACCEPT")
    ledger, _ = write_receipt({}, cycle_policy, _context(), "a")
    assert not ledger_is_eligible(ledger, cycle_policy, _context())
    assert ledger_is_eligible(ledger, cycle_policy, _context(cycle=1))

    predicate_policy = HitPolicy("ONCE_PER_PREDICATE_ACTIVATION", "ON_ACCEPT", predicate_id="ACTIVE")
    ledger, _ = write_receipt({}, predicate_policy, _context(), "a")
    assert not ledger_is_eligible(ledger, predicate_policy, _context())
    assert ledger_is_eligible(
        ledger,
        predicate_policy,
        _context(predicate_entry_serials={"ACTIVE": 2}),
    )


def test_cooldown_and_contact_partition_policies():
    cooldown = HitPolicy("COOLDOWN_TICKS", "ON_IMPACT", cooldown_ticks=3)
    ledger, _ = write_receipt({}, cooldown, _context(), "a")
    assert not ledger_is_eligible(ledger, cooldown, _context(tick=12))
    assert ledger_is_eligible(ledger, cooldown, _context(tick=13))

    partition = HitPolicy("ONCE_PER_CONTACT_PARTITION", "ON_CONTACT")
    ledger, _ = write_receipt({}, partition, _context(), "a")
    assert not ledger_is_eligible(ledger, partition, _context())
    assert ledger_is_eligible(ledger, partition, _context(contact_partition="weapon"))


def test_receipt_timing_conditions_are_explicit():
    assert receipt_required("ON_CONTACT", False, False)
    assert not receipt_required("ON_ACCEPT", False, True)
    assert receipt_required("ON_ACCEPT", True, False)
    assert not receipt_required("ON_IMPACT", True, False)
    assert receipt_required("ON_IMPACT", True, True)


def test_unbounded_policy_has_no_ledger_key_or_receipt():
    policy = HitPolicy("UNBOUNDED", "ON_CONTACT")
    assert ledger_key(policy, _context()) is None
    ledger, receipt = write_receipt({}, policy, _context(), "a")
    assert ledger == {}
    assert receipt is None
