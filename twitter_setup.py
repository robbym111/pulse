"""
twitter_setup.py — one-time setup for twscrape accounts using browser cookies.

Cookie-based auth bypasses Cloudflare blocks on automated logins.

How to get your cookies:
  1. Open x.com in your browser and log in
  2. Open DevTools (F12 or Cmd+Option+I)
  3. Find the cookie store for https://x.com:
       • Chrome/Edge/Arc: Application tab → Storage → Cookies
       • Safari:          Storage tab → Cookies   (NOT "Application")
       • Firefox:         Storage tab → Cookies
  4. Find and copy the values for: auth_token  and  ct0

Usage:
    python3 twitter_setup.py
"""

import asyncio
import os
from twscrape import API

TWSCRAPE_DB = os.environ.get("TWSCRAPE_DB", ".twscrape/accounts.db")


async def main():
    os.makedirs(".twscrape", exist_ok=True)
    api = API(TWSCRAPE_DB)

    print("\n  twscrape cookie-based setup")
    print("  ─────────────────────────────────────────")
    print("  Automated login is blocked by Cloudflare.")
    print("  Instead, grab your cookies from your browser:\n")
    print("    1. Go to x.com and log in")
    print("    2. Open DevTools (F12 or Cmd+Option+I)")
    print("    3. Find Cookies for https://x.com:")
    print("         Chrome/Arc: Application tab -> Cookies")
    print("         Safari:     Storage tab -> Cookies  (NOT Application)")
    print("    4. Copy the values for 'auth_token' and 'ct0'\n")

    username = input("  Twitter username (without @): ").strip()
    email = input("  Email on the account: ").strip()
    auth_token = input("  auth_token cookie value: ").strip()
    ct0 = input("  ct0 cookie value: ").strip()

    if not auth_token or not ct0:
        print("\n  ERROR: both auth_token and ct0 are required.")
        return

    cookies = f"auth_token={auth_token}; ct0={ct0}"

    await api.pool.add_account(
        username=username,
        password="cookie_auth",  # placeholder, not used
        email=email,
        email_password="",
        cookies=cookies,
    )
    print(f"\n  Added @{username} via cookies.")

    accounts = await api.pool.get_all()
    active = [a for a in accounts if a.active]
    print(f"\n  Done. {len(active)} account(s) active and ready.")
    if len(active) == 0:
        print("  WARNING: Account not active — cookies may be wrong or expired.")
        print("  Double-check auth_token and ct0 from your browser.")
    else:
        print("  You can now run: python3 main.py \"Lost Boys\" --sources reddit,twitter ...")
    print()


if __name__ == "__main__":
    asyncio.run(main())
