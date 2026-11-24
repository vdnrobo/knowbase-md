"""Markdown teaching blocks and content metadata shared with the offline checker."""

from datetime import date
import html
import json
from pathlib import Path
import re
from urllib.parse import quote, unquote, urlparse
from xml.etree import ElementTree as ET

from markdown import Markdown
from markdown.extensions import Extension
from markdown.inlinepatterns import InlineProcessor
from markdown.preprocessors import Preprocessor
from markdown.treeprocessors import Treeprocessor


RELATIONS = {'requires': 'Перед чтением', 'related': 'По теме', 'next': 'Дальше'}
CALLOUTS = {
    'note': ('Важно', 'info'), 'warning': ('Осторожно', 'triangle-alert'),
    'example': ('Пример', 'book-open'), 'tip': ('Совет', 'lightbulb'),
}


def format_fenced_code(source, language, class_name, options, md, **kwargs):
    """Keep the existing code markup and final newline with nested SuperFences."""
    pre = ET.Element('pre')
    classes = list(kwargs.get('classes') or [])
    if class_name:
        classes.insert(0, class_name)
    if classes:
        pre.set('class', ' '.join(classes))
    if kwargs.get('id_value'):
        pre.set('id', kwargs['id_value'])
    code = ET.SubElement(pre, 'code')
    if language:
        code.set('class', 'language-' + language)
    for key, value in (kwargs.get('attrs') or {}).items():
        code.set(key, str(value))
    code.text = source + '\n'
    return ET.tostring(pre, encoding='unicode', method='html')


class TeachingBlocksTreeprocessor(Treeprocessor):
    def run(self, root):
        for node in root.iter('div'):
            classes = node.get('class', '').split()
            if 'admonition' in classes:
                kind = next((key for key in CALLOUTS if key in classes), 'note')
                title = node.find('p')
                if title is not None and 'admonition-title' in title.get('class', '').split():
                    label, icon = CALLOUTS[kind]
                    if title.text == kind.capitalize():
                        title.text = label
                    image = ET.Element('img', {'src': f'/static/icons/{icon}.svg', 'alt': '', 'class': 'ui-icon', 'width': '20', 'height': '20'})
                    image.tail, title.text = title.text, None
                    title.insert(0, image)
            if 'tabbed-set' in classes:
                labels = node.find('./div[@class="tabbed-labels"]')
                content = node.find('./div[@class="tabbed-content"]')
                if labels is not None and content is not None:
                    for label, panel in zip(labels, content):
                        title = ET.Element('p', {'class': 'tab-panel-title'})
                        title.text = ''.join(label.itertext())
                        panel.insert(0, title)


class TeachingBlocksExtension(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(TeachingBlocksTreeprocessor(md), 'teaching_blocks', 4)


class HeadingLinksTreeprocessor(Treeprocessor):
    def run(self, root):
        for node in root.iter():
            if node.tag not in ('h2', 'h3', 'h4', 'h5', 'h6') or not node.get('id'):
                continue
            link = ET.SubElement(node, 'a', {
                'class': 'heading-link', 'href': '#' + quote(node.get('id'), safe=''),
                'data-heading-link': '', 'aria-label': 'Скопировать ссылку на раздел',
                'title': 'Скопировать ссылку на раздел',
            })
            ET.SubElement(link, 'img', {'src': '/static/icons/link.svg', 'alt': '', 'class': 'ui-icon', 'width': '20', 'height': '20'})


class HeadingLinksExtension(Extension):
    def extendMarkdown(self, md):
        md.treeprocessors.register(HeadingLinksTreeprocessor(md), 'heading_links', 2)


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        return ''
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError:
        return ''


def safe_link(value):
    if not isinstance(value, str) or any(ord(c) < 32 for c in value):
        return ''
    parsed = urlparse(value)
    if parsed.scheme in ('http', 'https') and parsed.netloc:
        return value
    if not parsed.scheme and not parsed.netloc and value.startswith(('/', '#')) and not value.startswith('//'):
        return value
    return ''


def load_glossary(directory):
    path = Path(directory) / 'glossary.json'
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, RecursionError):
        return {}
    if not isinstance(data, dict):
        return {}
    result = {}
    for key, entry in data.items():
        if not isinstance(entry, dict):
            continue
        title, definition = entry.get('title'), entry.get('definition')
        if isinstance(title, str) and title.strip() and isinstance(definition, str) and definition.strip():
            result[key] = {'title': title.strip(), 'definition': definition.strip(), 'url': safe_link(entry.get('url', ''))}
    return result


