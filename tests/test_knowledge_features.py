import importlib.util
import json
from pathlib import Path
import re
import os
import subprocess
import sys
import unittest
from urllib.parse import quote, urlencode
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from unittest.mock import patch

import knowledge
import main
import test_category_pages


class KnowledgeRenderingTests(unittest.TestCase):
    def test_metadata_does_not_change_legacy_defaults(self):
        meta, body = main.parse_article_metadata('<!-- requires: /a/b#x -->\n<!-- updated: 2026-11-23 -->\n<!-- update-note: New version -->\n<!-- protected -->\n<!-- authors: vdn -->\n# Title')
        self.assertTrue(meta['protected'])
        self.assertEqual(meta['requires'], ['/a/b#x'])
        self.assertEqual(meta['updated'], '2026-11-23')
        self.assertEqual(body, '# Title')

    def test_download_and_glossary_do_not_change_code_or_links(self):
        glossary = {'uart': {'title': 'UART', 'definition': '<b>Serial</b>', 'url': '/a/b'}}
        body, _ = main.render_markdown('[[uart]] [[missing|label]] `[[uart]]` [link [[uart]]](https://example.com)\n\n[Download](files/x.zip){.download}', glossary)
        self.assertEqual(body.count('class="glossary-term"'), 1)
        self.assertIn('<code>[[uart]]</code>', body)
        self.assertIn('link [[uart]]</a>', body)
        self.assertIn('&lt;b&gt;Serial&lt;/b&gt;', body)
        self.assertIn('download=""', body)
        self.assertIn('class="download download-button"', body)
        self.assertNotIn('[[missing', body)

    def test_quizzes_and_nested_examples(self):
        config = {'type': 'choice', 'question': '<script>test</script>', 'options': ['A', 'B'], 'correct': 1}
        source = '```quiz\n' + json.dumps(config) + '\n```'
        body, _ = main.render_markdown(source)
        self.assertIn('data-quiz-config=', body)
        self.assertNotIn('<script>test', body)
        self.assertIn('quiz-answer', body)
        nested, _ = main.render_markdown('````markdown\n' + source + '\n````')
        self.assertNotIn('data-quiz-config=', nested)
        invalid, _ = main.render_markdown('```quiz\n{"type":"choice"}\n```')
        self.assertIn('content-warning', invalid)
        exercise, _ = main.render_markdown('```quiz\n{"type":"exercise","question":"Q","hint":"H","answer":"A"}\n```')
        self.assertIn('quiz-hint', exercise)
        self.assertIn('quiz-answer', exercise)

    def test_validation_rejects_bad_indexes_and_types(self):
        for correct in (-1, 2, True, '0'):
            with self.subTest(correct=correct), self.assertRaises(ValueError):
                knowledge.validate_quiz({'type': 'choice', 'question': 'Q', 'options': ['A', 'B'], 'correct': correct})
        self.assertEqual(knowledge.valid_date('2026-02-30'), '')
        self.assertEqual(knowledge.valid_date('2026-2-3'), '')
        self.assertEqual(knowledge.valid_date('2026-11-23'), '2026-11-23')

    def test_quiz_hint_and_answer_support_markdown_without_javascript(self):
        config = {
            'type': 'exercise', 'question': 'Q',
            'hint': '**Bold** and *italic* with `Serial`\n\n- First\n- Second',
            'answer': '```python\nprint("<value>")\n```\n\n[Documentation](https://example.com)\n\n> A quote',
        }
        body, _ = main.render_markdown('```quiz\n' + json.dumps(config) + '\n```')
        for fragment in ('quiz-label', '<strong>Bold</strong>', '<em>italic</em>', '<code>Serial</code>', '<ul>', '<pre><code class="language-python">', '&lt;value&gt;', '<blockquote>', 'href="https://example.com"'):
            self.assertIn(fragment, body)

    def test_quiz_markdown_does_not_allow_raw_html_or_unsafe_links(self):
        source = '<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[bad](javascript:alert(1))\n\n[bad](data:text/html,hello)\n\n[safe](/category/article#section)'
        body = knowledge.render_quiz_markdown(source)
        for fragment in ('<script', '<img', 'href="javascript:', 'href="data:'):
            self.assertNotIn(fragment, body)
        self.assertIn('&lt;script&gt;', body)
        self.assertIn('href="/category/article#section"', body)

    def test_quiz_choice_answer_option_remains_plain_text(self):
        body = knowledge.render_quiz({'type': 'choice', 'question': 'Q', 'options': ['**literal**', 'B'], 'correct': 0, 'answer': '**Explanation**'})
        self.assertIn('class="quiz-correct-option">**literal**</p>', body)
        self.assertIn('<strong>Explanation</strong>', body)

    def test_quiz_question_supports_markdown_and_block_elements(self):
        question = '**Compare** `value` and *result*.\n\n1. Read a value.\n2. Print it.\n\n```cpp\nSerial.println(value);\n```'
        for kind in ('choice', 'exercise'):
            config = {'type': kind, 'question': question, 'options': ['A', 'B'], 'correct': 0}
            with self.subTest(kind=kind):
                body, _ = main.render_markdown('```quiz\n' + json.dumps(config) + '\n```')
                self.assertIn('<div class="quiz-question quiz-text">', body)
                self.assertNotIn('<h3 class="quiz-question">', body)
                for fragment in ('<strong>Compare</strong>', '<code>value</code>', '<em>result</em>', '<ol>', '<pre><code class="language-cpp">'):
                    self.assertIn(fragment, body)

    def test_quiz_question_filters_raw_html_and_unsafe_links(self):
        body = knowledge.render_quiz({'type': 'exercise', 'question': '<script>alert(1)</script>\n\n[bad](javascript:alert(1))'})
        self.assertNotIn('<script>', body)
        self.assertNotIn('href="javascript:', body)
        self.assertIn('&lt;script&gt;', body)

    def test_related_links_normalize_unicode_and_literal_percent(self):
        path = '/course/тема%'
        target = {'url': quote(path), 'title': 'Target', 'protected': False}
        article = {'url': '/course/intro', 'related': [path]}
        result = knowledge.render_relations(article, {quote(path): target})
        self.assertIn('Target', result)


class KnowledgeHTTPTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_category_pages.CategoryPageTests('test_loaded_categories_have_urls')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()
        self.root = Path(main.ARTICLES_DIR)
        self.course = self.root / '01-course'
        self.file = self.course / '00-intro.md'
        (self.course / 'files').mkdir()
        (self.course / 'files' / 'example.zip').write_bytes(b'PK\x00archive')
        (self.root / 'glossary.json').write_text(json.dumps({'uart': {'title': 'UART', 'definition': 'Serial', 'url': '/01-course/35-other'}}), encoding='utf-8')
        self.file.write_text('<!-- updated: 2026-11-23 -->\n<!-- update-note: New diagram -->\n<!-- related: /01-course/11-closed, /01-course/35-other -->\n# Introduction\n\n[[uart]]\n\n[Download](files/example.zip){.download}\n', encoding='utf-8')
        self.cookies = SimpleCookie()
        self.enterContext(patch.dict('os.environ', {'ADMIN_PASSWORD': 'admin-test-secret'}))

    def request(self, path, method='GET', form=None, headers=None):
        request_headers = {'User-Agent': 'Mozilla/5.0'}
        if self.cookies:
            request_headers['Cookie'] = '; '.join(f'{k}={v.value}' for k, v in self.cookies.items())
        data = None
        if form is not None:
            data = urlencode(form).encode('utf-8')
            request_headers['Content-Type'] = 'application/x-www-form-urlencoded'
        request_headers.update(headers or {})
        connection = HTTPConnection('127.0.0.1', self.fixture.server.server_port)
        try:
            connection.request(method, path, data, request_headers)
            response = connection.getresponse()
            all_headers = response.getheaders()
            for key, value in all_headers:
                if key.lower() == 'set-cookie':
                    self.cookies.load(value)
            return response.status, dict(all_headers), response.read()
        finally:
            connection.close()

    def token(self, path='/01-course/00-intro'):
        status, _, data = self.request(path)
        self.assertEqual(status, 200)
        return re.search(rb'name="csrf" value="([^"]+)"', data).group(1).decode()

    def valid_form(self, token):
        return {'csrf': token, 'surname': 'Иванов', 'first_name': 'Иван', 'telegram': 'https://t.me/test_user', 'quote': 'Citation', 'message': '<img src=x onerror=alert(1)>', 'anchor': 'introduction'}

    def test_pages_metadata_relations_and_public_catalog(self):
        status, _, raw = self.request('/01-course/00-intro')
        body = raw.decode()
        self.assertEqual(status, 200)
        self.assertIn('2026-11-23', body)
        self.assertIn('data-bookmark-toggle', body)
        self.assertIn('glossary-term', body)
        self.assertIn('related-articles', body)
        self.assertIn('Closed lesson', body)
        self.assertNotIn('Private lesson body.', body)
        for path in ('/bookmarks', '/updates', '/'):
            status, _, raw = self.request(path)
            self.assertEqual(status, 200)
            self.assertNotIn(b'Private lesson body.', raw)
        self.assertIn(b'New diagram', self.request('/updates')[2])

    def test_prerequisites_precede_article_and_other_relations_follow_it(self):
        self.file.write_text('<!-- requires: /01-course/35-other -->\n<!-- related: /01-course/11-closed -->\n<!-- next: /01-course/35-other -->\n# Introduction\n\nArticle body.', encoding='utf-8')
        status, _, raw = self.request('/01-course/00-intro')
        body = raw.decode()
        self.assertEqual(status, 200)
        start = body.index('<article class="article-body"')
        end = body.index('</article>', start)
        self.assertLess(body.index('<h3>Перед чтением</h3>'), start)
        self.assertGreater(body.index('<h3>По теме</h3>'), end)
        self.assertGreater(body.index('<h3>Дальше</h3>'), end)
        self.assertEqual(body.count('<h3>Перед чтением</h3>'), 1)
        self.assertIn('aria-label="Перед чтением"', body)
        self.assertNotIn('Private lesson body.', body)

    def test_article_without_prerequisites_has_no_empty_top_navigation(self):
        status, _, raw = self.request('/01-course/00-intro')
        body = raw.decode()
        self.assertEqual(status, 200)
        start = body.index('<article class="article-body"')
        self.assertNotIn('class="related-articles"', body[:start])
        self.assertNotIn('<h3>Перед чтением</h3>', body)
        self.assertIn('<h3>По теме</h3>', body)

    def test_download_is_public_and_cannot_escape(self):
        status, headers, data = self.request('/01-course/files/example.zip')
        self.assertEqual(status, 200)
        self.assertEqual(data, b'PK\x00archive')
        self.assertIn('attachment;', headers['Content-Disposition'])
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        (self.course / 'files' / 'пример.step').write_bytes(b'STEP')
        status, headers, data = self.request('/01-course/files/%D0%BF%D1%80%D0%B8%D0%BC%D0%B5%D1%80.step')
        self.assertEqual(status, 200)
        self.assertEqual(data, b'STEP')
        self.assertIn("filename*=UTF-8''%D0%BF", headers['Content-Disposition'])
        for path in ('/01-course/files/../00-intro.md', '/01-course/files/%2e%2e/00-intro.md', '/01-course/files/missing.zip', '/01-course/files/..%5c00-intro.md'):
            self.assertEqual(self.request(path)[0], 404)
        try:
            (self.course / 'files' / 'escape.txt').symlink_to(self.file)
        except OSError:
            pass
        else:
            self.assertEqual(self.request('/01-course/files/escape.txt')[0], 404)

    def test_closed_article_files_remain_public_but_feedback_requires_access(self):
        private = self.root / '03-private' / 'files'
        private.mkdir()
        (private / 'handout.bin').write_bytes(b'public attachment')
        self.assertEqual(self.request('/03-private/files/handout.bin')[0], 200)
        self.assertEqual(self.request('/01-course/11-closed/feedback', 'POST', self.valid_form(self.token()))[0], 403)

    def test_required_fields_telegram_csrf_and_rate_limit(self):
        token = self.token()
        original = self.valid_form(token)
        for key in ('surname', 'first_name', 'telegram', 'message'):
            values = dict(original, **{key: '   '})
            self.assertEqual(self.request('/01-course/00-intro/feedback', 'POST', values)[0], 400)
        self.assertEqual(self.request('/01-course/00-intro/feedback', 'POST', dict(original, csrf='bad'))[0], 403)
        self.assertEqual(self.request('/01-course/00-intro/feedback', 'POST', dict(original, telegram='https://evil.test/user'))[0], 400)
        self.assertEqual(self.request('/01-course/00-intro/feedback', 'POST', original, {'Origin': 'https://evil.test'})[0], 403)
        for _ in range(3):
            status, _, raw = self.request('/01-course/00-intro/feedback', 'POST', original, {'Accept': 'application/json'})
            self.assertEqual(status, 200)
            self.assertTrue(json.loads(raw)['ok'])
        self.assertEqual(self.request('/01-course/00-intro/feedback', 'POST', original)[0], 429)
        self.assertEqual(self.request('/01-course/00-intro/feedback', 'POST', {}, {'Content-Length': '70000'})[0], 413)

    def test_admin_session_private_fields_escape_and_actions(self):
        self.request('/01-course/00-intro/feedback', 'POST', self.valid_form(self.token()))
        status, _, body = self.request('/admin/feedback')
        self.assertEqual(status, 200)
        self.assertNotIn('Иванов'.encode(), body)
        self.assertEqual(self.request('/admin/feedback', 'POST', {'action': 'delete', 'id': '1', 'csrf': self.token('/admin/feedback')})[0], 403)
        token = self.token('/admin/feedback')
        status, _, _ = self.request('/admin/feedback', 'POST', {'action': 'login', 'password': 'admin-test-secret', 'csrf': token})
        self.assertEqual(status, 303)
        status, headers, raw = self.request('/admin/feedback')
        body = raw.decode()
        self.assertIn('private, no-store', headers['Cache-Control'])
        self.assertIn('Иванов', body)
        self.assertIn('https://t.me/test_user', body)
        self.assertIn('&lt;img src=x onerror', body)
        self.assertNotIn('<img src=x', body)
        token = re.search(r'name="csrf" value="([^"]+)"', body).group(1)
        for action in ('close', 'reopen', 'delete'):
            self.assertEqual(self.request('/admin/feedback', 'POST', {'action': action, 'id': '1', 'csrf': token})[0], 303)
        self.assertNotIn('Иванов'.encode(), self.request('/admin/feedback')[2])

    def test_admin_disabled_and_login_throttling(self):
        with patch.dict('os.environ', {'ADMIN_PASSWORD': ''}):
            self.assertEqual(self.request('/admin/feedback')[0], 503)
            self.assertNotIn(b'data-feedback-form', self.request('/01-course/00-intro')[2])
        token = self.token('/admin/feedback')
        for _ in range(5):
            self.assertEqual(self.request('/admin/feedback', 'POST', {'action': 'login', 'password': 'bad', 'csrf': token})[0], 403)
        self.assertEqual(self.request('/admin/feedback', 'POST', {'action': 'login', 'password': 'bad', 'csrf': token})[0], 429)

    def test_checker_reports_issues_without_modifying_content(self):
        spec = importlib.util.spec_from_file_location('checker', Path('tools/check_content.py'))
        checker = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checker)
        before = self.file.read_bytes()
        problems = checker.check_content()
        self.assertFalse([item for item in problems if item[0] == 'ERROR'], problems)
        self.assertEqual(before, self.file.read_bytes())
        self.file.write_text('# Title\n\n[[unknown]]\n\n[Broken](missing.md)\n\n## Same\n## Same\n', encoding='utf-8')
        problems = checker.check_content()
        self.assertTrue(any('unknown term' in item[2] for item in problems))
        self.assertTrue(any('missing link' in item[2] for item in problems))
        self.assertTrue(any('duplicate heading' in item[2] for item in problems))

    def test_checker_cli_handles_unicode_in_windows_pipes(self):
        self.file.write_text('# Title\n\n## Area ²\n\n## Area ²\n', encoding='utf-8')
        result = subprocess.run([sys.executable, 'tools/check_content.py', '--articles', str(self.root)], capture_output=True, env=dict(os.environ, PYTHONIOENCODING='cp1251'), timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr.decode('utf-8', errors='replace'))
        self.assertIn('Area ²', result.stdout.decode('utf-8'))


if __name__ == '__main__':
    unittest.main()
