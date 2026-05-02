from hermes_polymarket.forward_paper.calibration import ThresholdCalibration


def test_threshold_calibration_counts_hits():
    calibration = ThresholdCalibration([0.01, 0.02, 0.03])
    calibration.observe_move(0.025)
    result = calibration.to_dict()
    assert result["0.01"] == 1
    assert result["0.02"] == 1
    assert "0.03" not in result
