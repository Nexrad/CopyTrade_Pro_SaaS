"""
core/risk.py
---------------
Fast, pre-order eligibility checks (product spec section 13). Every
check here is a simple comparison against already-loaded data - no
network calls, no heavy computation, so this stays fast even with
many customers.

Nullable-limit rule (spec section 9): max_daily_loss and
max_drawdown_percent being NULL means "no limit configured" - NEVER
treated as 0, which would block every trade. This is enforced by
checking `is not None` before comparing, never by defaulting the
column to 0.

If a risk check itself throws an exception, the caller (signal_engine)
must treat that as REJECT, not as pass-through - a broken check must
never silently mean unrestricted trading (spec section 9's explicit
requirement).
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class RiskDecision:
    allowed: bool
    reason: Optional[str] = None


def evaluate(
    *,
    user_is_active: bool,
    access_status: str,
    copy_enabled: bool,
    provider_enabled: bool,
    mt5_connected: bool,
    global_emergency_stop: bool,
    open_trades_count: int,
    max_open_trades: int,
    daily_loss_so_far: float,
    max_daily_loss: Optional[float],
    drawdown_percent_so_far: float,
    max_drawdown_percent: Optional[float],
    lot_size: float,
    symbol: str,
) -> RiskDecision:
    if global_emergency_stop:
        return RiskDecision(False, "global emergency stop is active")
    if not user_is_active:
        return RiskDecision(False, "customer account is disabled")
    if access_status != "active":
        return RiskDecision(False, "challenge access is not active")
    if not copy_enabled:
        return RiskDecision(False, "copy trading is turned off")
    if not provider_enabled:
        return RiskDecision(False, "provider is disabled for this customer")
    if not mt5_connected:
        return RiskDecision(False, "MT5 account is not connected")
    if open_trades_count >= max_open_trades:
        return RiskDecision(False, "maximum open trades reached")
    if max_daily_loss is not None and daily_loss_so_far >= max_daily_loss:
        return RiskDecision(False, "maximum daily loss reached")
    if max_drawdown_percent is not None and drawdown_percent_so_far >= max_drawdown_percent:
        return RiskDecision(False, "maximum drawdown reached")
    if not symbol:
        return RiskDecision(False, "invalid symbol")
    if lot_size is None or lot_size <= 0:
        return RiskDecision(False, "invalid lot size")

    return RiskDecision(True, None)
