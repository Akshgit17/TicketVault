import re

ALIAS_MAP = {
    "bengaluru": "Bangalore",
    "bangalore": "Bangalore",
    "new delhi": "Delhi",
    "delhi ncr": "Delhi",
    "delhi-ncr": "Delhi",
    "navi mumbai": "Mumbai",
    "greater mumbai": "Mumbai",
    "mumbai": "Mumbai",
    "hyderabad": "Hyderabad",
    "secunderabad": "Hyderabad",
    "chennai": "Chennai",
    "madras": "Chennai",
    "kolkata": "Kolkata",
    "calcutta": "Kolkata",
    "pune": "Pune",
    "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur",
    "lucknow": "Lucknow",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "chandigarh": "Chandigarh",
    "goa": "Goa",
    "panaji": "Goa",
    "surat": "Surat",
    "indore": "Indore",
}


def normalize_city(raw: str) -> str | None:
    """Returns canonical city name or None if not in allowed list."""
    key = re.sub(r"[^a-z\s-]", "", raw.lower().strip())
    return ALIAS_MAP.get(key)
