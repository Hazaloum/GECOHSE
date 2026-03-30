import os
import time
import tempfile

import requests
import streamlit as st
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from dotenv import load_dotenv

import hse_bot

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

APP_PASSWORD = os.getenv("APP_PASSWORD", "geco2024")


@st.cache_data(ttl=300)
def fetch_all_groups(instance_id: str, token: str) -> dict:
    """Fetch all WhatsApp groups from the Green API device. Returns {group_id: group_name}."""
    try:
        url = f"https://api.green-api.com/waInstance{instance_id}/getContacts/{token}"
        resp = requests.get(url, timeout=15)
        if resp.status_code != 200:
            return {}
        contacts = resp.json()
        return {
            c["id"]: c.get("name") or c.get("id")
            for c in contacts
            if c.get("id", "").endswith("@g.us")
        }
    except Exception:
        return {}


def get_group_map() -> dict:
    instance_id = os.getenv("GREEN_API_INSTANCE_ID")
    token = os.getenv("GREEN_API_TOKEN")
    if instance_id and token:
        groups = fetch_all_groups(instance_id, token)
        if groups:
            return groups
    # Fallback to manually configured groups if API fails
    fallback = [g.strip() for g in os.getenv("GREEN_API_GROUPS", "").split(",") if g.strip()]
    return {g: g for g in fallback}


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


@st.cache_data(ttl=300)
def load_tips_library() -> list[dict]:
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

    result = []
    for row in rows[1:]:  # skip header
        while len(row) < 6:
            row.append("")
        category = row[3] if row[3] else "Uncategorized"
        # Old 4-col rows: column 3 was the full alert, not a category
        # Detect by checking if it looks like a category name (short, no newlines)
        tip_text  = row[4] if row[4] else row[3]
        full_alert = row[5] if row[5] else row[3]
        result.append({
            "timestamp":  row[0],
            "filename":   row[1],
            "groups":     row[2],
            "category":   category,
            "tip_text":   tip_text,
            "full_alert": full_alert,
        })
    return list(reversed(result))  # newest first


def main():
    st.set_page_config(page_title="GECO HSE Portal", page_icon="🦺", layout="centered")

    if not check_password():
        return

    page = st.sidebar.radio("Navigate", ["Send Alert", "Tips Library"])

    if page == "Tips Library":
        st.title("📚 Tips Library")
        st.caption("Browse individual safety tips by category.")
        st.divider()

        if not os.getenv("LOG_SHEET_ID"):
            st.warning("No LOG_SHEET_ID configured — cannot load library.")
            return

        col1, col2 = st.columns([6, 1])
        with col2:
            if st.button("🔄 Refresh"):
                load_tips_library.clear()
                st.rerun()

        with st.spinner("Loading tips library..."):
            try:
                tips_rows = load_tips_library()
            except Exception as e:
                st.error(f"Could not load library: {e}")
                return

        if not tips_rows:
            st.info("No tips logged yet.")
            return

        # Build category list from actual data only
        all_categories = sorted({r["category"] for r in tips_rows})

        selected_cats = st.multiselect(
            "Filter by Category",
            options=all_categories,
            default=all_categories,
        )

        filtered = [r for r in tips_rows if r["category"] in selected_cats]
        st.caption(f"Showing {len(filtered)} tip(s) across {len(selected_cats)} category/categories.")
        st.divider()

        # Group by category and display
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in filtered:
            grouped[r["category"]].append(r)

        for category in sorted(grouped.keys()):
            st.subheader(f"🏷️ {category}  ({len(grouped[category])})")
            for tip in grouped[category]:
                st.info(tip["tip_text"])
                st.caption(f"📅 {tip['timestamp']}  |  📁 {tip['filename']}  |  👥 {tip['groups']}")
            st.divider()
        return

    GROUP_MAP = get_group_map()

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
                    tips, structured_tips = hse_bot.generate_tips(descriptions)
                    st.session_state.tips = tips
                    st.session_state.structured_tips = structured_tips
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
            st.warning("No WhatsApp groups found. Make sure GREEN_API_INSTANCE_ID and GREEN_API_TOKEN are set correctly.")
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

                hse_bot.log_to_sheets(
                    st.session_state.filename, edited, selected, "sent",
                    st.session_state.get("structured_tips"),
                )

            if success == len(selected):
                st.success(f"✅ Sent to {success} group(s) successfully!")
                del st.session_state["tips"]
                del st.session_state["filename"]
                st.session_state.pop("structured_tips", None)
            else:
                st.warning(f"Sent to {success}/{len(selected)} groups. Failed: {', '.join(errors)}")


if __name__ == "__main__":
    main()
