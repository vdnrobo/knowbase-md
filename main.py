from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import html
import hmac
import mimetypes
import os
import re
from urllib.parse import parse_qs, quote, unquote, urlparse
from xml.etree import ElementTree

import markdown
from markdown.extensions import Extension
from markdown.postprocessors import Postprocessor
from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor

ENV_FILE = ".env"


def load_env_file(path):
    if not os.path.isfile(path):
        return

    with open(path, "r", encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue

            if line.startswith("export "):
                line = line[len("export "):].strip()

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if not key or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
                continue

            if (
                len(value) >= 2
                and value[0] == value[-1]
                and value[0] in {'"', "'"}
            ):
                value = value[1:-1]

            os.environ.setdefault(key, value)


load_env_file(ENV_FILE)

HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "80"))

ARTICLES_DIR = "./articles"
STATIC_DIR = "./static"
ANNOUNCEMENT_FILE = "./announcement.md"
FAVICON_FILE = "./favicon.ico"
SITE_VERSION = "1.1.0"
FOOTER_TEXT = (
    f"VDN 2026 · v{SITE_VERSION} · made by humans on Earth, "
    "слои не расходятся и лежат ровно"
)
PROTECTED_MARKER = "<!-- protected -->"
PASSWORD_ENV_PREFIX = "ARTICLE_PASSWORD_"
AUTH_COOKIE_PREFIX = "article_auth_"
MAX_FORM_BYTES = 4096
MEDIA_EXTENSIONS = {
    ".avif",
    ".gif",
    ".ico",
    ".jpeg",
    ".jpg",
    ".png",
    ".svg",
    ".webp",
}


class FigureImageTreeprocessor(Treeprocessor):
    def run(self, root):
        for parent in root.iter():
            children = list(parent)
            for index, child in enumerate(children):
                if child.tag != "p":
                    continue

                if (child.text or "").strip():
                    continue

                paragraph_children = list(child)
                if len(paragraph_children) != 1:
                    continue

                image = paragraph_children[0]
                if image.tag != "img" or (image.tail or "").strip():
                    continue

                figure = ElementTree.Element("figure")
                image.tail = None
                figure.append(image)

                caption = (image.get("alt") or "").strip()
                if caption:
                    figcaption = ElementTree.SubElement(figure, "figcaption")
                    figcaption.text = caption

                parent[index] = figure


