import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
UPLOAD_DIR = os.path.join(DATA_DIR, "uploads")
ASSETS_DIR = os.path.join(DATA_DIR, "assets")
OUTPUT_DIR = os.path.join(DATA_DIR, "output")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(ASSETS_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

BODY_FONT = "宋体"
HEADING_FONT = "黑体"
BODY_SIZE_PT = 12

PDF_BACKEND = "xhtml2pdf"
PDF_API_URL = ""
PDF_API_KEY = ""

MERMAID_CACHE = True
