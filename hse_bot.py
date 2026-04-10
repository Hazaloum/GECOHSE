import os
import sys
import json
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
GREEN_API_INSTANCE      = os.getenv("GREEN_API_INSTANCE_ID")
GREEN_API_TOKEN         = os.getenv("GREEN_API_TOKEN")
GREEN_API_GROUPS        = [g.strip() for g in os.getenv("GREEN_API_GROUPS", "").split(",") if g.strip()]
LOG_SHEET_ID            = os.getenv("LOG_SHEET_ID")
GOOGLE_DRIVE_FOLDER_ID  = os.getenv("GOOGLE_DRIVE_FOLDER_ID")

client = OpenAI(api_key=OPENAI_API_KEY)

CATEGORIES = [
    "Housekeeping", "Material Storage", "Scaffolding", "Barrication",
    "Welfare", "PPE", "Electrical", "Unsafe Condition (others)",
    "Access and egress", "Excavation", "Ladder", "Power tools",
    "Fall Protection", "Hand tools", "Public Safety", "Chemical",
    "Edge Protection", "Waste Disposal", "Fire Protection",
    "Housekeeping equipments", "Third Part Cert", "Compliance", "Dust",
    "Emergency service", "Environment Hazard", "First Aid", "HSE Document",
    "Lighting", "Pest Control", "Protruding nails", "Security", "Signage",
    "Slip & Trip", "Vehicle / Traffic", "Waste Management", "Work At height",
]


def read_descriptions(filepath: str) -> list[str]:
    df = pd.read_excel(filepath)
    if "Description" not in df.columns:
        raise ValueError(f"No 'Description' column found. Columns present: {df.columns.tolist()}")
    descriptions = df["Description"].dropna().astype(str).tolist()
    print(f"  Read {len(descriptions)} descriptions from {os.path.basename(filepath)}")
    return descriptions


def generate_tips(descriptions: list[str]) -> tuple[str, list[dict]]:
    incidents_text = "\n".join(f"- {d}" for d in descriptions)
    categories_str = ", ".join(CATEGORIES)
    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        max_completion_tokens=700,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a strict safety officer at GECO Engineering, a construction company "
                    "operating in the UAE doing MEP, Civil, and Power engineering. "
                    "You send WhatsApp safety alerts to all workers on site.\n\n"
                    "Each tip MUST follow this exact format — one single line:\n"
                    "*[Subject]* - [Action] - [Warning & Consequence]\n\n"
                    "Rules:\n"
                    "- Subject: the safety topic (e.g. PPE, Scaffolding, Fire Protection)\n"
                    "- Action: a short, direct instruction. No fluff.\n"
                    "- Warning & Consequence: one sharp sentence — what happens if ignored.\n"
                    "- The entire tip is ONE line. No line breaks within a tip.\n"
                    "- Add one relevant emoji at the start of the subject.\n"
                    "- Example: ⚠️ *PPE* - Always wear your PPE in all circumstances, no exceptions - Accidents don't give warnings\n\n"
                    "Start with a bold header line. End with: _Management & HSE Team_\n\n"
                    "You MUST respond with a JSON object with exactly two keys:\n"
                    "1. 'alert': the full WhatsApp alert string. Each tip on its own numbered line in the format above. "
                    "Do NOT append any category label at the end of the tip line.\n"
                    "2. 'tips': a JSON array with one object per tip. Each object must have:\n"
                    "   - 'tip_text': plain-English version of the tip (no emojis, no WhatsApp formatting)\n"
                    f"   - 'category': one category chosen strictly from this list: {categories_str}\n"
                    "The 'tips' array must have the same number of items as tips in 'alert'."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Read these incident descriptions and generate a safety alert for all workers. "
                    "Pick exactly 3 of the most critical recurring issues. "
                    "Each tip must be one line: Subject - Action - Warning & Consequence. Keep it short and direct.\n\n"
                    f"Incidents:\n{incidents_text}"
                ),
            },
        ],
    )
    try:
        data = json.loads(response.choices[0].message.content)
        alert_string = data.get("alert", "").strip()
        tips_list = data.get("tips", [])
        if not alert_string:
            raise ValueError("Missing 'alert' key in response")
        # Normalise categories — fallback to "Unsafe Condition (others)" if unrecognised
        for tip in tips_list:
            tip.setdefault("tip_text", "")
            tip.setdefault("category", "Unsafe Condition (others)")
            if tip["category"] not in CATEGORIES:
                tip["category"] = "Unsafe Condition (others)"
        return alert_string, tips_list
    except Exception as e:
        print(f"  Warning: Could not parse structured tips: {e}. Falling back to raw string.")
        raw = response.choices[0].message.content.strip()
        return raw, []


