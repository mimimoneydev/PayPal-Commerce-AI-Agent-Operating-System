"""Gross clearing journals, not tax calculation or revenue recognition."""

from decimal import Decimal

MINOR_DIGITS = {
    "USD": 2,
    "EUR": 2,
    "GBP": 2,
    "CAD": 2,
    "AUD": 2,
    "NZD": 2,
    "CHF": 2,
    "SEK": 2,
    "NOK": 2,
    "DKK": 2,
    "JPY": 0,
    "KRW": 0,
    "UGX": 0,
    "BHD": 3,
    "KWD": 3,
}


def minor_units(amount, currency):
    if currency not in MINOR_DIGITS:
        raise ValueError("Configure accounting minor units for this currency")
    value = Decimal(str(amount)) * 10 ** MINOR_DIGITS[currency]
    if not value.is_finite() or value < 0 or value != value.to_integral_value():
        raise ValueError("Invalid money amount")
    return int(value)


def record_order(store, tenant, provider, order_id, currency, total, refunds):
    amount = minor_units(total, currency)
    store.ledger(
        tenant,
        f"{provider}-paid-{order_id}",
        currency,
        [
            {"account": "store_payment_clearing", "amount": amount},
            {"account": "order_liability", "amount": -amount},
        ],
        description="Gross paid order; reconcile fees, tax and settlement separately",
    )
    for refund in refunds:
        amount = minor_units(refund["amount"], currency)
        store.ledger(
            tenant,
            f"{provider}-refund-{refund['id']}",
            currency,
            [
                {"account": "store_payment_clearing", "amount": -amount},
                {"account": "order_liability", "amount": amount},
            ],
            description="Confirmed refund",
        )
