(() => {
    "use strict";

    let sequence = 0;
    const el = (tag, className, text) => {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== undefined) node.textContent = text;
        return node;
    };
    function validate(value) {
        if (!value || !["choice", "exercise"].includes(value.type)) throw new Error("Выберите тип задания.");
        const result = {type: value.type};
        for (const key of ["question", "hint", "answer"]) {
            const text = value[key] ?? "";
            if (typeof text !== "string" || text.length > 16000) throw new Error("Проверьте текст задания.");
            result[key] = text.trim();
        }
        if (!result.question) throw new Error("Укажите вопрос.");
        if (result.type === "choice") {
            if (!Array.isArray(value.options) || value.options.length < 2 || value.options.length > 10
                || value.options.some(item => typeof item !== "string" || !item.trim() || item.length > 4000)) {
                throw new Error("Нужно от 2 до 10 непустых вариантов ответа.");
            }
            if (!Number.isInteger(value.correct) || value.correct < 0 || value.correct >= value.options.length) {
                throw new Error("Отметьте правильный ответ.");
            }
            result.options = value.options.map(item => item.trim());
            result.correct = value.correct;
        }
        return result;
    }
    function markdown(text) {
        const node = el("div", "quiz-text");
        if (window.marked && window.DOMPurify) {
            const renderer = new window.marked.Renderer();
            renderer.html = token => {
                const escaped = el("span", "", token.text);
                return escaped.innerHTML;
            };
            const output = window.marked.parse(text, {renderer, async: false, breaks: false});
            node.append(window.DOMPurify.sanitize(output, {
                RETURN_DOM_FRAGMENT: true,
                ALLOWED_TAGS: ["p", "br", "hr", "strong", "em", "del", "s", "code", "pre", "blockquote", "ul", "ol", "li", "a", "table", "thead", "tbody", "tr", "th", "td", "h1", "h2", "h3", "h4", "h5", "h6"],
                ALLOWED_ATTR: ["href", "title", "class", "start"],
                ALLOW_DATA_ATTR: false,
                ALLOW_ARIA_ATTR: false,
            }));
            node.querySelectorAll("a[href]").forEach(link => {
                const href = link.getAttribute("href");
                if (/[\u0000-\u001f\\]/.test(href) || /^\/\//.test(href) || !/^(?:https?:|mailto:|[^:]*$)/i.test(href)) link.removeAttribute("href");
            });
        } else {
            node.append(el("p", "", text));
        }
        return node;
    }
    function details(label, content, className) {
        const node = el("details", className);
        node.append(el("summary", "", label), content);
        return node;
    }
    function enhance(root, config) {
        if (root.dataset.quizReady) return;
        config = validate(config);
        const question = root.querySelector(".quiz-question") || markdown(config.question);
        question.classList.add("quiz-question");
        const rendered = {};
        for (const key of ["hint", "answer"]) {
            rendered[key] = root.querySelector(`.quiz-${key} .quiz-text`);
        }
        root.dataset.quizReady = "true";
        root.replaceChildren(el("p", "quiz-label", config.type === "choice" ? "Вопрос" : "Задание"), question);
        const inputs = [];
        const result = el("p", "quiz-result");
        result.setAttribute("role", "status");
        result.hidden = true;
        if (config.type === "choice") {
            const options = el("fieldset", "quiz-options");
            const legend = el("legend", "visually-hidden", question.textContent.trim());
            options.append(legend);
            const name = `quiz-${++sequence}`;
            config.options.forEach((text, index) => {
                const label = el("label", "quiz-option");
                const input = document.createElement("input");
                input.type = "radio";
                input.name = name;
                input.value = String(index);
                label.append(input, el("span", "", text));
                options.append(label);
                inputs.push(input);
            });
            const actions = el("div", "quiz-actions");
            const check = el("button", "reader-command", "Проверить");
            const reset = el("button", "reader-command", "Повторить");
            check.type = reset.type = "button";
            check.addEventListener("click", () => {
                const chosen = inputs.find(input => input.checked);
                result.hidden = false;
                result.classList.remove("is-correct", "is-incorrect");
                if (!chosen) {
                    result.textContent = "Ответ не выбран.";
                    return;
                }
                const correct = Number(chosen.value) === config.correct;
                result.textContent = correct ? "Верно." : "Неверно. Можно попробовать ещё раз.";
                result.classList.add(correct ? "is-correct" : "is-incorrect");
            });
            reset.addEventListener("click", () => {
                inputs.forEach(input => { input.checked = false; });
                root.querySelectorAll("details").forEach(item => { item.open = false; });
                result.hidden = true;
                result.textContent = "";
                inputs[0].focus();
            });
            actions.append(check, reset);
            root.append(options, actions, result);
        }
        if (config.hint) root.append(details("Подсказка", rendered.hint || markdown(config.hint), "quiz-hint"));
        if (config.answer || config.type === "choice") {
            const answer = rendered.answer || markdown(config.answer);
            if (!rendered.answer && config.type === "choice") answer.prepend(el("p", "quiz-correct-option", config.options[config.correct]));
            root.append(details("Ответ", answer, "quiz-answer"));
        }
    }
    function render(config) {
        const root = el("section", "quiz-block");
        enhance(root, validate(config));
        return root;
    }
    window.QuizBlocks = {validate, render, enhance};
    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll("[data-quiz-config]").forEach(root => {
            try {
                enhance(root, JSON.parse(root.dataset.quizConfig));
            } catch {
                root.replaceChildren(el("p", "content-warning", "Блок самопроверки настроен неверно."));
            }
        });
    });
})();
