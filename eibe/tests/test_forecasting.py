"""
예측 엔진 검증.

숫자가 맞는지보다 **경계와 퇴화 조건**을 주로 본다. 실무 데이터는 늘
불완전하다 — 신규 품목이라 이력이 3주뿐이거나, 소진율이 0이거나,
출고와 판매 기록의 길이가 다르거나.
"""

from __future__ import annotations

import math

import pytest

from app.services.forecasting import (
    RISK_THRESHOLDS_WEEKS,
    StockRisk,
    calc_loss_buffer,
    calc_smoothing_constant,
    check_air_shipment,
    classify_stock_risk,
    round_up_to_moq,
    simulate_inventory,
    suggest_order_qty,
    weeks_of_supply,
)


class TestSmoothingConstant:
    def test_average_of_recent_window(self) -> None:
        assert calc_smoothing_constant([100] * 12) == 100.0

    def test_ignores_data_beyond_window(self) -> None:
        # 앞의 999 는 12주 창 밖이라 반영되지 않아야 한다
        history = [999] * 5 + [100] * 12
        assert calc_smoothing_constant(history) == 100.0

    def test_short_history_uses_what_exists(self) -> None:
        """신규 품목: 3주치뿐이어도 그 평균을 쓴다.

        0으로 채워 12주 평균을 내면 수요를 1/4로 과소평가하게 된다.
        """
        assert calc_smoothing_constant([100, 100, 100]) == 100.0

    def test_empty_history_gives_zero(self) -> None:
        assert calc_smoothing_constant([]) == 0.0

    def test_smooths_a_spike(self) -> None:
        flat = calc_smoothing_constant([100] * 12)
        spiked = calc_smoothing_constant([100] * 11 + [400])
        # 스파이크가 평균을 올리되, 스파이크 값 자체보다는 훨씬 낮아야 한다
        assert flat < spiked < 400


class TestLossBuffer:
    def test_difference_between_outflow_and_sales(self) -> None:
        assert calc_loss_buffer([110] * 12, [100] * 12) == 10.0

    def test_zero_when_sales_explain_all_outflow(self) -> None:
        assert calc_loss_buffer([100] * 12, [100] * 12) == 0.0

    def test_aligns_unequal_lengths_from_the_end(self) -> None:
        """출고 4주 · 판매 3주 → 마지막 3주끼리 비교해야 한다."""
        outflow = [100, 200, 300, 400]
        sales = [10, 20, 30]
        expected = ((200 - 10) + (300 - 20) + (400 - 30)) / 3
        assert calc_loss_buffer(outflow, sales) == expected

    def test_missing_side_gives_zero(self) -> None:
        assert calc_loss_buffer([100] * 12, []) == 0.0
        assert calc_loss_buffer([], [100] * 12) == 0.0

    def test_negative_buffer_when_sales_exceed_outflow(self) -> None:
        """기록 불일치로 판매가 출고를 넘을 수 있다. 예외 없이 음수로 드러낸다."""
        assert calc_loss_buffer([100] * 12, [110] * 12) == -10.0


class TestWeeksOfSupply:
    def test_basic(self) -> None:
        assert weeks_of_supply(1000, 100) == 10.0

    def test_zero_demand_is_infinite_not_an_error(self) -> None:
        """소진율 0 — 화면에 '소진 불가'로 표시된다. 0으로 나누면 안 된다."""
        assert math.isinf(weeks_of_supply(1000, 0))

    def test_no_stock_is_zero(self) -> None:
        assert weeks_of_supply(0, 100) == 0.0


class TestRiskClassification:
    @pytest.mark.parametrize(
        ("weeks", "expected"),
        [
            (0.0, StockRisk.HIGH),
            (5.9, StockRisk.HIGH),
            (6.0, StockRisk.MID),    # 경계는 위쪽 구간에 포함
            (8.9, StockRisk.MID),
            (9.0, StockRisk.LOW),
            (12.9, StockRisk.LOW),
            (13.0, StockRisk.SAFE),
            (100.0, StockRisk.SAFE),
        ],
    )
    def test_boundaries(self, weeks: float, expected: StockRisk) -> None:
        assert classify_stock_risk(weeks) == expected

    def test_infinite_supply_is_surplus(self) -> None:
        assert classify_stock_risk(math.inf) == StockRisk.SAFE

    def test_none_is_surplus(self) -> None:
        assert classify_stock_risk(None) == StockRisk.SAFE

    def test_thresholds_match_documented_rule(self) -> None:
        """업무 규칙: 6주 / 9주 / 13주(약 3개월)가 적정 기준."""
        assert RISK_THRESHOLDS_WEEKS == (6.0, 9.0, 13.0)

    def test_values_are_css_class_names(self) -> None:
        """화면에서 그대로 클래스명으로 쓰므로 값이 바뀌면 안 된다."""
        assert StockRisk.HIGH == "risk-high"
        assert StockRisk.SAFE == "risk-safe"


