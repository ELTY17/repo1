"""Agente 1 — NOTICIAS.

Lee titulares reales (RSS) y produce un sentimiento por instrumento mediante un
lexicon financiero. Sin dependencias externas ni claves de API.
"""
from __future__ import annotations

import re
import ssl
import urllib.request
import xml.etree.ElementTree as ET

from ..config import UNIVERSE
from ..indicators import clamp
from .base import Agent

FEEDS = [
    ("https://cointelegraph.com/rss", "crypto"),
    ("https://feeds.a.dj.com/rss/RSSMarketsMain.xml", "equity"),
    ("https://news.google.com/rss/search?q=stock+market+OR+nasdaq+OR+s%26p+500&hl=en-US&gl=US&ceid=US:en", "equity"),
    ("https://news.google.com/rss/search?q=bitcoin+OR+ethereum+OR+solana&hl=en-US&gl=US&ceid=US:en", "crypto"),
    ("https://news.google.com/rss/search?q=xrp+OR+cardano+OR+chainlink+OR+avalanche+OR+litecoin&hl=en-US&gl=US&ceid=US:en", "crypto"),
    ("https://news.google.com/rss/search?q=altcoins+OR+defi+OR+uniswap+OR+aave+OR+cosmos&hl=en-US&gl=US&ceid=US:en", "crypto"),
]

POSITIVE = {
    "surge": 2, "surges": 2, "rally": 2, "rallies": 2, "soar": 3, "soars": 3,
    "jump": 2, "jumps": 2, "gain": 1, "gains": 1, "rise": 1, "rises": 1,
    "record": 2, "high": 1, "highs": 1, "bullish": 3, "bull": 2, "boom": 2,
    "beat": 2, "beats": 2, "upgrade": 2, "upgraded": 2, "breakout": 2,
    "inflow": 2, "inflows": 2, "adoption": 1, "approval": 2, "approved": 2,
    "optimism": 2, "strong": 1, "outperform": 2, "recovery": 2, "rebound": 2,
}
NEGATIVE = {
    "plunge": -3, "plunges": -3, "crash": -3, "crashes": -3, "slump": -2,
    "slumps": -2, "fall": -1, "falls": -1, "drop": -2, "drops": -2,
    "tumble": -2, "tumbles": -2, "sink": -2, "sinks": -2, "bearish": -3,
    "bear": -2, "selloff": -3, "sell-off": -3, "loss": -1, "losses": -1,
    "low": -1, "lows": -1, "downgrade": -2, "downgraded": -2, "fear": -2,
    "fears": -2, "risk": -1, "warning": -2, "warns": -2, "hack": -3,
    "hacked": -3, "exploit": -3, "lawsuit": -2, "ban": -2, "outflow": -2,
    "outflows": -2, "recession": -3, "liquidation": -2, "liquidations": -2,
    "collapse": -3, "slide": -2, "slides": -2, "weak": -1, "sell": -1,
}

KEYWORDS = {
    "BTC-USD": ["bitcoin", "btc"],
    "ETH-USD": ["ethereum", "ether", "eth"],
    "SOL-USD": ["solana", "sol"],
    "XRP-USD": ["xrp", "ripple"],
    "ADA-USD": ["cardano", "ada"],
    "DOT-USD": ["polkadot", "dot"],
    "LINK-USD": ["chainlink", "link"],
    "AVAX-USD": ["avalanche", "avax"],
    "LTC-USD": ["litecoin", "ltc"],
    "ATOM-USD": ["cosmos", "atom"],
    "UNI-USD": ["uniswap", "uni"],
    "AAVE-USD": ["aave"],
    "FIL-USD": ["filecoin", "fil"],
    "NEAR-USD": ["near protocol", "near"],
    "XLM-USD": ["stellar", "xlm", "lumens"],
    "BCH-USD": ["bitcoin cash", "bch"],
    "ETC-USD": ["ethereum classic", "etc"],
    "SPY": ["s&p", "s&p 500", "sp500", "wall street", "stocks", "equities", "spy"],
    "QQQ": ["nasdaq", "tech stocks", "qqq", "big tech"],
}

_WORD = re.compile(r"[a-z&\-]+")


def _fetch_titles(url: str, limit: int = 40) -> list[str]:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=12, context=ctx) as r:
        raw = r.read()
    root = ET.fromstring(raw)
    titles = []
    for item in root.iter():
        if item.tag.endswith("item") or item.tag.endswith("entry"):
            for child in item:
                if child.tag.endswith("title") and child.text:
                    titles.append(child.text.strip())
                    break
        if len(titles) >= limit:
            break
    return titles


def score_headline(title: str) -> int:
    words = _WORD.findall(title.lower())
    return sum(POSITIVE.get(w, 0) + NEGATIVE.get(w, 0) for w in words)


class NewsAgent(Agent):
    name = "news"
    role = "Lee titulares de mercado y mide el sentimiento"
    emoji = "N"

    def __init__(self, ctx):
        super().__init__(ctx)
        self.interval = ctx.cfg.news_seconds
        self.headlines: list[dict] = []

    def step(self):
        titles: list[tuple[str, str]] = []
        ok_feeds = 0
        for url, kind in FEEDS:
            try:
                for t in _fetch_titles(url):
                    titles.append((t, kind))
                ok_feeds += 1
            except Exception:                            # noqa: BLE001,S110
                continue

        if not titles:
            self.say("sin acceso a fuentes de noticias; sentimiento neutro")
            self.output = {"sentiment": {i.symbol: 0.0 for i in UNIVERSE},
                           "headlines": [], "feeds_ok": 0, "analyzed": 0}
            return

        scored = []
        for t, kind in titles:
            s = score_headline(t)
            if s != 0:
                scored.append({"title": t[:150], "score": s, "kind": kind})

        sentiment = {}
        for inst in UNIVERSE:
            # Un instrumento nuevo sin palabras clave no debe tumbar al agente:
            # se queda con el tono general de su clase, que es el reparto por
            # defecto de todas formas.
            kws = KEYWORDS.get(inst.symbol, [])
            hits = [h for h in scored
                    if any(k in h["title"].lower() for k in kws)]
            if not hits:
                # sin menciones directas -> tono general de su clase de activo
                hits = [h for h in scored if h["kind"] == inst.kind]
            if hits:
                avg = sum(h["score"] for h in hits) / len(hits)
                sentiment[inst.symbol] = round(clamp(avg / 3.0), 3)
            else:
                sentiment[inst.symbol] = 0.0

        self.headlines = sorted(scored, key=lambda h: -abs(h["score"]))[:12]
        self.output = {
            "sentiment": sentiment,
            "headlines": self.headlines,
            "feeds_ok": ok_feeds,
            "analyzed": len(titles),
        }
        best = max(sentiment, key=lambda k: sentiment[k])
        worst = min(sentiment, key=lambda k: sentiment[k])
        self.say(f"{len(titles)} titulares de {ok_feeds} fuentes | "
                 f"mejor tono: {best} ({sentiment[best]:+.2f}) | "
                 f"peor: {worst} ({sentiment[worst]:+.2f})")
