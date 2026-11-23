"""Run with: python3 -m unittest discover -s tools -p 'test_dzen_feed.py'."""
import sys
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import build
from dzen_feed import adapt_html


class DzenTests(unittest.TestCase):
    def test_table_preserves_column_meaning_and_links(self):
        source = ('<div class="table-wrap"><table><thead><tr><th>Игра</th>'
                  '<th>Цена</th></tr></thead><tbody><tr><td><a href="/game.html">Игра A</a>'
                  '</td><td>100 ₽</td></tr><tr><td>Игра B</td><td>200 ₽</td>'
                  '</tr></tbody></table></div>')
        result = adapt_html(source, build.SITE["url"], lambda _: True)
        self.assertNotIn("<table", result)
        self.assertNotIn("<div", result)
        self.assertIn('<b>Игра:</b> <a href="https://geekovski.ru/game.html">Игра A</a>', result)
        self.assertIn('<b>Цена:</b> 100 ₽', result)
        self.assertIn('<b>Игра:</b> Игра B; <b>Цена:</b> 200 ₽', result)

    def test_plain_lists_keep_source_addresses(self):
        source = '<ol><li><strong>Источник:</strong> <a href="https://example.com/">Сайт</a></li></ol>'
        self.assertEqual(adapt_html(source, build.SITE["url"], lambda _: True),
                         '<ol><li>Источник: Сайт (https://example.com/)</li></ol>')

    def test_supported_formatting_anchors_and_escaping(self):
        source = ('<h2 id="test">A &amp; B</h2><p class="x"><strong>Важно</strong>'
                  '<em>текст</em><code>x &lt; 3</code><a href="#test">Вверх</a></p>')
        result = adapt_html(source, build.SITE["url"], lambda _: True)
        self.assertIn('<h2 id="test">A &amp; B</h2>', result)
        self.assertIn('<b>Важно</b><i>текст</i>x &lt; 3<a href="#test">Вверх</a>', result)
        self.assertNotIn('class=', result)

    def test_rejected_images_and_active_content_are_removed(self):
        source = ('<script>bad()</script><p><a href="javascript:bad()">Текст</a></p>'
                  '<figure><img src="/small.jpg"><figcaption>Маленькая</figcaption></figure>'
                  '<figure><img src="/large.jpg" loading="lazy" onerror="bad()"></figure>')
        result = adapt_html(source, build.SITE["url"], lambda u: u.endswith('/large.jpg'))
        self.assertEqual(result, '<p>Текст</p><figure><img src="https://geekovski.ru/large.jpg" alt=""></figure>')

    def post(self, hours=1, **changes):
        post = dict(slug="article", title="A & B", date=self.now - timedelta(hours=hours),
                    category="ai", summary="Описание", body="Текст " * 100,
                    cover="", sources=[], tldr=[], kind="post", draft=False, meta={})
        post.update(changes)
        return post

    def setUp(self):
        self.now = datetime(2026, 11, 23, 10, 0)

    def test_window_excludes_future_drafts_digests_and_explicit_optout(self):
        selected = self.post()
        posts = [self.post(hours=73), self.post(hours=-1), self.post(draft=True),
                 self.post(kind="digest"), self.post(meta={"dzen": "false"}), selected]
        self.assertEqual(build.dzen_selection(posts, self.now), [selected])
        self.assertEqual(len(build.dzen_selection([self.post(hours=72)], self.now)), 1)

    def test_limit_is_500_and_sorted(self):
        posts = [self.post(hours=1 + i / 1000, slug=str(i)) for i in range(501)]
        result = build.dzen_selection(list(reversed(posts)), self.now)
        self.assertEqual(len(result), 500)
        self.assertEqual(result[0]["slug"], "0")

    def test_rss_controls_and_guid_stability(self):
        post = self.post()
        root = ET.fromstring(build.dzen_feed([post], self.now))
        item = root.find('./channel/item')
        self.assertEqual([c.text for c in item.findall('category')], ['format-article', 'noindex'])
        self.assertEqual(item.findtext('guid'), 'https://geekovski.ru/article.html')
        self.assertEqual(item.findtext('link'), item.findtext('guid'))
        content = item.findtext('{http://purl.org/rss/1.0/modules/content/}encoded')
        self.assertIn('Текст', content)
        post['body'] += ' Изменение.'
        updated = ET.fromstring(build.dzen_feed([post], self.now)).find('./channel/item')
        self.assertEqual(updated.findtext('guid'), item.findtext('guid'))
        self.assertIn('Изменение.', updated.findtext('{http://purl.org/rss/1.0/modules/content/}encoded'))
        atom = root.find('./channel/{http://www.w3.org/2005/Atom}link')
        self.assertEqual(atom.get('href'), 'https://geekovski.ru/dzen.xml')
        self.assertIn('<category>AI</category>', build.rss([post]))

    def test_empty_window_is_valid_rss(self):
        root = ET.fromstring(build.dzen_feed([], self.now))
        self.assertEqual(root.findall('./channel/item'), [])


if __name__ == '__main__':
    unittest.main()
