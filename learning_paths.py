"""Local Markdown learning paths; links reference existing article metadata only."""

import html
from html.parser import HTMLParser
from pathlib import Path
import re
from urllib.parse import parse_qs, quote, unquote, urlencode, urlparse, urlunparse
from xml.etree import ElementTree as ET

from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor


class AnchorIds(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.ids = set()
        self.feed(content)

    def handle_starttag(self, tag, attributes):
        value = dict(attributes).get('id')
        if value:
            self.ids.add(value)


def resolve_step(value, articles):
    if not value.startswith('/') or value.startswith('//') or any(ord(c) < 32 or c == '\\' for c in value):
        return None
    try:
        parsed = urlparse(value)
        path = quote(unquote(parsed.path), safe="/:@!$&'()*+,;=-._~")
        article = articles.get(path)
        if parsed.scheme or parsed.netloc or parsed.query or not article:
            return None
        anchor = unquote(parsed.fragment)
        if anchor and anchor not in AnchorIds(article['content']).ids:
            return None
        href = article['url'] + ('#' + quote(anchor, safe='') if anchor else '')
        return article, href
    except ValueError:
        return None


def step_url(step, route):
    parsed = urlparse(step['href'])
    return urlunparse(parsed._replace(query=urlencode({'route': route['slug']})))


class PathDocument(Treeprocessor):
    def __init__(self, md, route, articles, problems):
        super().__init__(md)
        self.route, self.articles, self.problems = route, articles, problems

    def error(self, message):
        self.problems.append((self.route['source_path'], message))

    def run(self, root):
        children = list(root)
        title = next((node for node in children if node.tag == 'h1'), None)
        headings = [i for i, node in enumerate(children) if node.tag == 'h2' and ''.join(node.itertext()).strip().casefold() == 'шаги']
        if title is None or not ''.join(title.itertext()).strip() or len(headings) != 1:
            self.error('a path needs a # title and exactly one ## Шаги section')
            return
        self.route['title'] = ''.join(title.itertext()).strip()
        start = headings[0]
        end = next((i for i in range(start + 1, len(children)) if children[i].tag in ('h1', 'h2')), len(children))
        lists = [node for node in children[start + 1:end] if node.tag == 'ol']
        if len(lists) != 1:
            self.error('## Шаги must contain exactly one top-level numbered list')
            return
        summary = next((node for node in children[:start] if node.tag == 'p'), None)
        self.route['summary'] = ''.join(summary.itertext()).strip()[:220] if summary is not None else ''
        seen = set()
        for position, item in enumerate(list(lists[0]), 1):
            paragraph = item.find('p')
            container = paragraph if paragraph is not None else item
            link = next(container.iter('a'), None)
            target = resolve_step(link.get('href', ''), self.articles) if link is not None else None
            if not target or target[0]['url'] in seen:
                self.error(f'invalid or duplicate step {position}: {link.get("href", "") if link is not None else "missing link"}')
                lists[0].remove(item)
                continue
            article, href = target
            seen.add(article['url'])
            step = {'url': article['url'], 'href': href, 'title': ''.join(link.itertext()).strip() or article['title'], 'protected': article['protected']}
            self.route['steps'].append(step)
            link.set('href', step_url(step, self.route))
            item.set('class', 'path-step')
            if article['protected']:
                marker = ET.SubElement(container, 'span', {'class': 'protected-mark'})
                marker.text = ' закрыто'
        root.remove(title)
        if not self.route['steps']:
            self.error('a path needs at least one valid step')


class PathDocumentExtension(Extension):
    def __init__(self, route, articles, problems):
        self.route, self.articles, self.problems = route, articles, problems
        super().__init__()

    def extendMarkdown(self, md):
        md.treeprocessors.register(PathDocument(md, self.route, self.articles, self.problems), 'learning_path_document', 1)


def load_paths(directory, articles, render_markdown):
    root = Path(directory)
    paths, problems = {}, []
    if not root.is_dir():
        return paths, problems
    for source in sorted(root.glob('*.md'), key=lambda path: path.name.casefold()):
        if not re.fullmatch(r'[\w-]+', source.stem) or not source.resolve().is_relative_to(root.resolve()):
            problems.append((str(source), 'unsafe path filename'))
            continue
        route = {'slug': source.stem, 'url': '/paths/' + quote(source.stem), 'source_path': str(source), 'steps': []}
        try:
            route['content'], _ = render_markdown(source.read_text(encoding='utf-8'), extra_extensions=[PathDocumentExtension(route, articles, problems)])
        except (OSError, UnicodeError, ValueError, RecursionError) as error:
            problems.append((str(source), f'cannot load path: {error}'))
            continue
        if route['steps']:
            paths[route['slug']] = route
    return paths, problems


def active_path(request_url, article, paths):
    slug = parse_qs(urlparse(request_url).query).get('route', [''])[0]
    route = paths.get(slug)
    return route if route and any(step['url'] == article['url'] for step in route['steps']) else None


def article_request_url(request_url, article, paths):
    route = active_path(request_url, article, paths)
    if route:
        step = next(step for step in route['steps'] if step['url'] == article['url'])
        return step_url(step, route)
    return article['url']


def render_path_list(paths, home=False):
    if not paths:
        return '' if home else '<p>Учебных маршрутов пока нет.</p>'
    body = '<ul class="learning-path-list">'
    for route in paths.values():
        body += f'<li><a href="{html.escape(route["url"])}">{html.escape(route["title"])}</a><span class="path-step-count">Шагов: {len(route["steps"])}</span>'
        if route.get('summary'):
            body += '<p>' + html.escape(route['summary']) + '</p>'
        body += '</li>'
    body += '</ul>'
    return '<section class="home-learning-paths"><h2><a href="/paths">Учебные маршруты</a></h2>' + body + '</section>' if home else body


def render_article_paths(article, paths, active=None):
    memberships = [route for route in paths.values() if any(step['url'] == article['url'] for step in route['steps'])]
    if not memberships:
        return ''
    body = ''
    if active:
        index = next(i for i, step in enumerate(active['steps']) if step['url'] == article['url'])
        body += f'<p class="path-current"><a href="{html.escape(active["url"])}">{html.escape(active["title"])}</a><span>Шаг {index + 1} из {len(active["steps"])}</span></p><nav class="path-step-nav" aria-label="Шаги учебного маршрута">'
        for offset, label, icon in ((-1, 'Предыдущий шаг', 'chevron-left'), (1, 'Следующий шаг', 'chevron-right')):
            target = index + offset
            text = f'<img class="ui-icon" src="/static/icons/{icon}.svg" alt="">{label}'
            if 0 <= target < len(active['steps']):
                body += f'<a href="{html.escape(step_url(active["steps"][target], active))}">{text}</a>'
            else:
                body += f'<span class="is-disabled" aria-disabled="true">{text}</span>'
        body += '</nav>'
        memberships = [route for route in memberships if route is not active]
    if memberships:
        label = 'Другие маршруты' if active else 'Учебные маршруты'
        body += f'<p class="path-memberships">{label}: ' + ', '.join(f'<a href="{html.escape(route["url"])}">{html.escape(route["title"])}</a>' for route in memberships) + '</p>'
    return '<section class="article-learning-paths" aria-label="Учебные маршруты">' + body + '</section>'
