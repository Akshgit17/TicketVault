"""
TicketVault Scraper — Main entry point.
Runs all scrapers and schedules them every 6 hours.

Sources (in priority order):
  1. Songkick API     — best quality, requires free API key
  2. Bandsintown API  — good coverage, no key needed
  3. Insider.in       — India-specific, no key needed
"""
import asyncio
import os
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from scraper.scrapers.insider import InsiderScraper
from scraper.scrapers.bandsintown import BandsInTownScraper

# Optional — requires SONGKICK_API_KEY in .env
SONGKICK_KEY = os.getenv("SONGKICK_API_KEY")


async def run_all():
    print("\n" + "=" * 60)
    print("TicketVault Scraper — Starting run")
    print("=" * 60)

    # 1. Bandsintown (no key needed)
    print("\n🔄 Running Bandsintown scraper...")
    try:
        await BandsInTownScraper().run()
    except Exception as e:
        print(f"[Bandsintown] Fatal error: {e}")

    # 2. Insider.in (no key needed)
    print("\n🔄 Running Insider.in scraper...")
    try:
        await InsiderScraper().run()
    except Exception as e:
        print(f"[Insider] Fatal error: {e}")

    # 3. Songkick (only if API key present)
    if SONGKICK_KEY:
        print("\n🔄 Running Songkick scraper...")
        from scraper.scrapers.songkick import SongkickScraper
        try:
            await SongkickScraper(api_key=SONGKICK_KEY).run()
        except Exception as e:
            print(f"[Songkick] Fatal error: {e}")
    else:
        print("\n⚠️  Songkick skipped — set SONGKICK_API_KEY in .env for better coverage")
        print("   Get free key at: https://www.songkick.com/developer")

    print("\n✅ Scraper run complete")


async def main():
    await run_all()

    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        lambda: asyncio.create_task(run_all()),
        "interval",
        hours=6,
        id="scraper_run",
    )
    scheduler.start()
    print("\n⏰ Scheduler started — next run in 6 hours")

    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        scheduler.shutdown()


if __name__ == "__main__":
    asyncio.run(main())
