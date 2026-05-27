"""
Songkick API scraper — free official API, no Cloudflare issues.
Sign up for free API key: https://www.songkick.com/developer
"""
import asyncio
import httpx
from datetime import datetime
from scraper.config import ALLOWED_CITIES
from scraper.storage import get_city_id, upsert_event

# Songkick metro area IDs for Indian cities
# Find yours at: https://www.songkick.com/metro_areas
SONGKICK_METRO_IDS = {
    "Mumbai":    "9868",
    "Delhi":     "9886",
    "Bangalore": "9932",
    "Hyderabad": "9931",
    "Chennai":   "9973",
    "Kolkata":   "9987",
    "Pune":      "9984",
    "Ahmedabad": "29130",
    "Jaipur":    "29398",
    "Goa":       "29362",
    "Kochi":     "29133",
}

BASE_URL = "https://api.songkick.com/api/3.0"


class SongkickScraper:
    source = "songkick"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def run(self):
        async with httpx.AsyncClient(timeout=30) as client:
            for city_name, metro_id in SONGKICK_METRO_IDS.items():
                try:
                    await self._fetch_city(client, city_name, metro_id)
                except Exception as e:
                    print(f"[Songkick] Failed {city_name}: {e}")
                await asyncio.sleep(1)  # respect rate limit

    async def _fetch_city(self, client: httpx.AsyncClient, city_name: str, metro_id: str):
        city_id = get_city_id(city_name)
        if not city_id:
            print(f"[Songkick] City not in DB: {city_name}")
            return

        page = 1
        saved = 0

        while True:
            url = f"{BASE_URL}/metro_areas/{metro_id}/calendar.json"
            params = {
                "apikey": self.api_key,
                "page":   page,
                "per_page": 50,
            }

            resp = await client.get(url, params=params)
            if resp.status_code != 200:
                print(f"[Songkick] HTTP {resp.status_code} for {city_name}")
                break

            data = resp.json()
            results = data.get("resultsPage", {})
            events  = results.get("results", {}).get("event", [])

            if not events:
                break

            for ev in events:
                try:
                    name  = ev.get("displayName", "").strip()
                    if not name:
                        continue

                    # Date
                    start     = ev.get("start", {})
                    date_str  = start.get("date")           # "2025-06-14"
                    if not date_str:
                        continue
                    parsed_date = datetime.strptime(date_str, "%Y-%m-%d").isoformat()

                    # Venue
                    venue_obj  = ev.get("venue", {})
                    venue_name = venue_obj.get("displayName", "TBD")

                    # Image — Songkick doesn't provide images in calendar API
                    # Use performance artist image if available
                    img_src = None
                    performances = ev.get("performance", [])
                    if performances:
                        artist = performances[0].get("artist", {})
                        img_src = artist.get("onTourUntil")  # not image but placeholder

                    upsert_event({
                        "name":      name,
                        "venue":     venue_name,
                        "city_id":   city_id,
                        "date":      parsed_date,
                        "image_url": img_src,
                        "source":    self.source,
                    })
                    saved += 1
                    print(f"[Songkick] ✓ {name[:40]:<40} | {venue_name[:25]:<25} | {date_str}")

                except Exception as e:
                    print(f"[Songkick] Event parse error: {e}")

            # Pagination
            total   = results.get("totalEntries", 0)
            per_pg  = results.get("perPage", 50)
            if page * per_pg >= total:
                break
            page += 1
            await asyncio.sleep(0.5)

        print(f"[Songkick] {city_name}: saved {saved} events")
