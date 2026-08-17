"""
get_design_detail.py — pulls full metadata for one specific design,
so we can see its actual structure before requesting an export.
"""
from dotenv import load_dotenv
load_dotenv()

import os
import json
import requests

ACCESS_TOKEN = os.environ["CANVA_ACCESS_TOKEN"]
DESIGN_ID = "DAHSiXKMgD4"  # Flyer - ROOTED — Cold Brew

response = requests.get(
    f"https://api.canva.com/rest/v1/designs/{DESIGN_ID}",
    headers={"Authorization": f"Bearer {ACCESS_TOKEN}"},
)

print(f"Status code: {response.status_code}")
print(json.dumps(response.json(), indent=2))