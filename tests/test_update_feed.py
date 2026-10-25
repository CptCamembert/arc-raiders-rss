import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from update_feed import (Article, CONTENT_NS, MEDIA_NS, article_url, date_from_text,
                         listing_articles, old_articles, render, update)

HTML = '''<html><body><nav><a href="/news/">News</a></nav><main>
<h2>From Embark</h2><div class="cards"><article><a href="https://arcraiders.com/news/new-event">
<img data-src="/assets/thumb.jpg"><h3>Frozen Trail announcement</h3></a><p>A new event has been announced.</p>
<time datetime="2026-10-20T11:00:00Z">20 Oct 2026</time></article></div>
<h2>Community transmissions</h2><article><a href="/intel/report-1"><h3>Field report October</h3>
<img src="/assets/field.webp"></a><p>Community analysis of the event.</p></article>
<h2>Elsewhere</h2><a href="https://arcraiders.com/news/ignore">ignore</a>
</main></body></html>'''

class NewsTest(unittest.TestCase):
    def test_parse_both_sections_and_thumbnails(self):
        items = listing_articles(BeautifulSoup(HTML, 'html.parser'), datetime(2026, 10, 25, tzinfo=timezone.utc))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].image, 'https://arcraiderscommunity.com/assets/thumb.jpg')
        self.assertEqual(items[1].url, 'https://arcraiderscommunity.com/intel/report-1')
        self.assertEqual(items[0].published.day, 20)
    def test_no_navigation(self):
        self.assertFalse(article_url('/news/'))
        self.assertFalse(article_url('https://arcraiders.com/de/news/'))
    def test_rss_media_roundtrip(self):
        a = Article('https://arcraiders.com/news/new-event', 'New event',
                    datetime(2026, 10, 20, tzinfo=timezone.utc), 'Event summary',
                    'https://arcraiderscommunity.com/p.jpg')
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / 'feed.xml'
            render([a]).write(p, encoding='utf-8', xml_declaration=True)
            root = ET.parse(p).getroot()
            self.assertEqual(root.find('.//{%s}content' % MEDIA_NS).get('url'), a.image)
            self.assertIn('<img', root.find('.//{%s}encoded' % CONTENT_NS).text)
            self.assertEqual(old_articles(p), [a])
    def test_preserve_file_if_site_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'feed.xml'
            path.write_text('<rss version="2.0"><channel></channel></rss>')
            before = path.read_text()
            fake = Mock()
            fake.get.return_value.text = '<html><body>error</body></html>'
            fake.get.return_value.raise_for_status.return_value = None
            with self.assertRaises(RuntimeError):
                update(path, fake)
            self.assertEqual(path.read_text(), before)
    def test_date(self):
        self.assertEqual(date_from_text('16 Oct 2026').day, 16)

if __name__ == '__main__':
    unittest.main()
