"""
canva_pipeline.py — reusable Canva-side functions for the Streamlit
app. Wraps the same export/download/extract logic already verified
working in download_design_assets.py, as real functions instead of a
top-to-bottom script, so the UI can call them on button clicks.
"""
import time
from pathlib import Path

import requests

CANVA_API_BASE = "https://api.canva.com/rest/v1"
PRINT_WIDTH_PX = 2480
PRINT_HEIGHT_PX = 3508


def list_designs(access_token: str) -> list:
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{CANVA_API_BASE}/designs", headers=headers)
    if response.status_code != 200:
        return []
    return response.json().get("items", [])


def create_export(access_token: str, design_id: str, format_type: str, extra: dict = None) -> str:
    headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    body = {"design_id": design_id, "format": {"type": format_type, **(extra or {})}}
    response = requests.post(f"{CANVA_API_BASE}/exports", headers=headers, json=body)
    data = response.json()
    job = data.get("job", {})
    return job.get("id")


def poll_export(access_token: str, export_id: str, max_attempts: int = 30) -> list:
    headers = {"Authorization": f"Bearer {access_token}"}
    for _ in range(max_attempts):
        response = requests.get(f"{CANVA_API_BASE}/exports/{export_id}", headers=headers)
        data = response.json()
        status = data.get("job", {}).get("status")
        if status == "success":
            return data["job"]["urls"]
        if status == "failed":
            return []
        time.sleep(2)
    return []


def pull_design_assets(access_token: str, design_id: str, output_dir: Path) -> dict:
    """Pulls both PDF (text/layout) and print-resolution PNG (visual
    palette + embeddable image). Returns paths, or None for any asset
    that failed - caller decides how to handle a partial result."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = {"pdf_path": None, "png_path": None}

    pdf_job = create_export(access_token, design_id, "pdf")
    if pdf_job:
        pdf_urls = poll_export(access_token, pdf_job)
        if pdf_urls:
            pdf_path = output_dir / "page_1.pdf"
            pdf_path.write_bytes(requests.get(pdf_urls[0]).content)
            result["pdf_path"] = pdf_path

    png_job = create_export(access_token, design_id, "png", {"width": PRINT_WIDTH_PX, "height": PRINT_HEIGHT_PX})
    if png_job:
        png_urls = poll_export(access_token, png_job)
        if png_urls:
            png_path = output_dir / "page_1.png"
            png_path.write_bytes(requests.get(png_urls[0]).content)
            result["png_path"] = png_path

    return result

def get_user_info(access_token: str) -> dict:
    """GET /v1/users/me — returns user_id and team_id, no special
    scope required. Used to show which Canva account is connected."""
    headers = {"Authorization": f"Bearer {access_token}"}
    response = requests.get(f"{CANVA_API_BASE}/users/me", headers=headers)
    if response.status_code != 200:
        return {}
    data = response.json()
    team_user = data.get("team_user", {})
    return {"user_id": team_user.get("user_id"), "team_id": team_user.get("team_id")}