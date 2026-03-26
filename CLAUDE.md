# GECO HSE Bot V2 — Claude Context

## Project Overview
Automated WhatsApp safety alert bot for GECO Engineering (MEP, Civil, Power).
Reads PowerBI Excel exports, generates AI-powered safety alerts from incident descriptions,
and sends them to WhatsApp groups via Green API. Logs all sends to Google Sheets.

## Project Structure
```
GECOSafetyV2/
├── hse_bot.py          # Core logic: Excel → OpenAI → Green API → Sheets log
├── watcher.py          # Watches input/ folder, triggers hse_bot on new .xlsx
├── run_watcher.sh      # Start watcher in background
├── stop_watcher.sh     # Stop the watcher
├── .env                # All secrets (never commit)
├── credentials.json    # Google service account key (never commit)
├── input/              # Drop PowerBI Excel exports here
├── processed/          # Successfully processed files moved here automatically
├── watcher.log         # Created at runtime
└── CLAUDE.md           # This file
```

## How It Works
1. Site manager exports data from PowerBI as `.xlsx` and drops it into `input/`
2. `watcher.py` detects the new file automatically
3. `hse_bot.py` reads the `Description` column from the Excel
4. Sends all descriptions to OpenAI (gpt-4o-mini) → generates a WhatsApp-formatted safety alert
5. Posts the alert to all configured WhatsApp groups via Green API
6. Logs the send to Google Sheets
7. Moves the file to `processed/`

## Running the Bot

### Start the watcher (recommended — runs in background)
```bash
bash /Users/yahyakhaled/Desktop/GECOSafetyV2/run_watcher.sh
```

### Stop the watcher
```bash
bash /Users/yahyakhaled/Desktop/GECOSafetyV2/stop_watcher.sh
```

### Run manually on a specific file
```bash
/opt/anaconda3/bin/python3 /Users/yahyakhaled/Desktop/GECOSafetyV2/hse_bot.py input/data.xlsx
```

### Check logs
```bash
cat /Users/yahyakhaled/Desktop/GECOSafetyV2/watcher.log
```

## Environment Variables (.env)
| Variable               | Description                                          |
|------------------------|------------------------------------------------------|
| OPENAI_API_KEY         | OpenAI API key                                       |
| GOOGLE_CREDS_JSON      | Path to credentials.json                             |
| GREEN_API_INSTANCE_ID  | Green API instance ID                                |
| GREEN_API_TOKEN        | Green API token                                      |
| GREEN_API_GROUPS       | Comma-separated WhatsApp group IDs (GROUPID@g.us)   |
| LOG_SHEET_ID           | Google Sheet ID for logging (optional)               |

## Excel Format (PowerBI Export)
The script reads the `Description` column only. All other columns are ignored.
File must be `.xlsx`. Drop into `input/` folder.

Columns present in the PowerBI export (for reference):
```
ReqNo | RefID | Initiated Date | Company | Project No | Project Name |
Priority | Observations/Quality | Observation Type | Observations Related To |
Observation Status | Emirate | Location | Division | Department | Description
```

## WhatsApp Groups
Group IDs are fetched via:
```bash
curl "https://api.green-api.com/waInstance{ID}/getContacts/{TOKEN}"
```
Groups end in `@g.us`. Add multiple groups as comma-separated values in `.env`.

Current configured group: `GreenApi test` (for testing)

## AI Prompt Behaviour
- Model: `gpt-4o-mini`
- Tone: Sharp, formal, pedagogical — explains consequences of non-compliance
- Format: WhatsApp-native (bold via `*text*`, heavy emoji use)
- Picks 3-4 most critical recurring issues from the incident data
- Ends with: `_Management & HSE Team_`

## Python Environment
- Use `/opt/anaconda3/bin/python3` — NOT `/usr/bin/python3`

## Dependencies
```
pandas openpyxl watchdog requests gspread openai oauth2client python-dotenv
```
Install: `pip install pandas openpyxl watchdog requests gspread openai oauth2client python-dotenv`

## Planned Features
- Per-site targeting (group incidents by site, send to respective site groups)
- Google Sheets logging (LOG_SHEET_ID in .env — pending sheet setup)
- Weekly summary memo from uploaded HSE reports

## Never Commit
- `.env`
- `credentials.json`
