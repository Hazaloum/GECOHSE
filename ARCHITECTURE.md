# GECO HSE Bot V2 — Architecture

## Project Structure

```
GECOSafetyV2/
│
├── app.py                        # Streamlit UI — entry point, all user interaction
│
├── agent/
│   ├── __init__.py
│   ├── pipeline.py               # Orchestrates full run: descriptions → tips → send → log
│   ├── generator.py              # OpenAI: generates tips + MCQ from descriptions
│   └── router.py                 # Reads correspondence table → maps site to group IDs
│
├── integrations/
│   ├── __init__.py
│   ├── green_api.py              # send_text(), send_image() via Green API
│   ├── google_sheets.py          # All Sheets read/write (log, libraries, correspondence)
│   ├── google_drive.py           # Upload/download images
│   └── google_forms.py           # Create MCQ Google Form, send link
│
├── libraries/
│   ├── __init__.py
│   ├── tip_library.py            # Read/write Tip Library sheet
│   ├── image_library.py          # Read/write Image Library metadata + Drive files
│   └── correspondence.py         # Read Site → Group mapping from Sheets
│
├── config.py                     # All env vars in one place, imported everywhere
│
├── .env                          # Secrets (never commit)
├── credentials.json              # Google service account (never commit)
├── requirements.txt
├── render.yaml
└── CLAUDE.md
```

---

## User Flow

The app is hosted on Render (Streamlit). There is no file watcher — the user interaction is the trigger.

```
User opens Streamlit app
        │
        ▼
  Upload Excel (.xlsx)
        │
        ▼
  Select Site (dropdown — pulled from Correspondence Table)
        │
        ▼
  agent/pipeline.py runs:
        │
        ├──► generator.py → OpenAI → tips + MCQ
        │
        ├──► router.py → correspondence.py → which Group ID for this site
        │
        ├──► image_library.py → best matching image
        │
        ├──► green_api.py → send alert + image to group
        │
        ├──► google_forms.py → create MCQ form → send link to group
        │
        └──► google_sheets.py → log tips, message, MCQ
        │
        ▼
  User sees success summary in app
```

---

## Data Inputs

| Input | Source | Status |
|---|---|---|
| Hazard report descriptions | PowerBI Excel export (.xlsx) | Built |
| Tip Library | Google Sheets tab | Built |
| Image Library | Google Drive + Sheets metadata | Planned |
| Correspondence Table | Google Sheets (Site → WhatsApp Group ID) | Planned |

---

## Data Outputs

| Output | Destination | Status |
|---|---|---|
| Safety alert (text + image) | WhatsApp groups via Green API | Built (text only) |
| MCQ Google Form link | WhatsApp groups via Green API | Planned |
| Tips logged | Google Sheets — Tips Library tab | Built |
| Sends logged | Google Sheets — Message Log tab | Built |
| MCQ logged | Google Sheets — MCQ Log tab | Planned |

---

## Google Sheets Layout (one workbook)

| Tab | Purpose |
|---|---|
| Message Log | Every send: timestamp, site, groups, status |
| Tips Library | Per-tip rows: category, tip text, full alert |
| Image Library | Metadata: name, category, Drive file ID |
| Correspondence | Site name → WhatsApp Group ID |
| MCQ Log | Form URL, questions, responses |

---

## Agent Pipeline (agent/)

- **generator.py** — takes hazard descriptions, calls OpenAI, returns structured tips (with categories) + MCQ questions
- **router.py** — takes site name, reads Correspondence Table, returns the correct WhatsApp Group ID
- **pipeline.py** — orchestrates the full sequence: generator → router → image match → send → log

## Integrations (integrations/)

- **green_api.py** — `send_text(group_id, message)`, `send_image(group_id, file_bytes, filename, caption)`
- **google_sheets.py** — shared read/write for all Sheets tabs
- **google_drive.py** — `upload_file()`, `download_file()` for image library
- **google_forms.py** — `create_mcq_form(questions)` → returns shareable form URL

## Libraries (libraries/)

- **tip_library.py** — read/write Tip Library; future: RAG source once large enough
- **image_library.py** — match images to categories, upload new images
- **correspondence.py** — `get_group_for_site(site_name)` → WhatsApp Group ID

---

## Notes

- **No watcher.py** — not used in the hosted version. User uploads via the app.
- **Tip Library as future RAG** — once large enough, generator.py will fetch relevant past tips instead of generating from scratch.
- **Image selection** — AI auto-selects best matching image based on alert categories; user can override before sending.
- **MCQ delivery** — Google Form link sent to WhatsApp group; workers fill the form; responses logged to Sheets.
