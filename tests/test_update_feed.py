import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup
from update_feed import (Article, CONTENT_NS, MEDIA_NS, article_url, date_from_text,
                         article_metadata, listing_articles, old_articles, render, update)

HTML = '''<html><body><nav><a href="/news/">News</a></nav><main>
<h2>From Embark</h2><div class="cards"><article><a href="https://arcraiders.com/news/new-event">
<img data-src="/assets/thumb.jpg"><h3>Frozen Trail announcement</h3></a><p>A new event has been announced.</p>
<time datetime="2026-10-20T11:00:00Z">20 Oct 2026</time></article></div>
<h2>Community transmissions</h2><article><a href="/intel/report-1"><h3>Field report October</h3>
<img src="/assets/field.webp"></a><p>Community analysis of the event.</p></article>
<h2>Elsewhere</h2><a href="https://arcraiders.com/news/ignore">ignore</a>
</main></body></html>'''

class NewsTest(unittest.TestCase):
    def test_existing_feed_gets_new_title_without_new_articles(self):
        fake = Mock()
        fake.get.return_value.text = HTML
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'feed.xml'
            update(path, fake)
            before = old_articles(path)
            tree = ET.parse(path)
            tree.find('./channel/title').text = 'ARC Raiders News (mit Bildern)'
            tree.write(path, encoding='utf-8', xml_declaration=True)
            self.assertEqual(update(path, fake), (0, 2))
            self.assertEqual(old_articles(path), before)
            self.assertEqual(ET.parse(path).findtext('./channel/title'), 'ARC Raiders News')
            contents = path.read_bytes()
            update(path, fake)
            self.assertEqual(path.read_bytes(), contents)

    def test_realistic_cards_keep_their_own_metadata(self):
        source = Path(__file__).with_name('fixtures').joinpath('news-cards.html').read_text()
        items = listing_articles(BeautifulSoup(source, 'html.parser'))
        self.assertEqual(len(items), 4)
        self.assertEqual([a.image for a in items], [
            'https://arcraiderscommunity.com/art/first.webp',
            'https://arcraiderscommunity.com/art/second.webp', '', '',
        ])
        self.assertEqual([a.summary for a in items[:3]], [
            'First summary.', 'Second summary.', 'Third summary.',
        ])
        self.assertEqual([a.published.day for a in items[:3]], [20, 19, 18])
        self.assertEqual(items[3].title, 'Archived community report')
        self.assertTrue(items[3].url.endswith('/transmission-archived'))

    def test_no_navigation_without_main_or_section_headings(self):
        footer = '<footer><a href="/contact"><h3>Contact us today</h3></a></footer>'
        self.assertEqual(listing_articles(BeautifulSoup(footer, 'html.parser')), [])
        source = '<main><a href="https://arcraiders.com/news/new-event"><h3>New event announcement</h3></a></main>' + footer
        self.assertEqual(len(listing_articles(BeautifulSoup(source, 'html.parser'))), 1)

    def test_navigation_urls_are_rejected(self):
        for url in ('/map', '/map/blue-gate', '/maps', '/cdn-cgi/l/email-protection#abc',
                    '/contact', 'mailto:hello@example.com'):
            with self.subTest(url=url):
                self.assertEqual(article_url(url), '')

    def test_generic_image_uses_article_artwork_instead(self):
        fake = Mock()
        fake.get.return_value.text = '''<html><head>
        <meta property="og:image" content="https://assets.arcraiders.com/static/social/arc-raiders-social.png">
        </head><body><header><img src="/logo.svg"></header>
        <div class="payload-richtext"><img src="/media/event-header.jpg"></div></body></html>'''
        _, image, _ = article_metadata(fake, 'https://arcraiders.com/news/new-event')
        self.assertEqual(image, 'https://arcraiders.com/media/event-header.jpg')
        fake.get.return_value.text = '''<html><head>
        <meta property="og:image" content="https://arcraiderscommunity.com/bg.jpg">
        </head><body><header><img src="/logo.svg"></header></body></html>'''
        self.assertEqual(article_metadata(fake, 'https://arcraiderscommunity.com/live-update-1')[1], '')

    def test_update_repairs_existing_images_and_removes_junk(self):
        date = datetime(2026, 10, 20, tzinfo=timezone.utc)
        wrong_image = 'https://arcraiderscommunity.com/art/first.webp'
        urls = ['https://arcraiders.com/news/' + name for name in
                ('first-update', 'second-update', 'third-update', 'historical-update')]
        old = [Article(url, 'Old title', date, 'Old summary', wrong_image) for url in urls]
        old.extend([Article('https://arcraiderscommunity.com/map', 'Tactical maps', date),
                    Article('https://arcraiderscommunity.com/cdn-cgi/l/email-protection', '[email protected]', date)])
        source = Path(__file__).with_name('fixtures').joinpath('news-cards.html').read_text()
        fake = Mock()
        response = Mock()
        response.text = source
        metadata = Mock()
        metadata.text = '<html><main>No article image available</main></html>'
        fake.get.side_effect = lambda url, **kwargs: response if url.endswith('/news/') else metadata
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'feed.xml'
            render(old).write(path, encoding='utf-8', xml_declaration=True)
            update(path, fake)
            items = {a.url: a for a in old_articles(path)}
            self.assertEqual(len(items), 5)
            self.assertEqual(items[urls[0]].image, wrong_image)
            self.assertEqual(items[urls[1]].image, 'https://arcraiderscommunity.com/art/second.webp')
            self.assertEqual(items[urls[1]].summary, 'Second summary.')
            self.assertEqual(items[urls[1]].published, date)
            self.assertEqual(items[urls[2]].image, '')
            self.assertEqual(items[urls[3]].image, '')
            before = path.read_bytes()
            self.assertEqual(update(path, fake), (0, 5))
            self.assertEqual(path.read_bytes(), before)

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
