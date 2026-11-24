(() => {
    "use strict";

    const delay = 120;
    let showTimer;
    let resetTimer;
    let indicator;

    const reset = () => {
        clearTimeout(showTimer);
        clearTimeout(resetTimer);
        if (indicator) indicator.hidden = true;
    };

    const show = (timeout) => {
        reset();
        showTimer = setTimeout(() => {
            if (!indicator) {
                indicator = document.createElement("div");
                indicator.className = "page-loading";
                indicator.setAttribute("role", "status");
                indicator.setAttribute("aria-live", "polite");
                indicator.setAttribute("aria-atomic", "true");
                const spinner = document.createElement("span");
                spinner.className = "page-loading-spinner";
                spinner.setAttribute("aria-hidden", "true");
                const label = document.createElement("span");
                label.textContent = "Загрузка…";
                indicator.append(spinner, label);
                document.body.append(indicator);
            }
            indicator.hidden = false;
        }, delay);
        // A cancelled navigation or an unavailable CDN must not cover the page indefinitely.
        resetTimer = setTimeout(reset, timeout);
    };

    const isPage = (url) => url.origin === location.origin
        && /^https?:$/.test(url.protocol)
        && !/^\/(?:static\/|favicon\.ico(?:$|\/))/.test(url.pathname)
        && !/\/media\//.test(url.pathname)
        && !/\.[^/]+$/.test(url.pathname);
    const sameDocument = (url) => url.pathname === location.pathname && url.search === location.search;
    const selfTarget = (target) => !target || target.toLowerCase() === "_self";

    window.addEventListener("click", (event) => {
        if (event.defaultPrevented || event.button !== 0
            || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const link = event.target instanceof Element ? event.target.closest("a[href]") : null;
        if (!link || link.hasAttribute("download")
            || !selfTarget(link.getAttribute("target") || document.querySelector("base[target]")?.target)) return;
        const url = new URL(link.href, location.href);
        if (isPage(url) && !sameDocument(url)) show(10000);
    });

    window.addEventListener("submit", (event) => {
        if (event.defaultPrevented || !(event.target instanceof HTMLFormElement)) return;
        const form = event.target;
        const submitter = event.submitter;
        const method = submitter?.getAttribute("formmethod") || form.method;
        const target = submitter?.getAttribute("formtarget") || form.target
            || document.querySelector("base[target]")?.target;
        const action = submitter?.getAttribute("formaction") || form.action;
        if (method.toLowerCase() !== "dialog" && selfTarget(target)
            && isPage(new URL(action, location.href))) show(10000);
    });

    window.addEventListener("pageshow", reset);
    window.addEventListener("pagehide", reset);
    window.addEventListener("load", reset, { once: true });
    window.addEventListener("keydown", (event) => {
        if (event.key === "Escape") reset();
    });
    if (document.readyState !== "complete") show(3000);
})();
