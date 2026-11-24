document.addEventListener("DOMContentLoaded", () => {
    "use strict";
    const activators = new WeakMap();
    let sequence = 0;
    document.querySelectorAll(".tabbed-set").forEach(set => {
        const labels = set.querySelector(":scope > .tabbed-labels");
        const content = set.querySelector(":scope > .tabbed-content");
        if (!labels || !content) return;
        const source = Array.from(labels.children);
        const panels = Array.from(content.children).filter(node => node.classList.contains("tabbed-block"));
        if (!panels.length || source.length !== panels.length) return;
        const buttons = source.map((label, index) => {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "content-tab";
            button.textContent = label.textContent;
            button.id = `reader-tab-${++sequence}`;
            button.setAttribute("role", "tab");
            panels[index].id = `${button.id}-panel`;
            button.setAttribute("aria-controls", panels[index].id);
            panels[index].setAttribute("role", "tabpanel");
            panels[index].setAttribute("aria-labelledby", button.id);
            panels[index].tabIndex = 0;
            return button;
        });
        const activate = index => {
            buttons.forEach((button, current) => {
                const selected = current === index;
                button.setAttribute("aria-selected", String(selected));
                button.tabIndex = selected ? 0 : -1;
                panels[current].hidden = !selected;
            });
        };
        buttons.forEach((button, index) => {
            activators.set(panels[index], () => activate(index));
            button.addEventListener("click", () => activate(index));
            button.addEventListener("keydown", event => {
                let next;
                if (event.key === "ArrowRight") next = (index + 1) % buttons.length;
                if (event.key === "ArrowLeft") next = (index - 1 + buttons.length) % buttons.length;
                if (event.key === "Home") next = 0;
                if (event.key === "End") next = buttons.length - 1;
                if (next === undefined) return;
                event.preventDefault();
                activate(next);
                buttons[next].focus();
                buttons[next].scrollIntoView({block: "nearest", inline: "nearest"});
            });
        });
        labels.replaceChildren(...buttons);
        labels.setAttribute("role", "tablist");
        labels.setAttribute("aria-label", "Варианты материала");
        set.classList.add("is-enhanced");
        activate(0);
    });

    function revealTarget(target) {
        const panels = [];
        for (let node = target; node; node = node.parentElement) {
            if (activators.has(node)) panels.push(node);
        }
        panels.reverse().forEach(panel => activators.get(panel)());
    }
    function hashTarget(hash) {
        try { return hash && document.getElementById(decodeURIComponent(hash.slice(1))); }
        catch { return null; }
    }
    function revealHash() {
        const target = hashTarget(location.hash);
        if (!target) return;
        revealTarget(target);
        requestAnimationFrame(() => target.scrollIntoView({behavior: "auto"}));
    }
    window.TeachingBlocks = {revealTarget};
    window.addEventListener("hashchange", revealHash);
    document.addEventListener("click", event => {
        const link = event.target.closest("a[href]");
        if (!link || event.defaultPrevented || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        const url = new URL(link.href, location.href);
        if (url.origin === location.origin && url.pathname === location.pathname) {
            const target = hashTarget(url.hash);
            if (target) revealTarget(target);
        }
    });
    revealHash();
});
