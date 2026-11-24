import json
from pathlib import Path
import re
import struct
import unittest
import xml.etree.ElementTree as ET

import main
import test_category_pages


class ThemeMarkupTests(unittest.TestCase):
    def test_switcher_has_all_options_and_no_script_fallback(self):
        body = main.render_theme_switcher()
        self.assertIn('class="theme-switcher" hidden', body)
        self.assertIn('class="season-background" aria-hidden="true"', body)
        self.assertIn('class="season-background-secondary"', body)
        self.assertIn('id="site-theme" data-theme-select', body)
        self.assertEqual(body.count('<option '), len(main.SITE_THEMES))
        self.assertIn('class="color-mode-switch" hidden', body)
        self.assertIn('type="checkbox" role="switch" data-color-mode-switch', body)
        self.assertEqual(body.count('data-color-mode-switch'), 1)
        for value, label in main.SITE_THEMES:
            self.assertIn(f'<option value="{value}">{label}</option>', body)

    def test_page_header_escapes_custom_labels_and_links(self):
        body = main.render_page_header('/authors?name="test"', 'Names & <authors>', 'Back "home"')
        self.assertIn('href="/authors?name=&quot;test&quot;"', body)
        self.assertIn('Names &amp; &lt;authors&gt;', body)
        self.assertIn('aria-label="Back &quot;home&quot;"', body)
        self.assertEqual(body.count('data-theme-select'), 1)

    def test_theme_names_match_bootstrap_allowlist(self):
        source = Path('static/theme.js').read_text(encoding='utf-8')
        match = re.search(r'new Set\((\[.*?\])\)', source)
        self.assertIsNotNone(match)
        self.assertEqual(json.loads(match.group(1)), [value for value, _ in main.SITE_THEMES])
        self.assertIn('"siteTheme"', source)
        self.assertIn('"siteColorMode"', source)
        self.assertIn('dataset.colorMode', source)

    def test_dark_palette_covers_every_theme_without_replacing_illustrations(self):
        css = Path('static/dark.css').read_text(encoding='utf-8')
        self.assertIn(':root[data-theme][data-color-mode="dark"]', css)
        self.assertIn('color-scheme: dark', css)
        self.assertNotIn('--theme-pattern:', css)
        self.assertNotIn('--theme-corner:', css)
        for name, _ in main.SITE_THEMES[1:]:
            self.assertIn(f'[data-theme="{name}"][data-color-mode="dark"]', css)
        for token in ('page-bg', 'surface', 'text', 'heading', 'muted', 'accent', 'link-color', 'danger', 'success', 'on-accent', 'nav-bg'):
            self.assertIn(f'--{token}:', css)

    def test_theme_patterns_have_transparent_assets(self):
        css = Path('static/style.css').read_text(encoding='utf-8')
        for name, _ in main.SITE_THEMES[1:]:
            with self.subTest(theme=name):
                theme_css = re.search(r':root\[data-theme="' + re.escape(name) + r'"\]\s*\{([^}]+)', css).group(1)
                path = Path(re.search(r'--theme-pattern:\s*url\("/([^"]+)"\)', theme_css).group(1))
                if path.suffix == '.svg':
                    root = ET.parse(path).getroot()
                    self.assertEqual(root.tag, '{http://www.w3.org/2000/svg}svg')
                    self.assertEqual(root.get('viewBox'), '0 0 1024 1024')
                    self.assertEqual(len(root.findall('{http://www.w3.org/2000/svg}rect')), 0)
                    continue
                data = path.read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                width, height = struct.unpack('>II', data[16:24])
                self.assertGreaterEqual(width, 512)
                self.assertEqual(width, height)
                self.assertIn(data[25], (4, 6))

    def test_67_mixes_digits_with_a_transparent_character_tile(self):
        css = Path('static/style.css').read_text(encoding='utf-8')
        theme_css = re.search(r':root\[data-theme="67"\]\s*\{([^}]+)', css).group(1)
        self.assertIn('--theme-pattern: url("/static/themes/67.png")', theme_css)
        self.assertIn('--theme-pattern-secondary: url("/static/themes/67-character.png")', theme_css)
        self.assertIn('background-image: var(--theme-pattern-secondary)', css)
        self.assertIn('--theme-secondary-opacity: 0.5;', theme_css)
        self.assertIn('opacity: var(--theme-secondary-opacity);', css)
        secondary_css = re.search(r'html\[data-theme="67"\] \.season-background-secondary\s*\{([^}]+)', css).group(1)
        self.assertIn('filter: none;', secondary_css)
        self.assertEqual(css.count('--theme-pattern-secondary:'), 1)
        data = Path('static/themes/67-character.png').read_bytes()
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        width, height = struct.unpack('>II', data[16:24])
        self.assertGreaterEqual(width, 512)
        self.assertEqual(width, height)
        self.assertIn(data[25], (4, 6))

    def test_robo_pattern_is_vector_art_from_the_reference(self):
        root = ET.parse('static/themes/robo548.svg').getroot()
        namespace = {'svg': 'http://www.w3.org/2000/svg'}
        self.assertEqual(root.get('viewBox'), '0 0 1024 1024')
        self.assertEqual(root.findall('.//svg:image', namespace), [])
        mark = root.find('svg:g', namespace)
        self.assertEqual(mark.get('transform'), 'translate(352 352) scale(0.32)')
        self.assertEqual(mark.get('fill'), 'none')
        self.assertEqual(mark.get('stroke'), '#5673db')
        self.assertEqual(len(mark.findall('svg:use', namespace)), 8)
        self.assertEqual(len(mark.findall('svg:circle', namespace)), 3)
        self.assertEqual(mark.find('svg:circle[@stroke]', namespace).get('stroke'), '#000070')

    def test_each_decorated_theme_has_a_transparent_corner_illustration(self):
        css = Path('static/style.css').read_text(encoding='utf-8')
        for name, _ in main.SITE_THEMES[1:]:
            with self.subTest(theme=name):
                path = Path(f'static/themes/corners/{name}.png')
                data = path.read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                width, height = struct.unpack('>II', data[16:24])
                self.assertGreaterEqual(width, 512)
                self.assertGreaterEqual(height, 512)
                self.assertIn(data[25], (4, 6))
                theme_css = re.search(r':root\[data-theme="' + re.escape(name) + r'"\]\s*\{([^}]+)', css)
                self.assertIsNotNone(theme_css)
                self.assertIn(f'--theme-corner: url("/{path.as_posix()}")', theme_css.group(1))

    def test_corner_geometry_preserves_aspect_ratio_and_trims_padding(self):
        manifest = json.loads(Path('static/themes/corners/prompts.json').read_text(encoding='utf-8'))
        css = Path('static/style.css').read_text(encoding='utf-8')
        for name, _ in main.SITE_THEMES[1:]:
            with self.subTest(theme=name):
                source = Path(f'static/themes/corners/{name}.png').read_bytes()
                dimensions = struct.unpack('>II', source[16:24])
                crop = manifest['crop'][name]
                self.assertEqual(list(dimensions), crop['source'])
                x, y, width, height = crop['bounds']
                self.assertGreater(width, 0)
                self.assertGreater(height, 0)
                self.assertGreaterEqual(x, 0)
                self.assertGreaterEqual(y, 0)
                self.assertLessEqual(x + width, dimensions[0])
                self.assertLessEqual(y + height, dimensions[1])
                theme_css = re.search(r':root\[data-theme="' + re.escape(name) + r'"\]\s*\{([^}]+)', css).group(1)
                aspect = float(re.search(r'--theme-corner-aspect:\s*([\d.]+)', theme_css).group(1))
                self.assertAlmostEqual(aspect, width / height, places=7)
                size = re.search(r'--theme-corner-size:\s*([\d.]+)%\s+([\d.]+)%', theme_css)
                position = re.search(r'--theme-corner-position:\s*([\d.]+)%\s+([\d.]+)%', theme_css)
                self.assertAlmostEqual(float(size.group(1)), dimensions[0] / width * 100, places=5)
                self.assertAlmostEqual(float(size.group(2)), dimensions[1] / height * 100, places=5)
                self.assertAlmostEqual(float(position.group(1)), x / (dimensions[0] - width) * 100, places=5)
                self.assertAlmostEqual(float(position.group(2)), y / (dimensions[1] - height) * 100, places=5)

    def test_minions_preserves_bear_colors_in_dark_mode(self):
        css = Path('static/dark.css').read_text(encoding='utf-8')
        block = re.search(r':root\[data-theme="minions"\]\[data-color-mode="dark"\]\s*\{([^}]+)', css).group(1)
        self.assertIn('--theme-pattern-filter: none;', block)


class ThemePageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_category_pages.CategoryPageTests('test_loaded_categories_have_urls')
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.setUp()

    def test_bootstrap_precedes_styles_and_switcher_exists_on_every_page(self):
        for path, expected_status in (
            ('/', 200),
            ('/categories/01-course', 200),
            ('/01-course/00-intro', 200),
            ('/01-course/11-closed', 200),
            ('/authors', 200),
            ('/authors/alex', 200),
            ('/authors/missing', 404),
            ('/missing', 404),
        ):
            with self.subTest(path=path):
                status, _, body = self.fixture.request(path)
                self.assertEqual(status, expected_status)
                self.assertEqual(body.count('src="/static/theme.js"'), 1)
                self.assertIn('<script src="/static/theme.js"></script>', body)
                self.assertLess(body.index('src="/static/theme.js"'), body.index('href="/static/style.css"'))
                self.assertEqual(body.count('data-theme-select'), 1)
                self.assertEqual(body.count('data-color-mode-switch'), 1)
                self.assertEqual(body.count('class="season-background"'), 1)
                self.assertEqual(body.count('<option '), len(main.SITE_THEMES))

    def test_password_errors_also_have_theme_controls(self):
        status, _, body = self.fixture.request(
            '/01-course/11-closed', method='POST', body='password=wrong',
        )
        self.assertEqual(status, 403)
        self.assertIn('src="/static/theme.js"', body)
        self.assertEqual(body.count('data-theme-select'), 1)
        self.assertNotIn('Private lesson body.', body)

    def test_theme_script_is_public(self):
        status, headers, body = self.fixture.request('/static/theme.js')
        self.assertEqual(status, 200)
        content_type = next(value for key, value in headers.items() if key.lower() == 'content-type')
        self.assertIn('javascript', content_type)
        self.assertIn('siteTheme', body)


if __name__ == '__main__':
    unittest.main()
