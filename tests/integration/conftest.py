"""Integration test specific fixtures

Integration tests may use database and multiple components together.
"""

# Load .env.test before any imports to ensure DATABASE_URL is available
from dotenv import load_dotenv

load_dotenv(".env.test", override=False)


# Add integration-test specific fixtures here (e.g., test database setup)
