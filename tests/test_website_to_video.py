import unittest

from website_to_video import WebsiteAnalysisError, _looks_like_news, _news_score, normalize_url, parse_page


class WebsiteToVideoTests(unittest.TestCase):
    def test_parses_structured_news_article(self):
        html = """
        <html><head>
        <meta property="og:site_name" content="Daily Example">
        <meta property="og:type" content="article">
        <meta property="og:title" content="Major clean-energy project opens today">
        <meta property="og:description" content="The project begins operations after three years of construction.">
        <meta property="article:published_time" content="2026-09-19T08:00:00Z">
        </head><body><h1>Major clean-energy project opens today</h1></body></html>
        """
        page = parse_page("https://news.example/story", html)
        self.assertEqual(page.site_name, "Daily Example")
        self.assertEqual(page.title, "Major clean-energy project opens today")
        self.assertEqual(page.published_at, "2026-09-19T08:00:00Z")
        self.assertTrue(_looks_like_news(page))

    def test_company_page_is_not_forced_into_news(self):
        html = """
        <html><head><title>Acme Cloud Platform</title>
        <meta name="description" content="Workflow software for growing teams."></head>
        <body><img src="/assets/acme-logo.png" alt="Acme logo"><h1>One platform for modern operations</h1>
        <h2>Automate approvals</h2><p>Acme helps teams organize work and reduce repetitive tasks.</p></body></html>
        """
        page = parse_page("https://acme.example/", html)
        self.assertFalse(_looks_like_news(page))
        self.assertIn("Workflow software", page.description)
        self.assertEqual(page.logo_url, "https://acme.example/assets/acme-logo.png")

    def test_article_paths_outscore_navigation(self):
        article = _news_score("https://example.com/news/2026/09/launch-story", "Company launches a major new product worldwide", 4)
        navigation = _news_score("https://example.com/privacy", "Privacy policy and account information", 4)
        self.assertGreater(article, navigation)

    def test_url_normalization_rejects_unsafe_forms(self):
        self.assertEqual(normalize_url("example.com"), "https://example.com/")
        for value in ("file:///etc/passwd", "ftp://example.com/file", "https://user:pass@example.com", "https://example.com:99999/story"):
            with self.assertRaises(WebsiteAnalysisError):
                normalize_url(value)


if __name__ == "__main__":
    unittest.main()