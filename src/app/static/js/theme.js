/**
 * Lights / Dark skin. Applied before paint when this file is loaded in <head>.
 * Preference is stored in localStorage so it survives reloads and login.
 */
(function () {
    "use strict";

    var KEY = "traderbot-theme";
    var root = document.documentElement;

    function normalize(theme) {
        return theme === "dark" ? "dark" : "light";
    }

    function current() {
        return normalize(root.getAttribute("data-theme"));
    }

    function stored() {
        try {
            return normalize(localStorage.getItem(KEY));
        } catch (err) {
            return "light";
        }
    }

    function syncButtons() {
        var theme = current();
        document.querySelectorAll("[data-theme-option]").forEach(function (btn) {
            var on = btn.getAttribute("data-theme-option") === theme;
            btn.classList.toggle("active", on);
            btn.setAttribute("aria-pressed", on ? "true" : "false");
        });
    }

    function apply(theme, persist) {
        theme = normalize(theme);
        root.setAttribute("data-theme", theme);
        if (persist !== false) {
            try {
                localStorage.setItem(KEY, theme);
            } catch (err) {
                /* private mode */
            }
        }
        syncButtons();
        try {
            window.dispatchEvent(new CustomEvent("traderbot-theme", { detail: theme }));
        } catch (err) {
            /* CustomEvent missing in very old browsers */
        }
    }

    apply(stored(), false);

    function bind() {
        document.querySelectorAll("[data-theme-option]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                apply(btn.getAttribute("data-theme-option"));
            });
        });
        syncButtons();
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", bind);
    } else {
        bind();
    }

    window.TraderBotTheme = { apply: apply, current: current };
})();
