"""
streamlit_app.py — Canva design to long-form document.

Restructured per feedback: "Generate" (plain, reliable path) and
"Human Review" (experimental async+approval path) are now separate
tabs with separate buttons - generating with review no longer
re-triggers or interferes with the already-generated plain documents.
The review tab shows raw job status at every step, visibly, so any
failure is diagnosable instead of a silent "it didn't work."

Usage:
    streamlit run streamlit_app.py
"""
import os
import uuid
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import streamlit as st

from extract_content import extract_text, extract_palette
from document_quality import check_color_consistency, detect_duplicate_headings
from canva_pipeline import list_designs, pull_design_assets, get_user_info
from superdocs_pipeline import (
    upload_image, seed_document, generate_plain,
    generate_with_approval_start, poll_job, submit_approval_decision,
    export_document,
)

ASSET_ROOT = Path("design_assets")
DOC_TYPES = ["Leave-behind report", "Brochure", "Long-form article"]

st.set_page_config(page_title="Canva → Long-Form Document", page_icon="📄", layout="wide")

st.markdown("""
<style>
[data-testid="stAppViewContainer"] { direction: rtl; }
[data-testid="stAppViewContainer"] > * { direction: ltr; }
h1 { text-align: center; }
.subtitle-center { text-align: center; color: #999; margin-bottom: 1.5rem; }
</style>
""", unsafe_allow_html=True)

st.title("Canva → Long-Form Document")
st.markdown(
    '<p class="subtitle-center">Built on SuperDocs — turns a Canva design into a branded, long-form document</p>',
    unsafe_allow_html=True,
)

DEFAULTS = {
    "canva_token": os.environ.get("CANVA_ACCESS_TOKEN", ""),
    "superdocs_key": os.environ.get("SUPERDOCS_API_KEY", ""),
    "design_list": [],
    "selected_design": None,
    "canva_user_info": None,
    "token_connected_at": None,
    "pulled_text": None,
    "pulled_colors": None,
    "pulled_image_path": None,
    "image_url": None,
    "sessions": {},
    "generated": {},
    "review_session_id": None,
    "review_pending_job_id": None,
    "review_pending_changes": None,
    "review_generated_html": None,
    "review_debug_log": [],
}
for key, default in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default

TOKEN_LIFETIME_SECONDS = int(os.environ.get("CANVA_TOKEN_EXPIRES_IN", 14400))


