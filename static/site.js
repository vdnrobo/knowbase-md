document.addEventListener("DOMContentLoaded", () => {
    const pageTransitionMs = 240;
    const prefersReducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    window.addEventListener("pageshow", () => {
        document.body.classList.remove("is-page-leaving");
    });

    const isSamePageAnchor = (url) => {
        return (
            url.origin === window.location.origin
            && url.pathname === window.location.pathname
            && url.search === window.location.search
            && url.hash
        );
    };

    document.addEventListener("click", (event) => {
        if (
            event.defaultPrevented
            || event.button !== 0
            || event.metaKey
            || event.ctrlKey
            || event.shiftKey
            || event.altKey
        ) {
            return;
        }

        if (!(event.target instanceof Element)) {
            return;
        }

        const link = event.target.closest("a[href]");
        if (!link) {
            return;
        }

        const href = link.getAttribute("href");
        if (!href || href.startsWith("#")) {
            return;
        }

        const url = new URL(link.href, window.location.href);
        if (
            url.origin !== window.location.origin
            || (link.target && link.target.toLowerCase() !== "_self")
            || link.hasAttribute("download")
            || isSamePageAnchor(url)
        ) {
            return;
        }

        if (prefersReducedMotion) {
            return;
        }

        event.preventDefault();
        document.body.classList.add("is-page-leaving");

        window.setTimeout(() => {
            window.location.href = url.href;
        }, pageTransitionMs);
    });

    document.addEventListener("submit", (event) => {
        const form = event.target;
        if (!(form instanceof HTMLFormElement) || event.defaultPrevented) {
            return;
        }

        const action = new URL(form.action || window.location.href, window.location.href);
        if (
            action.origin !== window.location.origin
            || (form.target && form.target.toLowerCase() !== "_self")
            || prefersReducedMotion
        ) {
            return;
        }

        document.body.classList.add("is-page-leaving");
    });

    if (window.hljs) {
        window.hljs.highlightAll();
    }

    const tocPanel = document.querySelector("[data-toc-panel]");
    if (tocPanel) {
        const tocToggle = tocPanel.querySelector(".toc-toggle");
        const tocNav = tocPanel.querySelector(".toc");
        const savedState = localStorage.getItem("tocCollapsed");

        const setTocCollapsed = (collapsed) => {
            tocPanel.classList.toggle("is-collapsed", collapsed);

            if (tocToggle) {
                tocToggle.textContent = collapsed ? "Показать" : "Свернуть";
                tocToggle.setAttribute("aria-expanded", String(!collapsed));
            }

            if (tocNav) {
                tocNav.hidden = collapsed;
            }
        };

        const shouldCollapseOnMobile = window.matchMedia("(max-width: 700px)").matches;
        setTocCollapsed(savedState === null ? shouldCollapseOnMobile : savedState === "true");

        if (tocToggle) {
            tocToggle.addEventListener("click", () => {
                const collapsed = !tocPanel.classList.contains("is-collapsed");
                setTocCollapsed(collapsed);
                localStorage.setItem("tocCollapsed", String(collapsed));
            });
        }

        if (tocNav) {
            tocNav.querySelectorAll("li").forEach((item) => {
                const childList = Array.from(item.children).find((child) => child.tagName === "UL");
                const link = Array.from(item.children).find((child) => child.tagName === "A");

                if (!childList || !link) {
                    return;
                }

                const toggle = document.createElement("button");
                toggle.className = "toc-branch-toggle";
                toggle.type = "button";
                toggle.textContent = "-";
                toggle.setAttribute("aria-expanded", "true");
                toggle.setAttribute("aria-label", `Свернуть подразделы: ${link.textContent.trim()}`);

                toggle.addEventListener("click", () => {
                    const collapsed = toggle.getAttribute("aria-expanded") === "true";
                    childList.hidden = collapsed;
                    item.classList.toggle("is-branch-collapsed", collapsed);
                    toggle.textContent = collapsed ? "+" : "-";
                    toggle.setAttribute("aria-expanded", String(!collapsed));
                    toggle.setAttribute(
                        "aria-label",
                        `${collapsed ? "Показать" : "Свернуть"} подразделы: ${link.textContent.trim()}`,
                    );
                });

                link.after(toggle);
            });
        }
    }

    const protectedBlocks = Array.from(document.querySelectorAll("[data-protected-articles]"));
    const setProtectedExpanded = (block, expanded) => {
        const button = block.querySelector(".protected-toggle");
        const list = block.querySelector(".protected-article-list");

        if (!button || !list) {
            return;
        }

        list.hidden = !expanded;
        button.setAttribute("aria-expanded", String(expanded));
        button.textContent = expanded ? "Скрыть защищённые статьи" : "Показать защищённые статьи";
        block.classList.toggle("is-expanded", expanded);
    };

    protectedBlocks.forEach((block) => {
        const button = block.querySelector(".protected-toggle");
        if (!button) {
            return;
        }

        setProtectedExpanded(block, false);
        button.addEventListener("click", () => {
            setProtectedExpanded(block, button.getAttribute("aria-expanded") !== "true");
        });
    });

    const searchInput = document.querySelector("#site-search");
    if (!searchInput) {
        return;
    }

    const categories = Array.from(document.querySelectorAll(".category"));
    const noResults = document.querySelector("#no-results");

    searchInput.addEventListener("input", () => {
        const query = searchInput.value.trim().toLowerCase();
        let visibleCategories = 0;

        categories.forEach((category) => {
            const categoryText = (category.dataset.search || "").toLowerCase();
            const categoryMatches = categoryText.includes(query);
            const articles = Array.from(category.querySelectorAll(".article-item"));
            let visibleArticles = 0;

            articles.forEach((article) => {
                const articleText = (article.dataset.search || "").toLowerCase();
                const articleMatches = !query || categoryMatches || articleText.includes(query);
                article.hidden = !articleMatches;

                if (articleMatches) {
                    visibleArticles += 1;
                }
            });

            const matchingProtectedArticle = articles.some((article) => {
                return article.classList.contains("protected-article") && !article.hidden;
            });
            const protectedBlock = category.querySelector("[data-protected-articles]");
            if (query && matchingProtectedArticle && protectedBlock) {
                setProtectedExpanded(protectedBlock, true);
            }

            const categoryVisible = visibleArticles > 0;
            category.hidden = !categoryVisible;

            if (query && categoryVisible) {
                category.open = true;
            }

            if (categoryVisible) {
                visibleCategories += 1;
            }
        });

        if (noResults) {
            noResults.hidden = visibleCategories > 0;
        }
    });
});
