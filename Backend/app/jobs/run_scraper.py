"""
Entry point used by: python -m app.jobs.run_scraper
Runs all scrapers once immediately.
"""
import asyncio
from scraper.main import run_all

if __name__ == "__main__":
    asyncio.run(run_all())
