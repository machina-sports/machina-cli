from machina_cli.commands.context_graph import _edge_summary


def test_edge_summary_renders_arena_certified_artifact():
    badge, color, detail = _edge_summary(
        "arena:artifact<->machina_template",
        {
            "edge": "arena:artifact<->machina_template",
            "decision": "pass",
            "next_action": "request_human_approval",
            "gate_pass_rate_pct": 100,
            "judge_score": 5.8,
            "failed_gates": [],
        },
    )

    assert badge == "certified"
    assert color == "green"
    assert "gates 100%" in detail
    assert "judge 5.8" in detail
    assert "approval" in detail


def test_edge_summary_renders_arena_repair_artifact():
    badge, color, detail = _edge_summary(
        "arena:artifact<->sportsclaw_output",
        {
            "edge": "arena:artifact<->sportsclaw_output",
            "decision": "repair",
            "next_action": "repair_artifact",
            "gate_pass_rate_pct": 75,
            "failed_gates": ["build_test", "promotion"],
        },
    )

    assert badge == "repair"
    assert color == "yellow"
    assert "gates 75%" in detail
    assert "build_test,promotion" in detail


def test_edge_summary_renders_arena_blocked_artifact():
    badge, color, detail = _edge_summary(
        "arena:artifact<->machina_template",
        {
            "edge": "arena:artifact<->machina_template",
            "decision": "block",
            "gate_pass_rate_pct": 40,
            "failed_gates": ["build_test"],
        },
    )

    assert badge == "blocked"
    assert color == "red"


def test_edge_summary_arena_unknown_decision_falls_back():
    # unrecognized decision -> the decision string itself, yellow
    badge, color, _ = _edge_summary("arena:artifact<->x", {"decision": "pending"})
    assert badge == "pending"
    assert color == "yellow"

    # missing decision -> generic "arena" label, yellow
    badge, color, _ = _edge_summary("arena:artifact<->x", {})
    assert badge == "arena"
    assert color == "yellow"


def test_edge_summary_arena_empty_detail_is_placeholder():
    _, _, detail = _edge_summary("arena:artifact<->x", {"decision": "pass"})
    assert detail == "—"


def test_edge_summary_arena_renders_zero_valued_metrics():
    # 0 is a valid value guarded by `is not None`, not suppressed as falsy
    _, _, detail = _edge_summary(
        "arena:artifact<->x",
        {"decision": "pass", "gate_pass_rate_pct": 0, "judge_score": 0},
    )
    assert "gates 0%" in detail
    assert "judge 0" in detail
