document.addEventListener("DOMContentLoaded", () => {
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
