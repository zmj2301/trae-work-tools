from flask import Flask, request, jsonify, send_file, render_template
import os
import uuid
import tempfile
from datetime import datetime
from converter.pipeline import convert_to_docx, convert_to_pdf
from config import OUTPUT_DIR

app = Flask(__name__)

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/convert/docx", methods=["POST"])
def convert_docx():
    md_content = request.form.get("content", "")
    if not md_content and "file" in request.files:
        f = request.files["file"]
        md_content = f.read().decode("utf-8", errors="replace")
    if not md_content.strip():
        return jsonify({"error": "No content"}), 400
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}.docx"
    path = convert_to_docx(md_content, filename)
    return send_file(path, as_attachment=True, download_name=filename)


@app.route("/convert/pdf", methods=["POST"])
def convert_pdf():
    md_content = request.form.get("content", "")
    if not md_content and "file" in request.files:
        f = request.files["file"]
        md_content = f.read().decode("utf-8", errors="replace")
    if not md_content.strip():
        return jsonify({"error": "No content"}), 400
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{ts}.pdf"
    path = convert_to_pdf(md_content, filename)
    if path is None:
        return jsonify({"error": "PDF conversion not available"}), 501
    return send_file(path, as_attachment=True, download_name=filename)


@app.route("/extract/link", methods=["POST"])
def extract_link():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"error": "No URL"}), 400
    from converter.link_extractor import is_ai_conversation_link, extract_thread
    if not is_ai_conversation_link(url):
        return jsonify({"error": "Not an AI conversation link", "ai_link": False}), 422
    try:
        result = extract_thread(url)
    except Exception as e:
        return jsonify({"error": f"Extract failed: {e}"}), 502
    if result is None:
        return jsonify({"error": "抓取超时或页面无数据，请稍后重试", "ai_link": True}), 502
    return jsonify({"ai_link": True, **result})


@app.route("/preview", methods=["POST"])
def preview():
    md_content = request.form.get("content", "")
    if not md_content:
        return jsonify({"html": ""})
    import markdown_it
    mdi = markdown_it.MarkdownIt("gfm-like", {"linkify": False})
    html = mdi.render(md_content)
    return jsonify({"html": html})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=True, port=port)
