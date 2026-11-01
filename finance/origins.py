"""Source ids across scrapers (shared by the digest and the views)."""

# RiseUp tags transactions with its own origin names; map them to our source ids
# so a CAL charge from riseup and the same charge from data/cal/ dedup together.
RISEUP_ORIGIN = {
    "cal": "cal",
    "leumicard": "max",                          # Max (ex-Leumi Card): RiseUp's cards 3819/9613
    "americanexpress": "amex", "isracard": "amex",
    "discount": "discount", "leumiBank": "leumi", "leumi": "leumi",
}
