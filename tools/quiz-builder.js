document.addEventListener("DOMContentLoaded", () => {
    "use strict";
    const field = name => document.getElementById(name);
    let options = ["", ""];
    let correct = 0;
    let config = null;
    function update() {
        field("choices").hidden = field("type").value !== "choice";
        try {
            config = window.QuizBlocks.validate({type: field("type").value, question: field("question").value,
                hint: field("hint").value, answer: field("answer").value, options, correct});
            field("output").value = "```quiz\n" + JSON.stringify(config, null, 2) + "\n```\n";
            field("preview").replaceChildren(window.QuizBlocks.render(config));
            field("builder-status").textContent = "";
        } catch (error) {
            config = null;
            field("output").value = "";
            field("preview").replaceChildren();
            field("builder-status").textContent = error.message;
        }
        field("copy").disabled = field("download").disabled = !config;
    }
    function paintOptions() {
        field("options").replaceChildren();
        options.forEach((text, index) => {
            const row = document.createElement("div"); row.className = "builder-option";
            const radio = document.createElement("input"); radio.type = "radio"; radio.name = "correct";
            radio.checked = correct === index; radio.setAttribute("aria-label", `Правильный ответ: вариант ${index + 1}`);
            radio.addEventListener("change", () => { correct = index; update(); });
            const input = document.createElement("input"); input.value = text; input.maxLength = 4000;
            input.setAttribute("aria-label", `Вариант ${index + 1}`);
            input.addEventListener("input", () => { options[index] = input.value; update(); });
            const remove = document.createElement("button"); remove.type = "button"; remove.className = "reader-icon-button";
            remove.title = `Удалить вариант ${index + 1}`; remove.setAttribute("aria-label", remove.title); remove.disabled = options.length <= 2;
            const image = document.createElement("img"); image.src = "../static/icons/x.svg"; image.alt = ""; image.className = "ui-icon"; remove.append(image);
            remove.addEventListener("click", () => {
                options.splice(index, 1);
                if (correct > index) correct--;
                else if (correct === index) correct = 0;
                paintOptions(); update();
            });
            row.append(radio, input, remove); field("options").append(row);
        });
        field("add-option").disabled = options.length >= 10;
    }
    ["type", "question", "hint", "answer"].forEach(name => field(name).addEventListener("input", update));
    field("add-option").addEventListener("click", () => { if (options.length < 10) options.push(""); paintOptions(); update(); });
    field("copy").addEventListener("click", async () => {
        let success = false;
        try { if (navigator.clipboard?.writeText) { await navigator.clipboard.writeText(field("output").value); success = true; } } catch { /* Use selection. */ }
        if (!success) {
            field("output").focus(); field("output").select();
            try { success = document.execCommand("copy"); } catch { /* Keep selected text. */ }
        }
        field("builder-status").textContent = success ? "Скопировано." : "Текст выделен.";
    });
    field("download").addEventListener("click", () => {
        const url = URL.createObjectURL(new Blob([field("output").value], {type: "text/markdown;charset=utf-8"}));
        const link = document.createElement("a"); link.href = url; link.download = "self-check.md";
        document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    });
    field("load").addEventListener("click", () => {
        try {
            const text = field("import").value.trim().replace(/^(`{3,}|~{3,})quiz\s*\n/, "").replace(/\n(`{3,}|~{3,})\s*$/, "");
            const value = window.QuizBlocks.validate(JSON.parse(text));
            ["type", "question", "hint", "answer"].forEach(name => { field(name).value = value[name]; });
            options = value.options || ["", ""]; correct = value.correct || 0;
            paintOptions(); update();
        } catch (error) { field("builder-status").textContent = `Не удалось открыть блок: ${error.message}`; }
    });
    paintOptions(); update();
});
