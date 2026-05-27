import asyncio
import re
from datetime import datetime
from playwright.async_api import Page

from scraper.scrapers.base import BaseScraper
from scraper.config import BMS_CITY_MAP
from scraper.storage import get_city_id, upsert_event


class BookMyShowScraper(BaseScraper):
    source = "bookmyshow"
    BASE = "https://in.bookmyshow.com/explore/concerts-{city}"

    async def scrape(self, page: Page):
        for slug, canonical in BMS_CITY_MAP.items():
            url = self.BASE.format(city=slug)
            try:
                await self._scrape_city(page, url, canonical)
            except Exception as e:
                print(f"[BMS] Failed {slug}: {e}")
            await asyncio.sleep(4)

    async def _scrape_city(self, page: Page, url: str, canonical: str):
        city_id = get_city_id(canonical)
        if not city_id:
            print(f"[BMS] City not found in DB: {canonical}")
            return

        # ── 1. Load page ───────────────────────────────────────────────────────
        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
        except Exception:
            await page.goto(url, wait_until="domcontentloaded", timeout=40000)
            await asyncio.sleep(6)

        # ── 2. Dismiss popups ──────────────────────────────────────────────────
        for sel in [
            "[aria-label='close']",
            "[aria-label='Close']",
            "button[class*='close']",
            "button[class*='Cross']",
            "button[class*='modal'] svg",
        ]:
            try:
                await page.click(sel, timeout=2000)
                await asyncio.sleep(0.5)
            except Exception:
                pass

        # ── 3. Scroll to load all lazy cards ───────────────────────────────────
        prev_height = 0
        for _ in range(8):
            await page.evaluate("window.scrollBy(0, window.innerHeight)")
            await asyncio.sleep(1.2)
            curr_height = await page.evaluate("document.body.scrollHeight")
            if curr_height == prev_height:
                break
            prev_height = curr_height

        await page.evaluate("window.scrollTo(0, 0)")
        await asyncio.sleep(1)

        # ── 4. Extract cards via page.evaluate (bypasses selector guessing) ────
        #
        # From the screenshot, each event card contains:
        #   - An <img> (the poster)
        #   - Event name text (below or inside the card)
        #   - Venue text
        #   - "Concerts" category label
        #
        # We use JS inside the page to walk the DOM and collect data directly.
        #
        raw_events = await page.evaluate("""
        () => {
            const results = [];

            // Strategy 1: find all anchor tags that link to event/movie detail pages
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            const eventAnchors = anchors.filter(a => {
                const href = a.href || '';
                return (
                    href.includes('/events/') ||
                    href.includes('/concert') ||
                    href.includes('/shows/') ||
                    href.includes('/buytickets')
                );
            });

            for (const anchor of eventAnchors) {
                // Get all text nodes inside this anchor
                const allText = [];
                const walker = document.createTreeWalker(
                    anchor,
                    NodeFilter.SHOW_TEXT,
                    null
                );
                let node;
                while ((node = walker.nextNode())) {
                    const t = node.textContent.trim();
                    if (t.length > 1) allText.push(t);
                }

                // Image
                const img = anchor.querySelector('img');
                const imgSrc = img
                    ? (img.src || img.dataset.src || img.dataset.lazySrc || null)
                    : null;

                // Deduplicate texts
                const unique = [...new Set(allText)];

                if (unique.length === 0) continue;

                results.push({
                    href:   anchor.href,
                    texts:  unique,
                    imgSrc: imgSrc,
                });
            }

            // Deduplicate by href
            const seen = new Set();
            return results.filter(r => {
                if (seen.has(r.href)) return false;
                seen.add(r.href);
                return true;
            });
        }
        """)

        if not raw_events:
            print(f"[BMS] No events extracted for {canonical}")
            print(f"[BMS]   Title: {await page.title()!r}")
            body = await page.inner_text("body")
            print(f"[BMS]   Body[:300]: {body[:300]!r}")
            return

        print(f"[BMS] {canonical}: {len(raw_events)} raw events found")

        seen_names: set[str] = set()
        saved = 0

        for ev in raw_events:
            texts: list[str] = ev.get("texts", [])
            img_src: str | None = ev.get("imgSrc")

            if not texts:
                continue

            # First text is almost always the event name on BMS
            name_text = texts[0].strip()
            if not name_text or name_text in seen_names:
                continue

            # Skip obvious non-event texts
            if name_text.lower() in {
                "concerts", "plays", "sports", "events", "movies",
                "stream", "home", "login", "sign in", "sign up",
                "list your show", "sell", "offers",
            }:
                continue

            seen_names.add(name_text)

            venue_text, date_text = _extract_venue_date(texts[1:])
            parsed_date = _parse_date(date_text) if date_text else None

            if not parsed_date:
                print(f"[BMS] Skipping '{name_text[:40]}' — bad date: {date_text!r}")
                continue

            upsert_event({
                "name":      name_text,
                "venue":     venue_text or "TBD",
                "city_id":   city_id,
                "date":      parsed_date,
                "image_url": img_src,
                "source":    self.source,
            })
            saved += 1
            print(
                f"[BMS] ✓  {name_text[:38]:<38} | "
                f"{(venue_text or 'TBD')[:22]:<22} | {parsed_date}"
            )

        print(f"[BMS] {canonical}: saved {saved} events")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _extract_venue_date(texts: list[str]) -> tuple[str | None, str | None]:
    """
    Given the remaining texts from a card (after the name),
    classify each as a date string or venue string.
    """
    month_kw = {
        "jan","feb","mar","apr","may","jun",
        "jul","aug","sep","oct","nov","dec",
        "january","february","march","april","june","july",
        "august","september","october","november","december",
    }
    day_kw  = {"mon","tue","wed","thu","fri","sat","sun"}
    misc_kw = {"onwards","2024","2025","2026","today","tomorrow"}
    all_kw  = month_kw | day_kw | misc_kw

    date_text  = None
    venue_text = None

    for t in texts:
        lower = t.lower()
        has_kw    = any(kw in lower for kw in all_kw)
        has_digit = any(c.isdigit() for c in t)

        # Skip category labels like "Concerts", "Sports"
        if t.lower() in {
            "concerts","plays","sports","activities","events",
            "comedy","music","kids","workshop",
        }:
            continue

        if has_kw and (has_digit or any(kw in lower for kw in misc_kw)):
            if date_text is None:
                date_text = t
        elif venue_text is None and len(t) > 2:
            venue_text = t

    return venue_text, date_text