def validate_quiz(config):
    if not isinstance(config, dict) or config.get('type') not in ('choice', 'exercise'):
        raise ValueError('type must be choice or exercise')
    result = {'type': config['type']}
    for field in ('question', 'hint', 'answer'):
        value = config.get(field, '')
        if not isinstance(value, str) or len(value) > 16000:
            raise ValueError(f'{field} must be text (at most 16000 characters)')
        result[field] = value.strip()
    if not result['question']:
        raise ValueError('question is required')
    if result['type'] == 'choice':
        options, correct = config.get('options'), config.get('correct')
        if not isinstance(options, list) or not 2 <= len(options) <= 10:
            raise ValueError('choice needs 2 to 10 options')
        if any(not isinstance(item, str) or not item.strip() or len(item) > 4000 for item in options):
            raise ValueError('options must be nonempty text (at most 4000 characters)')
        if type(correct) is not int or not 0 <= correct < len(options):
            raise ValueError('correct must be a zero-based option index')
        result.update(options=[item.strip() for item in options], correct=correct)
    return result


def quiz_link(value):
    value = html.unescape(value).strip()
    if any(ord(char) < 32 or char == '\\' for char in value):
        return ''
    parsed = urlparse(value)
    return value if parsed.scheme.lower() in ('http', 'https', 'mailto') or not parsed.scheme and not parsed.netloc else ''


class QuizLinksTreeprocessor(Treeprocessor):
    def run(self, root):
        for element in root.iter():
            if element.tag == 'a':
                target = quiz_link(element.get('href', ''))
                if target:
                    element.set('href', target)
                else:
                    element.attrib.pop('href', None)
            elif element.tag == 'img':
                element.tag, element.text = 'span', element.get('alt', '')
                element.attrib.clear()


def render_quiz_markdown(text):
    renderer = Markdown(extensions=['fenced_code', 'tables', 'sane_lists'])
    # Teaching text supports Markdown, never executable raw HTML or unsafe URLs.
    renderer.preprocessors.deregister('html_block')
    renderer.inlinePatterns.deregister('html')
    renderer.treeprocessors.register(QuizLinksTreeprocessor(renderer), 'quiz_safe_links', 0)
    return renderer.convert(text)


def render_quiz(config):
    config = validate_quiz(config)
    escaped = lambda value: html.escape(value, quote=True)
    label = 'Вопрос' if config['type'] == 'choice' else 'Задание'
    body = f'<p class="quiz-label">{label}</p><div class="quiz-question quiz-text">{render_quiz_markdown(config["question"])}</div>'
    if config['type'] == 'choice':
        body += '<ol class="quiz-options">' + ''.join(
            f'<li>{escaped(option)}</li>' for option in config['options']
        ) + '</ol>'
    for key, label in (('hint', 'Подсказка'), ('answer', 'Ответ')):
        text = config[key]
        prefix = ''
        if key == 'answer' and config['type'] == 'choice':
            prefix = f'<p class="quiz-correct-option">{escaped(config["options"][config["correct"]])}</p>'
        if text or prefix:
            body += f'<details class="quiz-{key}"><summary>{label}</summary><div class="quiz-text">{prefix}{render_quiz_markdown(text)}</div></details>'
    encoded = escaped(json.dumps(config, ensure_ascii=False))
    return f'<section class="quiz-block" data-quiz-config="{encoded}">{body}</section>'


def quiz_fences(lines):
    """Yield top-level fenced blocks; never interpret examples inside another fence."""
    index = 0
    while index < len(lines):
        match = re.match(r'^ {0,3}(`{3,}|~{3,})([^\n]*)$', lines[index])
        if not match:
            index += 1
            continue
        fence, language = match.groups()
        end = index + 1
        closing = re.compile(r'^ {0,3}' + re.escape(fence[0]) + '{' + str(len(fence)) + r',}\s*$')
        while end < len(lines) and not closing.fullmatch(lines[end]):
            end += 1
        if language.strip() == 'quiz':
            yield index, end, '\n'.join(lines[index + 1:end])
        index = end + 1


class QuizPreprocessor(Preprocessor):
    def run(self, lines):
        for start, end, payload in reversed(list(quiz_fences(lines))):
            try:
                if end >= len(lines):
                    raise ValueError('unclosed quiz fence')
                block = render_quiz(json.loads(payload))
            except (ValueError, TypeError, RecursionError):
                block = '<p class="content-warning" role="status">Блок самопроверки настроен неверно.</p>'
            lines[start:min(end + 1, len(lines))] = ['', self.md.htmlStash.store(block), '']
        return lines


class GlossaryInlineProcessor(InlineProcessor):
    ANCESTOR_EXCLUDES = ('a', 'code', 'pre', 'button')

    def handleMatch(self, match, data):
        key, label = match.group(1).strip(), match.group(2)
        entry = self.md.knowledge_glossary.get(key)
        if not entry:
            self.md.knowledge_unknown_terms.add(key)
            return label or key, match.start(0), match.end(0)
        element = ET.Element('button', {
            'type': 'button', 'class': 'glossary-term', 'data-term-title': entry['title'],
            'data-term-definition': entry['definition'], 'data-term-url': entry['url'],
        })
        element.text = label or entry['title']
        return element, match.start(0), match.end(0)