class FigureImageExtension(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(
            FigureImageTreeprocessor(md),
            "figure_images",
            15,
        )


class MathPreservePreprocessor(Preprocessor):
    placeholder_prefix = "MATHJAX_PLACEHOLDER_"
    math_pattern = re.compile(
        r"(?s)(\$\$.*?\$\$|\\\[.*?\\\]|\\\(.*?\\\)|(?<!\\)\$(?!\s)(?:\\.|[^$\\])+\$)"
    )

    def run(self, lines):
        self.md.mathjax_stash = []
        processed_lines = []
        text_chunk = []
        in_fence = False

        def flush_text_chunk():
            if not text_chunk:
                return
            chunk = "\n".join(text_chunk)
            processed_lines.extend(
                self.math_pattern.sub(self.preserve_math, chunk).split("\n")
            )
            text_chunk.clear()

        for line in lines:
            if re.match(r"^\s*(```|~~~)", line):
                flush_text_chunk()
                in_fence = not in_fence
                processed_lines.append(line)
                continue

            if in_fence:
                processed_lines.append(line)
                continue

            text_chunk.append(line)

        flush_text_chunk()

        return processed_lines

    def preserve_math(self, match):
        index = len(self.md.mathjax_stash)
        self.md.mathjax_stash.append(match.group(0))
        return f"{self.placeholder_prefix}{index}_END"


class MathPreservePostprocessor(Postprocessor):
    placeholder_pattern = re.compile(r"MATHJAX_PLACEHOLDER_(\d+)_END")

    def run(self, text):
        stash = getattr(self.md, "mathjax_stash", [])

        def restore_math(match):
            index = int(match.group(1))
            if index >= len(stash):
                return match.group(0)
            return stash[index]

        return self.placeholder_pattern.sub(restore_math, text)


class OrderedListContinuationTreeprocessor(Treeprocessor):
    placeholder_pattern = re.compile(r"^MATHJAX_PLACEHOLDER_(\d+)_END$")

    def run(self, root):
        self.continue_ordered_lists(root)

    def continue_ordered_lists(self, parent):
        ordered_list_count = None

        for child in list(parent):
            if child.tag == "ol":
                if ordered_list_count is not None and "start" not in child.attrib:
                    child.set("start", str(ordered_list_count + 1))

                ordered_list_count = self.get_ordered_list_end(child)
                self.continue_ordered_lists(child)
                continue

            if self.is_display_math_paragraph(child):
                continue

            ordered_list_count = None
            self.continue_ordered_lists(child)

    def get_ordered_list_end(self, ordered_list):
        start = int(ordered_list.get("start", "1"))
        items = sum(1 for child in list(ordered_list) if child.tag == "li")
        return start + items - 1

    def is_display_math_paragraph(self, element):
        if element.tag != "p" or list(element):
            return False

        text = (element.text or "").strip()
        match = self.placeholder_pattern.match(text)
        if not match:
            return False

        stash = getattr(self.md, "mathjax_stash", [])
        index = int(match.group(1))
        if index >= len(stash):
            return False

        math = stash[index].strip()
        return math.startswith("$$") or math.startswith("\\[")


class MathPreserveExtension(Extension):
    def extendMarkdown(self, md):
        md.preprocessors.register(
            MathPreservePreprocessor(md),
            "preserve_math",
            175,
        )
        md.treeprocessors.register(
            OrderedListContinuationTreeprocessor(md),
            "continue_ordered_lists_around_math",
            25,
        )
        md.postprocessors.register(
            MathPreservePostprocessor(md),
            "restore_math",
            5,
        )


def read_text_file(path, default=""):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return f.read().strip()
    except FileNotFoundError:
        return default


def render_site_footer():
    return f"""
        <footer class="site-footer">
            {html.escape(FOOTER_TEXT)}
        </footer>
    """


def normalize_category_slug(category_slug):
    normalized = re.sub(r"[^A-Z0-9]+", "_", category_slug.upper()).strip("_")
    return normalized or "CATEGORY"


def get_category_password_env(category_slug):
    return f"{PASSWORD_ENV_PREFIX}{normalize_category_slug(category_slug)}"


def get_category_auth_cookie_name(category):
    suffix = category["password_env"][len(PASSWORD_ENV_PREFIX):].lower()
    return f"{AUTH_COOKIE_PREFIX}{suffix}"


def get_category_password(category):
    return os.environ.get(category["password_env"], "")


def build_auth_token(category, password):
    message = f"{category['slug']}:article-access".encode("utf-8")
    return hmac.new(password.encode("utf-8"), message, hashlib.sha256).hexdigest()


def split_protected_marker(content):
    body = content.lstrip()

    if not body.startswith(PROTECTED_MARKER):
        return False, content

    return True, body[len(PROTECTED_MARKER):].lstrip()


def strip_leading_html_comments(content):
    body = content.lstrip()

    while body.startswith("<!--"):
        comment_end = body.find("-->")
        if comment_end == -1:
            break
        body = body[comment_end + 3:].lstrip()

    return body


def get_article_title(content, fallback):
    for line in strip_leading_html_comments(content).splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1).strip()

    return fallback


def count_toc_items(tokens):
    total = 0
    for token in tokens:
        total += 1
        total += count_toc_items(token.get("children", []))
    return total


def render_markdown(content):
    md = markdown.Markdown(
        extensions=["extra", "toc", FigureImageExtension(), MathPreserveExtension()],
        extension_configs={
            "toc": {
                "toc_depth": "1-6",
                "permalink": False,
            },
        },
        output_format="html5",
    )
    content_html = md.convert(content)
    toc_html = md.toc if count_toc_items(md.toc_tokens) else ""
    return content_html, toc_html


