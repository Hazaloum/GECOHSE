import os
import time
import tempfile

import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

import hse_bot

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

APP_PASSWORD = os.getenv("APP_PASSWORD", "geco2024")
GROUPS_RAW   = [g.strip() for g in os.getenv("GREEN_API_GROUPS", "").split(",") if g.strip()]
GROUP_NAMES  = [g.strip() for g in os.getenv("GREEN_API_GROUP_NAMES", "").split(",") if g.strip()]

# Map group IDs to friendly names — fallback to ID if names not set
GROUP_MAP = {
    GROUPS_RAW[i]: (GROUP_NAMES[i] if i < len(GROUP_NAMES) else GROUPS_RAW[i])
    for i in range(len(GROUPS_RAW))
}


def check_password():
    if st.session_state.get("authenticated"):
        return True
    st.title("🦺 GECO HSE Portal")
    pwd = st.text_input("Password", type="password")
    if st.button("Login"):
        if pwd == APP_PASSWORD:
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Incorrect password.")
    return False


def load_tips_library():
    log_sheet_id = os.getenv("LOG_SHEET_ID")
    creds_content = os.getenv("GOOGLE_CREDS_JSON_CONTENT")
    if creds_content:
        import json, tempfile
        tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        tmp.write(creds_content)
        tmp.close()
        creds_path = tmp.name
    else:
        creds_path = os.getenv("GOOGLE_CREDS_JSON", os.path.join(os.path.dirname(__file__), "credentials.json"))

    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_name(creds_path, scope)
    gc = gspread.authorize(creds)
    sheet = gc.open_by_key(log_sheet_id).worksheet("Tips Library")
    rows = sheet.get_all_values()
    if len(rows) <= 1:
        return []
    # Skip header row
    return list(reversed(rows[1:]))  # newest first


def main():
    st.set_page_config(page_title="GECO HSE Portal", page_icon="🦺", layout="centered")

    if not check_password():
        return

    page = st.sidebar.radio("Navigate", ["Send Alert", "Tips Library"])

    if page == "Tips Library":
        st.title("📚 Tips Library")
        st.caption("All previously generated and sent safety alerts.")
        st.divider()

        if not os.getenv("LOG_SHEET_ID"):
            st.warning("No LOG_SHEET_ID configured — cannot load library.")
            return

        with st.spinner("Loading tips library..."):
            try:
                rows = load_tips_library()
            except Exception as e:
                st.error(f"Could not load library: {e}")
                return

        if not rows:
            st.info("No alerts have been sent yet.")
            return

        for row in rows:
            timestamp = row[0] if len(row) > 0 else "—"
            filename  = row[1] if len(row) > 1 else "—"
            groups    = row[2] if len(row) > 2 else "—"
            alert     = row[3] if len(row) > 3 else ""
            with st.expander(f"{timestamp} — {filename} → {groups}"):
                st.text(alert)
        return

    st.title("🦺 GECO HSE Safety Alert")
    st.caption("Upload a PowerBI Excel export → review the AI-generated alert → send to WhatsApp groups.")
    st.divider()

    # --- Step 1: Upload ---
    uploaded_file = st.file_uploader("Step 1 — Upload Excel Report (.xlsx)", type=["xlsx"])

    if uploaded_file:
        if st.button("Generate Safety Alert", type="primary"):
            with st.spinner("Reading report and generating alert..."):
                with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
                    tmp.write(uploaded_file.read())
                    tmp_path = tmp.name
                try:
                    descriptions = hse_bot.read_descriptions(tmp_path)
                    tips = hse_bot.generate_tips(descriptions)
                    st.session_state.tips = tips
                    st.session_state.filename = uploaded_file.name
                    st.session_state.desc_count = len(descriptions)
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    os.unlink(tmp_path)

    # --- Step 2: Review ---
    if "tips" in st.session_state:
        st.divider()
        st.markdown(f"**Step 2 — Review Alert** _(generated from {st.session_state.desc_count} incidents)_")
        edited = st.text_area("Edit if needed:", value=st.session_state.tips, height=420, label_visibility="collapsed")

        # --- Step 3: Send ---
        st.divider()
        st.markdown("**Step 3 — Select Groups & Send**")

        if not GROUP_MAP:
            st.warning("No WhatsApp groups configured. Set GREEN_API_GROUPS in your environment variables.")
            return

        selected = []
        for group_id, name in GROUP_MAP.items():
            if st.checkbox(name, value=True, key=group_id):
                selected.append(group_id)

        st.write("")
        if st.button("Send to WhatsApp 🚀", type="primary", disabled=len(selected) == 0):
            with st.spinner("Sending..."):
                success = 0
                errors = []
                for group_id in selected:
                    if hse_bot.send_to_group(group_id, edited):
                        success += 1
                    else:
                        errors.append(GROUP_MAP[group_id])
                    time.sleep(3)

                hse_bot.log_to_sheets(st.session_state.filename, edited, selected, "sent")

            if success == len(selected):
                st.success(f"✅ Sent to {success} group(s) successfully!")
                del st.session_state["tips"]
                del st.session_state["filename"]
            else:
                st.warning(f"Sent to {success}/{len(selected)} groups. Failed: {', '.join(errors)}")


if __name__ == "__main__":
    main()
