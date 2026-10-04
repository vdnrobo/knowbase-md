import os
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode

import main


class QuietHandler(main.Handler):
    def log_message(self, format, *args):
        pass


class CategoryPageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        articles = root / "articles"
        authors = root / "authors"
        course = articles / "01-course"
        plain = articles / "02-plain"
        private = articles / "03-private"
        author = authors / "alex"
        for path in (course, plain, private, author, articles / "04-empty"):
            path.mkdir(parents=True)
        (course / "category.txt").write_text("Robotics & electronics", encoding="utf-8")
        (course / "description.txt").write_text("A **practical** course with [a link](https://example.com).", encoding="utf-8")
        (course / "sections.txt").write_text("00-09: Basics\n10-19: Advanced\n", encoding="utf-8")
        (course / "00-intro.md").write_text("<!-- authors: alex -->\n# Introduction\nUnique introductory text.\n", encoding="utf-8")
        (course / "11-closed.md").write_text("<!-- protected -->\n<!-- authors: alex -->\n# Closed lesson\nPrivate lesson body.\n", encoding="utf-8")
        (course / "35-other.md").write_text("# Other topic\nUngrouped text.\n", encoding="utf-8")
        (plain / "00-first.md").write_text("# Plain lesson\nPlain text.\n", encoding="utf-8")
        (private / "00-closed.md").write_text("<!-- protected -->\n# Closed collection\nRestricted content.\n", encoding="utf-8")
        (author / "profile.md").write_text("# Alex Robinson\nAuthor biography.\n", encoding="utf-8")
        self.enterContext(patch.object(main, "ARTICLES_DIR", str(articles)))
        self.enterContext(patch.object(main, "AUTHORS_DIR", str(authors)))
        self.enterContext(patch.object(main, "ACTIVITY_DB_PATH", str(root / "activity.sqlite3")))
        self.enterContext(patch.object(main, "load_announcement", return_value=""))
        self.enterContext(patch.dict(os.environ, {"ARTICLE_PASSWORD_01_COURSE": "let-me-in"}))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, cookie=None, method="GET", body=None):
        headers = {"User-Agent": "Mozilla/5.0"}
        if cookie:
            headers["Cookie"] = cookie
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        connection = HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode("utf-8")
        finally:
            connection.close()

    def test_loaded_categories_have_urls(self):
        categories, _, _ = main.load_content()
        self.assertEqual([category["url"] for category in categories], [
            "/categories/01-course", "/categories/02-plain", "/categories/03-private",
        ])

    def test_category_has_description_authors_groups_and_search(self):
        status, _, body = self.request("/categories/01-course")
        self.assertEqual(status, 200)
        self.assertIn("<h1>Robotics &amp; electronics</h1>", body)
        self.assertIn("<strong>practical</strong>", body)
        self.assertIn('href="https://example.com"', body)
        self.assertIn('href="/authors/alex"', body)
        self.assertIn("Alex Robinson", body)
        self.assertIn('id="site-search"', body)
        self.assertIn("data-search-category", body)
        self.assertIn('class="category-section-title">Basics', body)
        self.assertIn('class="category-section-title">Advanced', body)
        self.assertEqual(body.count('class="article-item'), 3)
        self.assertIn('class="article-list protected-article-list" hidden', body)
        self.assertIn('href="/01-course/11-closed"', body)
        self.assertNotIn('class="home-sidebar"', body)
        self.assertNotIn('class="category"', body)

    def test_category_without_groups_and_private_only_category(self):
        status, _, body = self.request("/categories/02-plain")
        self.assertEqual(status, 200)
        self.assertIn("Plain lesson", body)
        self.assertNotIn('class="category-section-title"', body)
        status, _, body = self.request("/categories/03-private")
        self.assertEqual(status, 200)
        self.assertIn("Closed collection", body)
        self.assertIn('class="article-list protected-article-list" hidden', body)
        self.assertNotIn('type="password"', body)

    def test_home_keeps_lists_and_adds_category_links(self):
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn('href="/categories/01-course"', body)
        self.assertIn('href="/01-course/00-intro"', body)
        self.assertIn('class="category" open data-search-category', body)
        self.assertIn('class="home-sidebar"', body)

    def test_article_password_page_and_author_link_to_category(self):
        status, _, body = self.request("/01-course/00-intro")
        self.assertEqual(status, 200)
        self.assertIn('class="article-category"', body)
        self.assertIn('href="/categories/01-course"', body)
        self.assertIn('class="article-bottom-nav"', body)
        status, _, body = self.request("/01-course/11-closed")
        self.assertEqual(status, 200)
        self.assertIn('type="password"', body)
        self.assertIn('href="/categories/01-course"', body)
        self.assertNotIn("Private lesson body.", body)
        status, _, body = self.request("/authors/alex")
        self.assertEqual(status, 200)
        self.assertIn('<h3><a href="/categories/01-course">', body)

    def test_protected_article_still_requires_password(self):
        status, _, body = self.request("/01-course/11-closed")
        self.assertEqual(status, 200)
        self.assertIn('type="password"', body)
        status, _, body = self.request("/01-course/11-closed", method="POST", body=urlencode({"password": "wrong"}))
        self.assertEqual(status, 403)
        self.assertNotIn("Private lesson body.", body)
        status, headers, _ = self.request("/01-course/11-closed", method="POST", body=urlencode({"password": "let-me-in"}))
        self.assertEqual(status, 303)
        cookies = SimpleCookie(headers["Set-Cookie"])
        cookie = "; ".join(f"{name}={value.value}" for name, value in cookies.items())
        status, _, body = self.request("/01-course/11-closed", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("Private lesson body.", body)
        self.assertNotIn('type="password"', body)

    def test_category_visit_uses_same_visitor_cookie(self):
        status, headers, _ = self.request("/categories/01-course")
        self.assertEqual(status, 200)
        self.assertIn("no-store", headers["Cache-Control"])
        cookies = SimpleCookie(headers["Set-Cookie"])
        cookie = f'{main.VISITOR_COOKIE_NAME}={cookies[main.VISITOR_COOKIE_NAME].value}'
        _, headers, body = self.request("/", cookie=cookie)
        self.assertNotIn("Set-Cookie", headers)
        self.assertIn('<p class="visitor-count">1</p>', body)

    def test_unknown_and_empty_categories_return_404_without_counting(self):
        for path in ("/categories/missing", "/categories/04-empty", "/categories/01-course/extra"):
            status, headers, _ = self.request(path)
            self.assertEqual(status, 404)
            self.assertNotIn("Set-Cookie", headers)
        _, _, body = self.request("/")
        self.assertIn('<p class="visitor-count">1</p>', body)


if __name__ == "__main__":
    unittest.main()
