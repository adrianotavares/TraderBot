/**
 * Tracking charts built on TradingView Lightweight Charts (Apache 2.0).
 *
 * Each card shows one asset: candles, the regime ribbon, the position entry and
 * the take profit / stop loss levels. The library has no native "position on
 * chart" widget, so levels are price lines and fills are series markers.
 */
(function () {
    "use strict";

    var LWC = window.LightweightCharts;
    var TZ = "America/Sao_Paulo";
    var liveEntries = [];
    var OVERLAY_STORAGE_KEY = "traderbot.chartOverlays";
    var DEFAULT_OVERLAYS = {
        sma: true,
        volume: true,
        rsi: true,
        ema: false,
        adx: false,
    };
    var MAIN_PANE_STRETCH = 6;
    var INDICATOR_PANE_STRETCH = 1.5;
    var HIDDEN_PANE_STRETCH = 0.0001;

    function cssVar(name, fallback) {
        var value = getComputedStyle(document.documentElement)
            .getPropertyValue(name)
            .trim();
        return value || fallback;
    }

    function hexToRgba(hex, alpha) {
        var raw = (hex || "").replace("#", "").trim();
        if (raw.length === 3) {
            raw = raw
                .split("")
                .map(function (ch) {
                    return ch + ch;
                })
                .join("");
        }
        var n = parseInt(raw, 16);
        if (!raw || raw.length !== 6 || !isFinite(n)) {
            return "rgba(21, 101, 192, " + alpha + ")";
        }
        return (
            "rgba(" +
            ((n >> 16) & 255) +
            ", " +
            ((n >> 8) & 255) +
            ", " +
            (n & 255) +
            ", " +
            alpha +
            ")"
        );
    }

    // Mirrors the --md-* custom properties in app.css (Lights / Dark).
    function readColors() {
        return {
            up: cssVar("--md-up", "#1b7f3a"),
            down: cssVar("--md-down", "#b3261e"),
            info: cssVar("--md-info", "#1565c0"),
            warn: cssVar("--md-warn", "#e65100"),
            entry: cssVar("--md-on-surface-variant", "#5c5c57"),
            grid: cssVar("--md-chart-grid", "#eceff1"),
            text: cssVar("--md-on-surface-variant", "#5c5c57"),
            sma: cssVar("--md-chart-sma", "#7b1fa2"),
            emaFast: cssVar("--md-chart-ema-fast", "#00838f"),
            emaSlow: cssVar("--md-chart-ema-slow", "#5e35b1"),
            rsi: cssVar("--md-chart-rsi", "#c2185b"),
            adx: cssVar("--md-chart-adx", "#6d4c41"),
        };
    }

    var COLORS = readColors();

    function normalizeOverlays(flags) {
        var next = {
            sma: DEFAULT_OVERLAYS.sma,
            volume: DEFAULT_OVERLAYS.volume,
            rsi: DEFAULT_OVERLAYS.rsi,
            ema: DEFAULT_OVERLAYS.ema,
            adx: DEFAULT_OVERLAYS.adx,
        };
        if (!flags || typeof flags !== "object") return next;
        ["sma", "volume", "rsi", "ema", "adx"].forEach(function (key) {
            if (typeof flags[key] === "boolean") next[key] = flags[key];
        });
        return next;
    }

    function loadOverlays() {
        try {
            var raw = localStorage.getItem(OVERLAY_STORAGE_KEY);
            if (!raw) return normalizeOverlays(null);
            return normalizeOverlays(JSON.parse(raw));
        } catch (err) {
            return normalizeOverlays(null);
        }
    }

    function saveOverlays(flags) {
        try {
            localStorage.setItem(OVERLAY_STORAGE_KEY, JSON.stringify(flags));
        } catch (err) {
            // Private mode / quota — chips still work for this session.
        }
    }

    var overlayFlags = loadOverlays();
    saveOverlays(overlayFlags);

    function overlayMeta(asset) {
        return (asset && asset.indicators && asset.indicators.meta) || {};
    }

    function volumeBars(candles, volumes) {
        var byTime = {};
        (candles || []).forEach(function (candle) {
            byTime[candle.time] = candle;
        });
        var up = hexToRgba(COLORS.up, 0.55);
        var down = hexToRgba(COLORS.down, 0.55);
        return (volumes || []).map(function (point) {
            var candle = byTime[point.time];
            var bull = candle ? candle.close >= candle.open : true;
            return {
                time: point.time,
                value: point.value,
                color: bull ? up : down,
            };
        });
    }

    function oscillatorScale() {
        return function () {
            return { priceRange: { minValue: 0, maxValue: 100 } };
        };
    }

    function paneStretch(on) {
        return on ? INDICATOR_PANE_STRETCH : HIDDEN_PANE_STRETCH;
    }

    function applyOverlayVisibility(handle) {
        if (!handle || handle.mode !== "asset" || !handle.overlays) return;
        var flags = overlayFlags;
        handle.overlays.sma.applyOptions({ visible: !!flags.sma });
        handle.overlays.emaFast.applyOptions({ visible: !!flags.ema });
        handle.overlays.emaSlow.applyOptions({ visible: !!flags.ema });
        handle.overlays.volume.applyOptions({ visible: !!flags.volume });
        handle.overlays.rsi.applyOptions({ visible: !!flags.rsi });
        handle.overlays.adx.applyOptions({ visible: !!flags.adx });
        if (handle.overlayPanes) {
            if (handle.overlayPanes.volume) {
                handle.overlayPanes.volume.setStretchFactor(paneStretch(flags.volume));
            }
            if (handle.overlayPanes.rsi) {
                handle.overlayPanes.rsi.setStretchFactor(paneStretch(flags.rsi));
            }
            if (handle.overlayPanes.adx) {
                handle.overlayPanes.adx.setStretchFactor(paneStretch(flags.adx));
            }
        }
        var panes = handle.chart.panes && handle.chart.panes();
        if (panes && panes[0] && panes[0].setStretchFactor) {
            panes[0].setStretchFactor(MAIN_PANE_STRETCH);
        }
    }

    function refreshEntryOverlays(entry) {
        var handle = entry.handle;
        applyOverlayVisibility(handle);
        if (handle.mode === "asset" && handle.lastAsset) {
            renderLegend(
                handle,
                entry.card,
                handle.lastAsset,
                handle.lastPrecision || 2
            );
        }
    }

    function chartLayoutOptions() {
        return {
            layout: {
                background: { color: "transparent" },
                textColor: COLORS.text,
                fontFamily: "Roboto, system-ui, sans-serif",
                fontSize: 11,
                attributionLogo: false,
            },
            grid: {
                vertLines: { color: COLORS.grid },
                horzLines: { color: COLORS.grid },
            },
        };
    }

    function applyThemeToHandle(handle) {
        handle.chart.applyOptions(chartLayoutOptions());
        if (handle.candles) {
            handle.candles.applyOptions({
                upColor: COLORS.up,
                downColor: COLORS.down,
                borderUpColor: COLORS.up,
                borderDownColor: COLORS.down,
                wickUpColor: COLORS.up,
                wickDownColor: COLORS.down,
            });
        }
        if (handle.trailing) {
            handle.trailing.applyOptions({ color: COLORS.info });
        }
        if (handle.overlays) {
            handle.overlays.sma.applyOptions({ color: COLORS.sma });
            handle.overlays.emaFast.applyOptions({ color: COLORS.emaFast });
            handle.overlays.emaSlow.applyOptions({ color: COLORS.emaSlow });
            handle.overlays.rsi.applyOptions({ color: COLORS.rsi });
            handle.overlays.adx.applyOptions({ color: COLORS.adx });
            if (handle.lastAsset) {
                var indicators = handle.lastAsset.indicators || {};
                handle.overlays.volume.setData(
                    volumeBars(handle.lastAsset.candles, indicators.volume)
                );
            }
            if (handle.rsiBands) {
                var bandColor = hexToRgba(COLORS.text, 0.45);
                handle.rsiBands.low.applyOptions({ color: bandColor });
                handle.rsiBands.high.applyOptions({ color: bandColor });
            }
        }
        if (handle.equity) {
            handle.equity.applyOptions({
                lineColor: COLORS.info,
                topColor: hexToRgba(COLORS.info, 0.35),
                bottomColor: hexToRgba(COLORS.info, 0.05),
            });
        }
        handle.priceLines.forEach(function (item) {
            item.line.applyOptions({ color: colorForRole(item.role) });
        });
    }

    function applyTheme() {
        COLORS = readColors();
        liveEntries.forEach(function (entry) {
            applyThemeToHandle(entry.handle);
        });
    }

    var REGIME_COLORS = {
        TREND: "rgba(27, 127, 58, 0.85)",
        LATERAL: "rgba(230, 81, 0, 0.85)",
        GRAY: "rgba(158, 158, 153, 0.70)",
    };
    var REGIME_NAMES = ["TREND", "LATERAL", "GRAY"];
    var TRANSPARENT = "rgba(0, 0, 0, 0)";

    var REGIME_LABELS = {
        TREND: "Tendência",
        LATERAL: "Lateral",
        GRAY: "Indefinido",
    };

    var dateFormat = new Intl.DateTimeFormat("pt-BR", {
        timeZone: TZ,
        day: "2-digit",
        month: "2-digit",
    });
    var timeFormat = new Intl.DateTimeFormat("pt-BR", {
        timeZone: TZ,
        hour: "2-digit",
        minute: "2-digit",
    });
    var fullFormat = new Intl.DateTimeFormat("pt-BR", {
        timeZone: TZ,
        day: "2-digit",
        month: "2-digit",
        year: "numeric",
        hour: "2-digit",
        minute: "2-digit",
    });

    /**
     * The API sends true UTC epoch seconds; the axis is rendered in the
     * bot's timezone instead of shifting the timestamps.
     */
    function toDate(seconds) {
        return new Date(seconds * 1000);
    }

    function tickMark(seconds, tickMarkType) {
        var date = toDate(seconds);
        // 3 = Time, 4 = TimeWithSeconds. Anything coarser is a date tick.
        return tickMarkType >= 3 ? timeFormat.format(date) : dateFormat.format(date);
    }

    function precisionFor(price) {
        var value = Math.abs(Number(price) || 0);
        if (value >= 10) return 2;
        if (value >= 1) return 4;
        if (value >= 0.01) return 5;
        return 8;
    }

    function formatPrice(price, precision) {
        if (price == null || !isFinite(price)) return "—";
        return Number(price).toLocaleString("pt-BR", {
            minimumFractionDigits: precision,
            maximumFractionDigits: precision,
        });
    }

    function formatPct(value) {
        if (value == null || !isFinite(value)) return "—";
        var sign = value > 0 ? "+" : "";
        return sign + Number(value).toFixed(2) + "%";
    }

    function element(tag, className, text) {
        var node = document.createElement(tag);
        if (className) node.className = className;
        if (text != null) node.textContent = text;
        return node;
    }

    function buildCard(asset) {
        var isEquity = asset.series === "equity";
        var card = element("article", "chart-card" + (isEquity ? " equity" : ""));

        var header = element("header", "chart-header");
        var title = element("div", "chart-title");
        title.appendChild(element("span", "chart-ticker", asset.stock_code));
        var price = element("span", "chart-price", "—");
        title.appendChild(price);
        header.appendChild(title);

        var badges = element("div", "chart-badges");
        var regime = element("span", "regime-badge", "—");
        var pnl = element("span", "chart-pnl", "");
        if (isEquity) {
            regime.hidden = true;
        }
        badges.appendChild(regime);
        badges.appendChild(pnl);
        header.appendChild(badges);
        card.appendChild(header);

        var canvas = element("div", "chart-canvas");
        card.appendChild(canvas);

        var legend = element("footer", "chart-legend");
        card.appendChild(legend);

        var error = element("p", "chart-error");
        error.hidden = true;
        card.appendChild(error);

        return {
            root: card,
            canvas: canvas,
            price: price,
            regime: regime,
            pnl: pnl,
            legend: legend,
            error: error,
        };
    }

    function buildChart(canvas) {
        var chart = LWC.createChart(
            canvas,
            Object.assign(
                {
                    autoSize: true,
                    rightPriceScale: { borderVisible: false },
                    timeScale: {
                        borderVisible: false,
                        timeVisible: true,
                        secondsVisible: false,
                        tickMarkFormatter: tickMark,
                    },
                    crosshair: { mode: LWC.CrosshairMode.Normal },
                    localization: {
                        locale: "pt-BR",
                        timeFormatter: function (seconds) {
                            return fullFormat.format(toDate(seconds));
                        },
                    },
                    handleScale: { axisPressedMouseMove: false },
                },
                chartLayoutOptions()
            )
        );

        // One area series per regime, on an overlay price scale that is
        // invisible by default. A histogram would leave a gap between bars and
        // read as a barcode; area fills broken by whitespace points give one
        // contiguous block per regime run. Created before the candles so the
        // candles draw on top.
        var bands = {};
        REGIME_NAMES.forEach(function (name) {
            bands[name] = chart.addSeries(LWC.AreaSeries, {
                priceScaleId: "regime",
                lineWidth: 1,
                lineColor: TRANSPARENT,
                topColor: REGIME_COLORS[name],
                bottomColor: REGIME_COLORS[name],
                lastValueVisible: false,
                priceLineVisible: false,
                crosshairMarkerVisible: false,
            });
        });
        chart.priceScale("regime").applyOptions({
            scaleMargins: { top: 0.9, bottom: 0 },
        });

        var candles = chart.addSeries(LWC.CandlestickSeries, {
            upColor: COLORS.up,
            downColor: COLORS.down,
            borderUpColor: COLORS.up,
            borderDownColor: COLORS.down,
            wickUpColor: COLORS.up,
            wickDownColor: COLORS.down,
            // The header already shows the last price. On the chart it would
            // add a fourth horizontal line in the same green as the take
            // profit, and an axis label over the price ticks.
            lastValueVisible: false,
            priceLineVisible: false,
        });
        // Keep the candles clear of the regime band at the bottom.
        chart.priceScale("right").applyOptions({
            scaleMargins: { top: 0.08, bottom: 0.16 },
        });

        var trailing = chart.addSeries(LWC.LineSeries, {
            color: COLORS.info,
            lineWidth: 1,
            lineStyle: LWC.LineStyle.Dotted,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
        });

        var sma = chart.addSeries(LWC.LineSeries, {
            color: COLORS.sma,
            lineWidth: 2,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
        });
        var emaFast = chart.addSeries(LWC.LineSeries, {
            color: COLORS.emaFast,
            lineWidth: 1,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
        });
        var emaSlow = chart.addSeries(LWC.LineSeries, {
            color: COLORS.emaSlow,
            lineWidth: 1,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: false,
        });

        // Volume / RSI / ADX sit on extra panes (LWC v5 addPane). Hidden
        // overlays keep their series mounted and collapse pane stretch so
        // toggling does not remount or reset the visible time range.
        var volumePane = chart.addPane(true);
        var rsiPane = chart.addPane(true);
        var adxPane = chart.addPane(true);

        var volume = volumePane.addSeries(LWC.HistogramSeries, {
            priceFormat: { type: "volume" },
            lastValueVisible: false,
            priceLineVisible: false,
        });
        volume.priceScale().applyOptions({
            scaleMargins: { top: 0.15, bottom: 0 },
        });

        var rsi = rsiPane.addSeries(LWC.LineSeries, {
            color: COLORS.rsi,
            lineWidth: 1,
            lastValueVisible: false,
            priceLineVisible: false,
            priceFormat: { type: "price", precision: 2, minMove: 0.01 },
            autoscaleInfoProvider: oscillatorScale(),
        });
        rsi.priceScale().applyOptions({
            scaleMargins: { top: 0.12, bottom: 0.12 },
        });
        var bandColor = hexToRgba(COLORS.text, 0.45);
        var rsiLow = rsi.createPriceLine({
            price: 40,
            color: bandColor,
            lineWidth: 1,
            lineStyle: LWC.LineStyle.Dashed,
            axisLabelVisible: false,
            title: "",
        });
        var rsiHigh = rsi.createPriceLine({
            price: 60,
            color: bandColor,
            lineWidth: 1,
            lineStyle: LWC.LineStyle.Dashed,
            axisLabelVisible: false,
            title: "",
        });

        var adx = adxPane.addSeries(LWC.LineSeries, {
            color: COLORS.adx,
            lineWidth: 1,
            lastValueVisible: false,
            priceLineVisible: false,
            priceFormat: { type: "price", precision: 2, minMove: 0.01 },
            autoscaleInfoProvider: oscillatorScale(),
        });
        adx.priceScale().applyOptions({
            scaleMargins: { top: 0.12, bottom: 0.12 },
        });

        var handle = {
            chart: chart,
            mode: "asset",
            candles: candles,
            bands: bands,
            trailing: trailing,
            overlays: {
                sma: sma,
                emaFast: emaFast,
                emaSlow: emaSlow,
                volume: volume,
                rsi: rsi,
                adx: adx,
            },
            overlayPanes: {
                volume: volumePane,
                rsi: rsiPane,
                adx: adxPane,
            },
            rsiBands: { low: rsiLow, high: rsiHigh },
            markers: LWC.createSeriesMarkers(candles, []),
            priceLines: [],
            fitted: false,
            lastTime: null,
            windowSeconds: null,
            lastAsset: null,
            lastPrecision: 2,
        };
        applyOverlayVisibility(handle);
        return handle;
    }

    function buildEquityChart(canvas) {
        var chart = LWC.createChart(
            canvas,
            Object.assign(
                {
                    autoSize: true,
                    rightPriceScale: { borderVisible: false },
                    timeScale: {
                        borderVisible: false,
                        timeVisible: true,
                        secondsVisible: false,
                        tickMarkFormatter: tickMark,
                    },
                    crosshair: { mode: LWC.CrosshairMode.Normal },
                    localization: {
                        locale: "pt-BR",
                        timeFormatter: function (seconds) {
                            return fullFormat.format(toDate(seconds));
                        },
                    },
                    handleScale: { axisPressedMouseMove: false },
                },
                chartLayoutOptions()
            )
        );

        var equity = chart.addSeries(LWC.AreaSeries, {
            lineColor: COLORS.info,
            topColor: hexToRgba(COLORS.info, 0.35),
            bottomColor: hexToRgba(COLORS.info, 0.05),
            lineWidth: 2,
            lastValueVisible: false,
            priceLineVisible: false,
            crosshairMarkerVisible: true,
        });
        chart.priceScale("right").applyOptions({
            scaleMargins: { top: 0.08, bottom: 0.08 },
        });

        return {
            chart: chart,
            mode: "equity",
            equity: equity,
            priceLines: [],
            fitted: false,
            lastTime: null,
            windowSeconds: null,
        };
    }

    function applyTimeWindow(handle) {
        var scale = handle.chart.timeScale();
        var last = handle.lastTime;
        var seconds = handle.windowSeconds;
        if (last == null || !seconds) {
            scale.fitContent();
            return;
        }
        try {
            scale.setVisibleRange({
                from: last - seconds,
                to: last,
            });
        } catch (err) {
            scale.fitContent();
        }
    }

    function restoreOrFit(handle) {
        if (handle.fitted) {
            return;
        }
        applyTimeWindow(handle);
        handle.fitted = true;
    }

    function priceSeries(handle) {
        return handle.mode === "equity" ? handle.equity : handle.candles;
    }

    function clearPriceLines(handle) {
        var series = priceSeries(handle);
        handle.priceLines.forEach(function (item) {
            series.removePriceLine(item.line);
        });
        handle.priceLines = [];
    }

    function colorForRole(role) {
        if (role === "tp") return COLORS.up;
        if (role === "sl") return COLORS.down;
        if (role === "sr") return COLORS.warn;
        return COLORS.entry;
    }

    function addPriceLine(handle, price, role, title, style) {
        handle.priceLines.push({
            role: role,
            line: priceSeries(handle).createPriceLine({
                price: price,
                color: colorForRole(role),
                lineWidth: 1,
                lineStyle: style,
                axisLabelVisible: false,
                title: title,
            }),
        });
    }

    /** Whitespace between runs breaks the fill, so each run is its own block. */
    function bandData(points, name) {
        return points.map(function (point) {
            return point.regime === name
                ? { time: point.time, value: 1 }
                : { time: point.time };
        });
    }

    function renderLegend(handle, card, asset, precision) {
        clearPriceLines(handle);
        card.legend.textContent = "";

        var items = [];
        var levels = asset.levels;
        if (!levels) {
            items.push({ cls: "flat", text: "Sem posição aberta" });
        } else {
            appendLevelItems(handle, items, levels, precision);
        }
        if ((asset.trailing_stop || []).length && handle.mode === "asset") {
            items.push({ cls: "trail", text: "Trailing stop (ATR)" });
        }
        appendOverlayLegend(handle, items, asset);
        appendChannelItems(handle, items, asset, precision);

        items.forEach(function (item) {
            card.legend.appendChild(
                element("span", "legend-item " + item.cls, item.text)
            );
        });
    }

    function appendLevelItems(handle, items, levels, precision) {
        if (levels.take_profit) {
            addPriceLine(
                handle,
                levels.take_profit.price,
                "tp",
                "TP " + formatPct(levels.take_profit.pct),
                LWC.LineStyle.Dashed
            );
            items.push({
                cls: "tp",
                text:
                    "TP " +
                    formatPct(levels.take_profit.pct) +
                    " · " +
                    formatPrice(levels.take_profit.price, precision),
            });
        }
        addPriceLine(
            handle,
            levels.entry,
            "entry",
            "Entrada",
            LWC.LineStyle.Solid
        );
        items.push({
            cls: "entry",
            text: "Entrada " + formatPrice(levels.entry, precision),
        });
        if (levels.stop_loss) {
            var slPrefix = levels.stop_loss.trailing ? "SL trail -" : "SL -";
            addPriceLine(
                handle,
                levels.stop_loss.price,
                "sl",
                slPrefix + levels.stop_loss.pct.toFixed(2) + "%",
                LWC.LineStyle.Dashed
            );
            items.push({
                cls: "sl",
                text:
                    slPrefix +
                    levels.stop_loss.pct.toFixed(2) +
                    "% · " +
                    formatPrice(levels.stop_loss.price, precision),
            });
        }
    }

    function appendOverlayLegend(handle, items, asset) {
        if (handle.mode !== "asset") return;
        var flags = overlayFlags;
        var meta = overlayMeta(asset);
        if (flags.sma) {
            items.push({
                cls: "sma",
                text: "SMA " + (meta.sma_period || ""),
            });
        }
        if (flags.ema) {
            items.push({
                cls: "ema-fast",
                text: "EMA " + (meta.ema_fast || ""),
            });
            items.push({
                cls: "ema-slow",
                text: "EMA " + (meta.ema_slow || ""),
            });
        }
        if (flags.volume) {
            items.push({ cls: "volume", text: "Volume" });
        }
        if (flags.rsi) {
            items.push({
                cls: "rsi",
                text: "RSI " + (meta.rsi_period || ""),
            });
        }
        if (flags.adx) {
            items.push({
                cls: "adx",
                text: "ADX " + (meta.adx_period || ""),
            });
        }
    }

    function appendChannelItems(handle, items, asset, precision) {
        if (handle.mode !== "asset") return;
        var current = asset.current_regime;
        if (!current) return;
        if (current.support != null && isFinite(current.support)) {
            addPriceLine(
                handle,
                current.support,
                "sr",
                "Suporte",
                LWC.LineStyle.Dashed
            );
            items.push({
                cls: "sr",
                text: "Suporte " + formatPrice(current.support, precision),
            });
        }
        if (current.resistance != null && isFinite(current.resistance)) {
            addPriceLine(
                handle,
                current.resistance,
                "sr",
                "Resistência",
                LWC.LineStyle.Dashed
            );
            items.push({
                cls: "sr",
                text: "Resistência " + formatPrice(current.resistance, precision),
            });
        }
    }

    function syncRsiBands(handle, meta) {
        if (!handle.rsiBands || !meta) return;
        var low = Number(meta.rsi_low);
        var high = Number(meta.rsi_high);
        if (isFinite(low)) handle.rsiBands.low.applyOptions({ price: low });
        if (isFinite(high)) handle.rsiBands.high.applyOptions({ price: high });
    }

    function renderHeader(card, asset, precision) {
        var position = asset.position || {};
        var isEquity = asset.series === "equity";
        var last = isEquity
            ? (asset.equity || []).length
                ? asset.equity[asset.equity.length - 1].value
                : null
            : asset.candles.length
              ? asset.candles[asset.candles.length - 1].close
              : null;
        card.price.textContent = formatPrice(last, precision);

        if (isEquity) {
            card.regime.hidden = true;
        } else {
            card.regime.hidden = false;
            var current = asset.current_regime;
            var name = current ? current.regime : null;
            card.regime.className =
                "regime-badge " + (name ? name.toLowerCase() : "unknown");
            card.regime.textContent = name ? REGIME_LABELS[name] || name : "—";
            card.regime.title = current
                ? "Score " +
                  current.score +
                  " · ADX " +
                  current.adx +
                  " · RSI " +
                  current.rsi +
                  (current.provisional ? " (candle em formação)" : "")
                : "";
        }

        var pnl = position.open ? position.pnl_pct : null;
        if (isEquity && position.pnl_pct != null) {
            pnl = position.pnl_pct;
        }
        card.pnl.className =
            "chart-pnl " + (pnl == null ? "" : pnl > 0 ? "up" : pnl < 0 ? "down" : "");
        card.pnl.textContent = pnl == null ? "" : formatPct(pnl);
    }

    function markerFor(marker) {
        var buy = marker.side === "BUY";
        return {
            time: marker.time,
            position: buy ? "belowBar" : "aboveBar",
            color: buy ? COLORS.up : COLORS.down,
            shape: buy ? "arrowUp" : "arrowDown",
            text: buy ? "C" : "V",
        };
    }

    function updateAsset(handle, card, asset) {
        if (!asset.candles || !asset.candles.length) {
            card.error.hidden = false;
            card.error.textContent = "Sem candles para exibir.";
            return;
        }

        var lastCandle = asset.candles[asset.candles.length - 1];
        var last = lastCandle.close;
        var precision = precisionFor(last);
        handle.candles.applyOptions({
            priceFormat: {
                type: "price",
                precision: precision,
                minMove: Math.pow(10, -precision),
            },
        });

        var range = handle.fitted
            ? handle.chart.timeScale().getVisibleLogicalRange()
            : null;

        handle.candles.setData(asset.candles);
        handle.lastTime = lastCandle.time;
        var regime = asset.regime || [];
        REGIME_NAMES.forEach(function (name) {
            handle.bands[name].setData(bandData(regime, name));
        });
        handle.trailing.setData(asset.trailing_stop || []);
        handle.markers.setMarkers((asset.markers || []).map(markerFor));

        var indicators = asset.indicators || {};
        if (handle.overlays) {
            handle.overlays.sma.setData(indicators.sma || []);
            handle.overlays.emaFast.setData(indicators.ema_fast || []);
            handle.overlays.emaSlow.setData(indicators.ema_slow || []);
            handle.overlays.volume.setData(
                volumeBars(asset.candles, indicators.volume)
            );
            handle.overlays.rsi.setData(indicators.rsi || []);
            handle.overlays.adx.setData(indicators.adx || []);
            syncRsiBands(handle, indicators.meta);
            applyOverlayVisibility(handle);
        }

        handle.lastAsset = asset;
        handle.lastPrecision = precision;
        renderHeader(card, asset, precision);
        renderLegend(handle, card, asset, precision);

        if (range) {
            handle.chart.timeScale().setVisibleLogicalRange(range);
        } else {
            restoreOrFit(handle);
        }
    }

    function updateEquity(handle, card, asset) {
        var series = asset.equity || [];
        if (!series.length) {
            card.error.hidden = false;
            card.error.textContent = "Sem dados de portfólio para exibir.";
            return;
        }

        var precision = 2;
        handle.equity.applyOptions({
            priceFormat: {
                type: "price",
                precision: precision,
                minMove: 0.01,
            },
        });

        var range = handle.fitted
            ? handle.chart.timeScale().getVisibleLogicalRange()
            : null;

        handle.equity.setData(series);
        handle.lastTime = series[series.length - 1].time;
        handle.lastAsset = asset;
        handle.lastPrecision = precision;
        renderHeader(card, asset, precision);
        renderLegend(handle, card, asset, precision);

        if (range) {
            handle.chart.timeScale().setVisibleLogicalRange(range);
        } else {
            restoreOrFit(handle);
        }
    }

    function update(handle, card, asset) {
        if (asset.error) {
            card.error.hidden = false;
            card.error.textContent = "Não foi possível carregar: " + asset.error;
            return;
        }
        card.error.hidden = true;

        if (asset.series === "equity") {
            updateEquity(handle, card, asset);
            return;
        }
        updateAsset(handle, card, asset);
    }

    window.TraderBotChart = {
        available: Boolean(LWC),

        /** Build a card for `asset` and append it to `parent`. */
        mount: function (parent, asset, options) {
            var card = buildCard(asset);
            parent.appendChild(card.root);
            var handle =
                asset.series === "equity"
                    ? buildEquityChart(card.canvas)
                    : buildChart(card.canvas);
            handle.windowSeconds = options && options.windowSeconds;
            var entry = { card: card, handle: handle };
            liveEntries.push(entry);
            update(handle, card, asset);
            return entry;
        },

        update: function (entry, asset) {
            update(entry.handle, entry.card, asset);
        },

        /** Zoom the already-loaded series to the last `seconds` of market time. */
        setWindow: function (entry, seconds) {
            entry.handle.windowSeconds = seconds;
            applyTimeWindow(entry.handle);
            entry.handle.fitted = true;
        },

        getOverlays: function () {
            return {
                sma: overlayFlags.sma,
                volume: overlayFlags.volume,
                rsi: overlayFlags.rsi,
                ema: overlayFlags.ema,
                adx: overlayFlags.adx,
            };
        },

        /** Show/hide overlays on already-mounted charts without remounting. */
        setOverlays: function (flags) {
            overlayFlags = normalizeOverlays(flags);
            saveOverlays(overlayFlags);
            liveEntries.forEach(refreshEntryOverlays);
        },

        dispose: function (entry) {
            var idx = liveEntries.indexOf(entry);
            if (idx >= 0) {
                liveEntries.splice(idx, 1);
            }
            entry.handle.chart.remove();
            if (entry.card.root.parentNode) {
                entry.card.root.parentNode.removeChild(entry.card.root);
            }
        },
    };

    window.addEventListener("traderbot-theme", applyTheme);
})();
