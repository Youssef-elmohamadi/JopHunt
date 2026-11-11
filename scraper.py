"""
Web Scraper Module for Fetching Full Freelance Job Details.
Enriches Telegram job snippets with the full project description, budget, and required skills
from Mostaql and Nafezly before passing to Gemini AI.
"""

import logging
import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse
import aiohttp
from bs4 import BeautifulSoup

logger = logging.getLogger("atrees.scraper")

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "ar,en-US;q=0.7,en;q=0.3",
}


@dataclass
class ScrapedJobDetails:
    url: str
    title: str = ""
    description: str = ""
    budget: str = ""
    duration: str = ""
    skills: list[str] = None

    def to_combined_text(self, original_text: str = "") -> str:
        """Combines scraped details into a rich prompt format for Gemini."""
        parts = []
        if self.title:
            parts.append(f"عنوان المشروع: {self.title}")
        if self.budget:
            parts.append(f"الميزانية المعروضة: {self.budget}")
        if self.duration:
            parts.append(f"مدة التنفيذ المتوقعة: {self.duration}")
        if self.skills:
            parts.append(f"المهارات المطلوبة: {', '.join(self.skills)}")
        
        if self.description:
            parts.append(f"\nتفاصيل المشروع الكاملة:\n{self.description}")
        elif original_text:
            parts.append(f"\nنص الإعلان:\n{original_text}")

        return "\n".join(parts) if parts else original_text


class ProjectScraper:
    def __init__(self, timeout_sec: int = 10):
        self.timeout = aiohttp.ClientTimeout(total=timeout_sec)

    async def fetch_full_details(
        self, url: str, fallback_text: str = ""
    ) -> ScrapedJobDetails:
        """
        Attempts to scrape full details from Mostaql or Nafezly project pages.
        Falls back cleanly to fallback_text if scraping fails or is blocked.
        """
        if not url:
            return ScrapedJobDetails(url=url, description=fallback_text)

        domain = urlparse(url).netloc.lower()

        # Only attempt scraping for project detail URLs
        is_mostaql_project = "mostaql.com" in domain and ("/project" in url or "/projects" in url)
        is_nafezly_project = "nafezly.com" in domain and ("/project" in url or "/projects" in url)

        if not (is_mostaql_project or is_nafezly_project):
            return ScrapedJobDetails(url=url, description=fallback_text)

        logger.info("Attempting to fetch full project details from: %s", url)

        try:
            async with aiohttp.ClientSession(
                headers=DEFAULT_HEADERS, timeout=self.timeout
            ) as session:
                async with session.get(url, allow_redirects=True) as resp:
                    if resp.status != 200:
                        logger.warning(
                            "Scraper received HTTP %s for %s. Using snippet.",
                            resp.status,
                            url,
                        )
                        return ScrapedJobDetails(url=url, description=fallback_text)

                    html_content = await resp.text()

            # Parse platform-specific HTML
            if "mostaql.com" in domain:
                return self._parse_mostaql(url, html_content, fallback_text)
            elif "nafezly.com" in domain:
                return self._parse_nafezly(url, html_content, fallback_text)

        except Exception as exc:
            logger.warning("Could not scrape %s: %s. Using snippet fallback.", url, exc)

        return ScrapedJobDetails(url=url, description=fallback_text)

    def _parse_mostaql(
        self, url: str, html: str, fallback_text: str
    ) -> ScrapedJobDetails:
        soup = BeautifulSoup(html, "html.parser")

        # Title
        title_el = soup.select_one("h1.project__title, h1")
        title = title_el.get_text(strip=True) if title_el else ""

        # Description
        desc_el = soup.select_one(
            ".project__description, .text-wrapper-div, .project-details, div[id='project-details']"
        )
        description = desc_el.get_text("\n", strip=True) if desc_el else fallback_text

        # Budget & Duration from metadata (Mostaql uses div.meta-row, table rows tr, or list items)
        budget = ""
        duration = ""
        meta_elements = soup.select(".meta-row, .project__meta tr, .table-project-meta tr, .project__meta li, li")
        for el in meta_elements:
            text = el.get_text(" ", strip=True)
            if "الميزانية" in text and not budget:
                clean_b = re.sub(r"الميزانية\s*:?", "", text).strip()
                if clean_b:
                    budget = clean_b
            elif "مدة التنفيذ" in text and not duration:
                clean_d = re.sub(r"مدة التنفيذ\s*:?", "", text).strip()
                if clean_d:
                    duration = clean_d

        # Skills / Tags
        skills = []
        for tag_el in soup.select("ul.skills__list li a, .tag, a[href*='/skills/']"):
            tag_text = tag_el.get_text(strip=True)
            if tag_text and tag_text not in skills:
                skills.append(tag_text)

        return ScrapedJobDetails(
            url=url,
            title=title,
            description=description,
            budget=budget,
            duration=duration,
            skills=skills,
        )

    def _parse_nafezly(
        self, url: str, html: str, fallback_text: str
    ) -> ScrapedJobDetails:
        soup = BeautifulSoup(html, "html.parser")

        title_el = soup.select_one("h1, .project-title")
        title = title_el.get_text(strip=True) if title_el else ""

        desc_el = soup.select_one(".project-details, .project-description, .content-box")
        description = desc_el.get_text("\n", strip=True) if desc_el else fallback_text

        skills = [
            el.get_text(strip=True)
            for el in soup.select(".skill-badge, a[href*='/skills/']")
            if el.get_text(strip=True)
        ]

        return ScrapedJobDetails(
            url=url,
            title=title,
            description=description,
            skills=skills,
        )


scraper = ProjectScraper()

