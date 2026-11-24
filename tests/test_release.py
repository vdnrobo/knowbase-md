from pathlib import Path
import re
import unittest

import main


class ReleaseTests(unittest.TestCase):
    def test_release_version_is_consistent(self):
        self.assertEqual(main.SITE_VERSION, '2.0.1')
        readme = Path('README.md').read_text(encoding='utf-8')
        self.assertIn('Текущая версия: **2.0.1**.', readme)
        changelog = Path('CHANGELOG.md').read_text(encoding='utf-8')
        first_release = re.search(r'^## (\d+\.\d+\.\d+) - (\d{4}-\d{2}-\d{2})$', changelog, re.MULTILINE)
        self.assertEqual(first_release.groups(), ('2.0.1', '2026-11-24'))
        self.assertIn('v2.0.1', main.render_site_footer())

    def test_fresh_server_guide_is_linked_and_uses_private_backend(self):
        guide = Path('docs/deploy-ubuntu-26.04.md').read_text(encoding='utf-8')
        self.assertIn('HOST=127.0.0.1', guide)
        self.assertIn('PORT=8000', guide)
        self.assertIn('User=knowbase', guide)
        self.assertIn('ReadWritePaths=/opt/knowbase-md/data', guide)
        self.assertIn('proxy_pass http://127.0.0.1:8000', guide)
        self.assertIn('git checkout --detach v2.0.1', guide)
        self.assertIn('scp -r .\\articles .\\authors', guide)
        for filename in ('README.md', 'docs/site-guide.md'):
            self.assertIn('deploy-ubuntu-26.04.md', Path(filename).read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
