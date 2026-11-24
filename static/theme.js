(() => {
    "use strict";

    const root = document.documentElement;
    root.dataset.imageLoading = "pending";
    // Keep images available if the separate image loader cannot be downloaded.
    setTimeout(() => {
        if (root.dataset.imageLoading === "pending") delete root.dataset.imageLoading;
    }, 5000);

    const themes = new Set(["classic", "winter", "spring", "summer", "autumn", "67", "magic", "hello-kitty", "548", "robo548", "minions"]);
    const lightOnlyThemes = new Set(["minions", "hello-kitty", "548", "robo548"]);
    const storageKey = "siteTheme";
    const modeStorageKey = "siteColorMode";
    let preferredMode = "light";
    const applyTheme = (value) => {
        const theme = themes.has(value) ? value : "classic";
        document.documentElement.dataset.theme = theme;
        applyMode(preferredMode);
        return theme;
    };
    const applyMode = (value) => {
        preferredMode = value === "dark" ? "dark" : "light";
        const lightOnly = lightOnlyThemes.has(document.documentElement.dataset.theme);
        const mode = lightOnly ? "light" : preferredMode;
        document.documentElement.dataset.colorMode = mode;
        document.querySelectorAll("[data-color-mode-switch]").forEach(input => {
            input.checked = mode === "dark";
            input.disabled = lightOnly;
            input.closest(".color-mode-switch").hidden = lightOnly;
        });
        return mode;
    };

    let savedTheme = "classic";
    let savedMode = "light";
    try {
        savedTheme = localStorage.getItem(storageKey);
        savedMode = localStorage.getItem(modeStorageKey);
    } catch {
        // Theme selection still works for this page when storage is unavailable.
    }
    applyTheme(savedTheme);
    applyMode(savedMode);

    const connectSwitchers = () => {
        document.querySelectorAll("[data-theme-select]").forEach((select) => {
            select.value = document.documentElement.dataset.theme;
            select.closest(".theme-switcher").hidden = false;
            select.addEventListener("change", () => {
                const theme = applyTheme(select.value);
                select.value = theme;
                try {
                    localStorage.setItem(storageKey, theme);
                } catch {
                    // Keep the selected theme without requiring persistence.
                }
            });
        });
        document.querySelectorAll("[data-color-mode-switch]").forEach(input => {
            input.addEventListener("change", () => {
                const mode = applyMode(input.checked ? "dark" : "light");
                try {
                    localStorage.setItem(modeStorageKey, mode);
                } catch {
                    // The mode remains usable without browser storage.
                }
            });
        });
        applyMode(preferredMode);
    };

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", connectSwitchers);
    } else {
        connectSwitchers();
    }
})();
