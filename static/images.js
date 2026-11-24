(() => {
    "use strict";

    const root = document.documentElement;
    const revisions = new WeakMap();
    const backgrounds = new Map();

    async function decodeImage(image) {
        if (!image.complete) {
            await new Promise(resolve => {
                const done = () => {
                    image.removeEventListener("load", done);
                    image.removeEventListener("error", done);
                    resolve();
                };
                image.addEventListener("load", done);
                image.addEventListener("error", done);
            });
        }
        if (image.naturalWidth && image.decode) {
            try { await image.decode(); } catch { /* Failed images still expose their alt text. */ }
        }
    }

    function prepareImage(image) {
        const revision = {};
        revisions.set(image, revision);
        delete image.dataset.imageReady;
        decodeImage(image).then(() => {
            if (revisions.get(image) === revision && image.complete) image.dataset.imageReady = "";
        });
    }

    function scan(node) {
        if (!(node instanceof Element)) return;
        if (node instanceof HTMLImageElement) prepareImage(node);
        node.querySelectorAll("img").forEach(prepareImage);
    }

    function loadBackground(url) {
        if (!backgrounds.has(url)) {
            const image = new Image();
            image.src = url;
            backgrounds.set(url, decodeImage(image));
        }
        return backgrounds.get(url);
    }

    function prepareLayer(node, pseudo, key) {
        if (!node) return;
        const revision = {};
        const stateKey = `${key}:${pseudo || "element"}`;
        let state = revisions.get(node);
        if (!(state instanceof Map)) {
            state = new Map();
            revisions.set(node, state);
        }
        state.set(stateKey, revision);
        delete node.dataset[key];
        const background = getComputedStyle(node, pseudo).backgroundImage;
        const urls = Array.from(background.matchAll(/url\(\s*(?:"([^"]*)"|'([^']*)'|([^)]*))\s*\)/g),
            match => match[1] ?? match[2] ?? match[3].trim());
        Promise.all([...new Set(urls)].map(loadBackground)).then(() => {
            if (state.get(stateKey) === revision) node.dataset[key] = "";
        });
    }

    function prepareBackgrounds() {
        const stylesheet = document.querySelector('link[href="/static/style.css"]');
        if (stylesheet && !stylesheet.sheet) return;
        const background = document.querySelector(".season-background");
        prepareLayer(background, "::before", "patternReady");
        prepareLayer(background, "::after", "cornerReady");
        prepareLayer(background?.querySelector(".season-background-secondary"), null, "imageReady");
    }

    scan(document.body);
    const observer = new MutationObserver(records => {
        for (const record of records) {
            if (record.type === "childList") record.addedNodes.forEach(scan);
            else if (record.target instanceof HTMLImageElement) prepareImage(record.target);
            else if (record.target instanceof HTMLSourceElement) {
                record.target.closest("picture")?.querySelectorAll("img").forEach(prepareImage);
            }
        }
    });
    observer.observe(document.body, {
        subtree: true, childList: true, attributes: true, attributeFilter: ["src", "srcset", "sizes", "media"],
    });
    new MutationObserver(prepareBackgrounds).observe(root, { attributes: true, attributeFilter: ["data-theme"] });
    document.querySelectorAll('link[rel="stylesheet"]').forEach(link => {
        link.addEventListener("load", prepareBackgrounds);
    });
    matchMedia("(min-width: 1360px)").addEventListener("change", prepareBackgrounds);
    window.addEventListener("resize", () => document.querySelectorAll("img[srcset], picture img").forEach(prepareImage));
    root.dataset.imageLoading = "active";
    prepareBackgrounds();
})();
