"""
Insider.in (Paytm Insider) scraper — no Cloudflare, clean JSON API.
Insider exposes a public API used by their own frontend — no key needed.
"""
import asyncio
import httpx
from datetime import datetime
from scraper.storage import get_city_id, upsert_event
from scraper.normalizer import normalize_city

# Insider city slugs
INSIDER_CITIES = {
    "mumbai":    "Mumbai",
    "delhi":     "Delhi",
    "bangalore": "Bangalore",
    "hyderabad": "Hyderabad",
    "chennai":   "Chennai",
    "kolkata":   "Kolkata",
    "pune":      "Pune",
    "ahmedabad": "Ahmedabad",
    "jaipur":    "Jaipur",
    "goa":       "Goa",
    "kochi":     "Kochi",
    "chandigarh":"Chandigarh",
    "indore":    "Indore",
}

BASE = "https://api.insider.in/api/v1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://insider.in/",
}


class InsiderScraper:
    source = "insider"

    async def run(self):
        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            for slug, canonical in INSIDER_CITIES.items():
                try:
                    await self._fetch_city(client, slug, canonical)
                except Exception as e:
                    print(f"[Insider] Failed {canonical}: {e}")
                await asyncio.sleep(1.5)

    async def _fetch_city(self, client: httpx.AsyncClient, slug: str, canonical: str):
        city_id = get_city_id(canonical)
        if not city_id:
            print(f"[Insider] City not in DB: {canonical}")
            return

        # Insider public API — category_id 6 = music/concerts
        url = f"{BASE}/events"
        params = {
            "city":        slug,
            "tags_slug":   "music",
            "page_size":   50,
            "status":      "live",
        }

        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            print(f"[Insider] HTTP {resp.status_code} for {canonical}")
            # Try alternate endpoint
            await self._fetch_alternate(client, slug, canonical, city_id)
            return

        try:
            data = resp.json()
        except Exception:
            await self._fetch_alternate(client, slug, canonical, city_id)
            return

        events = data if isinstance(data, list) else data.get("data", [])
        saved  = 0

        for ev in events:
            try:
                name = (ev.get("name") or ev.get("title") or "").strip()
                if not name:
                    continue

                # Date — Insider uses Unix timestamps
                start_ts  = ev.get("start_utc") or ev.get("min_show_start_time")
                if not start_ts:
                    continue
                parsed_date = datetime.utcfromtimestamp(start_ts / 1000).isoformat()

                venue_obj  = ev.get("venue") or {}
                venue_name = (
                    venue_obj.get("name") or
                    ev.get("venue_name") or
                    "TBD"
                )

                img_src = (
                    ev.get("horizontal_cover_image") or
                    ev.get("cover_image") or
                    ev.get("image") or
                    None
                )

                upsert_event({
                    "name":      name,
                    "venue":     venue_name,
                    "city_id":   city_id,
                    "date":      parsed_date,
                    "image_url": img_src,
                    "source":    self.source,
                })
                saved += 1
                print(f"[Insider] ✓ {name[:40]:<40} | {venue_name[:25]:<25} | {parsed_date[:10]}")

            except Exception as e:
                print(f"[Insider] Event parse error: {e}")

        print(f"[Insider] {canonical}: saved {saved} events")

    async def _fetch_alternate(
        self,
        client: httpx.AsyncClient,
        slug: str,
        canonical: str,
        city_id: str,
    ):
        """
        Fallback: scrape Insider's website JSON embedded in the page.
        Insider loads __NEXT_DATA__ with full event list.
        """
        url = f"https://insider.in/music-events-in-{slug}"
        resp = await client.get(url, timeout=30)
        if resp.status_code != 200:
            print(f"[Insider] Alternate also failed for {canonical}: HTTP {resp.status_code}")
            return

        import re, json
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            resp.text,
            re.DOTALL,
        )
        if not match:
            print(f"[Insider] No __NEXT_DATA__ found for {canonical}")
            return

        try:
            next_data = json.loads(match.group(1))
        except Exception:
            return

        # Navigate into the nested structure
        # Structure varies — try common paths
        events = (
            next_data.get("props", {}).get("pageProps", {}).get("events") or
            next_data.get("props", {}).get("initialState", {}).get("events", {}).get("data") or
            []
        )

        saved = 0
        for ev in events:
            try:
                name = (ev.get("name") or ev.get("title") or "").strip()
                if not name:
                    continue

                start_ts = ev.get("start_utc") or ev.get("min_show_start_time")
                if not start_ts:
                    continue
                parsed_date = datetime.utcfromtimestamp(start_ts / 1000).isoformat()

                venue_obj  = ev.get("venue") or {}
                venue_name = venue_obj.get("name") or ev.get("venue_name") or "TBD"
                img_src    = ev.get("horizontal_cover_image") or ev.get("cover_image")

                upsert_event({
                    "name":      name,
                    "venue":     venue_name,
                    "city_id":   city_id,
                    "date":      parsed_date,
                    "image_url": img_src,
                    "source":    self.source,
                })
                saved += 1
                print(f"[Insider] ✓ {name[:40]:<40} | {venue_name[:25]:<25} | {parsed_date[:10]}")

            except Exception as e:
                print(f"[Insider] Alt parse error: {e}")

        print(f"[Insider] {canonical} (alternate): saved {saved} events")
