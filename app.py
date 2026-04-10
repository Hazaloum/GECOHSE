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

    valid_categories = set(hse_bot.CATEGORIES)
    result = []
    for row in rows[1:]:  # skip header
        while len(row) < 6:
            row.append("")
        category = row[3].strip()
        # Skip old blob rows — if category is not a known category, discard the row
        if category not in valid_categories:
            continue
        result.append({
            "timestamp":  row[0],
            "filename":   row[1],
            "groups":     row[2],
            "category":   category,
            "tip_text":   row[4],
            "full_alert": row[5],
        })
    return list(reversed(result))  # newest first


def main():
    st.set_page_config(page_title="GECO HSE Portal", page_icon="🦺", layout="centered")

    if not check_password():
        return

    page = st.sidebar.radio("Navigate", ["Send Alert", "Tips Library", "Upload Image"])

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
            st.info("No tips logged yet. Tips will appear here after you send your first alert.")
            return

        # Group by category
        from collections import defaultdict
        grouped = defaultdict(list)
        for r in tips_rows:
            grouped[r["category"]].append(r)

        st.caption(f"{len(tips_rows)} tip(s) across {len(grouped)} category/categories.")
        st.divider()

        for category in sorted(grouped.keys()):
            tips_in_cat = grouped[category]
            with st.expander(f"🏷️ {category}  ({len(tips_in_cat)})"):
                for tip in tips_in_cat:
                    st.info(tip["tip_text"])
                    st.caption(f"📅 {tip['timestamp']}  |  📁 {tip['filename']}  |  👥 {tip['groups']}")
        return

    if page == "Upload Image":
        st.title("🖼️ Upload Image to Library")
        st.caption("Upload safety-related images to Google Drive. They will be available to attach to alerts.")
        st.divider()

        if not os.getenv("LOG_SHEET_ID"):
            st.warning("No LOG_SHEET_ID configured — cannot log to library.")
            return

        img_file = st.file_uploader("Select an image", type=["jpg", "jpeg", "png", "webp"])

        if img_file:
            st.image(img_file, width=300)
            category = st.selectbox("Category", hse_bot.CATEGORIES)
            description = st.text_input("Description (optional)", placeholder="e.g. Worker wearing full PPE on scaffold")

            if st.button("Upload to Library 📤", type="primary"):
                with st.spinner("Uploading to Google Drive..."):
                    try:
                        file_bytes = img_file.read()
                        mimetype = img_file.type or "image/jpeg"
                        file_id = hse_bot.upload_image_to_drive(file_bytes, img_file.name, mimetype)
                        hse_bot.log_image_to_library(img_file.name, file_id, category, description)
                        drive_url = f"https://drive.google.com/file/d/{file_id}/view"
                        st.success(f"✅ Uploaded successfully!")
                        st.markdown(f"[View on Google Drive]({drive_url})")
                    except Exception as e:
                        st.error(f"Upload failed: {e}")
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
                    os.unlink(tmp_path)
                    st.stop()
                finally:
                    if os.path.exists(tmp_path):
                        os.unlink(tmp_path)

            with st.spinner("Translating to Urdu..."):
                try:
                    st.session_state.tips_urdu = hse_bot.translate_alert(st.session_state.tips, "Urdu")
                except Exception as e:
                    st.session_state.tips_urdu = f"[Translation failed: {e}]"

            with st.spinner("Translating to Hindi..."):
                try:
                    st.session_state.tips_hindi = hse_bot.translate_alert(st.session_state.tips, "Hindi")
                except Exception as e:
                    st.session_state.tips_hindi = f"[Translation failed: {e}]"

    # --- Step 2: Review ---
    if "tips" in st.session_state:
        st.divider()
        st.markdown(f"**Step 2 — Review Alert** _(generated from {st.session_state.desc_count} incidents)_")
        edited = st.text_area("🇬🇧 English", value=st.session_state.tips, height=380)
        edited_urdu = st.text_area("🇵🇰 Urdu", value=st.session_state.get("tips_urdu", ""), height=380)
        edited_hindi = st.text_area("🇮🇳 Hindi", value=st.session_state.get("tips_hindi", ""), height=380)

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
            parts = [p for p in [edited, edited_urdu, edited_hindi] if p.strip()]
            combined_message = "\n\n━━━━━━━━━━━━━━━━━━━━\n\n".join(parts)

            with st.spinner("Sending..."):
                success = 0
                errors = []
                for group_id in selected:
                    if hse_bot.send_to_group(group_id, combined_message):
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
                st.session_state.pop("tips_urdu", None)
                st.session_state.pop("tips_hindi", None)
                del st.session_state["filename"]
                st.session_state.pop("structured_tips", None)
            else:
                st.warning(f"Sent to {success}/{len(selected)} groups. Failed: {', '.join(errors)}")


if __name__ == "__main__":
    main()
