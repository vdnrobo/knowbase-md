document.addEventListener("DOMContentLoaded", () => {
    "use strict";

    const element = (tag, className, text) => {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    };
    const icon = (name) => {
        const image = element("img", "ui-icon");
        image.src = `/static/icons/${name}.svg`;
        image.alt = "";
        return image;
    };
    const button = (name, label) => {
        const node = element("button", "reader-icon-button");
        node.type = "button";
        node.title = label;
        node.setAttribute("aria-label", label);
        node.append(icon(name));
        return node;
    };
    function dialog(title, className = "") {
        const previous = document.activeElement;
        const node = element("dialog", `reader-dialog ${className}`);
        const header = element("div", "reader-dialog-header");
        const heading = element("h2", "", title);
        const close = button("x", "Закрыть");
        const body = element("div", "reader-dialog-body");
        node.setAttribute("aria-label", title);
        header.append(heading, close);
        node.append(header, body);
        document.body.append(node);
        close.addEventListener("click", () => node.close());
        let backdrop = false;
        node.addEventListener("pointerdown", event => { backdrop = event.target === node; });
        node.addEventListener("click", event => { if (backdrop && event.target === node) node.close(); });
        node.addEventListener("close", () => {
            node.remove();
            if (previous?.isConnected) previous.focus({preventScroll: true});
        });
        return {node, body, heading, open: () => node.showModal()};
    }
    async function copyText(text, title = "Код") {
        try {
            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(text);
                return true;
            }
        } catch { /* Fall through to selection on non-secure or restricted origins. */ }
        const box = element("textarea");
        box.value = text;
        box.readOnly = true;
        box.style.cssText = "position:fixed;left:-10000px;top:0";
        document.body.append(box);
        box.select();
        let copied = false;
        try { copied = document.execCommand("copy"); } catch { /* Manual selection below. */ }
        box.remove();
        if (!copied) {
            const modal = dialog(title);
            box.style.cssText = "width:100%;min-height:200px";
            box.setAttribute("aria-label", title === "Код" ? "Код для копирования" : "Ссылка для копирования");
            modal.body.append(box);
            modal.open();
            box.focus();
            box.select();
        }
        return copied;
    }

    const memory = new Map();
    function read(key, fallback) {
        try {
            const raw = localStorage.getItem(key);
            return raw ? JSON.parse(raw) : memory.get(key) ?? fallback;
        } catch { return memory.get(key) ?? fallback; }
    }
    function write(key, data) {
        memory.set(key, data);
        try { localStorage.setItem(key, JSON.stringify(data)); return true; } catch { return false; }
    }
    function articleURL(value) {
        if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//") || value.length > 2000) return null;
        try {
            const url = new URL(value, location.origin);
            return url.origin === location.origin && /^\/[^/]+\/[^/]+$/.test(url.pathname) ? url.pathname : null;
        } catch { return null; }
    }
    const bookmarkKey = "knowbase.bookmarks.v1";
    const readingKey = "knowbase.reading.v1";
    let bookmarks = read(bookmarkKey, []);
    bookmarks = Array.isArray(bookmarks) ? bookmarks.filter(item => item && articleURL(item.url)).slice(0, 500) : [];
    let reading = read(readingKey, {});
    reading = reading && typeof reading === "object" && !Array.isArray(reading) ? Object.fromEntries(
        Object.entries(reading).filter(([url, item]) => articleURL(url) && item && Number.isFinite(item.fraction) && Number.isFinite(item.time)).slice(0, 100),
    ) : {};
    let catalog = [];
    try { catalog = JSON.parse(document.querySelector("#article-catalog")?.textContent || "[]"); } catch { /* Empty collection. */ }
    if (!Array.isArray(catalog)) catalog = [];
    const index = new Map(catalog.filter(item => articleURL(item.url)).map(item => [item.url, item]));

    function renderBookmarks() {
        const list = document.querySelector("[data-bookmark-list]");
        if (!list) return;
        list.replaceChildren();
        bookmarks.forEach(saved => {
            const current = index.get(saved.url);
            const row = element("li");
            const text = element("div");
            if (current) {
                const link = element("a", "", current.title);
                link.href = current.url;
                text.append(link, element("span", "bookmark-category", `${current.category}${current.protected ? " · закрыто" : ""}`));
            } else {
                text.append(element("span", "", typeof saved.title === "string" ? saved.title : saved.url), element("span", "bookmark-category", "Статья недоступна"));
            }
            const remove = button("x", "Удалить закладку");
            remove.addEventListener("click", () => {
                bookmarks = bookmarks.filter(item => item.url !== saved.url);
                write(bookmarkKey, bookmarks);
                renderBookmarks();
                const next = list.querySelector("button");
                if (next) next.focus();
                else {
                    const empty = document.querySelector("[data-bookmarks-empty]");
                    if (empty) { empty.tabIndex = -1; empty.focus(); }
                }
            });
            row.append(text, remove);
            list.append(row);
        });
        const empty = document.querySelector("[data-bookmarks-empty]");
        if (empty) empty.hidden = bookmarks.length > 0;
    }
    renderBookmarks();
    const latest = Object.entries(reading).filter(([url]) => index.has(url)).sort((a, b) => b[1].time - a[1].time)[0];
    const continuePanel = document.querySelector("[data-continue-reading]");
    if (latest && continuePanel) {
        const current = index.get(latest[0]);
        const link = continuePanel.querySelector("[data-continue-link]");
        const target = new URL(current.url, location.origin);
        target.searchParams.set("resume", "1");
        if (typeof latest[1].route === "string" && latest[1].route && latest[1].route.length <= 200) target.searchParams.set("route", latest[1].route);
        link.href = target.href;
        link.textContent = current.title;
        continuePanel.hidden = false;
    }

    const article = document.querySelector(".article-body[data-article-url]");
    if (article) {
        const url = article.dataset.articleUrl;
        const title = article.dataset.articleTitle;
        const category = article.dataset.articleCategory;
        const tools = document.querySelector("[data-reader-tools]");
        if (tools) tools.hidden = false;
        const bookmark = document.querySelector("[data-bookmark-toggle]");
        const status = document.querySelector("[data-reader-status]");
        const updateBookmark = () => {
            if (!bookmark) return;
            const active = bookmarks.some(item => item.url === url);
            const label = active ? "Удалить из закладок" : "Добавить в закладки";
            bookmark.setAttribute("aria-pressed", String(active));
            bookmark.setAttribute("aria-label", label);
            bookmark.title = label;
            bookmark.replaceChildren(icon(active ? "bookmark-check" : "bookmark"));
        };
        updateBookmark();
        bookmark?.addEventListener("click", () => {
            bookmarks = bookmarks.some(item => item.url === url) ? bookmarks.filter(item => item.url !== url) : [...bookmarks, {url, title}].slice(-500);
            const saved = write(bookmarkKey, bookmarks);
            updateBookmark();
            if (status) status.textContent = saved ? "" : "Постоянное сохранение недоступно.";
        });
        const previous = reading[url];
        const resume = document.querySelector("[data-resume-reading]");
        if (resume && previous && previous.fraction > 0.03) {
            resume.hidden = false;
            resume.addEventListener("click", () => {
                const target = new URL(url, location.origin);
                target.searchParams.set("resume", "1");
                if (article.dataset.learningRoute) target.searchParams.set("route", article.dataset.learningRoute);
                location.href = target.href;
            });
        }
        let interacted = false;
        let scrolled = false;
        ["wheel", "touchstart", "pointerdown", "keydown"].forEach(name => window.addEventListener(name, () => { interacted = true; }, {passive: true}));
        const headings = () => Array.from(article.querySelectorAll("h1[id],h2[id],h3[id],h4[id],h5[id],h6[id]"));
        function saveReading() {
            if (!scrolled) return;
            const heading = headings().filter(item => item.getClientRects().length && item.getBoundingClientRect().top <= 120).pop();
            const max = Math.max(1, document.documentElement.scrollHeight - innerHeight);
            reading[url] = {title, category, route: article.dataset.learningRoute || "", anchor: heading?.id || "", fraction: Math.max(0, Math.min(1, scrollY / max)), time: Date.now()};
            reading = Object.fromEntries(Object.entries(reading).sort((a, b) => b[1].time - a[1].time).slice(0, 100));
            write(readingKey, reading);
        }
        let timer;
        window.addEventListener("scroll", () => {
            if (!interacted) return;
            scrolled = true;
            clearTimeout(timer);
            timer = setTimeout(saveReading, 600);
        }, {passive: true});
        window.addEventListener("pagehide", saveReading);
        if (new URL(location.href).searchParams.get("resume") === "1" && previous && !location.hash) {
            (async () => {
                await Promise.race([
                    Promise.allSettled([window.MathJax?.startup?.promise, ...Array.from(article.querySelectorAll("img")).map(img => img.decode?.())]),
                    new Promise(resolve => setTimeout(resolve, 2000)),
                ]);
                requestAnimationFrame(() => {
                    const heading = previous.anchor && document.getElementById(previous.anchor);
                    if (heading && article.contains(heading)) {
                        window.TeachingBlocks?.revealTarget(heading);
                        heading.scrollIntoView({behavior: "auto"});
                    }
                    else window.scrollTo({top: previous.fraction * Math.max(0, document.documentElement.scrollHeight - innerHeight), behavior: "auto"});
                    const current = new URL(location.href);
                    current.searchParams.delete("resume");
                    history.replaceState(null, "", current);
                });
            })();
        }

        article.querySelectorAll("[data-heading-link]").forEach(link => link.addEventListener("click", async event => {
            if (event.button !== 0 || event.ctrlKey || event.shiftKey || event.altKey || event.metaKey) return;
            event.preventDefault();
            const target = new URL(url, location.origin);
            target.hash = link.parentElement.id;
            if (await copyText(target.href, "Ссылка на раздел")) {
                link.replaceChildren(icon("check"));
                link.title = "Ссылка скопирована";
                link.setAttribute("aria-label", "Ссылка скопирована");
                if (status) status.textContent = "Ссылка скопирована";
                setTimeout(() => {
                    link.replaceChildren(icon("link"));
                    link.title = "Скопировать ссылку на раздел";
                    link.setAttribute("aria-label", link.title);
                    if (status?.textContent === "Ссылка скопирована") status.textContent = "";
                }, 1800);
            }
        }));

        article.querySelectorAll("pre > code").forEach(code => {
            const pre = code.parentElement;
            pre.classList.add("reader-code");
            const copy = button("copy", "Копировать код");
            copy.classList.add("code-copy");
            copy.addEventListener("click", async () => {
                if (await copyText(code.textContent)) {
                    copy.replaceChildren(icon("check"));
                    copy.title = "Скопировано";
                    copy.setAttribute("aria-label", "Скопировано");
                    setTimeout(() => {
                        copy.replaceChildren(icon("copy"));
                        copy.title = "Копировать код";
                        copy.setAttribute("aria-label", "Копировать код");
                    }, 1800);
                }
            });
            pre.append(copy);
        });

        const images = Array.from(article.querySelectorAll("img")).filter(img => !img.closest("a,button") && !img.classList.contains("ui-icon"));
        function openImage(initial) {
            const modal = dialog("Изображение", "lightbox");
            const stage = element("div", "lightbox-stage");
            const wrap = element("div", "lightbox-image-wrap");
            const image = element("img", "lightbox-image");
            image.draggable = false;
            wrap.append(image);
            stage.append(wrap);
            const controls = element("div", "lightbox-controls");
            const previousButton = button("chevron-left", "Предыдущее изображение");
            const minus = button("minus", "Уменьшить");
            const zoomLabel = element("span", "lightbox-zoom", "100%");
            const plus = button("plus", "Увеличить");
            const reset = button("rotate-ccw", "Сбросить масштаб");
            const nextButton = button("chevron-right", "Следующее изображение");
            const caption = element("p", "lightbox-caption");
            controls.append(previousButton, minus, zoomLabel, plus, reset, nextButton);
            modal.body.append(stage, controls, caption);
            let current = initial;
            let zoom = 1;
            let loaded = false;
            function resize() {
                if (!loaded || !image.naturalWidth) return;
                const fit = Math.min((stage.clientWidth - 20) / image.naturalWidth, (stage.clientHeight - 20) / image.naturalHeight, 1);
                image.style.width = `${Math.max(1, image.naturalWidth * fit * zoom)}px`;
                image.style.height = `${Math.max(1, image.naturalHeight * fit * zoom)}px`;
                zoomLabel.textContent = `${Math.round(zoom * 100)}%`;
                minus.disabled = zoom <= 1;
                plus.disabled = zoom >= 4;
            }
            function setZoom(value) { zoom = Math.max(1, Math.min(4, value)); resize(); }
            function show(index) {
                current = index;
                loaded = false;
                zoom = 1;
                image.alt = images[index].alt;
                caption.textContent = images[index].closest("figure")?.querySelector("figcaption")?.textContent || image.alt;
                image.src = images[index].currentSrc || images[index].src;
                previousButton.disabled = index === 0;
                nextButton.disabled = index === images.length - 1;
                stage.scrollTo(0, 0);
            }
            image.addEventListener("load", () => { loaded = true; resize(); });
            image.addEventListener("error", () => { caption.textContent = "Не удалось загрузить изображение."; });
            previousButton.addEventListener("click", () => { if (current > 0) show(current - 1); });
            nextButton.addEventListener("click", () => { if (current < images.length - 1) show(current + 1); });
            minus.addEventListener("click", () => setZoom(zoom - .25));
            plus.addEventListener("click", () => setZoom(zoom + .25));
            reset.addEventListener("click", () => { setZoom(1); stage.scrollTo(0, 0); });
            modal.node.addEventListener("keydown", event => {
                if (event.key === "ArrowLeft" && current > 0) { event.preventDefault(); show(current - 1); }
                if (event.key === "ArrowRight" && current < images.length - 1) { event.preventDefault(); show(current + 1); }
                if (event.key === "+" || event.key === "=") { event.preventDefault(); setZoom(zoom + .25); }
                if (event.key === "-") { event.preventDefault(); setZoom(zoom - .25); }
            });
            stage.addEventListener("wheel", event => {
                event.preventDefault();
                setZoom(zoom + (event.deltaY < 0 ? .25 : -.25));
            }, {passive: false});
            const pointers = new Map();
            let pinch = null;
            stage.addEventListener("pointerdown", event => {
                pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
                stage.setPointerCapture(event.pointerId);
                if (pointers.size === 2) {
                    const [a, b] = [...pointers.values()];
                    pinch = {distance: Math.hypot(a.x - b.x, a.y - b.y), zoom};
                }
            });
            stage.addEventListener("pointermove", event => {
                const before = pointers.get(event.pointerId);
                if (!before) return;
                pointers.set(event.pointerId, {x: event.clientX, y: event.clientY});
                if (pointers.size === 2 && pinch?.distance) {
                    const [a, b] = [...pointers.values()];
                    setZoom(pinch.zoom * Math.hypot(a.x - b.x, a.y - b.y) / pinch.distance);
                } else if (zoom > 1) {
                    stage.scrollLeft += before.x - event.clientX;
                    stage.scrollTop += before.y - event.clientY;
                }
            });
            ["pointerup", "pointercancel"].forEach(name => stage.addEventListener(name, event => { pointers.delete(event.pointerId); pinch = null; }));
            window.addEventListener("resize", resize);
            modal.node.addEventListener("close", () => window.removeEventListener("resize", resize));
            modal.open();
            show(initial);
        }
        images.forEach((image, index) => {
            const zoom = element("button", "image-zoom");
            zoom.type = "button";
            zoom.setAttribute("aria-label", image.alt ? `Увеличить: ${image.alt}` : "Увеличить изображение");
            image.before(zoom);
            zoom.append(image);
            zoom.addEventListener("click", () => openImage(index));
        });
    }

    document.querySelectorAll(".glossary-term").forEach(term => term.addEventListener("click", () => {
        const modal = dialog(term.dataset.termTitle);
        modal.body.append(element("p", "", term.dataset.termDefinition));
        const target = term.dataset.termUrl;
        if (target) {
            try {
                const url = new URL(target, location.href);
                if (["http:", "https:"].includes(url.protocol)) {
                    const link = element("a", "", "Подробнее");
                    link.href = url.href;
                    modal.body.append(link);
                }
            } catch { /* Missing optional link does not hide the definition. */ }
        }
        modal.open();
    }));

    const panel = document.querySelector("[data-feedback-panel]");
    if (article && panel) {
        const form = panel.querySelector("form");
        const summary = panel.querySelector("summary");
        const selectionButton = button("flag", "Сообщить об ошибке в выделенном тексте");
        selectionButton.classList.add("feedback-selection");
        selectionButton.hidden = true;
        document.body.append(selectionButton);
        let selection = {quote: "", anchor: ""};
        const updateSelection = () => {
            const current = window.getSelection();
            if (!current?.rangeCount || current.isCollapsed) { selectionButton.hidden = true; return; }
            const range = current.getRangeAt(0);
            if (!article.contains(range.startContainer) || !article.contains(range.endContainer)) { selectionButton.hidden = true; return; }
            const start = range.startContainer.nodeType === Node.ELEMENT_NODE ? range.startContainer : range.startContainer.parentElement;
            const top = start.getBoundingClientRect().top;
            const heading = Array.from(article.querySelectorAll("h1[id],h2[id],h3[id],h4[id],h5[id],h6[id]")).filter(item => item.getClientRects().length && item.getBoundingClientRect().top <= top + 2).pop();
            selection = {quote: current.toString().trim().slice(0, 1000), anchor: heading?.id || ""};
            selectionButton.hidden = !selection.quote;
        };
        document.addEventListener("selectionchange", updateSelection);
        function openFeedback() {
            const modal = dialog("Сообщить об ошибке");
            if (selection.quote) {
                form.elements.quote.value = selection.quote;
                form.elements.anchor.value = selection.anchor;
            }
            selectionButton.hidden = true;
            modal.body.append(form);
            modal.node.addEventListener("close", () => { panel.append(form); panel.open = false; });
            modal.open();
        }
        summary.addEventListener("click", event => { event.preventDefault(); openFeedback(); });
        selectionButton.addEventListener("pointerdown", event => event.preventDefault());
        selectionButton.addEventListener("click", openFeedback);
        form.addEventListener("submit", async event => {
            event.preventDefault();
            const result = form.querySelector(".feedback-result");
            const submit = form.querySelector("button[type=submit]");
            submit.disabled = true;
            result.classList.remove("is-success");
            try {
                const response = await fetch(form.action, {method: "POST", body: new URLSearchParams(new FormData(form)), headers: {Accept: "application/json"}, credentials: "same-origin"});
                const data = await response.json();
                result.textContent = data.message || "Не удалось отправить замечание.";
                if (response.ok && data.ok) {
                    result.classList.add("is-success");
                    form.reset();
                    selection = {quote: "", anchor: ""};
                }
            } catch { result.textContent = "Не удалось отправить замечание. Попробуйте ещё раз."; }
            finally { submit.disabled = false; }
        });
    }
    document.querySelectorAll("[data-confirm]").forEach(control => control.addEventListener("click", event => {
        if (!window.confirm(control.dataset.confirm)) event.preventDefault();
    }));
});
