/**
 * Lights / Dark skin. Applied before paint when this file is loaded in <head>.
 * Preference is stored in localStorage so it survives reloads and login.
 */
(function () {
    "use strict";

    var KEY = "traderbot-theme";
    var root = document.documentElement;
    var ICONS = { light: "light_mode", dark: "dark_mode" };
    var LABELS = { light: "Lights", dark: "Dark" };

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
        document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
            btn.setAttribute("aria-pressed", theme === "dark" ? "true" : "false");
            btn.setAttribute("aria-label", LABELS[theme]);
            btn.setAttribute("title", LABELS[theme]);
            var icon = btn.querySelector(".material-symbols-outlined");
            if (icon) {
                icon.textContent = ICONS[theme];
            }
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
        document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
            btn.addEventListener("click", function () {
                apply(current() === "dark" ? "light" : "dark");
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