with st.sidebar:
    st.subheader("How to use this app")
    st.markdown(
        "1. **Connect to Canva** below and pick a design\n"
        "2. **Pull & Preview** — extract the design's copy, colors, and a print-quality image\n"
        "3. **Generate** — creates all three document types (reliable path)\n"
        "4. **Human Review** — optional, experimental review-gated generation\n"
        "5. **Quality & Export** — check each result, then download\n"
        "6. **Sync** — check for updates if you edit the design in Canva later"
    )

    st.divider()
    st.subheader("Canva connection")

    if st.button("Connect to Canva", use_container_width=True, type="primary"):
        with st.spinner("Connecting..."):
            designs = list_designs(st.session_state.canva_token)
            user_info = get_user_info(st.session_state.canva_token)
        if designs:
            st.session_state.design_list = designs
            st.session_state.canva_user_info = user_info
            st.session_state.token_connected_at = time.time()
            st.success(f"Connected — {len(designs)} design(s) found")
        else:
            st.error("Could not connect. Token may have expired.")
            st.caption("Run `python refresh_canva_token.py`, update .env, then click again.")

    designs = st.session_state.design_list
    if designs:
        labels = {f"{d.get('title', '(untitled)')}": d["id"] for d in designs}
        chosen_label = st.selectbox("Design name", options=list(labels.keys()))
        st.session_state.selected_design = labels[chosen_label]
        st.caption("Design ID")
        st.code(st.session_state.selected_design, language=None)
    else:
        st.caption("Click 'Connect to Canva' to load your designs.")
        manual_id = st.text_input("Or enter a design ID directly")
        if manual_id:
            st.session_state.selected_design = manual_id

    if st.session_state.canva_user_info:
        st.caption("Canva user ID")
        st.code(st.session_state.canva_user_info.get("user_id", "unknown"), language=None)

    st.divider()
    st.subheader("Connection status")
    if st.session_state.canva_token:
        st.success("Canva token loaded")
        if st.session_state.token_connected_at:
            elapsed = time.time() - st.session_state.token_connected_at
            remaining = TOKEN_LIFETIME_SECONDS - elapsed
            if remaining > 0:
                mins_remaining = int(remaining // 60)
                st.caption(f"Token verified {int(elapsed // 60)} min ago — "
                           f"~{mins_remaining} min remaining before it likely expires")
                if mins_remaining < 15:
                    st.warning("Token expiring soon — refresh it after this session.")
            else:
                st.warning("Token likely expired — click 'Connect to Canva' to verify, or refresh it.")
        else:
            st.caption("Click 'Connect to Canva' to verify and start the countdown.")
    else:
        st.error("No Canva token found in .env")

    if st.session_state.superdocs_key:
        st.success("SuperDocs key loaded")
    else:
        st.error("No SuperDocs key found in .env")


if not st.session_state.selected_design:
    st.info("Connect to Canva and select a design in the sidebar to begin.")
    st.stop()

design_id = st.session_state.selected_design
asset_dir = ASSET_ROOT / design_id

tab_pull, tab_generate, tab_review, tab_quality, tab_sync = st.tabs(
    ["1. Pull & Preview", "2. Generate", "3. Human Review", "4. Quality & Export", "5. Sync"]
)

with tab_pull:
    st.subheader("Pull content from Canva")
    st.caption("Extracts copy (via PDF) and visual palette (via a print-resolution PNG export).")

    if st.button("Pull design", type="primary"):
        with st.spinner("Exporting and downloading from Canva..."):
            assets = pull_design_assets(st.session_state.canva_token, design_id, asset_dir)

        if not assets.get("pdf_path") or not assets.get("png_path"):
            st.error("Pull failed — check that your Canva token is still valid.")
        else:
            st.session_state.pulled_text = extract_text(assets["pdf_path"])
            st.session_state.pulled_colors = extract_palette(assets["png_path"])
            st.session_state.pulled_image_path = assets["png_path"]
            st.success("Pulled successfully")

    if st.session_state.pulled_text:
        col1, col2 = st.columns([2, 1])
        with col1:
            st.markdown("**Extracted copy**")
            st.text_area("Copy", st.session_state.pulled_text, height=200, label_visibility="collapsed")
        with col2:
            st.markdown("**Brand palette**")
            for c in st.session_state.pulled_colors:
                st.markdown(
                    f'<div style="background-color:{c}; padding:8px; margin-bottom:4px; '
                    f'border-radius:4px; color:white; font-family:monospace;">{c}</div>',
                    unsafe_allow_html=True,
                )
        st.markdown("**Print-resolution preview**")
        st.image(str(st.session_state.pulled_image_path), width=300)

with tab_generate:
    st.subheader("Generate all document types")
    st.caption("Uses the direct generation path — verified reliable across every test in this build.")

    if not st.session_state.pulled_text:
        st.info("Pull a design first (Tab 1).")
    else:
        if st.button("Generate all 3 documents", type="primary"):
            colors = st.session_state.pulled_colors

            if not st.session_state.image_url:
                with st.spinner("Uploading image..."):
                    st.session_state.image_url = upload_image(st.session_state.superdocs_key, st.session_state.pulled_image_path)

            for doc_type in DOC_TYPES:
                session_id = st.session_state.sessions.get(doc_type) or f"canva-{design_id}-{doc_type.split()[0].lower()}-{uuid.uuid4().hex[:6]}"
                st.session_state.sessions[doc_type] = session_id

                seed_html = "\n".join(f"<p>{l}</p>" for l in st.session_state.pulled_text.split("\n") if l.strip())

                with st.spinner(f"Seeding '{doc_type}'..."):
                    seed_document(st.session_state.superdocs_key, session_id, seed_html)

                instruction = (
                    f"This is the copy from a promotional flyer. Expand it into a full {doc_type.lower()}, "
                    f"in an energetic tone matching the brand. Use {colors[0]} for all section headings. "
                    f"Brand palette: {', '.join(colors)}. "
                    + (f"Include this image: {st.session_state.image_url}" if st.session_state.image_url else "")
                )

                with st.spinner(f"Generating '{doc_type}'..."):
                    result = generate_plain(st.session_state.superdocs_key, session_id, instruction)
                st.session_state.generated[doc_type] = result.get("document_changes", {}).get("updated_html", "")

            st.success("All 3 documents generated — see tabs below")

        if st.session_state.generated:
            doc_tabs = st.tabs([dt for dt in DOC_TYPES if dt in st.session_state.generated])
            for doc_type, doc_tab in zip([dt for dt in DOC_TYPES if dt in st.session_state.generated], doc_tabs):
                with doc_tab:
                    st.markdown(st.session_state.generated[doc_type], unsafe_allow_html=True)

with tab_review:
    st.subheader("Human review mode (experimental)")
    st.warning(
        "This is a separate, independent generation path from Tab 2 — it does NOT re-run or "
        "affect anything already generated there. Uses SuperDocs' approval flow. Found during "
        "testing to activate inconsistently (sometimes completes without pausing for review), "
        "and to sometimes propose placeholder content rather than real content even when it "
        "does activate. This tab shows the raw status at every step so any failure is visible, "
        "not silent."
    )

    if not st.session_state.pulled_text:
        st.info("Pull a design first (Tab 1).")
    else:
        review_doc_type = st.selectbox("Document type to generate with review", DOC_TYPES, key="review_doc_type_select")

        if st.button("Generate with review", type="primary"):
            st.session_state.review_debug_log = []
            st.session_state.review_pending_job_id = None
            st.session_state.review_pending_changes = None
            st.session_state.review_generated_html = None

            colors = st.session_state.pulled_colors
            session_id = f"canva-{design_id}-review-{review_doc_type.split()[0].lower()}-{uuid.uuid4().hex[:6]}"
            st.session_state.review_session_id = session_id
            st.session_state.review_debug_log.append(f"New session: {session_id}")

            if not st.session_state.image_url:
                with st.spinner("Uploading image..."):
                    st.session_state.image_url = upload_image(st.session_state.superdocs_key, st.session_state.pulled_image_path)
                st.session_state.review_debug_log.append(f"Image uploaded: {st.session_state.image_url}")

            seed_html = "\n".join(f"<p>{l}</p>" for l in st.session_state.pulled_text.split("\n") if l.strip())
            with st.spinner("Seeding document..."):
                seed_document(st.session_state.superdocs_key, session_id, seed_html)
            st.session_state.review_debug_log.append("Document seeded.")

            instruction = (
                f"This is the copy from a promotional flyer. Expand it into a full {review_doc_type.lower()}, "
                f"in an energetic tone matching the brand. Use {colors[0]} for all section headings. "
                f"Brand palette: {', '.join(colors)}. "
                + (f"Include this image: {st.session_state.image_url}" if st.session_state.image_url else "")
            )

            with st.spinner("Starting async job..."):
                job_id = generate_with_approval_start(st.session_state.superdocs_key, session_id, instruction)
            st.session_state.review_debug_log.append(f"generate_with_approval_start returned job_id: {job_id!r}")

            if not job_id:
                st.session_state.review_debug_log.append("FAILED: no job_id returned — the async call itself failed.")
            else:
                with st.spinner("Polling job status..."):
                    job_data = poll_job(st.session_state.superdocs_key, job_id)
                    st.session_state.review_debug_log.append(f"Poll: status={job_data.get('status')}")
                    poll_count = 0
                    while job_data.get("status") == "in_progress" and poll_count < 40:
                        time.sleep(3)
                        job_data = poll_job(st.session_state.superdocs_key, job_id)
                        poll_count += 1
                        st.session_state.review_debug_log.append(f"Poll #{poll_count}: status={job_data.get('status')}")

                final_status = job_data.get("status")
                st.session_state.review_debug_log.append(f"Final status reached: {final_status}")

                if final_status == "awaiting_approval":
                    st.session_state.review_pending_job_id = job_id
                    st.session_state.review_pending_changes = job_data.get("metadata", {}).get("pending_changes", [])
                    st.session_state.review_debug_log.append(f"{len(st.session_state.review_pending_changes)} pending change(s) found.")
                elif final_status == "completed":
                    st.session_state.review_generated_html = job_data.get("result", {}).get("document_changes", {}).get("updated_html", "")
                    st.session_state.review_debug_log.append("Job completed WITHOUT pausing for approval (known inconsistent-activation issue).")
                else:
                    st.session_state.review_debug_log.append(f"Unexpected terminal status: {final_status}")
                    st.session_state.review_debug_log.append(f"Full job data: {job_data}")

        with st.expander("Debug log (raw status at every step)", expanded=True):
            for line in st.session_state.review_debug_log:
                st.text(line)

        if st.session_state.review_pending_changes:
            st.subheader("Proposed changes — review each one")
            decisions = []
            for i, change in enumerate(st.session_state.review_pending_changes):
                with st.container(border=True):
                    st.write(change.get("ai_explanation", "(no explanation)"))
                    st.markdown("**Preview of proposed content:**")
                    st.markdown((change.get("new_html") or "(none)"), unsafe_allow_html=True)
                    approved = st.radio("Decision", ["Approve", "Reject"], key=f"review_decision_{i}", horizontal=True)
                    decisions.append({"change_id": change.get("change_id"), "approved": approved == "Approve"})

            if st.button("Submit review decisions"):
                result = submit_approval_decision(
                    st.session_state.superdocs_key, st.session_state.review_session_id,
                    st.session_state.review_pending_job_id, decisions,
                )
                st.session_state.review_debug_log.append(f"Submit result: {result}")
                final = poll_job(st.session_state.superdocs_key, st.session_state.review_pending_job_id)
                st.session_state.review_generated_html = final.get("result", {}).get("document_changes", {}).get("updated_html", "")
                st.session_state.review_pending_changes = None
                st.rerun()

        if st.session_state.review_generated_html:
            st.subheader("Final result")
            st.markdown(st.session_state.review_generated_html, unsafe_allow_html=True)

with tab_quality:
    if not st.session_state.generated:
        st.info("Generate documents first (Tab 2).")
    else:
        primary = st.session_state.pulled_colors[0]
        available_types = [dt for dt in DOC_TYPES if dt in st.session_state.generated]
        quality_tabs = st.tabs(available_types)
        
        for doc_type, q_tab in zip(available_types, quality_tabs):
            with q_tab:
                html = st.session_state.generated[doc_type]
                consistency = check_color_consistency(html, primary)
                duplicates = detect_duplicate_headings(html)

                col1, col2 = st.columns(2)
                col1.metric("On-brand headings", f"{consistency['on_brand_count']}/{consistency['total']}")
                col2.metric("Duplicate sections", len(duplicates))

                if duplicates:
                    st.warning("Duplicate sections found:")
                    for d in duplicates:
                        st.write(f"- \"{d['text']}\" appears {d['count']} times")

                passed = not consistency["off_brand"] and not duplicates
                if passed:
                    st.success("Quality gate passed")
                else:
                    st.error("Quality gate failed — review before exporting")

                st.divider()
                col1, col2, col3 = st.columns(3)
                session_id = st.session_state.sessions[doc_type]
                with col1:
                    if st.button(f"Export .docx", key=f"docx_{doc_type}"):
                        data = export_document(st.session_state.superdocs_key, session_id, "docx")
                        if data:
                            st.download_button("Download .docx", data, file_name=f"{doc_type}.docx", key=f"dl_docx_{doc_type}")
                with col2:
                    if st.button(f"Export .pdf", key=f"pdf_{doc_type}"):
                        data = export_document(st.session_state.superdocs_key, session_id, "pdf")
                        if data:
                            st.download_button("Download .pdf", data, file_name=f"{doc_type}.pdf", key=f"dl_pdf_{doc_type}")
                with col3:
                    st.download_button("Download .html", html, file_name=f"{doc_type}.html", key=f"dl_html_{doc_type}")

with tab_sync:
    st.subheader("Check for design updates")
    st.caption("Re-pulls the Canva design and pushes only the changed content, if anything changed.")
    st.info("Uses the same logic verified in sync_design.py. Run that script directly for now.")