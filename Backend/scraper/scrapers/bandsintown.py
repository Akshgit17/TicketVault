"""
Bandsintown Public API — free, no auth needed for basic queries.
Docs: https://app.swaggerhub.com/apis/Bandsintown/PublicAPI/3.0.0
"""
import asyncio
import httpx
from datetime import datetime, timedelta
from scraper.storage import get_city_id, upsert_event

CITIES = [
    "Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai",
    "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Goa",
    "Kochi", "Chandigarh", "Indore", "Lucknow", "Surat",
]

BASE = "https://rest.bandsintown.com"
APP_ID = "ticketvault"   # any string works for public endpoints

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}


class BandsInTownScraper:
    source = "bandsintown"

    async def run(self):
        today    = datetime.now().strftime("%Y-%m-%d")
        end_date = (datetime.now() + timedelta(days=180)).strftime("%Y-%m-%d")

        async with httpx.AsyncClient(timeout=30, headers=HEADERS) as client:
            for city in CITIES:
                try:
                    await self._fetch_city(client, city, today, end_date)
                except Exception as e:
                    print(f"[BIT] Failed {city}: {e}")
                await asyncio.sleep(1)

    async def _fetch_city(
        self,
        client: httpx.AsyncClient,
        city: str,
        date_from: str,
        date_to: str,
    ):
        city_id = get_city_id(city)
        if not city_id:
            return

        # Bandsintown events by location
        url = f"{BASE}/events/search"
        params = {
            "app_id":   APP_ID,
            "location": f"{city},India",
            "radius":   "25",
            "date":     f"{date_from},{date_to}",
            "per_page": "100",
        }

        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            print(f"[BIT] HTTP {resp.status_code} for {city}")
            return

        try:
            events = resp.json()
        except Exception as e:
            print(f"[BIT] JSON error for {city}: {e}")
            return

        if not isinstance(events, list):
            print(f"[BIT] Unexpected response for {city}: {type(events)}")
            return

        saved = 0
        seen  = set()

        for ev in events:
            try:
                # Artist name + event title
                artist   = ev.get("artist", {})
                art_name = artist.get("name", "").strip()
                title    = ev.get("title", "").strip()
                name     = title if title else (f"{art_name} Live" if art_name else "")

                if not name or name in seen:
                    continue
                seen.add(name)

                # Date
                date_str = ev.get("datetime", "")    # "2025-06-14T19:00:00"
                if not date_str:
                    continue
                parsed_date = datetime.fromisoformat(date_str.replace("Z", "+00:00")).isoformat()

                # Venue
                venue_obj  = ev.get("venue", {})
                venue_name = venue_obj.get("name", "TBD")

                # Image
                img_src = artist.get("image_url") or artist.get("thumb_url")

                upsert_event({
                    "name":      name,
                    "venue":     venue_name,
                    "city_id":   city_id,
                    "date":      parsed_date,
                    "image_url": img_src,
                    "source":    self.source,
                })
                saved += 1
                print(
                    f"[BIT] ✓ {name[:40]:<40} | "
                    f"{venue_name[:22]:<22} | {date_str[:10]}"
                )

            except Exception as e:
                print(f"[BIT] Event parse error: {e}")

        print(f"[BIT] {city}: saved {saved} events")
