import html
import unittest

import main


class HomeAuthorCarouselTests(unittest.TestCase):
    def make_author(self, slug, title, description="", photo_url=""):
        authors = {}
        author = main.get_or_create_author(authors, slug)
        author.update({
            "title": title,
            "description": description,
            "description_html": main.render_description_markdown(description) if description else "",
            "photo_url": photo_url,
        })
        return author

    def test_empty_collection_has_no_carousel(self):
        self.assertEqual(main.render_home_authors({}), "")

    def test_four_authors_have_full_names_descriptions_and_controls(self):
        authors = {
            slug: self.make_author(slug, title, f"Biography for **{slug}**.")
            for slug, title in (
                ("zoe", "Zoe Writer"),
                ("alex", "Alex With A Very Long Unabridged Full Name"),
                ("dana", "Dana Editor"),
                ("bob", "Bob Teacher"),
            )
        }
        body = main.render_home_authors(authors)
        self.assertIn("data-author-carousel", body)
        self.assertEqual(body.count('class="home-author-slide"'), 4)
        self.assertEqual(body.count('class="home-author-description author-description"'), 4)
        self.assertEqual(body.count("data-author-previous"), 1)
        self.assertEqual(body.count("data-author-next"), 1)
        self.assertIn('data-author-controls hidden', body)
        self.assertIn('aria-controls="home-author-list"', body)
        self.assertIn('role="status" aria-live="polite"', body)
        self.assertIn('aria-label="4 из 4"', body)
        self.assertIn("/static/icons/chevron-left.svg", body)
        self.assertIn("/static/icons/chevron-right.svg", body)
        self.assertIn("<strong>alex</strong>", body)
        positions = [body.index(authors[slug]["title"]) for slug in ("alex", "bob", "dana", "zoe")]
        self.assertEqual(positions, sorted(positions))

    def test_one_author_has_no_arrows(self):
        body = main.render_home_authors({"alex": self.make_author("alex", "Alex Writer", "Biography.")})
        self.assertEqual(body.count('class="home-author-slide"'), 1)
        self.assertNotIn("data-author-controls", body)
        self.assertNotIn("data-author-previous", body)
        self.assertNotIn("data-author-next", body)
        self.assertIn('class="home-author-link" href="/authors/alex"', body)

    def test_photos_name_escaping_and_description_links(self):
        author = self.make_author(
            "alex", "Alex & <Writer>",
            "A [project](https://example.com) and **robotics**.",
            "/authors/alex/photo.png",
        )
        body = main.render_home_authors({"alex": author})
        self.assertIn(html.escape(author["title"]), body)
        self.assertNotIn("Alex & <Writer>", body)
        self.assertIn('class="home-author-photo" src="/authors/alex/photo.png"', body)
        self.assertIn('href="https://example.com"', body)
        self.assertIn("<strong>robotics</strong>", body)

    def test_unknown_profile_has_initials_and_description_fallback(self):
        author = self.make_author("unknown", "Unknown Editor")
        body = main.render_home_authors({"unknown": author})
        self.assertIn("author-photo-placeholder", body)
        self.assertIn(">UE</div>", body)
        self.assertIn("Описание пока не добавлено.", body)
        self.assertIn('href="/authors/unknown"', body)


if __name__ == "__main__":
    unittest.main()
