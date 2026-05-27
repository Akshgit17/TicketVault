"""
Run this FIRST to diagnose what BMS actually renders.
Usage: python -m scraper.diagnose
It will save a screenshot + print all visible text/links so we can find real selectors.
"""
import asyncio
from playwright.async_api import async_playwright


async def diagnose_bms():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)  # visible so you can watch
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        url = "https://in.bookmyshow.com/explore/concerts-mumbai"
        print(f"Opening: {url}")
        await page.goto(url, wait_until="networkidle", timeout=60000)

        # Wait for page to settle
        await asyncio.sleep(5)

        # Screenshot so you can see what rendered
        await page.screenshot(path="bms_debug.png", full_page=True)
        print("Screenshot saved: bms_debug.png")

        # Print page title
        print(f"Page title: {await page.title()}")

        # Try every plausible card selector and report which ones find elements
        selectors_to_try = [
            "a[href*='/events/']",
            "a[href*='/concert']",
            "[data-testid='event-card']",
            "[class*='EventCard']",
            "[class*='event-card']",
            "[class*='card']",
            "[class*='Card']",
            "[class*='listing']",
            "[class*='Listing']",
            "[class*='show-card']",
            "[class*='ShowCard']",
            "[class*='item']",
            "li a",
            "article",
        ]

        print("\n--- SELECTOR RESULTS ---")
        for sel in selectors_to_try:
            try:
                count = await page.locator(sel).count()
                if count > 0:
                    print(f"  ✅ FOUND {count:3d} elements: {sel}")
                    # Print first element's inner text as sample
                    sample = await page.locator(sel).first.inner_text()
                    print(f"     Sample text: {sample[:120].strip()!r}")
                else:
                    print(f"  ❌ No match:              {sel}")
            except Exception as e:
                print(f"  ⚠️  Error with {sel}: {e}")

        # Print all hrefs that look event-related
        print("\n--- HREFS CONTAINING 'event' or 'concert' or 'show' ---")
        links = await page.eval_on_selector_all(
            "a[href]",
            "els => els.map(e => e.href).filter(h => /event|concert|show/i.test(h)).slice(0, 20)"
        )
        for link in links:
            print(f"  {link}")

        # Dump full HTML to file for inspection
        html = await page.content()
        with open("bms_debug.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("\nFull HTML saved: bms_debug.html")
        print("Open bms_debug.html in browser and inspect element classes on event cards.")

        await browser.close()


async def diagnose_district():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=False)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        url = "https://district.zomato.com/mumbai/events"
        print(f"\nOpening: {url}")
        await page.goto(url, wait_until="networkidle", timeout=60000)
        await asyncio.sleep(5)

        await page.screenshot(path="district_debug.png", full_page=True)
        print("Screenshot saved: district_debug.png")
        print(f"Page title: {await page.title()}")

        selectors_to_try = [
            "[class*='EventCard']",
            "[class*='event-card']",
            "[class*='event_card']",
            "[class*='Card']",
            "[class*='card']",
            "a[href*='/event']",
            "a[href*='/events']",
            "[class*='listing']",
            "[class*='item']",
            "article",
        ]

        print("\n--- SELECTOR RESULTS ---")
        for sel in selectors_to_try:
            try:
                count = await page.locator(sel).count()
                if count > 0:
                    print(f"  ✅ FOUND {count:3d} elements: {sel}")
                    sample = await page.locator(sel).first.inner_text()
                    print(f"     Sample: {sample[:120].strip()!r}")
                else:
                    print(f"  ❌ No match: {sel}")
            except Exception as e:
                print(f"  ⚠️  Error: {e}")

        html = await page.content()
        with open("district_debug.html", "w", encoding="utf-8") as f:
            f.write(html)
        print("\nFull HTML saved: district_debug.html")

        await browser.close()


if __name__ == "__main__":
    print("=" * 50)
    print("BMS DIAGNOSIS")
    print("=" * 50)
    asyncio.run(diagnose_bms())

    print("\n" + "=" * 50)
    print("DISTRICT DIAGNOSIS")
    print("=" * 50)
    asyncio.run(diagnose_district())
