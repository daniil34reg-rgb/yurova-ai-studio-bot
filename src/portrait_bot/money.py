from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

MONEY_STEP = Decimal("0.01")


def money(value: Decimal | int | str) -> Decimal:
    return Decimal(str(value)).quantize(MONEY_STEP, rounding=ROUND_HALF_UP)


def parse_money(value: str) -> Decimal:
    normalized = value.strip().replace(" ", "").replace(",", ".")
    try:
        result = money(normalized)
    except InvalidOperation as exc:
        raise ValueError("invalid_money") from exc
    if not result.is_finite():
        raise ValueError("invalid_money")
    return result


def format_rub(value: Decimal | int | str) -> str:
    amount = money(value)
    if amount == amount.to_integral():
        return f"{int(amount):,}".replace(",", " ") + " ₽"
    return f"{amount:,.2f}".replace(",", " ").replace(".", ",") + " ₽"


def setting_enabled(value: str, *, default: bool = False) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on", "да", "вкл"}:
        return True
    if normalized in {"0", "false", "no", "off", "нет", "выкл"}:
        return False
    return default


def parse_amount_list(value: str) -> tuple[Decimal, ...]:
    amounts: list[Decimal] = []
    for raw in value.replace(";", ",").split(","):
        if not raw.strip():
            continue
        amount = parse_money(raw)
        if amount > 0 and amount not in amounts:
            amounts.append(amount)
    return tuple(amounts[:10])
