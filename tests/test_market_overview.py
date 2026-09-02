import pytest

from services.market_overview import (
    NEWS_FEEDS,
    build_market_overview,
    clear_market_cache,
    coin_detail_url,
    parse_feed_items,
)

RSS = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <item>
      <title>Empresa lista Bitcoin</title>
      <link>https://livecoins.com.br/noticia/?utm_source=rss&amp;utm_medium=feed</link>
      <pubDate>Wed, 02 Sep 2026 12:00:00 +0000</pubDate>
      <description>&lt;p&gt;Resumo com &lt;b&gt;HTML&lt;/b&gt;.&lt;/p&gt;</description>
    </item>
  </channel>
</rss>
"""

ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Atom headline</title>
    <link rel="alternate" href="https://www.coindesk.com/story"/>
    <updated>2026-09-02T15:00:00Z</updated>
    <summary>Plain summary</summary>
  </entry>
</feed>
"""

GECKO_MARKETS = [
    {
        "id": "ethereum",
        "symbol": "eth",
        "name": "Ethereum",
        "image": "https://example.com/eth.png",
        "current_price": 3000.0,
        "market_cap": 360e9,
        "market_cap_rank": 2,
        "total_volume": 20e9,
        "price_change_percentage_24h": -2.5,
        "price_change_percentage_1h_in_currency": -0.4,
        "price_change_percentage_7d_in_currency": 8.1,
    },
    {
        "id": "bitcoin",
        "symbol": "btc",
        "name": "Bitcoin",
        "image": "https://example.com/btc.png",
        "current_price": 77000.0,
        "market_cap": 1500e9,
        "market_cap_rank": 1,
        "total_volume": 40e9,
        "price_change_percentage_24h": 1.2,
        "price_change_percentage_1h_in_currency": 0.3,
        "price_change_percentage_7d_in_currency": 4.0,
    },
]

PAPRIKA_GLOBAL = {
    "market_cap_usd": 2723555832772,
    "volume_24h_usd": 319223089363,
    "bitcoin_dominance_percentage": 56.93,
    "cryptocurrencies_number": 12933,
    "market_cap_change_24h": -0.32,
}

FEAR = {
    "name": "Fear and Greed Index",
    "data": [
        {
            "value": "63",
            "value_classification": "Greed",
            "timestamp": "1788307200",
            "time_until_update": "100",
        },
        {
            "value": "40",
            "value_classification": "Fear",
            "timestamp": "1788220800",
        },
    ],
}

TRENDING = {
    "coins": [
        {
            "item": {
                "id": "foo",
                "name": "Foo Coin",
                "symbol": "FOO",
                "market_cap_rank": 80,
                "thumb": "https://example.com/foo.png",
                "score": 0,
            }
        }
    ]
}


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_market_cache()
    yield
    clear_market_cache()


def test_parse_rss_strips_html_and_utm():
    items = parse_feed_items(
        RSS.encode("utf-8"),
        {"id": "livecoins", "name": "Livecoins", "lang": "pt"},
    )
    assert len(items) == 1
    item = items[0]
    assert item["title"] == "Empresa lista Bitcoin"
    assert item["url"] == "https://livecoins.com.br/noticia/"
    assert "HTML" in item["summary"]
    assert "<" not in item["summary"]
    assert item["lang"] == "pt"
    assert item["published_at"] == "2026-09-02T12:00:00+00:00"


def test_parse_atom_entries():
    items = parse_feed_items(
        ATOM.encode("utf-8"),
        {"id": "coindesk", "name": "CoinDesk", "lang": "en"},
    )
    assert items[0]["title"] == "Atom headline"
    assert items[0]["url"] == "https://www.coindesk.com/story"
    assert items[0]["summary"] == "Plain summary"


def _ok_json(url, params=None):
    if "coins/markets" in url:
        return GECKO_MARKETS
    if "coinpaprika.com/v1/global" in url:
        return PAPRIKA_GLOBAL
    if "/fng/" in url:
        return FEAR
    if "search/trending" in url:
        return TRENDING
    raise AssertionError(url)


