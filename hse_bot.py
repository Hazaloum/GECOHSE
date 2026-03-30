import os
import sys
import time
import shutil
from datetime import datetime

import pandas as pd
import requests
import gspread
from openai import OpenAI
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

OPENAI_API_KEY      = os.getenv("OPENAI_API_KEY")

# Support both a file path (local) and raw JSON content (Render/cloud)
_CREDS_CONTENT = os.getenv("GOOGLE_CREDS_JSON_CONTENT")
if _CREDS_CONTENT:
    import json, tempfile
    _tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
    _tmp.write(_CREDS_CONTENT)
    _tmp.close()
    GOOGLE_CREDS_JSON = _tmp.name
else:
    GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDS_JSON", os.path.join(os.path.dirname(__file__), "credentials.json"))
GREEN_API_INSTANCE  = os.getenv("GREEN_API_INSTANCE_ID")
GREEN_API_TOKEN     = os.getenv("GREEN_API_TOKEN")
GREEN_API_GROUPS    = [g.strip() for g in os.getenv("GREEN_API_GROUPS", "").split(",") if g.strip()]
LOG_SHEET_ID        = os.getenv("LOG_SHEET_ID")

client = OpenAI(api_key=OPENAI_API_KEY)


def read_descriptions(filepath: str) -> list[str]:
    df = pd.read_excel(filepath)
    if "Description" not in df.columns:
        raise ValueError(f"No 'Description' column found. Columns present: {df.columns.tolist()}")
    descriptions = df["Description"].dropna().astype(str).tolist()
    print(f"  Read {len(descriptions)} descriptions from {os.path.basename(filepath)}")
    return descriptions


def generate_tips(descriptions: list[str]) -> str:
    incidents_text = "\n".join(f"- {d}" for d in descriptions)
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=500,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict but caring safety officer at GECO Engineering, a construction company "
                    "operating in the UAE doing MEP, Civil, and Power engineering. "
                    "You send WhatsApp safety alerts to all workers on site. "
                    "Your writing style: sharp, direct, pedagogical — you don't just tell workers what to do, "
                    "you briefly explain WHY it matters (injuries, deaths, job loss). "
                    "Use a strong, commanding tone — these are non-negotiable safety rules. "
                    "Use emojis heavily to grab attention on mobile (🔴⚠️🦺🏗️📋🚫☠️✅👷). "
                    "Use WhatsApp bold (*text*) for key directives. "
                    "Keep it punchy — no long paragraphs. Each point is 1-2 sharp sentences max. "
                    "Start with a strong attention-grabbing header. "
                    "End with a motivational closing line, then: _Management & HSE Team_"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Read these incident descriptions from our sites and generate an urgent safety alert "
                    "for all workers on WhatsApp. "
                    "Pick the 3-4 most critical recurring issues. For each one: state the rule clearly, "
                    "and in one sentence explain the consequence if ignored (injury, death, dismissal). "
                    "Make workers feel the urgency. This message could save a life.\n\n"
                    f"Incidents:\n{incidents_text}"
                ),
            },
        ],
    )
    return response.choices[0].message.content.strip()


def send_to_group(group_id: str, message: str) -> bool:
    url = f"https://api.green-api.com/waInstance{GREEN_API_INSTANCE}/sendMessage/{GREEN_API_TOKEN}"
    payload = {"chatId": group_id, "message": message}
    resp = requests.post(url, json=payload, timeout=15)
    if resp.status_code == 200:
        print(f"  ✓ Sent to {group_id}")
        return True
    else:
        print(f"  ✗ Failed {group_id}: {resp.status_code} {resp.text}")
        return False


def log_to_sheets(filename: str, tips: str, groups: list[str], status: str):
    if not LOG_SHEET_ID:
        print("  (No LOG_SHEET_ID set — skipping Sheets log)")
        return
    try:
        scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
        creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_JSON, scope)
        gc = gspread.authorize(creds)
        workbook = gc.open_by_key(LOG_SHEET_ID)

        # --- Send log (sheet1) ---
        workbook.sheet1.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            filename,
            ", ".join(groups),
            status,
        ])

        # --- Tips Library tab ---
        try:
            library = workbook.worksheet("Tips Library")
        except gspread.exceptions.WorksheetNotFound:
            library = workbook.add_worksheet(title="Tips Library", rows=1000, cols=4)
            library.append_row(["Timestamp", "Filename", "Groups", "Alert"])

        library.append_row([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            filename,
            ", ".join(groups),
            tips,
        ])

        print("  ✓ Logged to Google Sheets")
    except Exception as e:
        print(f"  ✗ Sheets log failed: {e}")


def main(filepath: str):
    filepath = os.path.abspath(filepath)
    filename = os.path.basename(filepath)
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Processing {filename}")

    # 1. Read descriptions
    descriptions = read_descriptions(filepath)

    # 2. Generate tips
    print("  Generating tips via OpenAI...")
    tips = generate_tips(descriptions)
    print(f"\n--- Tips ---\n{tips}\n------------")

    # 3. Send to groups
    if not GREEN_API_GROUPS:
        print("  No GREEN_API_GROUPS set — skipping WhatsApp send")
        status = "no_groups"
    elif not GREEN_API_INSTANCE or not GREEN_API_TOKEN:
        print("  Green API credentials not set — skipping WhatsApp send")
        status = "no_credentials"
    else:
        message = tips
        success_count = 0
        for group_id in GREEN_API_GROUPS:
            if send_to_group(group_id, message):
                success_count += 1
            time.sleep(3)
        status = "sent" if success_count == len(GREEN_API_GROUPS) else f"partial ({success_count}/{len(GREEN_API_GROUPS)})"

    # 4. Log to Sheets
    log_to_sheets(filename, tips, GREEN_API_GROUPS, status)

    # 5. Move to processed/
    if os.path.exists(filepath):
        processed_dir = os.path.join(os.path.dirname(__file__), "processed")
        os.makedirs(processed_dir, exist_ok=True)
        shutil.move(filepath, os.path.join(processed_dir, filename))
        print(f"  Moved to processed/")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python hse_bot.py <path_to_excel>")
        sys.exit(1)
    main(sys.argv[1])
