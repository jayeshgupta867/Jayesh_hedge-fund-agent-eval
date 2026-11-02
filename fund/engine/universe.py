"""Investable universe: about 100 large-cap US stocks with GICS sectors, plus the benchmark.

A fixed list keeps the daily download small and reproducible. It is today's list of
large caps, so a replay over past dates has survivorship bias (noted on the dashboard).
"""
BENCHMARK = "SPY"

SECTORS = {
    "Information Technology": "AAPL MSFT NVDA AVGO ORCL CRM ADBE AMD CSCO ACN IBM INTU QCOM TXN AMAT NOW MU LRCX ADI KLAC PANW",
    "Communication Services": "GOOGL META NFLX DIS TMUS VZ T CMCSA",
    "Consumer Discretionary": "AMZN TSLA HD MCD LOW NKE SBUX BKNG TJX CMG",
    "Consumer Staples": "WMT PG COST KO PEP PM MO MDLZ CL",
    "Health Care": "LLY UNH JNJ ABBV MRK TMO ABT DHR PFE AMGN ISRG GILD BMY VRTX CVS",
    "Financials": "JPM V MA BAC WFC GS MS BLK SCHW AXP C SPGI CB PGR BRK-B",
    "Industrials": "GE CAT RTX HON UNP UPS BA DE LMT ETN ADP",
    "Energy": "XOM CVX COP SLB EOG",
    "Utilities": "NEE DUK SO",
    "Real Estate": "PLD AMT EQIX",
    "Materials": "LIN SHW APD FCX",
}

UNIVERSE = {t: s for s, names in SECTORS.items() for t in names.split()}
