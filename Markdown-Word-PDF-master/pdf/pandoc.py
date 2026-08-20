import io
import re
import base64
import os
from markdown_it import MarkdownIt
from xhtml2pdf import pisa
from xhtml2pdf.default import DEFAULT_FONT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.pdfmetrics import registerFontFamily
from pdf.backend import PdfBackend
from converter.math_converter import BLOCK_MATH_RE, INLINE_MATH_RE
from converter.formula_renderer import render_formula_bytes

_md = MarkdownIt("gfm-like", {"linkify": False})

_FONT_REGISTERED = False


def _get_font_dirs():
    """返回字体搜索路径列表：项目内 fonts/ 优先，系统字体回退。"""
    # 项目根目录：pdf/pandoc.py → 上两级
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    project_fonts = os.path.join(project_root, "fonts")

    dirs = []

    # 1. 项目内 fonts/ 目录（随项目迁移，零配置）
    if os.path.isdir(project_fonts):
        dirs.append(project_fonts)

    # 2. 系统字体目录（回退，兼容 Windows / Linux / macOS）
    if os.name == "nt":
        dirs.append(os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts"))
        dirs.append(r"C:\Windows\Fonts")
    elif os.name == "posix":
        dirs.extend([
            "/usr/share/fonts/truetype/wqy",
            "/usr/share/fonts/truetype/arphic",
            "/usr/share/fonts/opentype/noto",
            "/System/Library/Fonts/PingFang.ttc",
            "/System/Library/Fonts/STHeiti Medium.ttc",
        ])

    return dirs


def _register_fonts():
    global _FONT_REGISTERED
    if _FONT_REGISTERED:
        return

    font_dirs = _get_font_dirs()
    print(f"[xhtml2pdf] Font search dirs: {font_dirs}")

    # YaHei family (modern Chinese, with bold)
    _try_register(font_dirs, "YaHei", "msyh.ttc")
    _try_register(font_dirs, "YaHeiBold", "msyhbd.ttc")
    if "YaHei" in pdfmetrics.getRegisteredFontNames():
        registerFontFamily("YaHei", normal="YaHei", bold="YaHeiBold",
                          italic="YaHei", boldItalic="YaHeiBold")
        DEFAULT_FONT["yahei"] = "YaHei"
        DEFAULT_FONT["yahei bold"] = "YaHeiBold"
        print("[xhtml2pdf] YaHei font family registered")

    # SimHei (for headings)
    _try_register(font_dirs, "SimHei", "simhei.ttf")
    if "SimHei" in pdfmetrics.getRegisteredFontNames():
        registerFontFamily("SimHei", normal="SimHei", bold="SimHei",
                           italic="SimHei", boldItalic="SimHei")
        DEFAULT_FONT["simhei"] = "SimHei"
        print("[xhtml2pdf] SimHei font family registered")

    # SimSun (fallback)
    _try_register(font_dirs, "SimSun", "simsun.ttc")
    if "SimSun" in pdfmetrics.getRegisteredFontNames():
        registerFontFamily("SimSun", normal="SimSun", bold="SimSun",
                           italic="SimSun", boldItalic="SimSun")
        DEFAULT_FONT["simsun"] = "SimSun"
        print("[xhtml2pdf] SimSun font family registered")

    _FONT_REGISTERED = True


def _try_register(font_dirs, name, filename):
    for d in font_dirs:
        path = os.path.join(d, filename)
        if os.path.exists(path):
            try:
                if name not in pdfmetrics.getRegisteredFontNames():
                    pdfmetrics.registerFont(TTFont(name, path))
                return True
            except Exception:
                pass
    return False


_CSS_STYLE = """
@page { margin: 2cm; size: A4; }
body { font-family: YaHei; font-size: 12pt; line-height: 1.8; color: #333; }
h1 { font-family: SimHei; font-size: 22pt; margin: 18pt 0 12pt; color: #1a1a1a; }
h2 { font-family: SimHei; font-size: 18pt; margin: 16pt 0 10pt; color: #1a1a1a; }
h3 { font-family: SimHei; font-size: 15pt; margin: 14pt 0 8pt; color: #1a1a1a; }
h4 { font-family: SimHei; font-size: 13pt; margin: 12pt 0 6pt; }
p { margin: 6pt 0; text-align: justify; }
ul, ol { margin: 6pt 0; padding-left: 24pt; }
li { margin: 3pt 0; }
blockquote { border-left: 3px solid #ddd; padding: 4pt 12pt; color: #666; margin: 8pt 0; background: #fafafa; }
code { font-family: YaHei, monospace; background: #f4f4f4; padding: 1pt 4pt; border-radius: 2px; font-size: 11pt; }
pre { font-family: YaHei, monospace; background: #f4f4f4; padding: 10pt; border: 1px solid #ddd; border-radius: 3px; font-size: 10pt; white-space: pre-wrap; word-wrap: break-word; }
pre code { background: none; padding: 0; font-size: 10pt; }
table { border-collapse: collapse; width: 100%; margin: 10pt 0; }
th { border: 1px solid #999; padding: 6pt 8pt; background: #eee; font-weight: bold; }
td { border: 1px solid #999; padding: 5pt 8pt; }
img { max-width: 100%; }
a { color: #1a73e8; text-decoration: underline; }
hr { border: none; border-top: 1px solid #ccc; margin: 16pt 0; }
strong { font-weight: bold; }
em { font-style: italic; }
"""


def _math_to_img(latex, display=False):
    png_bytes = render_formula_bytes(latex, display=display)
    if png_bytes:
        b64 = base64.b64encode(png_bytes).decode("ascii")
        style = "display:block;margin:0.5em auto" if display else "vertical-align:middle"
        return f'<img src="data:image/png;base64,{b64}" style="{style}"/>'
    return None


class PandocBackend(PdfBackend):
    """Pure-Python PDF backend using xhtml2pdf. No external tools required."""

    def convert(self, docx_path: str, md_content: str | None = None) -> bytes | None:
        try:
            if not md_content:
                return None

            _register_fonts()

            def _replace_block(m):
                img = _math_to_img(m.group(1).strip(), display=True)
                return img or m.group(0)

            def _replace_inline(m):
                img = _math_to_img(m.group(1).strip(), display=False)
                return img or m.group(0)

            processed = BLOCK_MATH_RE.sub(_replace_block, md_content)
            processed = INLINE_MATH_RE.sub(_replace_inline, processed)
            html_body = _md.render(processed)

            full_html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><style>{_CSS_STYLE}</style></head>
<body>{html_body}</body></html>"""

            result = io.BytesIO()
            pisa.CreatePDF(io.StringIO(full_html), dest=result, encoding="utf-8")
            return result.getvalue()
        except Exception as e:
            print(f"[xhtml2pdf] convert error: {e}")
            import traceback
            traceback.print_exc()
            return None
