"""
Lists which Groq models are actually available for your account. Run this
once before setting up fallback models -- model availability varies by
account/region/tier, and guessing an invalid model ID just produces a 404
(as happened earlier with 'llama-3.3-70b-versatile' on this account).

Usage:
    python list_groq_models.py
"""

import os
from dotenv import load_dotenv
from groq import Groq

load_dotenv()

API_KEY = os.environ.get("GROQ_API_KEY")


def main():
    if not API_KEY:
        raise EnvironmentError("GROQ_API_KEY not set in .env")

    client = Groq(api_key=API_KEY)
    models = client.models.list()

    print(f"{'Model ID':<45} {'Owned by':<20} Active")
    print("-" * 80)
    for m in sorted(models.data, key=lambda x: x.id):
        active = getattr(m, "active", "?")
        owner = getattr(m, "owned_by", "?")
        print(f"{m.id:<45} {owner:<20} {active}")

    print(f"\n{len(models.data)} models available for this account.")


if __name__ == "__main__":
    main()