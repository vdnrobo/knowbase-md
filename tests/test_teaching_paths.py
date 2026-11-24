import importlib.util
from html.parser import HTMLParser
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET
from unittest.mock import patch
from urllib.parse import urlencode

import learning_paths
import knowledge
import main
import test_category_pages


class MarkdownExamples(HTMLParser):
    def __init__(self, content):
        super().__init__()
        self.blocks, self.current = [], None
        self.in_pre = False
        self.feed(content)

    def handle_starttag(self, tag, attributes):
        if tag == 'pre':
            self.in_pre = True
        if tag == 'code' and self.in_pre and dict(attributes).get('class') in ('language-md', 'language-markdown'):
            self.current = []

    def handle_data(self, data):
        if self.current is not None:
            self.current.append(data)

    def handle_endtag(self, tag):
        if tag == 'code' and self.current is not None:
            self.blocks.append(''.join(self.current))
            self.current = None
        if tag == 'pre':
            self.in_pre = False


class TeachingMarkupTests(unittest.TestCase):
    def test_teaching_icons_exist_and_are_valid_svg(self):
        for name in ['link', *(icon for _, icon in knowledge.CALLOUTS.values())]:
            with self.subTest(icon=name):
                root = ET.parse(Path('static/icons') / (name + '.svg')).getroot()
                self.assertEqual(root.tag, '{http://www.w3.org/2000/svg}svg')

    def test_code_markup_and_final_newline_match_existing_clipboard_behavior(self):
        body, _ = main.render_markdown('```python\nprint("<value>")\n```')
        self.assertIn('<pre><code class="language-python">print("&lt;value&gt;")\n</code></pre>', body)

    def test_callout_types_titles_markdown_and_nested_code(self):
        source = '''!!! note
    **Important** text.

!!! warning "Check power"
    Unplug first.

    ```cpp
    int value = 42;
    ```

!!! example
    $x^2$ and `value`.

!!! tip
    - First
    - Second
'''
        body, _ = main.render_markdown(source)
        for kind in ('note', 'warning', 'example', 'tip'):
            self.assertIn(f'class="admonition {kind}"', body)
        for text in ('Важно', 'Check power', 'Пример', 'Совет', '<strong>Important</strong>', '<code>value</code>', '$x^2$', 'language-cpp'):
            self.assertIn(text, body)
        self.assertNotIn('MATHJAX_PLACEHOLDER', body)
        self.assertIn('int value = 42;', body)

    def test_tabs_render_all_panels_for_no_javascript_and_preserve_headings(self):
        source = '''=== "Arduino IDE"
    ## First heading

    ```cpp
    Serial.println(1);
    ```

=== "PlatformIO"
    ## Second heading

    | Pin | Value |
    | --- | --- |
    | TX | 1 |

    ![Diagram](media/a.png)
'''
        body, toc = main.render_markdown(source, heading_links=True)
        self.assertEqual(body.count('class="tabbed-block"'), 2)
        self.assertEqual(body.count('class="tab-panel-title"'), 2)
        self.assertIn('language-cpp', body)
        self.assertIn('<table>', body)
        self.assertIn('<figcaption>Diagram</figcaption>', body)
        self.assertIn('href="#second-heading"', toc)
        self.assertNotIn('heading-link', toc)
        self.assertNotIn('hidden', body)

    def test_new_syntax_inside_code_examples_is_not_executed(self):
        body, _ = main.render_markdown('````markdown\n!!! note\n    Example.\n\n=== "Tab"\n    Text.\n\n```quiz\n{"type":"exercise","question":"Q"}\n```\n````')
        for token in ('class="admonition', 'class="tabbed-set', 'data-quiz-config'):
            self.assertNotIn(token, body)

    def test_heading_ids_and_toc_are_unchanged_by_copy_links(self):
        source = '# Title\n\n## Same *heading*\n\n## Same *heading*\n\n### A `value`\n'
        before, before_toc = main.render_markdown(source)
        after, after_toc = main.render_markdown(source, heading_links=True)
        self.assertEqual(re.findall(r'<h[1-6] id="([^"]+)"', before), re.findall(r'<h[1-6] id="([^"]+)"', after))
        self.assertEqual(before_toc, after_toc)
        self.assertEqual(after.count('data-heading-link='), 3)
        self.assertNotIn('data-heading-link', before)

    def test_documented_examples_are_rendered_by_the_real_pipeline(self):
        guide = Path('docs/site-guide.md').read_text(encoding='utf-8')
        examples = MarkdownExamples(main.render_markdown(guide)[0]).blocks
        callout = next(block for block in examples if '!!! warning' in block)
        tabs = next(block for block in examples if '=== "Arduino IDE"' in block)
        route_text = next(block for block in examples if '## Шаги' in block)
        self.assertIn('class="admonition warning"', main.render_markdown(callout)[0])
        self.assertIn('class="tabbed-block"', main.render_markdown(tabs)[0])
        anchor = next(block for block in examples if '{#power-connection}' in block)
        self.assertIn('id="power-connection"', main.render_markdown(anchor)[0])
        articles = {
            url: {'url': url, 'protected': False, 'title': 'Example', 'content': '<h2 id="connections">Connections</h2>'}
            for url in ('/10-example/00-intro', '/10-example/01-oled', '/20-practice/00-first-task')
        }
        route = {'slug': 'example', 'source_path': 'documentation', 'steps': []}
        problems = []
        main.render_markdown(route_text, extra_extensions=[learning_paths.PathDocumentExtension(route, articles, problems)])
        self.assertEqual(problems, [])
        self.assertEqual(len(route['steps']), 3)


class LearningPathTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_category_pages.CategoryPageTests('test_loaded_categories_have_urls')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.root = Path(main.ARTICLES_DIR).parent
        self.directory = self.root / 'learning-paths'
        self.directory.mkdir()
        self.enterContext(patch.object(main, 'LEARNING_PATHS_DIR', str(self.directory)))
        self.source = self.directory / 'pico.md'
        self.source.write_text('''# First robot

A **practical** introduction. [Background](/01-course/35-other).

## Шаги

1. [Start here](/01-course/00-intro#introduction)
2. [Private lesson](/01-course/11-closed)
3. [Another category](/02-plain/00-first#plain-lesson)
''', encoding='utf-8')

    def load(self):
        articles = main.load_content()[1]
        paths, problems = main.load_learning_paths(articles)
        return articles, paths, problems

    def test_paths_load_in_order_with_anchors_and_no_content_leak(self):
        _, paths, problems = self.load()
        self.assertEqual(problems, [])
        route = paths['pico']
        self.assertEqual(route['title'], 'First robot')
        self.assertEqual(len(route['steps']), 3)
        self.assertTrue(route['steps'][1]['protected'])
        self.assertEqual(route['steps'][0]['url'], '/01-course/00-intro')
        self.assertIn('/01-course/00-intro?route=pico#introduction', route['content'])
        self.assertNotIn('Private lesson body.', route['content'])
        self.assertNotIn('<h1', route['content'])

    def test_public_pages_and_home_routes_are_discoverable(self):
        for url in ('/paths', '/paths/pico', '/'):
            status, _, body = self.fixture.request(url)
            self.assertEqual(status, 200)
            self.assertIn('First robot', body)
            self.assertNotIn('Private lesson body.', body)
            self.assertIn('data-color-mode-switch', body)
        body = self.fixture.request('/paths/pico')[2]
        self.assertIn('закрыто', body)
        self.assertEqual(body.count('<h1>First robot</h1>'), 1)
        self.assertEqual(self.fixture.request('/paths/missing')[0], 404)

    def test_path_context_first_last_and_category_navigation(self):
        for url, position in (('/01-course/00-intro', 'Шаг 1 из 3'), ('/02-plain/00-first', 'Шаг 3 из 3')):
            status, _, body = self.fixture.request(url + '?route=pico')
            self.assertEqual(status, 200)
            self.assertIn(position, body)
            self.assertIn('data-learning-route="pico"', body)
            self.assertIn('class="article-bottom-nav"', body)
            self.assertIn('href="/">На главную', body)
            self.assertIn('aria-disabled="true"', body)
        body = self.fixture.request('/01-course/00-intro?route=pico')[2]
        self.assertIn('href="/01-course/11-closed?route=pico"', body)
        self.assertIn('href="/paths/pico"', body)

    def test_memberships_and_invalid_context(self):
        self.source.with_name('second.md').write_text('# Second route\n\n## Шаги\n\n1. [Intro](/01-course/00-intro)\n', encoding='utf-8')
        for query in ('', '?route=missing', '?route=https%3A%2F%2Fevil.test'):
            body = self.fixture.request('/01-course/00-intro' + query)[2]
            self.assertIn('href="/paths/pico"', body)
            self.assertIn('href="/paths/second"', body)
            self.assertNotIn('class="path-step-nav"', body)
            self.assertIn('data-learning-route=""', body)
        body = self.fixture.request('/01-course/35-other?route=pico')[2]
        self.assertNotIn('class="article-learning-paths"', body)

    def test_password_form_error_and_redirect_keep_validated_route(self):
        url = '/01-course/11-closed?route=pico'
        for method, data, status in (('GET', None, 200), ('POST', 'password=wrong', 403)):
            result, _, body = self.fixture.request(url, method=method, body=data)
            self.assertEqual(result, status)
            self.assertIn('action="' + url + '"', body)
            self.assertNotIn('Private lesson body.', body)
        status, headers, _ = self.fixture.request(url, method='POST', body=urlencode({'password': 'let-me-in'}))
        self.assertEqual(status, 303)
        self.assertEqual(headers['Location'], url)
        cookie = headers['Set-Cookie'].split(';')[0]
        status, _, body = self.fixture.request(url, cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('Шаг 2 из 3', body)
        self.assertIn('Private lesson body.', body)

    def test_password_redirect_keeps_step_anchor_and_drops_invalid_route(self):
        text = self.source.read_text(encoding='utf-8').replace('/01-course/11-closed)', '/01-course/11-closed#closed-lesson)')
        self.source.write_text(text, encoding='utf-8')
        for query, target in (('?route=pico', '?route=pico#closed-lesson'), ('?route=unknown', '')):
            _, headers, _ = self.fixture.request('/01-course/11-closed' + query, method='POST', body='password=let-me-in')
            self.assertEqual(headers['Location'], '/01-course/11-closed' + target)

    def test_invalid_missing_and_duplicate_steps_are_reported_and_skipped(self):
        self.source.write_text('# Robot\n\n## Шаги\n\n1. [Valid](/01-course/00-intro)\n2. [Duplicate](/01-course/00-intro#introduction)\n3. [Missing](/01-course/missing)\n4. [Bad heading](/02-plain/00-first#missing)\n5. [Unsafe](javascript:alert(1))\n', encoding='utf-8')
        _, paths, problems = self.load()
        self.assertEqual(len(problems), 4)
        self.assertEqual(len(paths['pico']['steps']), 1)
        self.assertNotIn('href="javascript:', paths['pico']['content'])
        self.assertNotIn('/01-course/missing', paths['pico']['content'])

    def test_empty_and_malformed_paths_fail_without_breaking_site(self):
        for text in ('# Title\nNo steps.', '# Title\n\n## Шаги\n\n1. [Missing](/a/b)', '# Title\n\n## Шаги\n\n1. [A](/01-course/00-intro)\n\n## Шаги\n\n1. [B](/01-course/35-other)'):
            self.source.write_text(text, encoding='utf-8')
            self.assertEqual(self.load()[1], {})
            self.assertTrue(self.load()[2])
            self.assertEqual(self.fixture.request('/paths')[0], 200)
            self.assertEqual(self.fixture.request('/paths/pico')[0], 404)
            self.assertNotIn('class="home-learning-paths"', self.fixture.request('/')[2])

    def test_unicode_filename_and_symlink_boundaries(self):
        self.source.rename(self.source.with_name('первый-робот.md'))
        _, paths, problems = self.load()
        self.assertFalse(problems)
        route = paths['первый-робот']
        self.assertIn('%', route['url'])
        self.assertEqual(self.fixture.request(route['url'])[0], 200)
        outside = self.root / 'outside.md'
        outside.write_text('# Secret\n\n## Шаги\n\n1. [A](/01-course/00-intro)', encoding='utf-8')
        try:
            (self.directory / 'escape.md').symlink_to(outside)
        except OSError:
            pass
        else:
            _, paths, problems = self.load()
            self.assertNotIn('escape', paths)
            self.assertTrue(any('unsafe' in item[1] for item in problems))

    def test_checker_validates_paths_and_does_not_write_content(self):
        spec = importlib.util.spec_from_file_location('path_checker', 'tools/check_content.py')
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        before = self.source.read_bytes()
        problems = checker.check_content()
        self.assertFalse([p for p in problems if p[0] == 'ERROR'], problems)
        self.assertEqual(before, self.source.read_bytes())
        self.source.write_text('# Title\n\n[Broken intro](/missing/article)\n\n## Шаги\n\n1. [A](/01-course/00-intro)\n2. [B](/unknown/article)', encoding='utf-8')
        problems = checker.check_content()
        self.assertTrue(any('invalid or duplicate step' in p[2] for p in problems))
        self.assertTrue(any('missing link' in p[2] and 'pico.md' in p[1] for p in problems))


if __name__ == '__main__':
    unittest.main()
