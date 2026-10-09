import base64
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


class ArticleEditorMetadataTests(unittest.TestCase):
    def test_roles_protection_and_duplicates_are_parsed_independently(self):
        metadata, body = main.parse_article_metadata(
            "<!-- EDITORS: dana, alex, dana -->\n"
            "<!-- protected -->\n"
            "<!-- authors: alex, alex -->\n"
            "<!-- editor: missing -->\n"
            "<!-- author: bob -->\n"
            "# Lesson\nArticle body.\n"
        )
        self.assertEqual(metadata, {
            "protected": True,
            "author_slugs": ["alex", "bob"],
            "editor_slugs": ["dana", "alex", "missing"],
        })
        self.assertEqual(body, "# Lesson\nArticle body.\n")

    def test_empty_editor_comment_does_not_block_other_metadata(self):
        metadata, body = main.parse_article_metadata(
            "<!-- editors: , -->\n<!-- authors: alex -->\n# Lesson"
        )
        self.assertEqual(metadata["editor_slugs"], [])
        self.assertEqual(metadata["author_slugs"], ["alex"])
        self.assertEqual(body, "# Lesson")

    def test_articles_without_editors_and_body_comments_are_unchanged(self):
        metadata, body = main.parse_article_metadata(
            "<!-- authors: alex -->\n# Lesson\n<!-- editors: dana -->"
        )
        self.assertEqual(metadata["editor_slugs"], [])
        self.assertIn("<!-- editors: dana -->", body)


class QuietHandler(main.Handler):
    def log_message(self, format, *args):
        pass


class ArticleEditorPageTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        articles = root / "articles"
        authors = root / "authors"
        course = articles / "01-course"
        other = articles / "02-other"
        for path in (course, other, authors / "alex", authors / "dana"):
            path.mkdir(parents=True)
        (course / "category.txt").write_text("Course", encoding="utf-8")
        (other / "category.txt").write_text("Other", encoding="utf-8")
        (course / "00-plain.md").write_text(
            "<!-- authors: alex -->\n<!-- editors: dana -->\n"
            "# Plain lesson\nVisible article body.\n", encoding="utf-8",
        )
        (course / "11-closed.md").write_text(
            "<!-- protected -->\n<!-- authors: alex -->\n"
            "<!-- editors: dana, missing, dana -->\n"
            "# Closed lesson\nSecret article body.\n", encoding="utf-8",
        )
        (course / "02-editor-only.md").write_text(
            "<!-- editor: editor-only -->\n# Editor-only lesson\nText.\n", encoding="utf-8",
        )
        (course / "03-ordinary.md").write_text("# Ordinary lesson\nText.\n", encoding="utf-8")
        (other / "00-dual.md").write_text(
            "<!-- authors: dana -->\n<!-- editors: dana -->\n# Dual role\nText.\n", encoding="utf-8",
        )
        (other / "01-authored.md").write_text(
            "<!-- authors: alex -->\n# Authored lesson\nText.\n", encoding="utf-8",
        )
        (authors / "alex" / "profile.md").write_text("# Alex Writer\nBiography.\n", encoding="utf-8")
        (authors / "dana" / "profile.md").write_text("# Dana & Editor\nBiography.\n", encoding="utf-8")
        (authors / "dana" / "photo.png").write_bytes(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j3ioAAAAASUVORK5CYII="
        ))
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

    def request(self, path, method="GET", body=None, cookie=None):
        headers = {"User-Agent": "Mozilla/5.0"}
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        if cookie:
            headers["Cookie"] = cookie
        connection = HTTPConnection("127.0.0.1", self.server.server_port)
        try:
            connection.request(method, path, body=body, headers=headers)
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode("utf-8")
        finally:
            connection.close()

    def test_loaded_roles_and_editor_names_in_search(self):
        categories, articles, authors = main.load_content()
        plain = articles["/01-course/00-plain"]
        self.assertEqual([person["slug"] for person in plain["authors"]], ["alex"])
        self.assertEqual([person["slug"] for person in plain["editors"]], ["dana"])
        self.assertIn("Dana & Editor", plain["search_text"])
        self.assertEqual(len(authors["dana"]["articles"]), 1)
        self.assertEqual(len(authors["dana"]["edited_articles"]), 3)
        self.assertEqual(len(authors["missing"]["edited_articles"]), 1)
        self.assertEqual(authors["missing"]["articles"], [])
        self.assertEqual(authors["missing"]["photo_url"], "")
        self.assertEqual(
            [person["slug"] for person in main.get_category_authors(categories[0])],
            ["alex"],
        )

    def test_editors_appear_below_authors_before_body_with_photo(self):
        status, _, body = self.request("/01-course/00-plain")
        self.assertEqual(status, 200)
        author_start = body.index('class="article-page-authors"')
        article_start = body.index('class="article-body"')
        editor_start = body.index('class="article-page-authors article-page-editors"')
        footer_start = body.index('class="site-footer"')
        self.assertLess(author_start, editor_start)
        self.assertLess(editor_start, article_start)
        self.assertLess(article_start, footer_start)
        self.assertEqual(body.count('class="article-page-authors article-page-editors"'), 1)
        editors = body[editor_start:article_start]
        self.assertIn("Редактор:", editors)
        self.assertIn('href="/authors/dana"', editors)
        self.assertIn('src="/authors/dana/photo.png"', editors)
        self.assertIn("Dana &amp; Editor", editors)
        self.assertNotIn("<!-- editors:", body)

    def test_multiple_and_unknown_editors(self):
        _, articles, _ = main.load_content()
        block = main.render_article_editors(articles["/01-course/11-closed"])
        self.assertIn("Редакторы:", block)
        self.assertEqual(block.count('href="/authors/dana"'), 1)
        self.assertIn('href="/authors/missing"', block)
        self.assertIn("author-photo-placeholder", block)
        status, _, body = self.request("/authors/missing")
        self.assertEqual(status, 200)
        self.assertIn("Closed lesson", body)
        self.assertNotIn("Secret article body.", body)

    def test_editor_only_article_and_existing_articles(self):
        status, _, body = self.request("/01-course/02-editor-only")
        self.assertEqual(status, 200)
        self.assertNotIn('class="article-page-authors"', body)
        self.assertIn("article-page-editors", body)
        self.assertLess(body.index("article-page-editors"), body.index('class="article-body"'))
        for path in ("/01-course/03-ordinary", "/02-other/01-authored"):
            status, _, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertNotIn("article-page-editors", body)

    def test_profile_has_separate_grouped_author_and_editor_sections(self):
        status, _, body = self.request("/authors/dana")
        self.assertEqual(status, 200)
        written = body.split('class="author-articles author-written-articles"', 1)[1]
        written, edited = written.split('class="author-articles author-edited-articles"', 1)
        self.assertIn("Статьи автора", written)
        self.assertIn('href="/02-other/00-dual"', written)
        self.assertNotIn('href="/01-course/00-plain"', written)
        self.assertIn("Статьи под редакцией", edited)
        self.assertIn('href="/01-course/00-plain"', edited)
        self.assertIn('href="/01-course/11-closed"', edited)
        self.assertIn('href="/02-other/00-dual"', edited)
        self.assertIn('<h3><a href="/categories/01-course">Course</a></h3>', edited)
        self.assertIn('<h3><a href="/categories/02-other">Other</a></h3>', edited)
        self.assertIn("protected-badge", edited)
        self.assertNotIn("Secret article body.", body)

    def test_editor_profiles_are_discoverable_without_authored_articles(self):
        status, _, body = self.request("/authors")
        self.assertEqual(status, 200)
        self.assertIn('href="/authors/editor-only"', body)
        self.assertIn("Как автор: 0 · Как редактор: 1", body)
        status, _, body = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn('class="home-author-link" href="/authors/editor-only"', body)
        status, _, body = self.request("/authors/editor-only")
        self.assertEqual(status, 200)
        self.assertIn("Авторские статьи пока не указаны.", body)
        self.assertIn('href="/01-course/02-editor-only"', body)
        status, _, body = self.request("/authors/alex")
        self.assertEqual(status, 200)
        self.assertIn("Редакторские статьи пока не указаны.", body)

    def test_protection_is_preserved_with_editor_metadata(self):
        for path in ("/", "/categories/01-course", "/authors/alex", "/authors/dana"):
            status, _, body = self.request(path)
            self.assertEqual(status, 200)
            self.assertIn("Closed lesson", body)
            self.assertNotIn("Secret article body.", body)
        status, _, body = self.request("/01-course/11-closed")
        self.assertEqual(status, 200)
        self.assertIn('type="password"', body)
        self.assertNotIn("Secret article body.", body)
        status, _, body = self.request(
            "/01-course/11-closed", method="POST", body=urlencode({"password": "wrong"}),
        )
        self.assertEqual(status, 403)
        self.assertNotIn("Secret article body.", body)
        status, headers, _ = self.request(
            "/01-course/11-closed", method="POST", body=urlencode({"password": "let-me-in"}),
        )
        self.assertEqual(status, 303)
        cookies = SimpleCookie(headers["Set-Cookie"])
        cookie = "; ".join(f"{name}={value.value}" for name, value in cookies.items())
        status, _, body = self.request("/01-course/11-closed", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertIn("Secret article body.", body)
        self.assertIn("Редакторы:", body)


if __name__ == "__main__":
    unittest.main()
