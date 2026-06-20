"""Shared valuation math and data-shaping helpers.

The project intentionally keeps forecast variables few and explicit.  These
functions are pure so both data generation and tests can reason about the same
contract without network access.
"""

from __future__ import annotations

from statistics import median
from typing import Any


DEFAULT_ASSUMPTIONS = {
    "projectionYears": 5,
    "growthRate": 0.04,
    "discountRate": 0.09,
    "terminalGrowthRate": 0.025,
    "benchmarkPe": 22.0,
    "benchmarkPb": 4.0,
    "benchmarkPs": 5.0,
    "benchmarkPfcf": 20.0,
}

SENSITIVITY_DISCOUNT_RATES = [0.08, 0.09, 0.10]
SENSITIVITY_TERMINAL_RATES = [0.015, 0.025, 0.035]
IMPLIED_EXPLICIT_GROWTH_BOUNDS = (-0.10, 0.18)
IMPLIED_TERMINAL_GROWTH_BOUNDS = (-0.02, 0.045)


class ValuationError(ValueError):
    """Raised when assumptions cannot produce a meaningful valuation."""


def safe_div(numerator: float | int | None, denominator: float | int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    try:
        denominator_f = float(denominator)
        if denominator_f == 0:
            return None
        return float(numerator) / denominator_f
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def cagr(start: float | None, end: float | None, years: int) -> float | None:
    if start is None or end is None or years <= 0 or start <= 0 or end <= 0:
        return None
    return (end / start) ** (1 / years) - 1


def derive_growth_rate(annual_rows: list[dict[str, Any]]) -> float:
    """Derive a conservative explicit-growth default from recent fundamentals.

    The result is capped because the product goal is a few-variable decision aid,
    not an aggressive extrapolation engine.
    """

    rows = sorted([row for row in annual_rows if row.get("revenue")], key=lambda r: r.get("fy") or 0)
    if len(rows) >= 2:
        oldest = rows[0]
        latest = rows[-1]
        years = max(1, int(latest.get("fy", 0) or 0) - int(oldest.get("fy", 0) or 0))
        revenue_cagr = cagr(oldest.get("revenue"), latest.get("revenue"), years)
        if revenue_cagr is not None:
            return round(clamp(revenue_cagr, -0.05, 0.12), 4)

    fcf_values = [row.get("freeCashFlow") for row in annual_rows if row.get("freeCashFlow") is not None]
    if len(fcf_values) >= 2 and fcf_values[0] and fcf_values[-1] and fcf_values[0] > 0 and fcf_values[-1] > 0:
        growth = cagr(float(fcf_values[0]), float(fcf_values[-1]), len(fcf_values) - 1)
        if growth is not None:
            return round(clamp(growth, -0.05, 0.12), 4)

    return DEFAULT_ASSUMPTIONS["growthRate"]


def normalize_fcf(annual_rows: list[dict[str, Any]], lookback: int = 3) -> float | None:
    recent = sorted(annual_rows, key=lambda r: r.get("fy") or 0, reverse=True)[:lookback]
    positive = [row.get("freeCashFlow") for row in recent if row.get("freeCashFlow") is not None and row.get("freeCashFlow") > 0]
    if positive:
        return float(median(positive))
    values = [row.get("freeCashFlow") for row in recent if row.get("freeCashFlow") is not None]
    return float(values[0]) if values else None


def _diagnostic_flag(level: str, title: str, detail: str) -> dict[str, str]:
    return {"level": level, "title": title, "detail": detail}


def _finite_numbers(values: list[float | int | None]) -> list[float]:
    usable: list[float] = []
    for value in values:
        try:
            number = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
        if number == number and number not in {float("inf"), float("-inf")}:
            usable.append(number)
    return usable


def summarize_sensitivity(
    sensitivity: list[dict[str, Any]],
    *,
    base_value: float | None,
    market_price: float | None,
) -> dict[str, Any]:
    """Compress a DCF sensitivity matrix into a user-readable fragility signal."""

    values = _finite_numbers(
        [
            cell.get("perShareValue")
            for row in sensitivity
            for cell in (row.get("values") or [])
        ]
    )
    if not values:
        return {
            "low": None,
            "mid": None,
            "high": None,
            "rangeWidth": None,
            "rangeToBase": None,
            "priceCoverage": "unavailable",
            "fragility": "unavailable",
            "flags": [_diagnostic_flag("warning", "민감도 계산 불가", "DCF 민감도 행렬을 만들 수 없어 단일 가치의 취약성을 판단할 수 없습니다.")],
            "interpretation": "민감도는 할인율과 영구성장률의 작은 변화가 주당가치에 주는 영향을 보는 장치입니다.",
        }

    low = min(values)
    high = max(values)
    mid = median(values)
    range_width = high - low
    range_to_base = safe_div(range_width, abs(base_value)) if base_value not in (None, 0) else None
    price = float(market_price) if market_price not in (None, 0) else None
    values_above_price = sum(1 for value in values if price is not None and value >= price)
    values_below_price = sum(1 for value in values if price is not None and value < price)
    price_coverage = "unavailable"
    if price is not None:
        if values_above_price and values_below_price:
            price_coverage = "mixed"
        elif values_above_price:
            price_coverage = "above_price"
        elif values_below_price:
            price_coverage = "below_price"

    if range_to_base is None:
        fragility = "unavailable"
    elif range_to_base >= 0.75:
        fragility = "fragile"
    elif range_to_base >= 0.35:
        fragility = "sensitive"
    else:
        fragility = "stable"

    flags: list[dict[str, str]] = []
    if fragility == "fragile":
        flags.append(_diagnostic_flag("warning", "민감도 범위 매우 넓음", "할인율·영구성장률의 작은 변화가 기준 DCF 가치를 크게 흔듭니다. 단일 가치보다 범위를 우선하세요."))
    elif fragility == "sensitive":
        flags.append(_diagnostic_flag("watch", "민감도 확인 필요", "DCF 범위가 기준값 대비 의미 있게 넓습니다. 낙관·비관 가정의 근거를 나눠 검토하세요."))
    if price_coverage == "mixed":
        flags.append(_diagnostic_flag("watch", "현재가 판단이 가정에 따라 뒤집힘", "민감도 행렬 안에서 현재가보다 높은 칸과 낮은 칸이 모두 있습니다. 결론보다 가정 검증이 우선입니다."))

    return {
        "low": low,
        "mid": mid,
        "high": high,
        "rangeWidth": range_width,
        "rangeToBase": range_to_base,
        "valuesAbovePrice": values_above_price if price is not None else None,
        "valuesBelowPrice": values_below_price if price is not None else None,
        "priceCoverage": price_coverage,
        "fragility": fragility,
        "flags": flags,
        "interpretation": "민감도 범위는 DCF가 정밀한 목표가인지, 아니면 가정 취약성 지도를 먼저 읽어야 하는지 알려줍니다.",
    }


def _solve_monotonic_rate(
    *,
    target_value: float,
    lower: float,
    upper: float,
    value_at_rate,
    iterations: int = 64,
) -> dict[str, Any]:
    lower_value = value_at_rate(lower)
    upper_value = value_at_rate(upper)
    if lower_value is None or upper_value is None:
        return {
            "status": "not_available",
            "rate": None,
            "lowerBound": lower,
            "upperBound": upper,
            "valueAtLowerBound": lower_value,
            "valueAtUpperBound": upper_value,
        }
    if target_value < lower_value:
        return {
            "status": "below_range",
            "rate": None,
            "lowerBound": lower,
            "upperBound": upper,
            "valueAtLowerBound": lower_value,
            "valueAtUpperBound": upper_value,
        }
    if target_value > upper_value:
        return {
            "status": "above_range",
            "rate": None,
            "lowerBound": lower,
            "upperBound": upper,
            "valueAtLowerBound": lower_value,
            "valueAtUpperBound": upper_value,
        }

    lo = lower
    hi = upper
    mid = (lo + hi) / 2
    mid_value = value_at_rate(mid)
    for _ in range(iterations):
        mid = (lo + hi) / 2
        mid_value = value_at_rate(mid)
        if mid_value is None:
            break
        if mid_value < target_value:
            lo = mid
        else:
            hi = mid
    return {
        "status": "solved",
        "rate": mid,
        "lowerBound": lower,
        "upperBound": upper,
        "valueAtLowerBound": lower_value,
        "valueAtUpperBound": upper_value,
        "valueAtSolvedRate": mid_value,
    }


def build_reverse_dcf(
    *,
    market_price: float | None,
    base_fcf: float | None,
    shares_outstanding: float | None,
    cash: float,
    debt: float,
    growth_rate: float,
    discount_rate: float,
    terminal_growth_rate: float,
    projection_years: int = DEFAULT_ASSUMPTIONS["projectionYears"],
) -> dict[str, Any]:
    """Infer what market price implies under the current sparse DCF structure."""

    if (
        market_price is None
        or market_price <= 0
        or base_fcf is None
        or base_fcf <= 0
        or shares_outstanding is None
        or shares_outstanding <= 0
        or discount_rate <= terminal_growth_rate
    ):
        return {
            "status": "not_available",
            "marketPrice": market_price,
            "targetEquityValue": None,
            "explicitGrowth": None,
            "terminalGrowth": None,
            "flags": [_diagnostic_flag("warning", "Reverse DCF 제한", "시장가격, 양수 FCF, 주식수, 할인율 조건이 모두 있어야 내재 기대를 역산할 수 있습니다.")],
            "interpretation": "Reverse DCF는 현재가가 어떤 성장 가정을 요구하는지 보는 보조 분석입니다.",
        }

    target_equity_value = market_price * shares_outstanding

    def value_with_growth(rate: float) -> float | None:
        try:
            return calculate_dcf(
                base_fcf=base_fcf,
                shares_outstanding=shares_outstanding,
                cash=cash,
                debt=debt,
                growth_rate=rate,
                discount_rate=discount_rate,
                terminal_growth_rate=terminal_growth_rate,
                projection_years=projection_years,
            )["perShareValue"]
        except ValuationError:
            return None

    terminal_lower, terminal_upper = IMPLIED_TERMINAL_GROWTH_BOUNDS
    terminal_upper = min(terminal_upper, discount_rate - 0.015)

    def value_with_terminal(rate: float) -> float | None:
        try:
            return calculate_dcf(
                base_fcf=base_fcf,
                shares_outstanding=shares_outstanding,
                cash=cash,
                debt=debt,
                growth_rate=growth_rate,
                discount_rate=discount_rate,
                terminal_growth_rate=rate,
                projection_years=projection_years,
            )["perShareValue"]
        except ValuationError:
            return None

    explicit = _solve_monotonic_rate(
        target_value=market_price,
        lower=IMPLIED_EXPLICIT_GROWTH_BOUNDS[0],
        upper=IMPLIED_EXPLICIT_GROWTH_BOUNDS[1],
        value_at_rate=value_with_growth,
    )
    terminal = (
        _solve_monotonic_rate(
            target_value=market_price,
            lower=terminal_lower,
            upper=terminal_upper,
            value_at_rate=value_with_terminal,
        )
        if terminal_upper > terminal_lower
        else {"status": "not_available", "rate": None, "lowerBound": terminal_lower, "upperBound": terminal_upper}
    )
    flags: list[dict[str, str]] = []
    if explicit["status"] == "above_range":
        flags.append(_diagnostic_flag("warning", "시장가가 높은 성장 기대 요구", "현재가를 설명하려면 보수적 상단을 넘는 명시 성장률이 필요합니다. 성장 옵션의 현실성을 직접 검토하세요."))
    elif explicit["status"] == "below_range":
        flags.append(_diagnostic_flag("watch", "시장가가 낮은 성장 기대 반영", "현재가가 보수적 성장 범위보다 낮은 DCF를 암시합니다. 구조적 악화나 데이터 오류 가능성을 확인하세요."))
    if terminal["status"] == "above_range":
        flags.append(_diagnostic_flag("warning", "영구성장률 상단 초과 요구", "현재가를 설명하려면 장기 안정성장 가정이 보수적 상단을 넘습니다. 터미널 가치 의존도를 특히 주의하세요."))

    return {
        "status": "available",
        "marketPrice": market_price,
        "targetEquityValue": target_equity_value,
        "explicitGrowth": explicit,
        "terminalGrowth": terminal,
        "flags": flags,
        "interpretation": "Reverse DCF는 목표가를 제시하지 않고, 현재 시장가격이 어떤 성장률/영구성장률을 요구하는지 보여줍니다.",
    }


def build_relative_quality_gate(
    *,
    eps: float | None,
    book_value_per_share: float | None,
    roe: float | None,
    net_margin: float | None,
    fcf_margin: float | None,
    headline_count: int,
    benchmark_source: str,
) -> dict[str, Any]:
    """Classify whether PER/PBR can be used as headline evidence."""

    checks = [
        {"key": "positive_eps", "label": "EPS 양수", "passed": eps is not None and eps > 0},
        {"key": "positive_bps", "label": "BPS 양수", "passed": book_value_per_share is not None and book_value_per_share > 0},
        {"key": "headline_pair", "label": "PER/PBR 모두 산출", "passed": headline_count >= 2},
        {"key": "user_confirmed", "label": "사용자 비교배수 확인", "passed": benchmark_source != "illustrative-default"},
        {"key": "profit_quality", "label": "수익성 신호 양호", "passed": (net_margin is None or net_margin > 0) and (fcf_margin is None or fcf_margin >= 0)},
        {"key": "roe_context", "label": "ROE 맥락 확인", "passed": roe is None or roe >= 0.08},
    ]
    blocking = [check for check in checks[:3] if not check["passed"]]
    if blocking:
        status = "limited"
        label = "사용 제한"
        detail = "EPS/BPS 또는 PER/PBR 산출 조건이 부족해 상대가치를 핵심 결론으로 쓰기 어렵습니다."
    elif benchmark_source == "illustrative-default":
        status = "needs_user_review"
        label = "검토 전"
        detail = "기본 배수는 예시값입니다. 비교기업의 산업·성장률·ROE 유사성을 확인해야 합니다."
    elif not checks[4]["passed"] or not checks[5]["passed"]:
        status = "usable_with_caution"
        label = "사용자 확인·주의"
        detail = "사용자가 배수를 확인했지만 수익성/현금흐름 품질 신호가 약해 보수적으로 해석해야 합니다."
    else:
        status = "usable"
        label = "사용자 확인됨"
        detail = "사용자가 비교배수를 확인했고 기본 수익성 신호가 통과했습니다. 모델 검증이 아니라 사용자 입력 기준이므로 DCF와 분리해서 보세요."

    return {
        "status": status,
        "label": label,
        "checks": checks,
        "detail": detail,
        "interpretation": "상대가치는 싸다/비싸다 자동판정이 아니라 비교군 품질을 통과했는지 확인하는 절차입니다.",
    }


def build_dcf_diagnostics(
    *,
    present_value_of_forecast: float,
    present_value_of_terminal: float,
    enterprise_value: float,
    equity_value: float,
    cash: float,
    debt: float,
    discount_rate: float,
    terminal_growth_rate: float,
) -> dict[str, Any]:
    """Return literature-aligned DCF guardrails without adding forecast variables."""

    terminal_value_weight = safe_div(present_value_of_terminal, enterprise_value)
    forecast_value_weight = safe_div(present_value_of_forecast, enterprise_value)
    terminal_spread = discount_rate - terminal_growth_rate
    net_debt = float(debt or 0) - float(cash or 0)
    flags: list[dict[str, str]] = []

    if terminal_value_weight is not None and terminal_value_weight >= 0.75:
        flags.append(
            _diagnostic_flag(
                "warning",
                "터미널 가치 집중",
                "기업가치의 75% 이상이 명시 예측 이후에서 나옵니다. 영구성장률과 할인율 근거를 보수적으로 재점검하세요.",
            )
        )
    elif terminal_value_weight is not None and terminal_value_weight >= 0.6:
        flags.append(
            _diagnostic_flag(
                "watch",
                "터미널 가치 영향 큼",
                "기업가치의 상당 부분이 터미널 가치입니다. 단일 주당가치보다 민감도 범위를 함께 읽으세요.",
            )
        )

    if terminal_spread < 0.025:
        flags.append(
            _diagnostic_flag(
                "warning",
                "할인율-영구성장률 간격 좁음",
                "작은 가정 변화가 터미널 가치를 크게 바꿀 수 있습니다. 장기 성장률이 지속 가능한지 확인하세요.",
            )
        )

    if terminal_growth_rate > 0.035:
        flags.append(
            _diagnostic_flag(
                "watch",
                "영구성장률 상단 근접",
                "영구성장률은 장기 경제 성장과 재투자 여력을 넘기 어렵다는 전제를 명시하세요.",
            )
        )

    if equity_value <= 0:
        flags.append(
            _diagnostic_flag(
                "warning",
                "자기자본가치 비양수",
                "순부채 조정 이후 자기자본가치가 0 이하입니다. 부채·현금·주식수 데이터를 원문에서 확인하세요.",
            )
        )

    return {
        "terminalValueWeight": terminal_value_weight,
        "forecastValueWeight": forecast_value_weight,
        "terminalSpread": terminal_spread,
        "netDebt": net_debt,
        "flags": flags,
        "interpretation": "DCF는 FCFF의 현재가치와 안정성장 터미널 가치를 분리해서 읽어야 하며, 터미널 비중이 높을수록 가정 검증이 더 중요합니다.",
    }


def calculate_dcf(
    base_fcf: float,
    shares_outstanding: float,
    cash: float = 0.0,
    debt: float = 0.0,
    growth_rate: float = DEFAULT_ASSUMPTIONS["growthRate"],
    discount_rate: float = DEFAULT_ASSUMPTIONS["discountRate"],
    terminal_growth_rate: float = DEFAULT_ASSUMPTIONS["terminalGrowthRate"],
    projection_years: int = DEFAULT_ASSUMPTIONS["projectionYears"],
) -> dict[str, Any]:
    if shares_outstanding <= 0:
        raise ValuationError("shares_outstanding must be positive")
    if discount_rate <= terminal_growth_rate:
        raise ValuationError("discount_rate must be greater than terminal_growth_rate")
    if projection_years < 1:
        raise ValuationError("projection_years must be at least 1")

    projected = []
    pv_sum = 0.0
    fcf = float(base_fcf)
    for year in range(1, projection_years + 1):
        fcf *= 1 + growth_rate
        pv = fcf / ((1 + discount_rate) ** year)
        pv_sum += pv
        projected.append({"year": year, "freeCashFlow": fcf, "presentValue": pv})

    terminal_fcf = fcf * (1 + terminal_growth_rate)
    terminal_value = terminal_fcf / (discount_rate - terminal_growth_rate)
    terminal_present_value = terminal_value / ((1 + discount_rate) ** projection_years)
    enterprise_value = pv_sum + terminal_present_value
    equity_value = enterprise_value + float(cash or 0) - float(debt or 0)
    per_share = equity_value / shares_outstanding
    diagnostics = build_dcf_diagnostics(
        present_value_of_forecast=pv_sum,
        present_value_of_terminal=terminal_present_value,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        cash=float(cash or 0),
        debt=float(debt or 0),
        discount_rate=discount_rate,
        terminal_growth_rate=terminal_growth_rate,
    )

    return {
        "baseFreeCashFlow": base_fcf,
        "projectedFreeCashFlows": projected,
        "presentValueOfForecast": pv_sum,
        "terminalValue": terminal_value,
        "presentValueOfTerminal": terminal_present_value,
        "enterpriseValue": enterprise_value,
        "equityValue": equity_value,
        "perShareValue": per_share,
        "diagnostics": diagnostics,
    }


def build_sensitivity(
    base_fcf: float,
    shares_outstanding: float,
    cash: float,
    debt: float,
    growth_rate: float,
    projection_years: int = DEFAULT_ASSUMPTIONS["projectionYears"],
) -> list[dict[str, Any]]:
    matrix = []
    for discount in SENSITIVITY_DISCOUNT_RATES:
        row = {"discountRate": discount, "values": []}
        for terminal in SENSITIVITY_TERMINAL_RATES:
            try:
                value = calculate_dcf(
                    base_fcf=base_fcf,
                    shares_outstanding=shares_outstanding,
                    cash=cash,
                    debt=debt,
                    growth_rate=growth_rate,
                    discount_rate=discount,
                    terminal_growth_rate=terminal,
                    projection_years=projection_years,
                )["perShareValue"]
            except ValuationError:
                value = None
            row["values"].append({"terminalGrowthRate": terminal, "perShareValue": value})
        matrix.append(row)
    return matrix


def calculate_relative_valuation(
    price: float | None,
    revenue: float | None,
    net_income: float | None,
    equity: float | None,
    free_cash_flow: float | None,
    shares_outstanding: float,
    benchmark_pe: float = DEFAULT_ASSUMPTIONS["benchmarkPe"],
    benchmark_pb: float = DEFAULT_ASSUMPTIONS["benchmarkPb"],
    benchmark_ps: float = DEFAULT_ASSUMPTIONS["benchmarkPs"],
    benchmark_pfcf: float = DEFAULT_ASSUMPTIONS["benchmarkPfcf"],
    benchmark_source: str = "illustrative-default",
) -> dict[str, Any]:
    if shares_outstanding <= 0:
        raise ValuationError("shares_outstanding must be positive")

    eps = safe_div(net_income, shares_outstanding)
    book_value_per_share = safe_div(equity, shares_outstanding)
    sales_per_share = safe_div(revenue, shares_outstanding)
    fcf_per_share = safe_div(free_cash_flow, shares_outstanding)
    roe = safe_div(net_income, equity)
    net_margin = safe_div(net_income, revenue)
    fcf_margin = safe_div(free_cash_flow, revenue)
    earnings_yield = safe_div(eps, price)

    rows = [
        {
            "key": "pe",
            "label": "PER",
            "baseMetric": eps,
            "currentMultiple": safe_div(price, eps) if eps and eps > 0 else None,
            "benchmarkMultiple": benchmark_pe,
            "impliedValue": eps * benchmark_pe if eps and eps > 0 else None,
            "description": "순이익 1주당 이익(EPS)에 비교 PER을 곱한 값",
        },
        {
            "key": "pb",
            "label": "PBR",
            "baseMetric": book_value_per_share,
            "currentMultiple": safe_div(price, book_value_per_share) if book_value_per_share and book_value_per_share > 0 else None,
            "benchmarkMultiple": benchmark_pb,
            "impliedValue": book_value_per_share * benchmark_pb if book_value_per_share and book_value_per_share > 0 else None,
            "description": "1주당 순자산(BPS)에 비교 PBR을 곱한 값",
        },
        {
            "key": "ps",
            "label": "P/S",
            "baseMetric": sales_per_share,
            "currentMultiple": safe_div(price, sales_per_share) if sales_per_share and sales_per_share > 0 else None,
            "benchmarkMultiple": benchmark_ps,
            "impliedValue": sales_per_share * benchmark_ps if sales_per_share and sales_per_share > 0 else None,
            "description": "1주당 매출에 비교 P/S를 곱한 보조 값",
        },
        {
            "key": "pfcf",
            "label": "P/FCF",
            "baseMetric": fcf_per_share,
            "currentMultiple": safe_div(price, fcf_per_share) if fcf_per_share and fcf_per_share > 0 else None,
            "benchmarkMultiple": benchmark_pfcf,
            "impliedValue": fcf_per_share * benchmark_pfcf if fcf_per_share and fcf_per_share > 0 else None,
            "description": "1주당 자유현금흐름에 비교 P/FCF를 곱한 보조 값",
        },
    ]
    headline_values = [
        row["impliedValue"]
        for row in rows
        if row["key"] in {"pe", "pb"} and row.get("impliedValue") is not None
    ]
    auxiliary_values = [
        row["impliedValue"]
        for row in rows
        if row["key"] not in {"pe", "pb"} and row.get("impliedValue") is not None
    ]
    flags: list[dict[str, str]] = []
    if eps is None or eps <= 0:
        flags.append(_diagnostic_flag("warning", "PER 사용 제한", "EPS가 양수가 아니면 PER 기반 암시 주가를 핵심 결론으로 쓰지 마세요."))
    if book_value_per_share is None or book_value_per_share <= 0:
        flags.append(_diagnostic_flag("warning", "PBR 사용 제한", "BPS가 양수가 아니면 PBR 비교가 경제적으로 취약합니다."))
    if roe is not None and roe < 0.08 and book_value_per_share and book_value_per_share > 0:
        flags.append(_diagnostic_flag("watch", "ROE 확인 필요", "PBR은 장부가치만이 아니라 지속 가능한 ROE와 함께 해석해야 합니다."))
    if fcf_margin is not None and fcf_margin < 0:
        flags.append(_diagnostic_flag("watch", "현금흐름 괴리", "순이익과 달리 FCF가 약하면 운전자본·CAPEX·일회성 요인을 확인하세요."))
    quality_gate = build_relative_quality_gate(
        eps=eps,
        book_value_per_share=book_value_per_share,
        roe=roe,
        net_margin=net_margin,
        fcf_margin=fcf_margin,
        headline_count=len(headline_values),
        benchmark_source=benchmark_source,
    )

    return {
        "perShareMetrics": {
            "eps": eps,
            "bookValuePerShare": book_value_per_share,
            "salesPerShare": sales_per_share,
            "freeCashFlowPerShare": fcf_per_share,
        },
        "qualitySignals": {
            "roe": roe,
            "netMargin": net_margin,
            "fcfMargin": fcf_margin,
            "earningsYield": earnings_yield,
        },
        "rows": rows,
        "range": {
            "low": min(headline_values) if headline_values else None,
            "mid": median(headline_values) if headline_values else None,
            "high": max(headline_values) if headline_values else None,
            "basis": "PER/PBR headline only",
            "confirmed": benchmark_source != "illustrative-default",
        },
        "auxiliaryRange": {
            "low": min(auxiliary_values) if auxiliary_values else None,
            "mid": median(auxiliary_values) if auxiliary_values else None,
            "high": max(auxiliary_values) if auxiliary_values else None,
            "basis": "P/S and P/FCF auxiliary cross-check only",
        },
        "benchmarkSource": benchmark_source,
        "benchmarkNote": "기본 배수는 예시값이며 사용자가 산업/비교기업 기준으로 확인해야 합니다.",
        "diagnostics": {
            "usableHeadlineMultiples": len(headline_values),
            "qualityGate": quality_gate,
            "flags": flags,
            "interpretation": "시장 배수는 성장률·수익성·위험·회계 품질이 비슷한 비교군을 전제로 할 때만 의미가 커집니다.",
        },
    }


def classify_quality(warnings: list[str], fatal_missing: bool = False) -> str:
    if fatal_missing:
        return "수동 확인 필요"
    if warnings:
        return "일부 누락"
    return "충분"
