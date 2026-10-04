import os
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from http.client import HTTPConnection
from http.cookies import SimpleCookie
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import main


class ActivityTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "activity.sqlite3")
        self.enterContext(patch.object(main, "ACTIVITY_DB_PATH", self.database))

    def test_visitors_are_unique_and_expire_after_24_hours(self):
        start = 100000
        self.assertEqual(main.record_visitor("a" * 32, now=start), 1)
        self.assertEqual(main.record_visitor("a" * 32, now=start + 10), 1)
        self.assertEqual(main.record_visitor("b" * 32, now=start + 20), 2)
        self.assertEqual(main.record_visitor("c" * 32, now=start + 86410), 2)
        with closing(sqlite3.connect(self.database)) as database:
            ids = [row[0] for row in database.execute("SELECT visitor_id FROM visitors")]
        self.assertTrue(all(len(value) == 64 for value in ids))
        self.assertNotIn("b" * 32, ids)

    def test_concurrent_visits_do_not_lose_visitors(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda number: main.record_visitor(f"{number:032x}", now=100000), range(20)))
        self.assertEqual(main.record_visitor("0" * 32, now=100001), 20)

    def test_recent_articles_keep_dates_when_edited(self):
        root = Path(self.directory.name) / "articles"
        category_path = root / "test"
        category_path.mkdir(parents=True)
        self.enterContext(patch.object(main, "ARTICLES_DIR", str(root)))
        category = {"slug": "test", "title": "Test"}
        articles = {}

        def add_article(slug, timestamp, protected=False):
            path = category_path / f"{slug}.md"
            path.write_text(f"# {slug}\n", encoding="utf-8")
            os.utime(path, (timestamp, timestamp))
            article = {
                "slug": slug, "url": f"/test/{slug}", "category": category,
                "title": slug, "protected": protected,
            }
            articles[article["url"]] = article
            return article

        older = add_article("00-old", 1000)
        newer = add_article("01-new", 2000)
        add_article("02-private", 4000, protected=True)
        recent = main.get_recent_articles(articles)
        self.assertEqual([(item["slug"], date) for item, date in recent], [(newer["slug"], 2000), (older["slug"], 1000)])

        os.utime(category_path / "00-old.md", (5000, 5000))
        self.assertEqual(main.get_recent_articles(articles)[0][0]["slug"], newer["slug"])
        added = add_article("03-added", 3000)
        with patch.object(main.time, "time", return_value=6000):
            recent = main.get_recent_articles(articles, limit=2)
        self.assertEqual([(item["slug"], date) for item, date in recent], [(added["slug"], 6000), (newer["slug"], 2000)])


class QuietHandler(main.Handler):
    def log_message(self, format, *args):
        pass


class SidebarHTTPTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.database = str(Path(self.directory.name) / "activity.sqlite3")
        self.enterContext(patch.object(main, "ACTIVITY_DB_PATH", self.database))
        category = {
            "slug": "test", "url": "/categories/test", "title": "Test",
            "description": "", "description_html": "", "sections": [],
            "password_env": "ARTICLE_PASSWORD_TEST", "articles": [],
        }
        self.articles = {}
        for slug, protected in (("00-public", False), ("01-private", True)):
            article = {
                "slug": slug, "url": f"/test/{slug}", "category": category,
                "title": slug, "protected": protected, "number": int(slug[:2]),
                "authors": [], "search_text": slug, "content": "<h1>Article</h1>", "toc": "",
            }
            category["articles"].append(article)
            self.articles[article["url"]] = article
        self.enterContext(patch.object(main, "load_content", return_value=([category], self.articles, {})))
        self.enterContext(patch.object(main, "load_announcement", return_value=""))
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), QuietHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, cookie=None, user_agent="Mozilla/5.0", **extra_headers):
        headers = {"User-Agent": user_agent, **extra_headers}
        if cookie:
            headers["Cookie"] = cookie
        connection = HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.request("GET", path, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode("utf-8")
        finally:
            connection.close()

    def test_cookie_deduplication_and_protected_article(self):
        status, headers, body = self.request("/", **{"X-Forwarded-Proto": "https"})
        self.assertEqual(status, 200)
        self.assertIn('<p class="visitor-count">1</p>', body)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Lax", headers["Set-Cookie"])
        self.assertIn("Secure", headers["Set-Cookie"])
        self.assertIn("no-store", headers["Cache-Control"])
        cookies = SimpleCookie(headers["Set-Cookie"])
        cookie = f'{main.VISITOR_COOKIE_NAME}={cookies[main.VISITOR_COOKIE_NAME].value}'

        status, _, body = self.request("/test/01-private", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn('type="password"', body)
        _, headers, body = self.request("/", cookie=cookie)
        self.assertNotIn("Set-Cookie", headers)
        self.assertIn('<p class="visitor-count">1</p>', body)
        sidebar = body.split('<aside class="home-sidebar"')[1].split("</aside>")[0]
        self.assertNotIn("01-private", sidebar)
        self.assertIn("00-public", sidebar)
        _, _, body = self.request("/")
        self.assertIn('<p class="visitor-count">2</p>', body)

    def test_bots_assets_and_404_do_not_count(self):
        self.request("/", user_agent="TelegramBot")
        self.request("/static/style.css")
        self.request("/not-found")
        _, headers, body = self.request("/", user_agent="Googlebot")
        self.assertNotIn("Set-Cookie", headers)
        self.assertIn('<p class="visitor-count">0</p>', body)

    def test_storage_failure_does_not_break_home(self):
        with patch.object(main, "open_activity_database", side_effect=sqlite3.OperationalError("readonly")):
            status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn('<p class="visitor-count">—</p>', body)
        self.assertIn("Список временно недоступен.", body)


if __name__ == "__main__":
    unittest.main()
