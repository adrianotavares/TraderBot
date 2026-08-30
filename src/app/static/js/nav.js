/**
 * Top / left menu chrome. Applied before paint when this file is loaded in <head>.
 * Preference is stored in localStorage so it survives reloads. Narrow viewports
 * keep the top bar via CSS regardless of this value.
 */
(function () {
    "use strict";

    var KEY = "traderbot-nav-pos";
    var root = document.documentElement;

    function normalize(pos) {
        return pos === "left" ? "left" : "top";
    }

    function current() {
        return normalize(root.getAttribute("data-nav-pos"));
    }

    function stored() {
        try {
            return normalize(localStorage.getItem(KEY));
        } catch (err) {
            return "top";
        }
    }

    function syncButtons() {
        var pos = current();
        document.querySelectorAll("[data-nav-pos-option]").forEach(function (btn) {
            var on = btn.getAttribute("data-nav-pos-option") === pos;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-pressed", on ? "true" : "false");
        });
    }

    function apply(pos, persist) {
        pos = normalize(pos);
        root.setAttribute("data-nav-pos", pos);
        if (persist !== false) {
            try {
                localStorage.setItem(KEY, pos);
            } catch (err) {
                /* private mode */
            }
        }
        syncButtons();
        try {
            window.dispatchEvent(new CustomEvent("traderbot-navpos", { detail: pos }));
        } catch (err) {
            /* CustomEvent missing in very old browsers */
        }
        if (persist !== false) {
            requestAnimationFrame(function () {
                requestAnimationFrame(function () {
                    try {
                        window.dispatchEvent(new Event("resize"));
                    } catch (err) {
                        /* ignore */
                    }
                });
            });
        }
    }

    apply(stored(), false);

    function bind() {
        document.querySelectorAll("[data-nav-pos-option]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                apply(btn.getAttribute("data-nav-pos-option"));
            });
        });
        syncButtons();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bind);
    } else {
        bind();
    }

    window.TraderBotNav = { apply: apply, current: current };
})();
