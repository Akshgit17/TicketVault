import asyncio
from datetime import datetime
from playwright.async_api import Page

from scraper.scrapers.base import BaseScraper
from scraper.config import DISTRICT_CITY_MAP
from scraper.storage import get_city_id, upsert_event


class DistrictScraper(BaseScraper):
    source = "district"
    BASE = "https://district.zomato.com/{city}/events"

    async def scrape(self, page: Page):
        for slug, canonical in DISTRICT_CITY_MAP.items():
            url = self.BASE.format(city=slug)
            try:
                await self._scrape_city(page, url, canonical)
            except Exception as e:
                print(f"[District] Failed {slug}: {e}")
            await asyncio.sleep(2)

    async def _scrape_city(self, page: Page, url: str, canonical: str):
        city_id = get_city_id(canonical)
        if not city_id:
            return

        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        await asyncio.sleep(2)

        try:
            await page.wait_for_selector("[class*='EventCard']", timeout=10000)
        except Exception:
            print(f"[District] No events for {canonical}")
            return

        cards = await page.query_selector_all("[class*='EventCard']")

        for card in cards:
            try:
                name = await card.query_selector("[class*='title'], h2, h3")
                venue = await card.query_selector("[class*='venue'], [class*='location']")
                date = await card.query_selector("[class*='date'], [class*='time']")
                img = await card.query_selector("img")

                name_text = (await name.inner_text()).strip() if name else None
                venue_text = (await venue.inner_text()).strip() if venue else "TBD"
                date_text = (await date.inner_text()).strip() if date else None
                img_src = await img.get_attribute("src") if img else None

                if not name_text or not date_text:
                    continue

                parsed_date = _parse_date(date_text)
                if not parsed_date:
                    continue

                upsert_event({
                    "name": name_text,
                    "venue": venue_text,
                    "city_id": city_id,
                    "date": parsed_date,
                    "image_url": img_src,
                    "source": self.source,
                })

            except Exception as e:
                print(f"[District] Card parse error: {e}")


def _parse_date(raw: str) -> str | None:
    formats = ["%d %b %Y", "%d %B %Y", "%a %d %b", "%d %b", "%B %d, %Y"]
    raw = raw.strip().split(",")[0].strip()
    for fmt in formats:
        try:
            dt = datetime.strptime(raw, fmt)
            if dt.year == 1900:
                dt = dt.replace(year=datetime.now().year)
            return dt.isoformat()
        except ValueError:
            continue
    return None
