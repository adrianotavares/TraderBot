"""Public crypto market snapshot for the dashboard Market page.

Quotes, Fear & Greed, trending coins and news come from third-party public
APIs and RSS feeds. This module never talks to Binance.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any, Callable, Iterable, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import requests

from modules.logging_setup import log_event

USER_AGENT = "TraderBot/1.0 (dashboard market overview)"
TIMEOUT = (5, 12)
QUOTE_LIMIT = 25
NEWS_LIMIT = 30
SUMMARY_CHARS = 220

COINGECKO_MARKETS = "https://api.coingecko.com/api/v3/coins/markets"
COINGECKO_TRENDING = "https://api.coingecko.com/api/v3/search/trending"
COINGECKO_GLOBAL = "https://api.coingecko.com/api/v3/global"
COINPAPRIKA_TICKERS = "https://api.coinpaprika.com/v1/tickers"
COINPAPRIKA_GLOBAL = "https://api.coinpaprika.com/v1/global"
FEAR_GREED_URL = "https://api.alternative.me/fng/"

NEWS_FEEDS = (
    {
        "id": "livecoins",
        "name": "Livecoins",
        "url": "https://livecoins.com.br/feed/",
        "lang": "pt",
    },
    {
        "id": "coindesk",
        "name": "CoinDesk",
        "url": "https://www.coindesk.com/arc/outboundfeeds/rss/",
        "lang": "en",
    },
    {
        "id": "cointelegraph",
        "name": "Cointelegraph",
        "url": "https://cointelegraph.com/rss",
        "lang": "en",
    },
)

QUOTES_TTL = 90.0
FEAR_TTL = 3600.0
TRENDING_TTL = 600.0
NEWS_TTL = 900.0
ERROR_TTL = 30.0

_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_SPACE_RE = re.compile(r"\s+")
_COIN_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9\-]*$")

COINGECKO_COIN_URL = "https://www.coingecko.com/en/coins/{id}"
COINPAPRIKA_COIN_URL = "https://coinpaprika.com/coin/{id}"

_cache_lock = threading.Lock()
_cache: dict[str, tuple[float, Any]] = {}


def clear_market_cache() -> None:
    with _cache_lock:
        _cache.clear()


def http_json(url: str, params: Optional[dict] = None) -> Any:
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
    }
    gecko_key = os.getenv("COINGECKO_DEMO_API_KEY", "").strip()
    if gecko_key and "coingecko.com" in url:
        headers["x-cg-demo-api-key"] = gecko_key
    response = requests.get(url, params=params, headers=headers, timeout=TIMEOUT)
    response.raise_for_status()
    return response.json()


def http_bytes(url: str) -> bytes:
    response = requests.get(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
        },
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.content


def _cache_get(key: str) -> Any:
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if not hit:
            return None
        expires, value = hit
        if expires <= now:
            return None
        return value


def _cache_set(key: str, value: Any, ttl: float) -> None:
    with _cache_lock:
        _cache[key] = (time.time() + ttl, value)


def _cached(key: str, ttl: float, builder: Callable[[], Any], error_ttl: float = ERROR_TTL) -> Any:
    cached = _cache_get(key)
    if cached is not None:
        return cached
    try:
        value = builder()
        _cache_set(key, value, ttl)
        return value
    except Exception as exc:
        failed = {"ok": False, "error": str(exc)}
        _cache_set(key, failed, error_ttl)
        return failed


def _iso_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _local_tag(tag: str) -> str:
    return tag.split("}", 1)[-1] if tag else ""


def _plain_text(raw: Optional[str], limit: int = SUMMARY_CHARS) -> str:
    text = _SPACE_RE.sub(" ", _TAG_RE.sub(" ", unescape(raw or ""))).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _source_slug(value: Any) -> str:
    slug = str(value or "").strip().lower()
    if not slug or "/" in slug or ".." in slug:
        return ""
    if not _COIN_SLUG_RE.fullmatch(slug):
        return ""
    return slug


def coin_detail_url(source: str, coin_id: Any) -> Optional[str]:
    """Public coin page on the site that supplied this row, or None."""
    slug = _source_slug(coin_id)
    if not slug:
        return None
    if source == "coingecko":
        return _canonical_url(COINGECKO_COIN_URL.format(id=slug)) or None
    if source == "coinpaprika":
        # Paprika ids are `{symbol}-{name}` (e.g. btc-bitcoin). A bare ticker 404s.
        if "-" not in slug:
            return None
        return _canonical_url(COINPAPRIKA_COIN_URL.format(id=slug)) or None
    return None


def _canonical_url(url: str) -> str:
    parsed = urlparse((url or "").strip())
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.lower().startswith("utm_")
    ]
    return urlunparse(parsed._replace(query=urlencode(query), fragment=""))


def _parse_datetime(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    text = raw.strip()
    parsed: Optional[datetime] = None
    try:
        parsed = parsedate_to_datetime(text)
    except (TypeError, ValueError, OverflowError):
        parsed = None
    if parsed is None:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _child_text(node: ET.Element, names: Iterable[str]) -> str:
    wanted = {name.lower() for name in names}
    for child in list(node):
        if _local_tag(child.tag).lower() in wanted:
            return (child.text or "").strip()
    return ""


def _child_link(node: ET.Element) -> str:
    for child in list(node):
        if _local_tag(child.tag).lower() != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        if href:
            rel = (child.attrib.get("rel") or "alternate").lower()
            if rel in {"alternate", ""}:
                return href
        if child.text and child.text.strip():
            return child.text.strip()
    return ""


def parse_feed_items(payload: bytes, source: dict) -> list[dict]:
    """Parse RSS 2.0 or Atom into normalized news rows."""
    root = ET.fromstring(payload)
    items: list[dict] = []
    nodes = [
        node
        for node in root.iter()
        if _local_tag(node.tag).lower() in {"item", "entry"}
    ]
    for node in nodes:
        title = _plain_text(_child_text(node, ("title",)), limit=240)
        url = _canonical_url(_child_link(node) or _child_text(node, ("link", "guid", "id")))
        if not title or not url:
            continue
        summary = _plain_text(
            _child_text(node, ("description", "summary", "content", "encoded")),
        )
        published = _parse_datetime(
            _child_text(node, ("pubDate", "published", "updated", "date"))
        )
        items.append(
            {
                "title": title,
                "url": url,
                "source": source["name"],
                "source_id": source["id"],
                "lang": source["lang"],
                "published_at": published,
                "summary": summary,
            }
        )
    return items


def _normalize_gecko_coin(row: dict) -> Optional[dict]:
    symbol = str(row.get("symbol") or "").upper()
    name = str(row.get("name") or "").strip()
    if not symbol or not name:
        return None
    change_1h = row.get("price_change_percentage_1h_in_currency")
    change_7d = row.get("price_change_percentage_7d_in_currency")
    gecko_id = str(row.get("id") or "").strip()
    return {
        "id": gecko_id or symbol.lower(),
        "symbol": symbol,
        "name": name,
        "rank": _int(row.get("market_cap_rank")),
        "price_usd": _float(row.get("current_price")),
        "change_1h": _float(change_1h),
        "change_24h": _float(row.get("price_change_percentage_24h")),
        "change_7d": _float(change_7d),
        "volume_24h": _float(row.get("total_volume")),
        "market_cap": _float(row.get("market_cap")),
        "image": str(row.get("image") or "") or None,
        "watched": False,
        "source": "coingecko",
        "url": coin_detail_url("coingecko", gecko_id),
    }


def _normalize_paprika_coin(row: dict) -> Optional[dict]:
    symbol = str(row.get("symbol") or "").upper()
    name = str(row.get("name") or "").strip()
    if not symbol or not name:
        return None
    quote = ((row.get("quotes") or {}).get("USD") or {})
    paprika_id = str(row.get("id") or "").strip()
    return {
        "id": paprika_id or symbol.lower(),
        "symbol": symbol,
        "name": name,
        "rank": _int(row.get("rank")),
        "price_usd": _float(quote.get("price")),
        "change_1h": _float(quote.get("percent_change_1h")),
        "change_24h": _float(quote.get("percent_change_24h")),
        "change_7d": _float(quote.get("percent_change_7d")),
        "volume_24h": _float(quote.get("volume_24h")),
        "market_cap": _float(quote.get("market_cap")),
        "image": None,
        "watched": False,
        "source": "coinpaprika",
        "url": coin_detail_url("coinpaprika", paprika_id),
    }


def _fetch_gecko_quotes() -> dict:
    rows = http_json(
        COINGECKO_MARKETS,
        {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": QUOTE_LIMIT,
            "page": 1,
            "sparkline": "false",
            "price_change_percentage": "1h,24h,7d",
        },
    )
    if not isinstance(rows, list):
        raise ValueError("CoinGecko markets payload is not a list")
    coins = [coin for coin in (_normalize_gecko_coin(row) for row in rows) if coin]
    return {"ok": True, "source": "coingecko", "coins": coins}


def _fetch_paprika_quotes() -> dict:
    rows = http_json(COINPAPRIKA_TICKERS, {"quotes": "USD"})
    if not isinstance(rows, list):
        raise ValueError("CoinPaprika tickers payload is not a list")
    coins = [coin for coin in (_normalize_paprika_coin(row) for row in rows) if coin]
    coins.sort(key=lambda coin: coin.get("rank") or 10**9)
    return {"ok": True, "source": "coinpaprika", "coins": coins[:QUOTE_LIMIT]}


def _fetch_paprika_global() -> dict:
    raw = http_json(COINPAPRIKA_GLOBAL)
    return {
        "market_cap_usd": _float(raw.get("market_cap_usd")),
        "volume_24h_usd": _float(raw.get("volume_24h_usd")),
        "btc_dominance": _float(raw.get("bitcoin_dominance_percentage")),
        "market_cap_change_24h": _float(raw.get("market_cap_change_24h")),
        "cryptocurrencies": _int(raw.get("cryptocurrencies_number")),
        "source": "coinpaprika",
    }


def _fetch_gecko_global() -> dict:
    raw = http_json(COINGECKO_GLOBAL)
    data = raw.get("data") if isinstance(raw, dict) else None
    if not isinstance(data, dict):
        raise ValueError("CoinGecko global payload missing data")
    cap = data.get("total_market_cap") or {}
    volume = data.get("total_volume") or {}
    dominance = data.get("market_cap_percentage") or {}
    return {
        "market_cap_usd": _float(cap.get("usd")),
        "volume_24h_usd": _float(volume.get("usd")),
        "btc_dominance": _float(dominance.get("btc")),
        "market_cap_change_24h": _float(data.get("market_cap_change_percentage_24h_usd")),
        "cryptocurrencies": _int(data.get("active_cryptocurrencies")),
        "source": "coingecko",
    }


def _section_quotes() -> dict:
    def builder() -> dict:
        quotes_error = None
        coins_payload = None
        try:
            coins_payload = _fetch_gecko_quotes()
        except Exception as exc:
            quotes_error = exc
            try:
                coins_payload = _fetch_paprika_quotes()
            except Exception as fallback_exc:
                log_event(
                    logging.WARNING,
                    "Market quotes fetch failed",
                    event="market_quotes_failed",
                    error=str(fallback_exc),
                    gecko_error=str(quotes_error),
                )
                raise fallback_exc from quotes_error
            log_event(
                logging.WARNING,
                "Market quotes fell back to CoinPaprika",
                event="market_quotes_fallback",
                error=str(quotes_error),
            )

        global_payload = None
        try:
            global_payload = _fetch_paprika_global()
        except Exception:
            try:
                global_payload = _fetch_gecko_global()
            except Exception as exc:
                log_event(
                    logging.WARNING,
                    "Market global stats fetch failed",
                    event="market_global_failed",
                    error=str(exc),
                )
                global_payload = None

        return {
            "ok": True,
            "source": coins_payload["source"],
            "coins": coins_payload["coins"],
            "global": global_payload,
        }

    return _cached("quotes", QUOTES_TTL, builder)


def _section_fear() -> dict:
    def builder() -> dict:
        raw = http_json(FEAR_GREED_URL, {"limit": 30, "format": "json"})
        rows = raw.get("data") if isinstance(raw, dict) else None
        if not isinstance(rows, list) or not rows:
            raise ValueError("Fear & Greed payload is empty")
        history = []
        for row in rows:
            value = _int(row.get("value"))
            timestamp = _int(row.get("timestamp"))
            if value is None or timestamp is None:
                continue
            history.append(
                {
                    "value": value,
                    "classification": str(row.get("value_classification") or ""),
                    "timestamp": timestamp,
                }
            )
        if not history:
            raise ValueError("Fear & Greed history is empty")
        current = history[0]
        # API returns newest first; the sparkline wants chronological order.
        chronological = list(reversed(history))
        return {
            "ok": True,
            "source": "alternative.me",
            "value": current["value"],
            "classification": current["classification"],
            "timestamp": current["timestamp"],
            "time_until_update": _int(rows[0].get("time_until_update")),
            "history": chronological,
        }

    result = _cached("fear", FEAR_TTL, builder)
    if not result.get("ok"):
        log_event(
            logging.WARNING,
            "Market Fear & Greed fetch failed",
            event="market_fear_failed",
            error=result.get("error"),
        )
    return result


def _normalize_trending_coin(row: dict) -> Optional[dict]:
    item = row.get("item") if isinstance(row, dict) else None
    if not isinstance(item, dict):
        return None
    symbol = str(item.get("symbol") or "").upper()
    name = str(item.get("name") or "").strip()
    if not symbol or not name:
        return None
    gecko_id = str(item.get("id") or item.get("slug") or "").strip()
    return {
        "id": gecko_id or symbol.lower(),
        "symbol": symbol,
        "name": name,
        "rank": _int(item.get("market_cap_rank")),
        "score": _int(item.get("score")),
        "thumb": str(item.get("thumb") or item.get("small") or "") or None,
        "source": "coingecko",
        "url": coin_detail_url("coingecko", gecko_id),
    }


def _movers(coins: list[dict], reverse: bool, limit: int = 5) -> list[dict]:
    ranked = [
        coin
        for coin in coins
        if coin.get("change_24h") is not None
    ]
    ranked.sort(key=lambda coin: coin["change_24h"], reverse=reverse)
    return [
        {
            "id": coin["id"],
            "symbol": coin["symbol"],
            "name": coin["name"],
            "change_24h": coin["change_24h"],
            "price_usd": coin.get("price_usd"),
            "source": coin.get("source"),
            "url": coin.get("url"),
        }
        for coin in ranked[:limit]
    ]


def _section_trending(quotes: dict) -> dict:
    def builder() -> dict:
        raw = http_json(COINGECKO_TRENDING)
        coins = [
            coin
            for coin in (
                _normalize_trending_coin(row) for row in (raw.get("coins") or [])
            )
            if coin
        ]
        return {"ok": True, "source": "coingecko", "coins": coins}

    result = _cached("trending", TRENDING_TTL, builder)
    quote_coins = list(quotes.get("coins") or []) if quotes.get("ok") else []
    gainers = _movers(quote_coins, reverse=True)
    losers = _movers(quote_coins, reverse=False)
    if result.get("ok"):
        payload = dict(result)
        payload["gainers"] = gainers
        payload["losers"] = losers
        return payload
    log_event(
        logging.WARNING,
        "Market trending fetch failed",
        event="market_trending_failed",
        error=result.get("error"),
    )
    if quote_coins:
        return {
            "ok": True,
            "source": "quotes",
            "coins": [
                {
                    "id": coin["id"],
                    "symbol": coin["symbol"],
                    "name": coin["name"],
                    "rank": coin.get("rank"),
                    "score": None,
                    "thumb": coin.get("image") or coin.get("thumb"),
                    "source": coin.get("source"),
                    "url": coin.get("url"),
                }
                for coin in gainers
            ],
            "gainers": gainers,
            "losers": losers,
            "error": result.get("error"),
        }
    return result


def _fetch_one_feed(source: dict) -> list[dict]:
    try:
        return parse_feed_items(http_bytes(source["url"]), source)
    except Exception as exc:
        log_event(
            logging.WARNING,
            "Market news feed failed",
            event="market_news_feed_failed",
            source=source["id"],
            error=str(exc),
        )
        return []


def _section_news() -> dict:
    def builder() -> dict:
        items: list[dict] = []
        seen: set[str] = set()
        for source in NEWS_FEEDS:
            for item in _fetch_one_feed(source):
                key = item["url"]
                if key in seen:
                    continue
                seen.add(key)
                items.append(item)
        items.sort(key=lambda row: row.get("published_at") or "", reverse=True)
        if not items:
            raise ValueError("Nenhum feed de notícias respondeu")
        return {"ok": True, "items": items[:NEWS_LIMIT]}

    result = _cached("news", NEWS_TTL, builder)
    if not result.get("ok"):
        log_event(
            logging.WARNING,
            "Market news fetch failed",
            event="market_news_failed",
            error=result.get("error"),
        )
    return result


def _apply_watched(quotes: dict, watched_symbols: Iterable[str]) -> dict:
    watched = {symbol.upper() for symbol in watched_symbols if symbol}
    payload = dict(quotes)
    coins = [dict(coin) for coin in (quotes.get("coins") or [])]
    for coin in coins:
        coin["watched"] = coin.get("symbol", "").upper() in watched
    coins.sort(key=lambda coin: (not coin["watched"], coin.get("rank") or 10**9))
    payload["coins"] = coins
    if quotes.get("global") is not None:
        payload["global"] = dict(quotes["global"])
    return payload


def build_market_overview(
    watched_symbols: Optional[Iterable[str]] = None,
    *,
    refresh: bool = False,
) -> dict:
    """Aggregate the Market page payload. Each section fails independently."""
    if refresh:
        clear_market_cache()
    quotes = _section_quotes()
    if quotes.get("ok"):
        quotes = _apply_watched(quotes, watched_symbols or [])
    fear = _section_fear()
    trending = _section_trending(quotes if quotes.get("ok") else {})
    news = _section_news()
    return {
        "updated_at": _iso_now(),
        "quotes": quotes,
        "fear": fear,
        "trending": trending,
        "news": news,
        "attribution": [
            {
                "name": "CoinGecko",
                "url": "https://www.coingecko.com/en/api",
                "role": "cotações e tendências",
            },
            {
                "name": "CoinPaprika",
                "url": "https://coinpaprika.com/api",
                "role": "estatísticas globais (fallback de cotações)",
            },
            {
                "name": "alternative.me",
                "url": "https://alternative.me/crypto/fear-and-greed-index/",
                "role": "Fear & Greed Index",
            },
            {
                "name": "Livecoins",
                "url": "https://livecoins.com.br/",
                "role": "notícias em português",
            },
            {
                "name": "CoinDesk",
                "url": "https://www.coindesk.com/",
                "role": "notícias",
            },
            {
                "name": "Cointelegraph",
                "url": "https://cointelegraph.com/",
                "role": "notícias",
            },
            {
                "name": "Modular Cripto",
                "url": "https://modularcrypto.xyz/",
                "role": "conteúdo em português (site, sem API/RSS público)",
            },
        ],
    }
