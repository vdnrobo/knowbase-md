import os
from pathlib import Path
import unittest
from unittest.mock import patch

import main
import test_category_pages


class NavigationPageTests(unittest.TestCase):
    def setUp(self):
        self.enterContext(patch.dict(os.environ, {'ADMIN_PASSWORD': 'navigation-test-password'}))
        self.fixture = test_category_pages.CategoryPageTests('test_loaded_categories_have_urls')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_loader_script_is_shared_and_independent_of_deferred_scripts(self):
        for path, expected_status in (
            ('/', 200),
            ('/categories/01-course', 200),
            ('/01-course/00-intro', 200),
            ('/01-course/11-closed', 200),
            ('/authors', 200),
            ('/authors/alex', 200),
            ('/bookmarks', 200),
            ('/updates', 200),
            ('/paths', 200),
            ('/admin/feedback', 200),
            ('/missing', 404),
        ):
            with self.subTest(path=path):
                status, _, body = self.fixture.request(path)
                self.assertEqual(status, expected_status)
                self.assertEqual(body.count('<script src="/static/navigation.js" async></script>'), 1)
                self.assertEqual(body.count('<script src="/static/images.js" async></script>'), 1)
                self.assertNotIn('class="page-loading"', body)

    def test_password_error_keeps_loader_and_does_not_reveal_content(self):
        status, _, body = self.fixture.request(
            '/01-course/11-closed', method='POST', body='password=wrong',
        )
        self.assertEqual(status, 403)
        self.assertIn('<script src="/static/navigation.js" async></script>', body)
        self.assertNotIn('Private lesson body.', body)

    def test_script_is_public(self):
        status, headers, body = self.fixture.request('/static/navigation.js')
        self.assertEqual(status, 200)
        content_type = next(value for key, value in headers.items() if key.lower() == 'content-type')
        self.assertIn('javascript', content_type)
        self.assertIn('pageshow', body)
        self.assertNotIn('event.preventDefault()', body)

    def test_shared_footer_has_one_loader(self):
        self.assertEqual(main.render_site_footer().count('src="/static/navigation.js"'), 1)

    def test_arrival_does_not_start_another_loading_screen(self):
        source = Path('static/navigation.js').read_text(encoding='utf-8')
        self.assertNotIn('document.readyState', source)
        self.assertNotIn('addEventListener("load", reset', source)

    def test_image_script_is_public_and_waits_for_decoding(self):
        status, headers, body = self.fixture.request('/static/images.js')
        self.assertEqual(status, 200)
        self.assertIn('javascript', next(value for key, value in headers.items() if key.lower() == 'content-type'))
        self.assertIn('await image.decode()', body)
        self.assertIn('MutationObserver', body)
        self.assertIn('prepareBackgrounds', body)


if __name__ == '__main__':
    unittest.main()
