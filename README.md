# ARC Raiders news: image-enabled, automatically updated RSS

Source: https://arcraiderscommunity.com/news/

This independent RSS 2.0 feed includes official ARC Raiders news aggregated by the
community site, Steam updates, and the community's own news reports. Entries
include card artwork or, if necessary, the article's Open Graph image.
Images are exposed via Media RSS (`media:content`) and embedded HTML in both
`description` and `content:encoded` for broad RSS-reader compatibility.
Each entry identifies its linked website in `dc:creator` author metadata.
Steam links use `store.steampowered.com`, including Steam CDN redirects.
RSS readers control where this label appears; some always show the shared feed
name beneath headlines and cannot replace it with an entry's author.

Subscribe (once GitHub Pages is enabled):
https://cptcamembert.github.io/arc-raiders-rss/feed.xml

## Enable hosting (one-time)

In **Settings > Pages > Build and deployment**, select **GitHub Actions**
as the source. The update workflow explicitly deploys the feed after each successful
run. Publication may take a few minutes. No personal access token or repository
secret is needed.

## Automatic updates

GitHub Actions checks https://arcraiderscommunity.com/news/ at `:07` and
`:37` UTC each hour, as well as on changes to the updater, tests, feed, dependencies, or workflow
on `main`, and on manual dispatch.
Each run tests the parser before fetching news. It merges articles by permanent URL, retains up to 100, enriches missing
thumbnails from article metadata, and commits a new feed only on changes. It then publishes `feed.xml` through
GitHub Pages, including on runs without new articles.
If parsing or fetching the listing fails, it leaves the existing feed intact.
Only article cards in the news content are included; navigation, tactical maps,
and email-protection links are excluded. Updates also remove those invalid entries
from older feeds and replace artwork that an earlier parser copied from a neighbouring
card. Shared site backgrounds and social preview images are omitted; articles without
card artwork use article metadata or an image inside the article when available.
Scheduled runs can be delayed, and GitHub may pause schedules after 60 days
of public repository inactivity.

In **Actions > Update ARC Raiders RSS**, run **Run workflow** for initial
verification. Review the workflow logs if the source site's markup changes.

## Local tests

```sh
pip install -r requirements.txt
python -m unittest discover -s tests -v
python update_feed.py
```

This repository is not affiliated with Embark Studios or the community site.
