document.addEventListener("DOMContentLoaded", () => {
    if (window.hljs) {
        window.hljs.highlightAll();
    }

    document.querySelectorAll("[data-author-carousel]").forEach((carousel) => {
        const list = carousel.querySelector(".home-author-list");
        const slides = Array.from(carousel.querySelectorAll(".home-author-slide"));
        const controls = carousel.querySelector("[data-author-controls]");
        const previous = carousel.querySelector("[data-author-previous]");
        const next = carousel.querySelector("[data-author-next]");
        const position = carousel.querySelector("[data-author-position]");
        if (!list || !slides.length) {
            return;
        }

        let current = 0;
        const showAuthor = (index) => {
            const moveFocus = slides.some((slide) => slide.contains(document.activeElement));
            current = (index + slides.length) % slides.length;
            slides.forEach((slide, slideIndex) => {
                const active = slideIndex === current;
                slide.setAttribute("aria-hidden", String(!active));
                slide.inert = !active;
            });
            if (position) {
                position.textContent = `${current + 1} / ${slides.length}`;
            }
            if (moveFocus) {
                slides[current].querySelector(".home-author-link").focus({ preventScroll: true });
            }
        };

        list.classList.add("is-carousel");
        carousel.setAttribute("aria-roledescription", "карусель");
        showAuthor(0);
        if (controls) {
            controls.hidden = slides.length < 2;
        }
        if (previous) {
            previous.addEventListener("click", () => showAuthor(current - 1));
        }
        if (next) {
            next.addEventListener("click", () => showAuthor(current + 1));
        }
        carousel.addEventListener("keydown", (event) => {
            if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey
                || event.target.closest("input, textarea, select, [contenteditable]")) {
                return;
            }
            if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
                event.preventDefault();
                showAuthor(current + (event.key === "ArrowRight" ? 1 : -1));
            }
        });
    });

    const tocPanel = document.querySelector("[data-toc-panel]");
    if (tocPanel) {
        const tocToggle = tocPanel.querySelector(".toc-toggle");
        const tocNav = tocPanel.querySelector(".toc");
        let savedState = null;
        try {
            savedState = localStorage.getItem("tocCollapsed");
        } catch {
            // Use the default TOC state if browser storage is unavailable.
        }

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
                try {
                    localStorage.setItem("tocCollapsed", String(collapsed));
                } catch {
                    // The toggle remains usable without saving its state.
                }
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

    const categories = Array.from(document.querySelectorAll("[data-search-category]"));
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

            if (query) {
                category.querySelectorAll("[data-protected-articles]").forEach((protectedBlock) => {
                    const matchingProtectedArticle = Array.from(protectedBlock.querySelectorAll(".protected-article")).some((article) => {
                        return !article.hidden;
                    });

                    if (matchingProtectedArticle) {
                        setProtectedExpanded(protectedBlock, true);
                    }
                });
            }

            category.querySelectorAll("[data-category-section]").forEach((section) => {
                const visibleSectionArticle = Array.from(section.querySelectorAll(".article-item")).some((article) => {
                    return !article.hidden;
                });
                section.hidden = !visibleSectionArticle;
            });

            const categoryVisible = visibleArticles > 0;
            category.hidden = !categoryVisible;

            if (query && categoryVisible && category.tagName === "DETAILS") {
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
