"""Unit tests for Pricing module and Skyscanner scraper logic."""

from datetime import date
import pytest
from scrape_pricing.skyscanner_scraper import SkyscannerScraper
from scrape_pricing.user_agents import get_random_user_agent, get_stealth_headers


def test_url_formatting():
    scraper = SkyscannerScraper()
    url = scraper.format_search_url("JFK", "LAX", date(2024, 7, 15), cabin_class="economy")
    assert "https://www.skyscanner.com/transport/flights/jfk/lax/240715/" in url
    assert "cabinclass=economy" in url


def test_stealth_headers():
    ua = get_random_user_agent()
    headers = get_stealth_headers(ua)
    assert headers["User-Agent"] == ua
    assert "Accept-Language" in headers
    assert headers["Upgrade-Insecure-Requests"] == "1"


def test_calibrated_prices_generation():
    scraper = SkyscannerScraper()
    prices = scraper.generate_calibrated_prices("JFK", "LAX", date(2024, 7, 15))
    assert len(prices) > 0
    for p in prices:
        assert p["price"] > 50.0
        assert p["origin"] == "JFK"
        assert p["dest"] == "LAX"
        assert p["cabin_class"] == "economy"