def _ok_bytes(url):
    if "livecoins" in url:
        return RSS.encode("utf-8")
    if "coindesk" in url:
        return ATOM.encode("utf-8")
    if "cointelegraph" in url:
        return b"<rss><channel></channel></rss>"
    raise AssertionError(url)


def test_build_overview_happy_path(monkeypatch):
    monkeypatch.setattr("services.market_overview.http_json", _ok_json)
    monkeypatch.setattr("services.market_overview.http_bytes", _ok_bytes)

    payload = build_market_overview(watched_symbols=["BTC"])

    assert payload["quotes"]["ok"] is True
    assert payload["quotes"]["source"] == "coingecko"
    coins = payload["quotes"]["coins"]
    assert coins[0]["symbol"] == "BTC"
    assert coins[0]["watched"] is True
    assert coins[0]["source"] == "coingecko"
    assert coins[0]["url"] == "https://www.coingecko.com/en/coins/bitcoin"
    assert coins[1]["symbol"] == "ETH"
    assert coins[1]["watched"] is False
    assert coins[1]["source"] == "coingecko"
    assert coins[1]["url"] == "https://www.coingecko.com/en/coins/ethereum"
    assert payload["quotes"]["global"]["btc_dominance"] == pytest.approx(56.93)

    assert payload["fear"]["ok"] is True
    assert payload["fear"]["value"] == 63
    assert payload["fear"]["history"][0]["value"] == 40
    assert payload["fear"]["history"][-1]["value"] == 63

    assert payload["trending"]["ok"] is True
    assert payload["trending"]["coins"][0]["symbol"] == "FOO"
    assert payload["trending"]["coins"][0]["source"] == "coingecko"
    assert payload["trending"]["coins"][0]["url"] == "https://www.coingecko.com/en/coins/foo"
    assert payload["trending"]["gainers"][0]["symbol"] == "BTC"
    assert payload["trending"]["gainers"][0]["source"] == "coingecko"
    assert payload["trending"]["gainers"][0]["url"] == "https://www.coingecko.com/en/coins/bitcoin"
    assert payload["trending"]["losers"][0]["symbol"] == "ETH"
    assert payload["trending"]["losers"][0]["url"] == "https://www.coingecko.com/en/coins/ethereum"

    assert payload["news"]["ok"] is True
    titles = {item["title"] for item in payload["news"]["items"]}
    assert "Empresa lista Bitcoin" in titles
    assert "Atom headline" in titles
    assert len(payload["attribution"]) >= 6


def test_quotes_fall_back_to_coinpaprika(monkeypatch):
    paprika_tickers = [
        {
            "id": "btc-bitcoin",
            "name": "Bitcoin",
            "symbol": "BTC",
            "rank": 1,
            "quotes": {
                "USD": {
                    "price": 77000,
                    "volume_24h": 1,
                    "market_cap": 2,
                    "percent_change_1h": 0.1,
                    "percent_change_24h": 1.0,
                    "percent_change_7d": 2.0,
                }
            },
        }
    ]

    def json_fn(url, params=None):
        if "coins/markets" in url:
            raise RuntimeError("gecko 429")
        if "coinpaprika.com/v1/tickers" in url:
            return paprika_tickers
        if "coinpaprika.com/v1/global" in url:
            return PAPRIKA_GLOBAL
        if "/fng/" in url:
            return FEAR
        if "search/trending" in url:
            raise RuntimeError("trending down")
        raise AssertionError(url)

    monkeypatch.setattr("services.market_overview.http_json", json_fn)
    monkeypatch.setattr("services.market_overview.http_bytes", _ok_bytes)

    payload = build_market_overview(["ETH"])
    assert payload["quotes"]["ok"] is True
    assert payload["quotes"]["source"] == "coinpaprika"
    assert payload["quotes"]["coins"][0]["symbol"] == "BTC"
    assert payload["quotes"]["coins"][0]["source"] == "coinpaprika"
    assert payload["quotes"]["coins"][0]["url"] == "https://coinpaprika.com/coin/btc-bitcoin"
    assert payload["trending"]["ok"] is True
    assert payload["trending"]["source"] == "quotes"
    assert payload["trending"]["gainers"][0]["symbol"] == "BTC"
    assert payload["trending"]["gainers"][0]["url"] == "https://coinpaprika.com/coin/btc-bitcoin"
    assert payload["trending"]["coins"][0]["url"] == "https://coinpaprika.com/coin/btc-bitcoin"


