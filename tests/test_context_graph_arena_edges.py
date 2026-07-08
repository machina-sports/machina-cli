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