def render_description_markdown(content):
    content_html, _ = render_markdown(content)
    def replace_url(match):
        url = match.group(1).rstrip(".,;:!?")
        trailing = match.group(1)[len(url):]
        return f'<a href="{url}">{url}</a>{trailing}'

    content_html = re.sub(r"(?<![\"'=])(https?://[^\s<)]+)", replace_url, content_html)
    return content_html


def load_announcement():
    content = read_text_file(ANNOUNCEMENT_FILE)
    if not content:
        return ""

    content_html, _ = render_markdown(content)
    return f"""
        <section class="announcement">
            {content_html}
        </section>
    """


def safe_join(base_dir, *parts):
    base_path = os.path.abspath(base_dir)
    file_path = os.path.abspath(os.path.join(base_path, *parts))

    if os.path.commonpath([base_path, file_path]) != base_path:
        return None

    return file_path


def find_article_media(path):
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        return None

    extension = os.path.splitext(parts[-1])[1].lower()
    if extension not in MEDIA_EXTENSIONS:
        return None

    category_dir = os.path.join(ARTICLES_DIR, parts[0])
    file_path = safe_join(category_dir, *parts[1:])
    if file_path and os.path.isfile(file_path):
        return file_path

    return None


def load_content():
    categories = []
    articles_by_url = {}

    for category_slug in sorted(os.listdir(ARTICLES_DIR)):
        category_dir = os.path.join(ARTICLES_DIR, category_slug)
        if not os.path.isdir(category_dir):
            continue

        category_title = read_text_file(
            os.path.join(category_dir, "category.txt"),
            category_slug,
        )
        category_description = read_text_file(
            os.path.join(category_dir, "description.txt"),
        )
        category_description_html = ""
        if category_description:
            category_description_html = render_description_markdown(category_description)

        category = {
            "slug": category_slug,
            "title": category_title,
            "description": category_description,
            "description_html": category_description_html,
            "password_env": get_category_password_env(category_slug),
            "articles": [],
        }

        for filename in sorted(os.listdir(category_dir)):
            if not filename.endswith(".md"):
                continue

            article_slug = os.path.splitext(filename)[0]
            article_path = os.path.join(category_dir, filename)

            with open(article_path, "r", encoding="utf-8") as f:
                content = f.read()

            protected, content = split_protected_marker(content)
            content_html, toc_html = render_markdown(content)
            url = f"/{quote(category_slug)}/{quote(article_slug)}"
            article = {
                "title": get_article_title(content, article_slug),
                "content": content_html,
                "toc": toc_html,
                "url": url,
                "search_text": content,
                "protected": protected,
                "category": category,
                "slug": article_slug,
            }

            category["articles"].append(article)
            articles_by_url[url] = article

        if category["articles"]:
            categories.append(category)

    categories.sort(key=lambda category: category["slug"].casefold())
    return categories, articles_by_url