def test_section_failure_does_not_kill_the_page(monkeypatch):
    def json_fn(url, params=None):
        if "/fng/" in url:
            raise RuntimeError("fear down")
        return _ok_json(url, params)

    def bytes_fn(url):
        raise RuntimeError("rss down")

    monkeypatch.setattr("services.market_overview.http_json", json_fn)
    monkeypatch.setattr("services.market_overview.http_bytes", bytes_fn)

    payload = build_market_overview()
    assert payload["quotes"]["ok"] is True
    assert payload["fear"]["ok"] is False
    assert payload["news"]["ok"] is False
    assert payload["trending"]["ok"] is True


def test_cache_survives_until_refresh(monkeypatch):
    calls = {"markets": 0}

    def json_fn(url, params=None):
        if "coins/markets" in url:
            calls["markets"] += 1
            rows = [dict(GECKO_MARKETS[1])]
            rows[0]["current_price"] = 1000 * calls["markets"]
            return rows
        return _ok_json(url, params)

    monkeypatch.setattr("services.market_overview.http_json", json_fn)
    monkeypatch.setattr("services.market_overview.http_bytes", _ok_bytes)

    first = build_market_overview()
    second = build_market_overview()
    assert first["quotes"]["coins"][0]["price_usd"] == 1000
    assert second["quotes"]["coins"][0]["price_usd"] == 1000
    assert calls["markets"] == 1

    third = build_market_overview(refresh=True)
    assert third["quotes"]["coins"][0]["price_usd"] == 2000
    assert calls["markets"] == 2


def test_coin_detail_url_uses_source_id_not_symbol():
    assert coin_detail_url("coingecko", "bitcoin") == "https://www.coingecko.com/en/coins/bitcoin"
    assert (
        coin_detail_url("coingecko", "binance-peg-dogecoin")
        == "https://www.coingecko.com/en/coins/binance-peg-dogecoin"
    )
    assert coin_detail_url("coinpaprika", "btc-bitcoin") == "https://coinpaprika.com/coin/btc-bitcoin"
    assert coin_detail_url("coinpaprika", "BTC") is None
    assert coin_detail_url("coingecko", "") is None
    assert coin_detail_url("coingecko", "../bitcoin") is None
    assert coin_detail_url("coingecko", "javascript:alert(1)") is None
    assert coin_detail_url("binance", "bitcoin") is None


def test_quotes_skip_detail_url_without_source_id(monkeypatch):
    def json_fn(url, params=None):
        if "coins/markets" in url:
            return [
                {
                    "symbol": "xyz",
                    "name": "Mystery",
                    "current_price": 1.0,
                    "market_cap": 1,
                    "market_cap_rank": 99,
                    "total_volume": 1,
                    "price_change_percentage_24h": 0.0,
                }
            ]
        return _ok_json(url, params)

    monkeypatch.setattr("services.market_overview.http_json", json_fn)
    monkeypatch.setattr("services.market_overview.http_bytes", _ok_bytes)

    payload = build_market_overview()
    coin = payload["quotes"]["coins"][0]
    assert coin["symbol"] == "XYZ"
    assert coin["id"] == "xyz"
    assert coin["source"] == "coingecko"
    assert coin["url"] is None


def test_news_feeds_are_the_curated_set():
    ids = [feed["id"] for feed in NEWS_FEEDS]
    assert ids == ["livecoins", "coindesk", "cointelegraph"]
