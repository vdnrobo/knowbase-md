from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import html
import hmac
import io
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
from PIL import Image, ImageDraw, ImageFont, ImageOps

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
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "").rstrip("/")

ARTICLES_DIR = "./articles"
STATIC_DIR = "./static"
ANNOUNCEMENT_FILE = "./announcement.md"
FAVICON_FILE = "./favicon.ico"
SITE_VERSION = "1.2.0"
GITHUB_URL = "https://github.com/vdnrobo/knowbase-md"
FOOTER_TEXT = (
    f"VDN 2026 · v{SITE_VERSION} · made by humans on Earth"
)
PROTECTED_MARKER = "<!-- protected -->"
PASSWORD_ENV_PREFIX = "ARTICLE_PASSWORD_"
AUTH_COOKIE_PREFIX = "article_auth_"
MAX_FORM_BYTES = 4096
AUTHORS_DIR = "./authors"
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
AUTHOR_PHOTO_EXTENSIONS = {".avif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


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
            {html.escape(FOOTER_TEXT)} · <a href="{GITHUB_URL}" target="_blank" rel="noopener">GitHub</a>
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


def parse_article_metadata(content):
    body = content.lstrip()
    metadata = {
        "protected": False,
        "author_slugs": [],
    }

    while body.startswith("<!--"):
        comment_end = body.find("-->")
        if comment_end == -1:
            break

        comment = body[4:comment_end].strip()
        lower_comment = comment.lower()

        if lower_comment == "protected":
            metadata["protected"] = True
            body = body[comment_end + 3:].lstrip()
            continue

        authors_match = re.match(r"authors?\s*:\s*(.+)$", comment, re.IGNORECASE)
        if authors_match:
            author_slugs = [
                author_slug.strip()
                for author_slug in authors_match.group(1).split(",")
                if author_slug.strip()
            ]
            metadata["author_slugs"].extend(author_slugs)
            body = body[comment_end + 3:].lstrip()
            continue

        break

    return metadata, body


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


def split_markdown_title(content, fallback):
    body = strip_leading_html_comments(content)
    lines = body.splitlines()

    for index, line in enumerate(lines):
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            title = match.group(1).strip()
            description = "\n".join(lines[index + 1:]).strip()
            return title, description

    return fallback, body.strip()


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


def strip_markdown_text(content):
    text = strip_leading_html_comments(content or "")
    text = re.sub(r"```.*?```", " ", text, flags=re.S)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.M)
    text = re.sub(r"[*_~>#-]+", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def truncate_text(text, limit):
    text = re.sub(r"\s+", " ", text or "").strip()
    if len(text) <= limit:
        return text

    return text[:max(0, limit - 1)].rstrip() + "…"


def get_og_description(description):
    return truncate_text(strip_markdown_text(description), 180)


def get_public_origin(handler):
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL

    host = handler.headers.get("Host") or f"{HOST}:{PORT}"
    if host.startswith("0.0.0.0"):
        host = f"localhost:{PORT}"

    proto = handler.headers.get("X-Forwarded-Proto") or "http"
    return f"{proto}://{host}".rstrip("/")


def absolute_url(handler, path):
    if path.startswith("http://") or path.startswith("https://"):
        return path
    if not path.startswith("/"):
        path = f"/{path}"
    return f"{get_public_origin(handler)}{path}"


def render_og_tags(title, description, page_url, image_url, og_type="website"):
    title = html.escape(title or "vdn@robo548", quote=True)
    description = html.escape(description or "База знаний VDN на Robo548", quote=True)
    page_url = html.escape(page_url, quote=True)
    image_url = html.escape(image_url, quote=True)

    return f"""
                <meta property="og:type" content="{html.escape(og_type, quote=True)}">
                <meta property="og:title" content="{title}">
                <meta property="og:description" content="{description}">
                <meta property="og:url" content="{page_url}">
                <meta property="og:image" content="{image_url}">
                <meta property="og:image:width" content="1200">
                <meta property="og:image:height" content="630">
                <meta name="twitter:card" content="summary_large_image">
                <meta name="twitter:title" content="{title}">
                <meta name="twitter:description" content="{description}">
                <meta name="twitter:image" content="{image_url}">
    """


def load_font(size, bold=False):
    candidates = []
    if bold:
        candidates.extend([
            "C:/Windows/Fonts/arialbd.ttf",
            "C:/Windows/Fonts/segoeuib.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ])
    candidates.extend([
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/segoeui.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ])

    for path in candidates:
        if os.path.isfile(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


def text_size(draw, text, font):
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def wrap_text(draw, text, font, max_width, max_lines):
    words = re.sub(r"\s+", " ", text or "").strip().split()
    lines = []
    current = ""

    for word in words:
        probe = word if not current else f"{current} {word}"
        if text_size(draw, probe, font)[0] <= max_width:
            current = probe
            continue

        if current:
            lines.append(current)
        current = word

        while text_size(draw, current, font)[0] > max_width and len(current) > 1:
            split_at = max(1, len(current) - 1)
            while split_at > 1 and text_size(draw, current[:split_at] + "…", font)[0] > max_width:
                split_at -= 1
            lines.append(current[:split_at] + "…")
            current = current[split_at:]

        if len(lines) >= max_lines:
            break

    if current and len(lines) < max_lines:
        lines.append(current)

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if lines and words and " ".join(lines).strip() != " ".join(words).strip():
        while lines[-1] and text_size(draw, lines[-1] + "…", font)[0] > max_width:
            lines[-1] = lines[-1][:-1].rstrip()
        if not lines[-1].endswith("…"):
            lines[-1] += "…"

    return lines


def draw_wrapped_text(draw, xy, text, font, fill, max_width, max_lines, line_gap=12):
    x, y = xy
    for line in wrap_text(draw, text, font, max_width, max_lines):
        draw.text((x, y), line, font=font, fill=fill)
        y += text_size(draw, line, font)[1] + line_gap
    return y


def load_raster_image(path, size=None, crop=False):
    try:
        image = Image.open(path).convert("RGBA")
    except Exception:
        return None

    if size:
        if crop:
            image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS)
        else:
            image.thumbnail(size, Image.Resampling.LANCZOS)

    return image


def paste_circle_image(base, image, xy, size):
    if not image:
        return

    image = ImageOps.fit(image, (size, size), method=Image.Resampling.LANCZOS)
    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.ellipse((0, 0, size, size), fill=255)
    base.paste(image, xy, mask)


def get_author_photo_image(author, size):
    photo_file, _ = find_author_photo_file(author["slug"])
    if not photo_file:
        return None

    return load_raster_image(photo_file, (size, size), crop=True)


def build_og_image(title, context="", author=None, description="", kind="vdn@robo548", include_author_description=False):
    width, height = 1200, 630
    page_bg = "#f5f7ff"
    surface = "#ffffff"
    accent = "#5070d0"
    accent_dark = "#000070"
    text = "#25293a"
    muted = "#626a86"
    border = "#ccd8ff"

    image = Image.new("RGBA", (width, height), page_bg)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((54, 54, width - 54, height - 54), radius=36, fill=surface, outline=border, width=3)
    draw.rectangle((54, 54, 92, height - 54), fill=accent)

    logo = load_raster_image(FAVICON_FILE, (92, 92), crop=True)
    if logo:
        image.alpha_composite(logo, (108, 94))

    brand_font = load_font(28, bold=True)
    small_font = load_font(30)
    title_font = load_font(58, bold=True)
    context_font = load_font(31, bold=True)
    description_font = load_font(28)

    draw.text((220, 103), "vdn@robo548", font=brand_font, fill=accent_dark)
    draw.text((220, 142), kind, font=small_font, fill=muted)

    y = 220
    y = draw_wrapped_text(draw, (108, y), title, title_font, text, 860, 3, line_gap=16)

    if context:
        y = max(y + 16, 392)
        y = draw_wrapped_text(draw, (108, y), context, context_font, accent_dark, 850, 2, line_gap=10)

    if description and not author:
        draw_wrapped_text(draw, (108, 430), description, description_font, muted, 850, 3, line_gap=10)

    if author:
        avatar_size = 118
        avatar = get_author_photo_image(author, avatar_size)
        avatar_x, avatar_y = 108, 466
        if avatar:
            paste_circle_image(image, avatar, (avatar_x, avatar_y), avatar_size)
            draw.ellipse(
                (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
                outline=border,
                width=4,
            )
            name_x = avatar_x + avatar_size + 28
        else:
            draw.ellipse((avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size), fill="#e5ebff", outline=border, width=4)
            initials = "".join(part[0] for part in author["title"].split()[:2]).upper()[:2]
            initials_font = load_font(42, bold=True)
            initials_w, initials_h = text_size(draw, initials, initials_font)
            draw.text(
                (avatar_x + (avatar_size - initials_w) / 2, avatar_y + (avatar_size - initials_h) / 2 - 4),
                initials,
                font=initials_font,
                fill=accent_dark,
            )
            name_x = avatar_x + avatar_size + 28

        draw.text((name_x, avatar_y + 18), author["title"], font=context_font, fill=text)
        if include_author_description:
            author_description = get_og_description(author.get("description", ""))
            if author_description:
                draw_wrapped_text(draw, (name_x, avatar_y + 60), author_description, description_font, muted, 690, 2, line_gap=8)

    footer_text = "vdn.robo548.ru"
    footer_font = load_font(22)
    footer_width, _ = text_size(draw, footer_text, footer_font)
    draw.text((width - 108 - footer_width, 524), footer_text, font=footer_font, fill=muted)

    output = io.BytesIO()
    image.convert("RGB").save(output, format="PNG", optimize=True)
    return output.getvalue()


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


def find_author_photo_file(author_slug):
    for extension in sorted(AUTHOR_PHOTO_EXTENSIONS):
        file_path = safe_join(AUTHORS_DIR, author_slug, f"photo{extension}")
        if file_path and os.path.isfile(file_path):
            return file_path, extension

    return None, ""


def find_author_photo(path):
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    if len(parts) != 3 or parts[0] != "authors":
        return None

    filename = parts[2]
    if not filename.startswith("photo."):
        return None

    extension = os.path.splitext(filename)[1].lower()
    if extension not in AUTHOR_PHOTO_EXTENSIONS:
        return None

    file_path = safe_join(AUTHORS_DIR, parts[1], filename)
    if file_path and os.path.isfile(file_path):
        return file_path

    return None


def load_authors():
    authors = {}
    if not os.path.isdir(AUTHORS_DIR):
        return authors

    for author_slug in sorted(os.listdir(AUTHORS_DIR)):
        author_dir = os.path.join(AUTHORS_DIR, author_slug)
        if not os.path.isdir(author_dir):
            continue

        profile = read_text_file(os.path.join(author_dir, "profile.md"))
        title, description = split_markdown_title(profile, author_slug)
        description_html = ""
        if description:
            description_html = render_description_markdown(description)

        photo_file, photo_extension = find_author_photo_file(author_slug)
        photo_url = ""
        if photo_file:
            photo_url = f"/authors/{quote(author_slug)}/photo{photo_extension}"

        authors[author_slug] = {
            "slug": author_slug,
            "title": title,
            "description": description,
            "description_html": description_html,
            "photo_url": photo_url,
            "url": f"/authors/{quote(author_slug)}",
            "articles": [],
        }

    return authors


def get_or_create_author(authors, author_slug):
    if author_slug not in authors:
        authors[author_slug] = {
            "slug": author_slug,
            "title": author_slug,
            "description": "",
            "description_html": "",
            "photo_url": "",
            "url": f"/authors/{quote(author_slug)}",
            "articles": [],
        }

    return authors[author_slug]


def sort_authors(authors):
    return sorted(
        authors.values(),
        key=lambda author: (author["title"].casefold(), author["slug"].casefold()),
    )


def get_category_authors(category):
    seen = set()
    category_authors = []
    for article in category["articles"]:
        for author in article["authors"]:
            if author["slug"] in seen:
                continue
            seen.add(author["slug"])
            category_authors.append(author)

    return sort_authors({author["slug"]: author for author in category_authors})


def render_author_links(authors):
    if not authors:
        return ""

    links = [
        f'<a href="{author["url"]}">{html.escape(author["title"])}</a>'
        for author in authors
    ]
    return ", ".join(links)


def render_article_authors(article, class_name):
    if not article["authors"]:
        return ""

    label = "Авторы" if len(article["authors"]) > 1 else "Автор"
    author_items = ""
    for author in article["authors"]:
        author_items += f"""
            <a class="article-author-link" href="{author["url"]}">
                {render_author_photo(author, "article-author-photo")}
                <span>{html.escape(author["title"])}</span>
            </a>
        """

    return f"""
        <div class="{class_name}">
            <span class="article-author-label">{label}:</span>
            <div class="article-author-list">
                {author_items}
            </div>
        </div>
    """


def render_category_authors(category):
    authors = get_category_authors(category)
    if not authors:
        return ""

    label = "Авторы" if len(authors) > 1 else "Автор"
    author_items = ""
    for author in authors:
        author_items += f"""
            <a class="category-author-link" href="{author["url"]}">
                {render_author_photo(author, "category-author-photo")}
                <span>{html.escape(author["title"])}</span>
            </a>
        """

    return f"""
        <span class="category-authors">
            <span class="category-author-label">{label}:</span>
            {author_items}
        </span>
    """


def render_author_photo(author, class_name):
    if author["photo_url"]:
        return (
            f'<img class="{class_name}" src="{author["photo_url"]}" '
            f'alt="{html.escape(author["title"])}">'
        )

    initials = "".join(
        part[0].upper()
        for part in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", author["title"])[:2]
    )
    if not initials:
        initials = "?"

    return f'<div class="{class_name} author-photo-placeholder">{html.escape(initials)}</div>'


def render_article_list_item(article, protected=False, show_authors=False):
    authors = ""
    if show_authors:
        authors = render_article_authors(article, "article-item-authors")
    badge = ""
    protected_class = ""
    if protected:
        protected_class = " protected-article"
        badge = '<span class="protected-badge">закрыто</span>'

    return f"""
        <li class="article-item{protected_class}" data-search="{html.escape(article["search_text"])}">
            <a href="{article["url"]}">{html.escape(article["title"])}</a>
            {badge}
            {authors}
        </li>
    """


def render_author_article_item(article):
    badge = ""
    protected_class = ""
    if article["protected"]:
        protected_class = " protected-article"
        badge = '<span class="protected-badge">закрыто</span>'

    category = article["category"]
    search_text = f'{category["title"]} {article["title"]} {article["search_text"]}'

    return f"""
        <li class="article-item{protected_class}" data-search="{html.escape(search_text)}">
            <a href="{article["url"]}">{html.escape(article["title"])}</a>
            {badge}
        </li>
    """


def load_content():
    categories = []
    articles_by_url = {}
    authors = load_authors()

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

            metadata, content = parse_article_metadata(content)
            article_authors = [
                get_or_create_author(authors, author_slug)
                for author_slug in metadata["author_slugs"]
            ]
            author_search_text = " ".join(
                author["title"] for author in article_authors
            )
            content_html, toc_html = render_markdown(content)
            url = f"/{quote(category_slug)}/{quote(article_slug)}"
            article = {
                "title": get_article_title(content, article_slug),
                "content": content_html,
                "toc": toc_html,
                "url": url,
                "search_text": f"{content} {author_search_text}",
                "protected": metadata["protected"],
                "category": category,
                "slug": article_slug,
                "authors": article_authors,
            }

            category["articles"].append(article)
            articles_by_url[url] = article
            for author in article_authors:
                author["articles"].append(article)

        if category["articles"]:
            categories.append(category)

    categories.sort(key=lambda category: category["slug"].casefold())
    return categories, articles_by_url, authors


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

    def send_png(self, content):
        self.send_response(200)
        self.send_header("Content-type", "image/png")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def send_og_image(self, path, articles, authors):
        parts = [unquote(part) for part in path.strip("/").split("/") if part]

        if parts == ["og", "home.png"]:
            self.send_png(build_og_image(
                "База знаний",
                context="Markdown-статьи VDN на Robo548",
                description="Учебные материалы, инструкции и заметки в одном месте.",
                kind="Главная страница",
            ))
            return True

        if len(parts) == 4 and parts[0] == "og" and parts[1] == "articles":
            article_slug = os.path.splitext(parts[3])[0]
            article_url = f"/{quote(parts[2])}/{quote(article_slug)}"
            article = articles.get(article_url)
            if not article:
                return False

            first_author = article["authors"][0] if article["authors"] else None
            self.send_png(build_og_image(
                article["title"],
                context=article["category"]["title"],
                author=first_author,
                kind="Статья",
            ))
            return True

        if len(parts) == 3 and parts[0] == "og" and parts[1] == "authors":
            author_slug = os.path.splitext(parts[2])[0]
            author = authors.get(author_slug)
            if not author:
                return False

            self.send_png(build_og_image(
                author["title"],
                context="Автор материалов",
                author=author,
                kind="Автор",
                include_author_description=True,
            ))
            return True

        return False

    def build_page_og_tags(self, title, description, page_path, image_path, og_type="website"):
        return render_og_tags(
            title,
            description,
            absolute_url(self, page_path),
            absolute_url(self, image_path),
            og_type=og_type,
        )

    def build_article_og_tags(self, article):
        first_author = article["authors"][0] if article["authors"] else None
        description = article["category"]["title"]
        if first_author:
            description = f'{description} · {first_author["title"]}'

        image_path = (
            f'/og/articles/{quote(article["category"]["slug"])}'
            f'/{quote(article["slug"])}.png'
        )
        return self.build_page_og_tags(
            article["title"],
            description,
            article["url"],
            image_path,
            og_type="article",
        )

    def build_author_og_tags(self, author):
        description = get_og_description(author["description"]) or "Автор материалов VDN на Robo548"
        return self.build_page_og_tags(
            author["title"],
            description,
            author["url"],
            f'/og/authors/{quote(author["slug"])}.png',
        )

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
        og_tags = self.build_article_og_tags(article)

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
                {og_tags}
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
        categories, articles, authors = load_content()

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

        author_photo_path = find_author_photo(path)
        if author_photo_path:
            self.send_file(author_photo_path)
            return

        categories, articles, authors = load_content()

        if path.startswith("/og/"):
            if self.send_og_image(path, articles, authors):
                return
            self.send_response(404)
            self.end_headers()
            return

        # --- MAIN PAGE ---
        if path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html; charset=utf-8")
            self.end_headers()

            announcement = load_announcement()
            site_footer = render_site_footer()
            og_tags = self.build_page_og_tags(
                "vdn@robo548",
                "База знаний VDN на Robo548",
                "/",
                "/og/home.png",
            )
            category_blocks = ""
            home_authors = ""
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
                    article["search_text"] = article_search_text
                    if article["protected"]:
                        protected_links += render_article_list_item(
                            article,
                            protected=True,
                        )
                    else:
                        links += render_article_list_item(article)

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
                            <span class="category-title">{html.escape(category["title"])}</span>
                            {render_category_authors(category)}
                        </summary>
                        {description}
                        {regular_list}
                        {protected_list}
                    </details>
                """

            home_author_items = ""
            for author in sort_authors(authors):
                home_author_items += f"""
                    <a class="home-author-link" href="{author["url"]}">
                        {render_author_photo(author, "home-author-photo")}
                        <span>{html.escape(author["title"])}</span>
                    </a>
                """

            if home_author_items:
                home_authors = f"""
                    <section class="home-authors" aria-labelledby="home-authors-title">
                        <h2 id="home-authors-title">Авторы</h2>
                        <div class="home-author-list">
                            {home_author_items}
                        </div>
                    </section>
                """

            self.wfile.write(f"""
            <!DOCTYPE html>
            <html lang="ru">
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>vdn@robo548</title>
                {og_tags}
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
                    {home_authors}
                    {site_footer}
                </div>
            </body>
            </html>
            """.encode("utf-8"))

        # --- AUTHORS LIST ---
        elif path == "/authors":
            site_footer = render_site_footer()
            og_tags = self.build_page_og_tags(
                "Авторы",
                "Авторы материалов VDN на Robo548",
                "/authors",
                "/og/home.png",
            )
            author_cards = ""
            for author in sort_authors(authors):
                articles_count = len(author["articles"])
                description = author["description_html"] or "<p>Описание пока не добавлено.</p>"
                author_cards += f"""
                    <article class="author-card">
                        <a class="author-card-photo-link" href="{author["url"]}">
                            {render_author_photo(author, "author-card-photo")}
                        </a>
                        <div class="author-card-body">
                            <h2><a href="{author["url"]}">{html.escape(author["title"])}</a></h2>
                            <div class="author-description">{description}</div>
                            <p class="author-article-count">Статей: {articles_count}</p>
                        </div>
                    </article>
                """

            if not author_cards:
                author_cards = '<p class="no-results">Авторы пока не добавлены.</p>'

            self.send_html(f"""
            <!DOCTYPE html>
            <html lang="ru">
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <title>Авторы</title>
                {og_tags}
                <link rel="icon" href="/favicon.ico" type="image/x-icon" sizes="any">
                <link rel="stylesheet" href="/static/style.css">
                <script src="/static/site.js" defer></script>
            </head>
            <body>
                <div class="container">
                    <a class="page-mark" href="/" aria-label="На главную">
                        <img class="page-mark-icon" src="/static/site-icon.svg" alt="" width="32" height="32">
                        <span>VDN на Robo548</span>
                    </a>
                    <main>
                        <h1>Авторы</h1>
                        <div class="author-grid">
                            {author_cards}
                        </div>
                    </main>
                    {site_footer}
                </div>
            </body>
            </html>
            """)

        # --- AUTHOR PAGE ---
        elif path.startswith("/authors/"):
            parts = [unquote(part) for part in path.strip("/").split("/") if part]
            if len(parts) != 2 or parts[0] != "authors" or parts[1] not in authors:
                site_footer = render_site_footer()
                self.send_html(f"""
                <!DOCTYPE html>
                <html lang="ru">
                <head>
                    <meta charset="utf-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <title>Автор не найден</title>
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
                        <p class="not-found-code">404</p>
                        <h1>Автор не найден</h1>
                        <p class="not-found-text">Такой автор пока не добавлен.</p>
                        <a class="primary-link" href="/authors">К списку авторов</a>
                        {site_footer}
                    </div>
                </body>
                </html>
                """, status=404)
            else:
                author = authors[parts[1]]
                site_footer = render_site_footer()
                og_tags = self.build_author_og_tags(author)
                description = author["description_html"] or "<p>Описание пока не добавлено.</p>"
                articles_by_category = {}
                for article in sorted(
                    author["articles"],
                    key=lambda item: (
                        item["category"]["slug"].casefold(),
                        item["slug"].casefold(),
                    ),
                ):
                    category = article["category"]
                    articles_by_category.setdefault(category["slug"], {
                        "category": category,
                        "articles": [],
                    })["articles"].append(article)

                article_groups = ""
                for group in articles_by_category.values():
                    category = group["category"]
                    article_items = "".join(
                        render_author_article_item(article)
                        for article in group["articles"]
                    )
                    article_groups += f"""
                        <section class="author-article-group">
                            <h3>{html.escape(category["title"])}</h3>
                            <ul class="article-list">
                                {article_items}
                            </ul>
                        </section>
                    """

                if not article_groups:
                    article_groups = '<p class="no-results">Статьи пока не указаны.</p>'

                self.send_html(f"""
                <!DOCTYPE html>
                <html lang="ru">
                <head>
                    <meta charset="utf-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1">
                    <title>{html.escape(author["title"])}</title>
                    {og_tags}
                    <link rel="icon" href="/favicon.ico" type="image/x-icon" sizes="any">
                    <link rel="stylesheet" href="/static/style.css">
                    <script src="/static/site.js" defer></script>
                </head>
                <body>
                    <div class="container">
                        <a class="page-mark" href="/authors" aria-label="К списку авторов">
                            <img class="page-mark-icon" src="/static/site-icon.svg" alt="" width="32" height="32">
                            <span>Авторы</span>
                        </a>
                        <main>
                            <section class="author-profile">
                                {render_author_photo(author, "author-profile-photo")}
                                <div class="author-profile-body">
                                    <h1>{html.escape(author["title"])}</h1>
                                    <div class="author-description">{description}</div>
                                </div>
                            </section>
                            <section class="author-articles">
                                <h2>Статьи автора</h2>
                                {article_groups}
                            </section>
                        </main>
                        {site_footer}
                    </div>
                </body>
                </html>
                """)

        # --- ARTICLE PAGE ---
        elif path in articles:
            article = articles[path]
            if not self.has_article_access(article):
                self.render_password_page(article)
                return

            category = article["category"]
            site_footer = render_site_footer()
            og_tags = self.build_article_og_tags(article)
            article_index = category["articles"].index(article)
            article_authors = render_article_authors(article, "article-page-authors")
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
                {og_tags}
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
                            {article_authors}
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
