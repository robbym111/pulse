"""
tiktok_setup.py — one-time setup: saves your ms_token to .env

TikTokApi needs an ms_token cookie from tiktok.com to make authenticated
requests. Without it TikTok returns empty results or blocks the scraper.

How to get your ms_token:
  1. Open tiktok.com in your browser and log in (or just visit, no login required)
  2. Open DevTools (F12 or Cmd+Option+I)
  3. Go to Application → Cookies → https://www.tiktok.com
  4. Find 'msToken' — copy its Value (it's a long string)

Usage:
    python3 tiktok_setup.py
"""

import os
import re


ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")


def read_env():
    if not os.path.exists(ENV_PATH):
        return {}
    lines = {}
    with open(ENV_PATH, "r") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                lines[k.strip()] = v.strip()
    return lines


def write_env(data):
    lines = []
    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            raw = f.readlines()
        written = set()
        for line in raw:
            key = line.split("=", 1)[0].strip()
            if key in data:
                lines.append(f"{key}={data[key]}\n")
                written.add(key)
            else:
                lines.append(line)
        for key, val in data.items():
            if key not in written:
                lines.append(f"{key}={val}\n")
    else:
        for key, val in data.items():
            lines.append(f"{key}={val}\n")

    with open(ENV_PATH, "w") as f:
        f.writelines(lines)


def main():
    print("\n  TikTok ms_token setup")
    print("  ─────────────────────────────────────────")
    print("  To search TikTok, we need an msToken cookie from your browser.\n")
    print("  Steps:")
    print("    1. Go to tiktok.com in Chrome/Safari (log in or just visit)")
    print("    2. Open DevTools → Cmd+Option+I")
    print("    3. Application tab → Cookies → https://www.tiktok.com")
    print("    4. Find 'msToken' and copy its Value\n")

    token = input("  Paste your msToken here: ").strip()

    if not token:
        print("\n  No token entered. Exiting.")
        return

    if len(token) < 50:
        print("\n  WARNING: That token looks short. Make sure you copied the full value.")

    env = read_env()
    env["TIKTOK_MS_TOKEN"] = token
    write_env(env)

    print(f"\n  Saved to .env as TIKTOK_MS_TOKEN.")
    print("  You can now run combined_report.py — TikTok will be included automatically.")
    print("  Token expires periodically — re-run this script if TikTok stops returning results.\n")


if __name__ == "__main__":
    main()
