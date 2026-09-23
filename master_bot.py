"""Standalone master-account runner.

Reads only MASTER_ID and MASTER_PWD from environment variables, then starts
TalkinBot authenticated as that master account. Keep both values in deployment
Secrets; never put them in source code or chat messages.
"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env.master", override=False)

master_id = os.getenv("MASTER_ID", "").strip()
master_pwd = os.getenv("MASTER_PWD", "")

if not master_id or not master_pwd:
    raise SystemExit(
        "Missing MASTER_ID or MASTER_PWD. Add both as deployment Secrets."
    )

# Force this process to authenticate as the master, independently from the
# primary bot's BOT_ID/BOT_PWD variables if they exist in the same project.
os.environ["BOT_ID"] = master_id
os.environ["BOT_PWD"] = master_pwd
os.environ["BOT_MASTER"] = master_id
os.environ["MASTER_SERVICE_ENABLED"] = "1"
os.environ["GROUP_TO_JOIN"] = ""
os.environ["FIRST_ROOM"] = ""
# PRIMARY_BOT_ID is supplied by the primary bot when it starts this process.

from bot import TalkinBot  # noqa: E402


if __name__ == "__main__":
    TalkinBot().start()
