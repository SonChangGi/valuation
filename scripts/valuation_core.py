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