def _get_drive_service():
    from googleapiclient.discovery import build
    scope = ["https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_JSON, scope)
    return build("drive", "v3", credentials=creds)


def upload_image_to_drive(file_bytes: bytes, filename: str, mimetype: str) -> str:
    """Upload an image to Google Drive and return the public file ID."""
    from googleapiclient.http import MediaInMemoryUpload
    service = _get_drive_service()
    metadata = {"name": filename}
    if GOOGLE_DRIVE_FOLDER_ID:
        metadata["parents"] = [GOOGLE_DRIVE_FOLDER_ID]
    media = MediaInMemoryUpload(file_bytes, mimetype=mimetype)
    file = service.files().create(body=metadata, media_body=media, fields="id").execute()
    file_id = file.get("id")
    # Make publicly readable so it can be sent via WhatsApp
    service.permissions().create(
        fileId=file_id,
        body={"type": "anyone", "role": "reader"},
    ).execute()
    return file_id


def log_image_to_library(filename: str, file_id: str, category: str, description: str):
    """Log an uploaded image to the Image Library tab in Google Sheets."""
    if not LOG_SHEET_ID:
        return
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(GOOGLE_CREDS_JSON, scope)
    gc = gspread.authorize(creds)
    workbook = gc.open_by_key(LOG_SHEET_ID)
    header = ["Timestamp", "Filename", "Drive File ID", "Category", "Description", "Drive URL"]
    try:
        sheet = workbook.worksheet("Image Library")
        if sheet.row_values(1) != header:
            sheet.update("A1:F1", [header])
    except gspread.exceptions.WorksheetNotFound:
        sheet = workbook.add_worksheet(title="Image Library", rows=2000, cols=6)
        sheet.append_row(header)
    drive_url = f"https://drive.google.com/file/d/{file_id}/view"
    sheet.append_row([
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        filename,
        file_id,
        category,
        description,
        drive_url,
    ])


def translate_alert(alert: str, language: str) -> str:
    response = client.chat.completions.create(
        model="gpt-5.4-mini",
        max_completion_tokens=900,
        messages=[
            {
                "role": "system",
                "content": (
                    f"You are a professional translator. Translate the following WhatsApp safety alert into {language}. "
                    "Preserve all formatting exactly: WhatsApp bold (*text*), emojis, line breaks, and structure. "
                    "Only translate the words — do not alter emojis, bullet numbers, or formatting symbols like * and _."
                ),
            },
            {"role": "user", "content": alert},
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


def log_to_sheets(filename: str, tips: str, groups: list[str], status: str,
                  structured_tips: list[dict] = None):
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

        # --- Tips Library tab (6-column schema) ---
        new_header = ["Timestamp", "Filename", "Groups", "Category", "Tip Text", "Full Alert"]
        try:
            library = workbook.worksheet("Tips Library")
            # Migrate old 4-column header if needed
            existing_header = library.row_values(1)
            if len(existing_header) < 6:
                library.update("A1:F1", [new_header])
        except gspread.exceptions.WorksheetNotFound:
            library = workbook.add_worksheet(title="Tips Library", rows=5000, cols=6)
            library.append_row(new_header)

        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        groups_str = ", ".join(groups)

        if structured_tips:
            rows_to_append = [
                [ts, filename, groups_str, t["category"], t["tip_text"], tips]
                for t in structured_tips
            ]
            library.append_rows(rows_to_append)
        else:
            # Fallback: log full alert with no category
            library.append_row([ts, filename, groups_str, "", tips, tips])

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
    tips, structured_tips = generate_tips(descriptions)
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
    log_to_sheets(filename, tips, GREEN_API_GROUPS, status, structured_tips)

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