class DownloadTreeprocessor(Treeprocessor):
    def run(self, root):
        for link in root.iter('a'):
            if 'download' not in link.get('class', '').split():
                continue
            link.set('class', link.get('class', '') + ' download-button')
            link.set('download', '')
            icon = ET.Element('img', {'src': '/static/icons/download.svg', 'alt': '', 'class': 'ui-icon', 'width': '20', 'height': '20'})
            icon.tail, link.text = link.text, None
            link.insert(0, icon)


class KnowledgeExtension(Extension):
    def __init__(self, glossary=None):
        self.glossary = glossary or {}
        super().__init__()

    def extendMarkdown(self, md):
        md.knowledge_glossary = self.glossary
        md.knowledge_unknown_terms = set()
        md.preprocessors.register(QuizPreprocessor(md), 'knowledge_quizzes', 27)
        md.inlinePatterns.register(GlossaryInlineProcessor(r'\[\[([^\]|\n]+)(?:\|([^\]\n]+))?\]\]', md), 'knowledge_terms', 75)
        md.treeprocessors.register(DownloadTreeprocessor(md), 'knowledge_downloads', 7)


def attachment_path(directory, request_path):
    parts = unquote(request_path).strip('/').split('/')
    if len(parts) < 3 or parts[1] != 'files' or any(part in ('', '.', '..') or '\\' in part for part in parts):
        return None
    root = Path(directory).resolve()
    category = (root / parts[0]).resolve()
    files = category / 'files'
    try:
        if not category.is_relative_to(root) or not files.resolve().is_relative_to(category):
            return None
        target = files.joinpath(*parts[2:]).resolve()
        if target.is_relative_to(files.resolve()) and target.is_file():
            return target
    except (OSError, ValueError):
        pass
    return None


def catalog_html(articles):
    data = [
        {'url': a['url'], 'title': a['title'], 'category': a['category']['title'], 'protected': a['protected']}
        for a in articles.values()
    ]
    encoded = json.dumps(data, ensure_ascii=False).replace('&', '\\u0026').replace('<', '\\u003c').replace('>', '\\u003e')
    return f'<script type="application/json" id="article-catalog">{encoded}</script>'


def render_relations(article, articles, fields=None):
    result = ''
    labels = []
    for field, label in RELATIONS.items():
        if fields is not None and field not in fields:
            continue
        items, seen = [], set()
        for value in article.get(field, []):
            parsed = urlparse(value)
            if parsed.scheme or parsed.netloc:
                continue
            target_path = quote(unquote(parsed.path), safe="/:@!$&'()*+,;=-._~")
            target = articles.get(target_path)
            if not target or value in seen or target_path == article['url'] and not parsed.fragment:
                continue
            seen.add(value)
            lock = ' <span class="protected-mark">закрыто</span>' if target['protected'] else ''
            items.append(f'<li><a href="{html.escape(value, quote=True)}">{html.escape(target["title"])}</a>{lock}</li>')
        if items:
            labels.append(label)
            result += f'<section><h3>{label}</h3><ul>{"".join(items)}</ul></section>'
    return f'<nav class="related-articles" aria-label="{" · ".join(labels)}">{result}</nav>' if result else ''


def updated_articles(articles):
    return sorted(
        [a for a in articles.values() if not a['protected'] and valid_date(a.get('updated'))],
        key=lambda a: (a['updated'], a['url']), reverse=True,
    )


def render_updates(articles, limit=None):
    items = updated_articles(articles)
    if limit is not None:
        items = items[:limit]
    if not items:
        return '<p class="no-results">Обновлений пока нет.</p>'
    result = '<ul class="update-list">'
    for article in items:
        note = html.escape(article.get('update_note', ''))
        result += (
            f'<li><time datetime="{article["updated"]}">{article["updated"]}</time> '
            f'<a href="{html.escape(article["url"])}">{html.escape(article["title"])}</a>'
            + (f'<p>{note}</p>' if note else '') + '</li>'
        )
    return result + '</ul>'


def icon_button(name, label, attributes=''):
    return (
        f'<button type="button" class="reader-icon-button" title="{html.escape(label)}" '
        f'aria-label="{html.escape(label)}" {attributes}>'
        f'<img src="/static/icons/{name}.svg" alt="" width="20" height="20"></button>'
    )


def article_tools(article):
    updated = article.get('updated', '')
    date_html = f'<span class="article-updated">Обновлено <time datetime="{updated}">{updated}</time></span>' if updated else ''
    return (
        '<div class="reader-tools" data-reader-tools hidden>'
        + icon_button('bookmark', 'Добавить в закладки', 'data-bookmark-toggle aria-pressed="false"')
        + '<button type="button" class="reader-command" data-resume-reading hidden>Продолжить чтение</button>'
        + '<span class="reader-status" data-reader-status role="status"></span></div>' + date_html
    )
