"""TradingView Screenshot Analysis — additive visual-confirmation layer.

Nothing in this package is imported by, or feeds back into, the existing
engines (strategies/risk/entry/regime/structure/indicators/recommendation/
expected_move/long_term_plan) or the EODHD market-data path. See
``apexinvest/api/screenshot.py`` for the single integration point (a new,
independent API route) and each module's own docstring for the source-
priority rules this layer follows (screenshot primary, EODHD secondary,
never fabricate, never silently reconcile a conflict).
"""
