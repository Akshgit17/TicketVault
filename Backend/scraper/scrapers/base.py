from abc import ABC, abstractmethod
from playwright.async_api import async_playwright, Page


class BaseScraper(ABC):
    source: str = ""

    async def run(self):
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )
            page = await context.new_page()
            try:
                await self.scrape(page)
            finally:
                await browser.close()

    @abstractmethod
    async def scrape(self, page: Page):
        ...
