import os
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

ALLOWED_CITIES = [
    "Mumbai", "Delhi", "Bangalore", "Hyderabad", "Chennai",
    "Kolkata", "Pune", "Ahmedabad", "Jaipur", "Lucknow",
    "Kochi", "Chandigarh", "Goa", "Surat", "Indore",
]

BMS_CITY_MAP = {
    "mumbai": "Mumbai",
    "delhi-ncr": "Delhi",
    "bengaluru": "Bangalore",
    "hyderabad": "Hyderabad",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
    "pune": "Pune",
    "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur",
    "lucknow": "Lucknow",
    "kochi": "Kochi",
    "chandigarh": "Chandigarh",
    "goa": "Goa",
    "surat": "Surat",
    "indore": "Indore",
}

DISTRICT_CITY_MAP = {
    "mumbai": "Mumbai",
    "new-delhi": "Delhi",
    "delhi": "Delhi",
    "bangalore": "Bangalore",
    "hyderabad": "Hyderabad",
    "chennai": "Chennai",
    "kolkata": "Kolkata",
    "pune": "Pune",
    "ahmedabad": "Ahmedabad",
    "jaipur": "Jaipur",
    "lucknow": "Lucknow",
    "kochi": "Kochi",
    "chandigarh": "Chandigarh",
    "goa": "Goa",
    "surat": "Surat",
    "indore": "Indore",
}
