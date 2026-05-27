from supabase import create_client, Client
from app.config import settings

# Service role key — bypasses RLS. Never expose to frontend.
supabase: Client = create_client(
    settings.SUPABASE_URL,
    settings.SUPABASE_SERVICE_KEY,
)
