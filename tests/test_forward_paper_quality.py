from hermes_polymarket.forward_paper.quality import forward_paper_quality_warnings


def test_quality_warns_no_signals_and_exploratory_threshold():
    warnings = forward_paper_quality_warnings(signals=0, closed_positions=0, min_move_pct=0.01)
    assert "no_signals_generated" in warnings
    assert "no_closed_positions" in warnings
    assert "exploratory_threshold_not_strategy_threshold" in warnings