class TestSimulation:
    def test_horizon_length(self) -> None:
        result = simulate_inventory(1000, 100, 0, horizon=24)
        assert len(result.projections) == 24
        assert result.projections[0].week == 1
        assert result.projections[-1].week == 24

    def test_stock_declines_by_demand_each_week(self) -> None:
        result = simulate_inventory(1000, 100, 0, horizon=3)
        assert [p.ending_stock for p in result.projections] == [900, 800, 700]

    def test_loss_buffer_adds_to_demand(self) -> None:
        result = simulate_inventory(1000, 100, 10, horizon=1)
        assert result.weekly_demand == 110.0

    def test_weight_scales_smoothing_but_not_buffer(self) -> None:
        """감모는 판매량과 무관한 고정 손실이라 가중치를 곱하지 않는다."""
        result = simulate_inventory(1000, 100, 10, weight_factor=2.0, horizon=1)
        assert result.weekly_demand == 210.0  # 100*2 + 10

    def test_scheduled_inbound_lands_on_its_week(self) -> None:
        result = simulate_inventory(
            1000, 100, 0, scheduled_inbounds={3: 500}, horizon=4
        )
        assert [p.ending_stock for p in result.projections] == [900, 800, 1200, 1100]

    def test_chained_weeks_carry_forward(self) -> None:
        result = simulate_inventory(100, 30, 0, horizon=3)
        # 이웃한 쌍을 비교하므로 길이가 하나 다르다 — strict 를 쓰면 안 된다
        for previous, current in zip(
            result.projections, result.projections[1:], strict=False
        ):
            assert current.beginning_stock == previous.ending_stock

    def test_first_stockout_week_detected(self) -> None:
        result = simulate_inventory(250, 100, 0, horizon=5)
        # 150, 50, -50 → 3주차에 처음 마이너스
        assert result.first_stockout_week == 3

    def test_no_stockout_returns_none(self) -> None:
        result = simulate_inventory(10_000, 100, 0, horizon=24)
        assert result.first_stockout_week is None

    def test_zero_demand_keeps_stock_flat(self) -> None:
        result = simulate_inventory(500, 0, 0, horizon=5)
        assert result.final_stock == 500
        assert result.risk == StockRisk.SAFE


class TestOrderSuggestion:
    def test_rounds_up_to_moq(self) -> None:
        assert round_up_to_moq(100, 24) == 120   # 24*5
        assert round_up_to_moq(120, 24) == 120   # 딱 맞으면 그대로

    def test_no_shortage_means_no_order(self) -> None:
        assert round_up_to_moq(0, 24) == 0
        assert round_up_to_moq(-50, 24) == 0

    def test_invalid_moq_gives_zero(self) -> None:
        """MOQ 가 0이면 나눗셈이 불가능하다. 예외 대신 0을 돌려준다."""
        assert round_up_to_moq(100, 0) == 0

    def test_suggests_enough_to_reach_safety_stock(self) -> None:
        # 재고 1000, 주간수요 100, 24주 → 종료 시 -1400
        # 목표: 6주치 = 600 → 부족분 2000
        result = simulate_inventory(1000, 100, 0, horizon=24)
        assert result.final_stock == -1400
        assert suggest_order_qty(result, moq=1, safety_stock_weeks=6) == 2000

    def test_surplus_stock_needs_no_order(self) -> None:
        result = simulate_inventory(100_000, 100, 0, horizon=24)
        assert suggest_order_qty(result, moq=24) == 0

    def test_suggestion_is_moq_multiple(self) -> None:
        result = simulate_inventory(1000, 137, 0, horizon=24)
        suggestion = suggest_order_qty(result, moq=24)
        assert suggestion % 24 == 0


class TestAirShipmentTrigger:
    def test_fires_when_stock_negative_at_check_week(self) -> None:
        result = simulate_inventory(500, 100, 0, horizon=24)
        alert = check_air_shipment(result, check_week=12)

        assert alert is not None
        assert alert.week == 12
        assert alert.shortage_qty == 700  # 500 - 1200

    def test_silent_when_stock_holds(self) -> None:
        result = simulate_inventory(10_000, 100, 0, horizon=24)
        assert check_air_shipment(result, check_week=12) is None

    def test_none_when_horizon_too_short(self) -> None:
        result = simulate_inventory(100, 100, 0, horizon=5)
        assert check_air_shipment(result, check_week=12) is None

    def test_message_contains_shortage(self) -> None:
        result = simulate_inventory(500, 100, 0, horizon=24)
        alert = check_air_shipment(result)
        assert alert is not None
        assert "700" in alert.message


class TestEndToEnd:
    def test_realistic_flow_from_history_to_suggestion(self) -> None:
        """이력 → 평탄화 → 시뮬레이션 → 제안까지 한 번에."""
        outflow = [520, 480, 610, 550, 500, 590, 470, 530, 560, 540, 505, 575]
        sales = [500, 460, 590, 530, 480, 570, 450, 510, 540, 520, 485, 555]

        smoothing = calc_smoothing_constant(outflow)
        buffer = calc_loss_buffer(outflow, sales)
        assert buffer == 20.0  # 매주 정확히 20개씩 설명되지 않음

        result = simulate_inventory(
            current_stock=8000, smoothing_constant=smoothing, loss_buffer=buffer
        )
        suggestion = suggest_order_qty(result, moq=24)

        # 재고 8000, 주간수요 약 555 → 24주를 못 버틴다
        assert result.first_stockout_week is not None
        assert suggestion > 0
        assert suggestion % 24 == 0

        # 재고일수 기준으로는 '과잉'(14.4주 > 13주)인데 24주 지평에서는 부족하다.
        # 히트맵만 보면 안심하게 되는 구간이라, 발주 제안이 따로 필요한 이유가 된다.
        assert result.weeks_of_supply > 13
        assert result.risk == StockRisk.SAFE

    def test_healthy_product_needs_no_action(self) -> None:
        outflow = [100] * 12
        result = simulate_inventory(
            current_stock=1200,
            smoothing_constant=calc_smoothing_constant(outflow),
            loss_buffer=0.0,
        )
        assert result.weeks_of_supply == 12.0
        assert result.risk == StockRisk.LOW
        assert check_air_shipment(result) is None