class Handler(BaseHTTPRequestHandler):
    def send_html(self, content, status=200, headers=None):
        self.send_response(status)
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode("utf-8"))

    def send_file(self, file_path, content_type=None):
        guessed_type = mimetypes.guess_type(file_path)[0]

        self.send_response(200)
        self.send_header("Content-type", content_type or guessed_type or "application/octet-stream")
        self.end_headers()

        with open(file_path, "rb") as f:
            self.wfile.write(f.read())

    def has_article_access(self, article):
        if not article["protected"]:
            return True

        category = article["category"]
        password = get_category_password(category)
        if not password:
            return False

        cookie_header = self.headers.get("Cookie", "")
        cookies = SimpleCookie()
        try:
            cookies.load(cookie_header)
        except CookieError:
            return False

        cookie_name = get_category_auth_cookie_name(category)
        auth_cookie = cookies.get(cookie_name)
        if not auth_cookie:
            return False

        expected_token = build_auth_token(category, password)
        return hmac.compare_digest(auth_cookie.value, expected_token)

    def render_password_page(self, article, status=200, error=""):
        category = article["category"]
        site_footer = render_site_footer()
        escaped_title = html.escape(article["title"])
        escaped_category = html.escape(category["title"])
        action = html.escape(article["url"])

        error_html = ""
        if error:
            error_html = f'<p class="auth-error">{html.escape(error)}</p>'

        self.send_html(f"""
            <!DOCTYPE html>
            <html lang="ru">
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>Доступ ограничен — {escaped_title}</title>
                <link rel="icon" href="/favicon.ico" type="image/x-icon" sizes="any">
                <link rel="stylesheet" href="/static/style.css">
                <script src="/static/site.js" defer></script>
            </head>
            <body>
                <div class="container auth-container">
                    <a class="page-mark" href="/" aria-label="На главную">
                        <img class="page-mark-icon" src="/static/site-icon.svg" alt="" width="32" height="32">
                        <span>VDN на Robo548</span>
                    </a>
                    <main class="auth-card">
                        <p class="auth-kicker">Закрытая статья</p>
                        <h1>{escaped_title}</h1>
                        <p class="auth-note">
                            Эта статья относится к разделу «{escaped_category}».
                            Введите пароль раздела, чтобы открыть все защищённые статьи внутри него.
                        </p>
                        {error_html}
                        <form class="auth-form" method="post" action="{action}">
                            <label for="article-password">Пароль</label>
                            <div class="auth-form-row">
                                <input id="article-password" name="password" type="password" autocomplete="current-password" required autofocus>
                                <button type="submit">Открыть</button>
                            </div>
                        </form>
                    </main>
                    {site_footer}
                </div>
            </body>
            </html>
        """, status=status)

    def do_POST(self):
        path = urlparse(self.path).path
        categories, articles = load_content()

        if path not in articles or not articles[path]["protected"]:
            self.send_response(404)
            self.end_headers()
            return

        article = articles[path]
        category = article["category"]
        password = get_category_password(category)

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0

        if content_length > MAX_FORM_BYTES:
            self.render_password_page(
                article,
                status=413,
                error="Слишком большой запрос. Попробуйте ввести пароль ещё раз.",
            )
            return

        raw_body = self.rfile.read(content_length).decode("utf-8", errors="replace")
        form = parse_qs(raw_body)
        submitted_password = form.get("password", [""])[0]

        if password and hmac.compare_digest(submitted_password, password):
            cookie_name = get_category_auth_cookie_name(category)
            token = build_auth_token(category, password)
            cookie_path = f"/{quote(category['slug'])}"

            self.send_response(303)
            self.send_header("Location", article["url"])
            self.send_header(
                "Set-Cookie",
                f"{cookie_name}={token}; Path={cookie_path}; HttpOnly; SameSite=Lax",
            )
            self.end_headers()
            return

        error = "Пароль не подошёл."
        if not password:
            error = "Доступ к этому разделу пока не настроен."

        self.render_password_page(article, status=403, error=error)

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/favicon.ico" and os.path.isfile(FAVICON_FILE):
            self.send_file(FAVICON_FILE, "image/x-icon")
            return

        # --- STATIC FILES ---
        if path.startswith("/static/"):
            file_path = safe_join(STATIC_DIR, unquote(path[len("/static/"):]))

            if file_path and os.path.isfile(file_path):
                self.send_file(file_path)
            else:
                self.send_response(404)
                self.end_headers()

            return

        media_path = find_article_media(path)
        if media_path:
            self.send_file(media_path)
            return

        categories, articles = load_content()

        # --- MAIN PAGE ---
        if path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()

            announcement = load_announcement()
            site_footer = render_site_footer()
            category_blocks = ""
            for category in categories:
                description = ""
                if category["description"]:
                    description = (
                        f'<div class="category-description">'
                        f'{category["description_html"]}</div>'
                    )

                links = ""
                protected_links = ""
                category_search_text = (
                    f'{category["title"]} {category["description"]}'
                )

                for article in category["articles"]:
                    article_search_text = (
                        f'{category_search_text} {article["title"]} '
                        f'{article["search_text"]}'
                    )
                    article_link = f"""
                        <li class="article-item" data-search="{html.escape(article_search_text)}">
                            <a href="{article["url"]}">{html.escape(article["title"])}</a>
                        </li>
                    """
                    if article["protected"]:
                        protected_links += f"""
                            <li class="article-item protected-article" data-search="{html.escape(article_search_text)}">
                                <a href="{article["url"]}">{html.escape(article["title"])}</a>
                                <span class="protected-badge">закрыто</span>
                            </li>
                        """
                    else:
                        links += article_link

                regular_list = ""
                if links:
                    regular_list = f"""
                        <ul class="article-list">
                            {links}
                        </ul>
                    """

                protected_list = ""
                if protected_links:
                    protected_id = f"protected-{normalize_category_slug(category['slug']).lower()}"
                    protected_list = f"""
                        <div class="protected-articles" data-protected-articles>
                            <button class="protected-toggle" type="button" aria-expanded="false" aria-controls="{html.escape(protected_id)}">
                                Показать защищённые статьи
                            </button>
                            <ul id="{html.escape(protected_id)}" class="article-list protected-article-list" hidden>
                                {protected_links}
                            </ul>
                        </div>
                    """

                category_blocks += f"""
                    <details id="category-{html.escape(category["slug"])}" class="category" open data-search="{html.escape(category_search_text)}">
                        <summary>
                            <span>{html.escape(category["title"])}</span>
                        </summary>
                        {description}
                        {regular_list}
                        {protected_list}
                    </details>
                """

            self.wfile.write(f"""
            <!DOCTYPE html>
            <html lang="ru">
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>vdn@robo548</title>
                <link rel="icon" href="/favicon.ico" type="image/x-icon" sizes="any">
                <link rel="stylesheet" href="/static/style.css">
                <script src="/static/site.js" defer></script>
            </head>
            <body>
                <div class="container">
                    <header class="site-brand">
                        <img class="site-brand-icon" src="/static/site-icon.svg" alt="" width="48" height="48">
                        <div>
                            <p class="site-brand-kicker">VDN на Robo548</p>
                            <h1>База знаний</h1>
                        </div>
                    </header>
                    {announcement}
                    <div class="search-box">
                        <label for="site-search">Поиск</label>
                        <input id="site-search" type="search" placeholder="Название, категория или текст статьи">
                    </div>
                    <p id="no-results" class="no-results" hidden>Ничего не найдено.</p>
                    {category_blocks}
                    {site_footer}
                </div>
            </body>
            </html>
            """.encode("utf-8"))

        # --- ARTICLE PAGE ---
        elif path in articles:
            article = articles[path]
            if not self.has_article_access(article):
                self.render_password_page(article)
                return

            category = article["category"]
            site_footer = render_site_footer()
            article_index = category["articles"].index(article)
            previous_article = (
                category["articles"][article_index - 1] if article_index > 0 else None
            )
            next_article = (
                category["articles"][article_index + 1]
                if article_index < len(category["articles"]) - 1
                else None
            )

            def render_article_nav_item(item, label, class_name):
                if not item:
                    return (
                        f'<span class="article-nav-item {class_name} is-disabled">'
                        f'{html.escape(label)}</span>'
                    )

                title = html.escape(item["title"])
                return (
                    f'<a class="article-nav-item {class_name}" href="{item["url"]}" '
                    f'title="{title}">{html.escape(label)}</a>'
                )

            article_nav = f"""
                <nav class="article-bottom-nav" aria-label="Навигация по статьям">
                    <div class="article-bottom-nav-inner">
                        {render_article_nav_item(previous_article, "← Предыдущая", "is-prev")}
                        <a class="article-nav-item is-home" href="/">На главную</a>
                        {render_article_nav_item(next_article, "Следующая →", "is-next")}
                    </div>
                </nav>
            """
            toc = ""
            if article["toc"]:
                toc = f"""
                    <aside class="toc-panel" data-toc-panel>
                        <div class="toc-header">
                            <h2>Оглавление</h2>
                            <button class="toc-toggle" type="button" aria-expanded="true" aria-controls="article-toc">
                                Свернуть
                            </button>
                        </div>
                        <nav id="article-toc" class="toc" aria-label="Оглавление">
                            {article["toc"]}
                        </nav>
                    </aside>
                """

            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()

            self.wfile.write(f"""
            <!DOCTYPE html>
            <html lang="ru">
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>{html.escape(article["title"])}</title>
                <link rel="icon" href="/favicon.ico" type="image/x-icon" sizes="any">
                <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/github.min.css">
                <link rel="stylesheet" href="/static/style.css">
                <script>
                    window.MathJax = {{
                        tex: {{
                            inlineMath: [["\\\\(", "\\\\)"], ["$", "$"]],
                            displayMath: [["\\\\[", "\\\\]"], ["$$", "$$"]],
                            processEscapes: true,
                        }},
                        options: {{
                            skipHtmlTags: ["script", "noscript", "style", "textarea", "pre", "code"],
                        }},
                    }};
                </script>
                <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-chtml.js" defer></script>
                <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js" defer></script>
                <script src="/static/site.js" defer></script>
            </head>
            <body class="article-page">
                <div class="container article-container">
                    <a class="page-mark" href="/" aria-label="На главную">
                        <img class="page-mark-icon" src="/static/site-icon.svg" alt="" width="32" height="32">
                        <span>VDN на Robo548</span>
                    </a>
                    <div class="article-layout">
                        {toc}
                        <main class="article-main">
                            <article class="article-body">
                                {article["content"]}
                            </article>
                        </main>
                    </div>
                    {site_footer}
                </div>
                {article_nav}
            </body>
            </html>
            """.encode("utf-8"))

        # --- 404 ---
        else:
            site_footer = render_site_footer()
            category_links = ""
            for category in categories:
                category_links += (
                    f'<li><a href="/#category-{quote(category["slug"])}">'
                    f'{html.escape(category["title"])}</a></li>'
                )

            suggestions = ""
            if category_links:
                suggestions = f"""
                    <div class="not-found-suggestions">
                        <h2>Пока робот ищет страницу...</h2>
                        <p>Можете перейти в один из разделов:</p>
                        <ul>
                            {category_links}
                        </ul>
                    </div>
                """

            self.send_response(404)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(f"""
        <!DOCTYPE html>
        <html lang="ru">
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1">
            <title>404 — Робот потерял страницу</title>
            <link rel="icon" href="/favicon.ico" type="image/x-icon" sizes="any">
            <link rel="stylesheet" href="/static/style.css">
            <script src="/static/site.js" defer></script>
        </head>
        <body>

        <div class="container not-found">

            <a class="page-mark" href="/" aria-label="На главную">
                <img class="page-mark-icon" src="/static/site-icon.svg" alt="" width="32" height="32">
                <span>VDN · Robo548</span>
            </a>

            <div class="robot">
                🤖
            </div>

            <div class="search-light"></div>

            <p class="not-found-code">404</p>

            <h1>Кажется, робот свернул не туда...</h1>

            <p class="not-found-text">
                Запрошенная страница не найдена.
                Наш маленький робот уже отправился на поиски,
                но пока безуспешно.
            </p>

            <a class="primary-link" href="/">
                ← Вернуться на главную
            </a>

            {suggestions}

            {site_footer}

        </div>

        </body>
        </html>
        """.encode("utf-8"))


def main():
    httpd = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"Сервер запущен на порту {PORT}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