def _parse_date(raw: str) -> str | None:
    """
    Parse BMS date strings robustly into ISO 8601.

    Handles all of these:
        "Sat, 24 May"
        "24 May 2025"
        "Sat, 24 May 2025"
        "24 May onwards"
        "24th May 2025"
        "24 May - 26 May"
        "24 May | Venue Name"
    """
    if not raw:
        return None

    clean = raw.strip()

    # Strip pipe and anything after it: "24 May | Venue" → "24 May"
    clean = clean.split("|")[0].strip()

    # Strip noise words
    for noise in ["onwards", "Onwards", "ONWARDS", "onward", "»", "•"]:
        clean = clean.replace(noise, "").strip()

    # Strip ordinal suffixes: "24th" → "24"
    clean = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", clean, flags=re.IGNORECASE)

    # Strip day-of-week prefix: "Sat, 24 May" → "24 May"
    if "," in clean:
        clean = clean.split(",", 1)[1].strip()

    # Take first in a date range: "24 May - 26 May" → "24 May"
    for sep in [" - ", " – ", " to ", "–"]:
        if sep in clean:
            clean = clean.split(sep)[0].strip()
            break

    # Collapse whitespace
    clean = " ".join(clean.split())

    formats = [
        "%d %b %Y",   # 24 May 2025
        "%d %B %Y",   # 24 May 2025  (full month)
        "%d %b",      # 24 May
        "%d %B",      # 24 May       (full month)
        "%B %d, %Y",  # May 24, 2025
        "%b %d, %Y",  # May 24, 2025 (abbrev)
        "%B %d %Y",   # May 24 2025
        "%b %d %Y",   # May 24 2025
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(clean, fmt)
            if dt.year == 1900:
                now = datetime.now()
                dt = dt.replace(year=now.year)
                if dt < now:
                    dt = dt.replace(year=now.year + 1)
            return dt.isoformat()
        except ValueError:
            continue

    return None
