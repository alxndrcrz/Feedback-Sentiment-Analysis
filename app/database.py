"""
app/database.py
───────────────
Single Supabase client instance shared across all routers.
Import `supabase` from here — never create a second client elsewhere.
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL: str = os.getenv(
    "SUPABASE_URL",
    "https://edrcecxnbvqzoihmqzac.supabase.co",
)
SUPABASE_KEY: str = os.getenv(
    "SUPABASE_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImVkcmNlY3huYnZxem9paG1xemFjIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQ5MjY5NzEsImV4cCI6MjA5MDUwMjk3MX0.k0tF2k9j8Y8f7H74EOjiLncvsx6MZ0PA4_MWMWKdV8A",
)

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
