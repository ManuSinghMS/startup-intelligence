"""
Tests for the LinkedIn Post Ingester (URL-First).
Tests post validation, discovery/ingestion separation, and batch logic.
"""
import unittest
import hashlib
from unittest.mock import patch, AsyncMock
from datetime import datetime

# ---------------------------------------------------------------------------
# Test classify_linkedin_url and is_valid_search_result
# ---------------------------------------------------------------------------

class TestIsValidLinkedInPost(unittest.TestCase):
    """The core filter — rejects profile pages, directories, etc."""

    def test_rejects_profile_directory(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, reason = is_valid_search_result({
            "title": "1600+ Thomas Ross profiles | LinkedIn",
            "url": "https://www.linkedin.com/pub/dir/Thomas/Ross",
        }, "founder")
        self.assertFalse(valid)
        self.assertEqual(cls, "invalid")

    def test_rejects_people_named(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, _ = is_valid_search_result({
            "title": "40+ people named Thomas Ross | LinkedIn",
            "url": "https://www.linkedin.com/search/results/people/",
        }, "founder")
        self.assertFalse(valid)
        self.assertEqual(cls, "invalid")

    def test_rejects_generic_profile_page_unless_founder(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        # The code allows founder profile URLs, but it maps them to founder_profile_url which is valid 
        # Wait: The ingest only stores things that are valid. `founder_profile_url` is valid but is not a post. 
        # Actually our `is_valid_search_result` accepts everything that doesn't say "invalid".
        valid, cls, _ = is_valid_search_result({
            "title": "Thomas Ross - CEO at TestCo | LinkedIn",
            "url": "https://www.linkedin.com/in/thomas-ross",
        }, "founder")
        self.assertTrue(valid)
        self.assertEqual(cls, "founder_profile_url")

    def test_rejects_generic_company_page_unless_company(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, _ = is_valid_search_result({
            "title": "TestCo | LinkedIn",
            "url": "https://www.linkedin.com/company/testco",
        }, "company")
        self.assertTrue(valid)
        self.assertEqual(cls, "company_page_url")

    def test_rejects_jobs_page(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, _ = is_valid_search_result({
            "title": "TestCo hiring Software Engineer | LinkedIn",
            "url": "https://www.linkedin.com/jobs/view/123456",
        }, "company")
        self.assertFalse(valid)
        self.assertEqual(cls, "invalid")

    def test_rejects_login_page(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, _ = is_valid_search_result({
            "title": "Sign in to LinkedIn",
            "url": "https://www.linkedin.com/login",
        }, "founder")
        self.assertFalse(valid)
        self.assertEqual(cls, "invalid")

    def test_rejects_short_title(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, _ = is_valid_search_result({
            "title": "LinkedIn",
            "url": "https://www.linkedin.com",
        }, "founder")
        self.assertFalse(valid)
        self.assertEqual(cls, "invalid")

    def test_accepts_post_url(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, reason = is_valid_search_result({
            "title": "Excited to announce our Series A! 🚀",
            "url": "https://www.linkedin.com/posts/john-doe_startup-activity-123456",
        }, "founder")
        self.assertTrue(valid)
        self.assertEqual(cls, "founder_post_url")

    def test_accepts_feed_update_url(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, reason = is_valid_search_result({
            "title": "Company milestone update",
            "url": "https://www.linkedin.com/feed/update/urn:li:activity:123456",
        }, "company")
        self.assertTrue(valid)
        self.assertEqual(cls, "company_post_url")

    def test_accepts_pulse_article(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, reason = is_valid_search_result({
            "title": "Why AI will transform healthcare",
            "url": "https://www.linkedin.com/pulse/ai-healthcare-john-doe",
        }, "founder")
        self.assertTrue(valid)
        self.assertEqual(cls, "founder_post_url")

    def test_accepts_news_about_linkedin_post(self):
        from src.ingestion.linkedin_ingester import is_valid_search_result
        valid, cls, reason = is_valid_search_result({
            "title": "CEO posted on LinkedIn about new funding round",
            "url": "https://techcrunch.com/article",
            "snippet": "The founder shared on LinkedIn that the company raised $5M.",
        }, "founder")
        self.assertTrue(valid)
        self.assertEqual(cls, "news_mention")


# ---------------------------------------------------------------------------
# Test _get_search_names
# ---------------------------------------------------------------------------

class TestGetSearchNames(unittest.TestCase):
    def test_founder_and_cofounder(self):
        from src.ingestion.linkedin_ingester import _get_search_names
        names = _get_search_names({
            "name": "Test", "founder_name": "Alice",
            "cofounder_name": "Bob", "founder_linkedin_url": "",
            "cofounder_linkedin_url": "", "contact_name": "",
        })
        self.assertEqual(len(names), 2)
        self.assertEqual(names[0]["role"], "founder")
        self.assertEqual(names[1]["role"], "cofounder")

    def test_fallback_to_contact(self):
        from src.ingestion.linkedin_ingester import _get_search_names
        names = _get_search_names({
            "name": "Test", "founder_name": "",
            "cofounder_name": "", "contact_name": "Charlie",
        })
        self.assertEqual(len(names), 1)
        self.assertEqual(names[0]["name"], "Charlie")

    def test_no_names(self):
        from src.ingestion.linkedin_ingester import _get_search_names
        names = _get_search_names({
            "name": "Test", "founder_name": "",
            "cofounder_name": "", "contact_name": "",
        })
        self.assertEqual(len(names), 0)


# ---------------------------------------------------------------------------
# Test _is_after_checkpoint
# ---------------------------------------------------------------------------

class TestIsAfterCheckpoint(unittest.TestCase):
    def test_no_checkpoint(self):
        from src.ingestion.linkedin_ingester import _is_after_checkpoint
        self.assertTrue(_is_after_checkpoint("2025-01-01T00:00:00", None))

    def test_after(self):
        from src.ingestion.linkedin_ingester import _is_after_checkpoint
        self.assertTrue(_is_after_checkpoint("2025-06-01", "2025-01-01"))

    def test_before(self):
        from src.ingestion.linkedin_ingester import _is_after_checkpoint
        self.assertFalse(_is_after_checkpoint("2024-06-01", "2025-01-01"))

    def test_malformed(self):
        from src.ingestion.linkedin_ingester import _is_after_checkpoint
        self.assertTrue(_is_after_checkpoint("not-a-date", "2025-01-01"))


# ---------------------------------------------------------------------------
# Test _extract_slug
# ---------------------------------------------------------------------------

class TestExtractSlug(unittest.TestCase):
    def test_company_url(self):
        from src.ingestion.linkedin_ingester import _extract_slug
        self.assertEqual(_extract_slug("https://linkedin.com/company/google/"), "google")

    def test_empty(self):
        from src.ingestion.linkedin_ingester import _extract_slug
        self.assertIsNone(_extract_slug(""))


# ---------------------------------------------------------------------------
# Test demo fixtures
# ---------------------------------------------------------------------------

class TestDemoFixtures(unittest.TestCase):
    def test_demo_posts_are_valid(self):
        from src.ingestion.linkedin_ingester import DEMO_POSTS, is_valid_search_result
        for post in DEMO_POSTS:
            valid, cls, reason = is_valid_search_result(post, "founder")
            self.assertTrue(valid, f"Demo post should be valid: {post['title']} — {reason}")


# ---------------------------------------------------------------------------
# Test ingest_for_company (mocked)
# ---------------------------------------------------------------------------

class TestIngestForCompany(unittest.IsolatedAsyncioTestCase):
    async def test_dry_run_post_focused(self):
        """Dry run should only count validated posts, not generic results."""
        from src.ingestion.linkedin_ingester import ingest_for_company

        startup = {
            "id": "test-123", "name": "TestStartup",
            "founder_name": "John Doe", "cofounder_name": "",
            "founder_linkedin_url": "https://linkedin.com/in/johndoe",
            "cofounder_linkedin_url": "",
            "contact_name": "", "linkedin_url": "",
            "last_ingested_at": None,
        }

        # Mix of valid posts and junk that should be filtered
        mock_results = [
            {
                "title": "1600+ John Doe profiles | LinkedIn",
                "url": "https://linkedin.com/pub/dir/John/Doe",
                "published_at": datetime.utcnow().isoformat(),
                "snippet": "", "source_name": "DuckDuckGo",
            },
            {
                "title": "John Doe posted on LinkedIn about AI funding",
                "url": "https://www.linkedin.com/posts/johndoe_ai-funding-activity-123",
                "published_at": datetime.utcnow().isoformat(),
                "snippet": "Excited to announce...", "source_name": "Google News",
            },
        ]

        with patch("src.ingestion.linkedin_ingester._search_posts",
                    new_callable=AsyncMock, return_value=mock_results):
            with patch("src.ingestion.linkedin_ingester._discover_linkedin_url",
                        new_callable=AsyncMock, return_value=None):
                with patch("src.ingestion.linkedin_ingester._discover_company_url",
                            new_callable=AsyncMock, return_value=None):
                    stats = await ingest_for_company(startup, dry_run=True)

        self.assertGreaterEqual(stats["skipped"], 1)
        self.assertGreaterEqual(stats["valid_posts"], 1)

    async def test_no_founders(self):
        from src.ingestion.linkedin_ingester import ingest_for_company

        startup = {
            "id": "test-456", "name": "EmptyStartup",
            "founder_name": "", "cofounder_name": "",
            "founder_linkedin_url": "", "cofounder_linkedin_url": "",
            "contact_name": "", "linkedin_url": "",
            "last_ingested_at": None,
        }

        with patch("src.ingestion.linkedin_ingester._search_posts",
                    new_callable=AsyncMock, return_value=[]):
            with patch("src.ingestion.linkedin_ingester._discover_company_url",
                        new_callable=AsyncMock, return_value=None):
                stats = await ingest_for_company(startup, dry_run=True)

        self.assertEqual(stats["valid_posts"], 0)


# ---------------------------------------------------------------------------
# Test the named URL helpers
# ---------------------------------------------------------------------------

class TestUrlHelpers(unittest.TestCase):
    def test_is_linkedin_post_url_true(self):
        from src.ingestion.linkedin_ingester import is_linkedin_post_url
        self.assertTrue(is_linkedin_post_url("https://www.linkedin.com/posts/john-doe_activity-123"))
        self.assertTrue(is_linkedin_post_url("https://www.linkedin.com/feed/update/urn:li:activity:1"))
        self.assertTrue(is_linkedin_post_url("https://www.linkedin.com/pulse/some-article"))

    def test_is_linkedin_post_url_false(self):
        from src.ingestion.linkedin_ingester import is_linkedin_post_url
        # Profile, company, activity pages, and external sites are not posts.
        self.assertFalse(is_linkedin_post_url("https://www.linkedin.com/in/johndoe"))
        self.assertFalse(is_linkedin_post_url("https://www.linkedin.com/company/acme"))
        self.assertFalse(is_linkedin_post_url("https://www.linkedin.com/in/johndoe/recent-activity/all/"))
        self.assertFalse(is_linkedin_post_url("https://news.google.com/articles/abc"))
        self.assertFalse(is_linkedin_post_url(""))

    def test_is_linkedin_activity_page(self):
        from src.ingestion.linkedin_ingester import is_linkedin_activity_page
        self.assertTrue(is_linkedin_activity_page("https://www.linkedin.com/in/john/recent-activity/all/"))
        self.assertTrue(is_linkedin_activity_page("https://www.linkedin.com/company/acme/posts/"))
        self.assertFalse(is_linkedin_activity_page("https://www.linkedin.com/in/john"))

    def test_is_linkedin_profile_url(self):
        from src.ingestion.linkedin_ingester import is_linkedin_profile_url
        self.assertTrue(is_linkedin_profile_url("https://www.linkedin.com/in/john-doe"))
        self.assertFalse(is_linkedin_profile_url("https://www.linkedin.com/in/john/recent-activity/"))
        self.assertFalse(is_linkedin_profile_url("https://www.linkedin.com/posts/john-doe_x"))
        self.assertFalse(is_linkedin_profile_url("https://www.linkedin.com/pub/dir/Thomas/Ross"))

    def test_is_linkedin_company_page_url(self):
        from src.ingestion.linkedin_ingester import is_linkedin_company_page_url
        self.assertTrue(is_linkedin_company_page_url("https://www.linkedin.com/company/acme"))
        self.assertFalse(is_linkedin_company_page_url("https://www.linkedin.com/company/acme/posts/"))
        self.assertFalse(is_linkedin_company_page_url("https://www.linkedin.com/in/john"))

    def test_canonicalize_drops_query_and_lowercases(self):
        from src.ingestion.linkedin_ingester import canonicalize_linkedin_url
        a = canonicalize_linkedin_url("HTTPS://LinkedIn.com/posts/JOHN-DOE_x?utm=foo&x=1#frag")
        self.assertEqual(a, "https://www.linkedin.com/posts/john-doe_x")

    def test_canonicalize_normalizes_host(self):
        from src.ingestion.linkedin_ingester import canonicalize_linkedin_url
        a = canonicalize_linkedin_url("https://m.linkedin.com/posts/abc/")
        b = canonicalize_linkedin_url("https://ca.linkedin.com/posts/abc")
        self.assertEqual(a, "https://www.linkedin.com/posts/abc")
        self.assertEqual(b, a)

    def test_canonicalize_empty(self):
        from src.ingestion.linkedin_ingester import canonicalize_linkedin_url
        self.assertEqual(canonicalize_linkedin_url(""), "")
        self.assertEqual(canonicalize_linkedin_url(None), "")

    def test_company_posts_feed_is_activity_not_post(self):
        """linkedin.com/company/<slug>/posts/ is the company's posts feed,
        not a single post — it must classify as activity_page.
        """
        from src.ingestion.linkedin_ingester import (
            is_linkedin_post_url, is_linkedin_activity_page, classify_linkedin_url,
        )
        url = "https://www.linkedin.com/company/salesbop/posts/"
        self.assertFalse(is_linkedin_post_url(url))
        self.assertTrue(is_linkedin_activity_page(url))
        self.assertEqual(classify_linkedin_url(url, "company"), "company_activity_page")


# ---------------------------------------------------------------------------
# Test parse_url_field (multi-URL field parsing)
# ---------------------------------------------------------------------------

class TestParseUrlField(unittest.TestCase):
    def test_comma_separated(self):
        from src.ingestion.linkedin_ingester import parse_url_field
        urls = parse_url_field("https://linkedin.com/posts/a, https://linkedin.com/posts/b")
        self.assertEqual(len(urls), 2)

    def test_newline_separated(self):
        from src.ingestion.linkedin_ingester import parse_url_field
        urls = parse_url_field("https://linkedin.com/posts/a\nhttps://linkedin.com/posts/b")
        self.assertEqual(len(urls), 2)

    def test_mixed_separators(self):
        from src.ingestion.linkedin_ingester import parse_url_field
        urls = parse_url_field("a.com\nb.com, c.com; d.com")
        self.assertEqual(len(urls), 4)

    def test_dedup_case_insensitive(self):
        from src.ingestion.linkedin_ingester import parse_url_field
        urls = parse_url_field("https://X.COM/p\nhttps://x.com/p")
        self.assertEqual(len(urls), 1)

    def test_empty(self):
        from src.ingestion.linkedin_ingester import parse_url_field
        self.assertEqual(parse_url_field(""), [])
        self.assertEqual(parse_url_field(None), [])


# ---------------------------------------------------------------------------
# Test classify_linkedin_url cofounder branch
# ---------------------------------------------------------------------------

class TestClassifyCofounder(unittest.TestCase):
    def test_cofounder_profile_classified_correctly(self):
        from src.ingestion.linkedin_ingester import classify_linkedin_url
        cls = classify_linkedin_url("https://www.linkedin.com/in/jane-doe", "cofounder")
        self.assertEqual(cls, "cofounder_profile_url")

    def test_cofounder_post_classified_correctly(self):
        from src.ingestion.linkedin_ingester import classify_linkedin_url
        cls = classify_linkedin_url("https://www.linkedin.com/posts/jane-doe_x", "cofounder")
        self.assertEqual(cls, "cofounder_post_url")

    def test_company_post_classified_correctly(self):
        from src.ingestion.linkedin_ingester import classify_linkedin_url
        cls = classify_linkedin_url("https://www.linkedin.com/posts/acme-co_x", "company")
        self.assertEqual(cls, "company_post_url")


if __name__ == "__main__":
    unittest.main()
