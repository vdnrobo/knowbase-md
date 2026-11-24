"""Read-only content preflight: python tools/check_content.py [--articles DIRECTORY]."""

import argparse
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import quote, unquote, urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import knowledge
import main


class Document(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.links, self.images, self.ids, self.headings = [], [], set(), []
        self.heading = None
        self.feed(text)

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if attributes.get('id'):
            self.ids.add(attributes['id'])
        if tag == 'a' and attributes.get('href'):
            self.links.append(attributes['href'])
        if tag == 'img' and attributes.get('src'):
            self.images.append(attributes['src'])
        if re.fullmatch(r'h[1-6]', tag):
            self.heading = []

    def handle_data(self, data):
        if self.heading is not None:
            self.heading.append(data)

    def handle_endtag(self, tag):
        if re.fullmatch(r'h[1-6]', tag) and self.heading is not None:
            self.headings.append(''.join(self.heading).strip())
            self.heading = None


def check_content(directory=None, paths_directory=None):
    if directory is not None:
        main.ARTICLES_DIR = str(directory)
    if paths_directory is not None:
        main.LEARNING_PATHS_DIR = str(paths_directory)
    root = Path(main.ARTICLES_DIR)
    problems = []
    def report(level, path, message):
        problems.append((level, str(path), message))
    if not root.is_dir():
        report('ERROR', root, 'articles directory does not exist')
        return problems
    glossary_path = root / 'glossary.json'
    glossary = knowledge.load_glossary(root)
    if glossary_path.exists():
        try:
            raw = json.loads(glossary_path.read_text(encoding='utf-8'))
            if not isinstance(raw, dict) or set(raw) != set(glossary):
                raise ValueError('entries need title and definition')
            for key, entry in raw.items():
                if entry.get('url') and not knowledge.safe_link(entry['url']):
                    report('ERROR', glossary_path, f'unsafe glossary link: {key}')
        except (ValueError, OSError, TypeError) as error:
            report('ERROR', glossary_path, f'invalid glossary: {error}')
    try:
        categories, articles, authors = main.load_content()
    except (OSError, UnicodeError, ValueError, RecursionError) as error:
        report('ERROR', root, f'cannot load content: {error}')
        return problems
    documents = {url: Document(article['content']) for url, article in articles.items()}
    paths, path_problems = main.load_learning_paths(articles)
    for path, message in path_problems:
        report('ERROR', path, message)
    documents.update({route['url']: Document(route['content']) for route in paths.values()})
    routes = {'/', '/authors', '/bookmarks', '/updates', '/paths'} | set(documents) | {c['url'] for c in categories} | {a['url'] for a in authors.values()}

    def validate_link(value, article, path, image=False):
        parsed = urlparse(value)
        if parsed.scheme or parsed.netloc:
            if parsed.scheme not in ('http', 'https', 'mailto', 'tel', 'data') and not parsed.netloc:
                report('ERROR', path, f'unsafe link: {value}')
            return
        target = urlparse(urljoin(article['url'], value))
        target = target._replace(path=quote(unquote(target.path), safe="/:@!$&'()*+,;=-._~"))
        if target.path in documents and not image:
            if target.fragment and unquote(target.fragment) not in documents[target.path].ids:
                report('ERROR', path, f'unknown heading: {value}')
            return
        if target.path in routes and not image:
            return
        if target.path.startswith('/static/'):
            file = main.safe_join(main.STATIC_DIR, unquote(target.path[len('/static/'):]))
            valid = file and Path(file).is_file()
        elif re.match(r'^/[^/]+/files(?:/|$)', unquote(target.path)):
            valid = knowledge.attachment_path(root, target.path)
        else:
            valid = main.find_article_media(target.path) or main.find_author_photo(target.path)
        if not valid:
            report('ERROR', path, f'missing {"image" if image else "link or attachment"}: {value}')

    for url, article in articles.items():
        path = Path(article['source_path'])
        source = path.read_text(encoding='utf-8')
        metadata, body = main.parse_article_metadata(source)
        if metadata.get('updated') and not knowledge.valid_date(metadata['updated']):
            report('ERROR', path, 'invalid updated date (expected YYYY-MM-DD)')
        if metadata.get('update_note') and not metadata.get('updated'):
            report('WARNING', path, 'update-note has no updated date')
        for role in ('author_slugs', 'editor_slugs'):
            for slug in metadata[role]:
                profile = main.safe_join(main.AUTHORS_DIR, slug, 'profile.md')
                if not profile or not Path(profile).is_file():
                    report('WARNING', path, f'unknown contributor: {slug}')
        for start, end, payload in knowledge.quiz_fences(body.splitlines()):
            try:
                if end >= len(body.splitlines()):
                    raise ValueError('unclosed fence')
                knowledge.validate_quiz(json.loads(payload))
            except (ValueError, TypeError, RecursionError) as error:
                report('ERROR', path, f'quiz near line {start+1}: {error}')
        term_parser = main.create_markdown_renderer(glossary)
        term_parser.convert(body)
        for key in sorted(term_parser.knowledge_unknown_terms):
            report('ERROR', path, f'unknown term: {key}')
        doc = documents[url]
        for value in doc.links:
            validate_link(value, article, path)
        for value in doc.images:
            validate_link(value, article, path, image=True)
        for field in knowledge.RELATIONS:
            for value in article.get(field, []):
                target = urlparse(value)
                target_path = quote(unquote(target.path), safe="/:@!$&'()*+,;=-._~")
                if target.scheme or target.netloc or target_path not in articles:
                    report('ERROR', path, f'unknown related article: {value}')
                else:
                    validate_link(value, article, path)
        seen = set()
        for title in doc.headings:
            if title in seen:
                report('WARNING', path, f'duplicate heading: {title}')
            seen.add(title)
    for route in paths.values():
        doc = documents[route['url']]
        for value in doc.links:
            validate_link(value, route, route['source_path'])
        for value in doc.images:
            validate_link(value, route, route['source_path'], image=True)
        term_parser = main.create_markdown_renderer(glossary)
        term_parser.convert(Path(route['source_path']).read_text(encoding='utf-8'))
        for key in sorted(term_parser.knowledge_unknown_terms):
            report('ERROR', route['source_path'], f'unknown term: {key}')
    for entry in glossary.values():
        if entry['url']:
            validate_link(entry['url'], {'url': '/'}, glossary_path)
    return problems


def main_cli():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='backslashreplace')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--articles', type=Path)
    parser.add_argument('--paths', type=Path, help='learning paths directory (default: learning-paths)')
    args = parser.parse_args()
    problems = check_content(args.articles, args.paths)
    for level, path, message in problems:
        print(f'{level}: {path}: {message}')
    errors = sum(level == 'ERROR' for level, _, _ in problems)
    warnings = len(problems) - errors
    print(f'{errors} error(s), {warnings} warning(s)')
    return 1 if errors else 0


if __name__ == '__main__':
    raise SystemExit(main_cli())
