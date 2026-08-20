import json
import re
import html as html_mod
import time
import requests
from urllib.parse import urlparse
from html.parser import HTMLParser

THREAD_RE = re.compile(r"^https?://(?:www\.)?doubao\.com/thread/([a-zA-Z0-9_-]+)", re.I)
TRAE_DOC_RE = re.compile(r"^https?://docs\.trae\.cn/[\w\-/]+", re.I)

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

_DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


def is_ai_conversation_link(url: str) -> bool:
    return bool(THREAD_RE.match(url.strip()) or TRAE_DOC_RE.match(url.strip()))


def get_link_type(url: str) -> str:
    """返回链接类型: 'doubao' 或 'trae_doc'"""
    url = url.strip()
    if THREAD_RE.match(url):
        return "doubao"
    if TRAE_DOC_RE.match(url):
        return "trae_doc"
    return ""


def _extract_text_from_content(content) -> str:
    try:
        blocks = json.loads(content)
    except Exception:
        return str(content).strip()
    out = []
    for b in blocks:
        c = b.get("content", "")
        try:
            cc = json.loads(c) if isinstance(c, str) else c
        except Exception:
            cc = c
        if isinstance(cc, dict):
            if isinstance(cc.get("text_block"), dict):
                out.append(cc["text_block"].get("text", ""))
            elif isinstance(cc.get("text"), str):
                out.append(cc["text"])
            else:
                for sub in cc.get("blocks", []):
                    sub_c = sub.get("content", "")
                    try:
                        sub_cc = json.loads(sub_c) if isinstance(sub_c, str) else sub_c
                    except Exception:
                        sub_cc = sub_c
                    if isinstance(sub_cc, dict):
                        if isinstance(sub_cc.get("text_block"), dict):
                            out.append(sub_cc["text_block"].get("text", ""))
                        elif isinstance(sub_cc.get("text"), str):
                            out.append(sub_cc["text"])
        elif isinstance(cc, str):
            out.append(cc)
    return "\n".join(t.strip() for t in out if t and t.strip())


class _HTMLToMarkdown(HTMLParser):
    """Simple HTML → Markdown converter for trae.cn documentation pages."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.current_tag = None
        self.current_attrs = {}
        self.in_skip = 0  # skip nested tags (script, style, nav, etc.)
        self.skip_tags = {"script", "style", "nav", "header", "footer", "aside", "iframe", "noscript"}
        self.list_stack = []  # stack of (type, index)
        self.table_header = False

    def handle_starttag(self, tag, attrs):
        self.current_tag = tag
        self.current_attrs = dict(attrs)

        if tag in self.skip_tags:
            self.in_skip += 1
            return

        if self.in_skip:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self.parts.append("\n\n" + "#" * level + " ")
        elif tag == "p":
            self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("  \n")
        elif tag == "strong" or tag == "b":
            self.parts.append("**")
        elif tag == "em" or tag == "i":
            self.parts.append("*")
        elif tag == "code":
            cls = self.current_attrs.get("class", "")
            if "language-" in cls or "hljs" in cls:
                self.parts.append("\n\n```")
                lang = re.search(r"language-(\w+)", cls)
                if lang:
                    self.parts.append(lang.group(1))
                self.parts.append("\n")
            else:
                self.parts.append("`")
        elif tag == "pre":
            self.parts.append("\n\n```\n")
        elif tag == "a":
            self.parts.append("[")
        elif tag == "img":
            alt = self.current_attrs.get("alt", "")
            src = self.current_attrs.get("src", "")
            if src and not src.startswith("data:"):
                self.parts.append(f"![{alt}]({src})")
        elif tag == "ul":
            self.list_stack.append(("ul", 0))
            self.parts.append("\n")
        elif tag == "ol":
            self.list_stack.append(("ol", 0))
            self.parts.append("\n")
        elif tag == "li":
            if self.list_stack:
                lst_type, idx = self.list_stack[-1]
                if lst_type == "ol":
                    idx += 1
                    self.list_stack[-1] = (lst_type, idx)
                    self.parts.append(f"{idx}. ")
                else:
                    self.parts.append("- ")
            else:
                self.parts.append("- ")
        elif tag == "blockquote":
            self.parts.append("\n\n> ")
        elif tag == "hr":
            self.parts.append("\n\n---\n\n")
        elif tag == "table":
            self.parts.append("\n\n")
        elif tag == "tr":
            self.parts.append("\n| ")
        elif tag == "th":
            self.table_header = True
            self.parts.append("**")
        elif tag == "td":
            self.parts.append("")
        elif tag == "div":
            cls = self.current_attrs.get("class", "")
            if "topic-table-container" in cls:
                self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.skip_tags:
            self.in_skip = max(0, self.in_skip - 1)
            return
        if self.in_skip:
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append("\n")
        elif tag == "p":
            self.parts.append("\n")
        elif tag == "strong" or tag == "b":
            self.parts.append("**")
        elif tag == "em" or tag == "i":
            self.parts.append("*")
        elif tag == "code":
            cls = self.current_attrs.get("class", "")
            if "language-" in cls or "hljs" in cls:
                self.parts.append("\n```\n")
            else:
                self.parts.append("`")
        elif tag == "pre":
            self.parts.append("\n```\n\n")
        elif tag == "a":
            href = self.current_attrs.get("href", "")
            self.parts.append(f"]({href})")
        elif tag == "ul" or tag == "ol":
            if self.list_stack:
                self.list_stack.pop()
            self.parts.append("\n")
        elif tag == "li":
            self.parts.append("\n")
        elif tag == "blockquote":
            self.parts.append("\n")
        elif tag == "th":
            self.parts.append("** | ")
        elif tag == "td":
            self.parts.append(" | ")
        elif tag == "tr":
            self.parts.append("\n")
        elif tag == "table":
            self.parts.append("\n")
        elif tag == "div":
            cls = self.current_attrs.get("class", "")
            if "topic-table-container" in cls:
                self.parts.append("\n")

    def handle_data(self, data):
        if self.in_skip:
            return
        text = data.strip()
        if text:
            # Collapse whitespace
            text = re.sub(r"\s+", " ", text)
            self.parts.append(text)

    def get_markdown(self) -> str:
        md = "".join(self.parts)
        # Clean up
        md = re.sub(r"\n{3,}", "\n\n", md)
        md = re.sub(r" {2,}", " ", md)
        md = re.sub(r"\n \n", "\n\n", md)
        md = re.sub(r"\n\s*\n\s*\n", "\n\n", md)
        return md.strip()


def _html_to_markdown(html_text: str) -> str:
    """Convert HTML string to Markdown."""
    converter = _HTMLToMarkdown()
    converter.feed(html_text)
    return converter.get_markdown()


def extract_trae_doc(url: str) -> dict | None:
    """Extract documentation content from docs.trae.cn and return as markdown."""
    if not TRAE_DOC_RE.match(url.strip()):
        return None

    raw = _fetch_page(url.strip())
    if not raw:
        print("[trae_doc] fetch failed")
        return None

    # Extract main content area
    content_html = _extract_trae_content(raw)
    if not content_html:
        print("[trae_doc] content extraction failed")
        return None

    md = _html_to_markdown(content_html)
    if not md or len(md) < 50:
        print("[trae_doc] markdown conversion produced little content")
        return None

    # Extract page title
    title = ""
    title_match = re.search(r'<h1[^>]*class="title-C1b1pA"[^>]*>(.*?)</h1>', raw, re.S)
    if title_match:
        title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
    if not title:
        title_match = re.search(r'<title[^>]*>(.*?)</title>', raw, re.S)
        if title_match:
            title = title_match.group(1).split("-")[0].strip()

    return {
        "type": "trae_doc",
        "title": title or "TRAE 文档",
        "markdown": md,
    }


def _extract_trae_content(raw: str) -> str | None:
    """Extract the main content HTML from a trae.cn documentation page."""
    # Extract only the topic-markdown div (main article content)
    # This contains the actual documentation content without navigation/sidebar
    match = re.search(
        r'<div[^>]*class="[^"]*topic-markdown[^"]*"[^>]*data-topic-doc-content[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*topic-rag-widget)',
        raw, re.S
    )
    if match:
        content = match.group(1).strip()
        if len(content) > 100:
            # Clean up: remove table container divs but keep their content
            content = re.sub(r'<div[^>]*class="[^"]*topic-table-container[^"]*"[^>]*>', '', content)
            content = re.sub(r'<div[^>]*class="[^"]*topic-table-fixed[^"]*"[^>]*>', '', content)
            return content

    # Fallback: try to find topic-markdown by itself
    match = re.search(
        r'<div[^>]*class="[^"]*topic-markdown[^"]*"[^>]*>(.*?)</div>\s*<div',
        raw, re.S
    )
    if match:
        content = match.group(1).strip()
        if len(content) > 100:
            return content

    # Fallback 2: extract the whole doc container
    match = re.search(
        r'data-topic-doc="true"[^>]*>(.*?)</div>\s*</div>\s*<div[^>]*class="[^"]*resizeHandle',
        raw, re.S
    )
    if match:
        return match.group(1)

    # Last fallback: body content
    body_match = re.search(r'<body[^>]*>(.*?)</body>', raw, re.S)
    if body_match:
        return body_match.group(1)

    return None


def extract_thread(url: str) -> dict | None:
    url = url.strip()

    # Dispatch based on URL type
    if TRAE_DOC_RE.match(url):
        return extract_trae_doc(url)

    if not THREAD_RE.match(url):
        return None

    raw = _fetch_page(url.strip())
    if not raw:
        print("[link_extractor] fetch failed")
        return None

    payload = _parse_payload(raw)
    if not payload:
        print("[link_extractor] parse failed - no payload found")
        return None

    share = payload.get("share_info", {})
    messages = []
    for msg in payload.get("message_snapshot", {}).get("message_list", []):
        role = "assistant" if msg.get("user_type") == 2 else "user"
        text = _extract_text_from_content(msg.get("content", ""))
        if not text:
            continue
        messages.append({"role": role, "text": text})

    if not messages:
        print("[link_extractor] no messages found in payload")
        return None

    return {
        "title": share.get("share_name", ""),
        "nick_name": share.get("user", {}).get("nick_name", ""),
        "create_time": share.get("share_time"),
        "messages": messages,
    }


def _parse_payload(raw: str) -> dict | None:
    """Try all known parsing strategies on the fetched HTML."""
    # Strategy 1: Old format - data-fn-args with isWebCollectionShareId
    payload = _parse_old_format(raw)
    if payload:
        return payload

    # Strategy 2: New format - HTML-entity-escaped JSON
    payload = _parse_new_format(raw)
    if payload:
        return payload

    # Strategy 3: Try unescaped JSON directly
    payload = _parse_direct_format(raw)
    if payload:
        return payload

    return None


def _parse_old_format(raw: str):
    idx = raw.find("isWebCollectionShareId")
    if idx < 0:
        return None
    search_start = max(0, idx - 2000)
    chunk = raw[search_start:idx + 500000]
    un = html_mod.unescape(chunk)
    uidx = un.find("isWebCollectionShareId")
    if uidx < 0:
        return None
    di = un.rfind('"data":', 0, uidx)
    if di < 0:
        di = un.rfind('"data":', max(0, uidx - 100), uidx)
    if di < 0:
        return None
    brace = un.find('{', di)
    if brace < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(un, brace)
        return obj
    except Exception:
        return None


def _parse_new_format(raw: str):
    try:
        un = html_mod.unescape(raw)
    except Exception:
        return None
    idx = un.find("isWebCollectionShareId")
    if idx < 0:
        return None
    start = un.find('"data":{', idx - 50)
    if start < 0:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(un, start + 7)
        return obj
    except Exception:
        return None


def _parse_direct_format(raw: str):
    """Parse direct JSON (unescaped) from the page."""
    for marker in ['"data":{', '"data": {']:
        idx = raw.find(marker)
        if idx < 0:
            continue
        # Look for isWebCollectionShareId after this position
        rest = raw[idx:idx + 1000000]
        if "isWebCollectionShareId" not in rest:
            continue
        try:
            obj, _ = json.JSONDecoder().raw_decode(raw, idx + marker.find('{'))
            if "isWebCollectionShareId" in json.dumps(obj):
                return obj
        except Exception:
            continue
    return None


def _fetch_page(url: str, max_bytes: int = 5_000_000, max_attempts: int = 3) -> str | None:
    """Fetch URL with requests.Session for connection reuse and retry logic."""
    session = requests.Session()
    parsed = urlparse(url)
    referer = f"{parsed.scheme}://{parsed.netloc}/"

    for attempt in range(max_attempts):
        try:
            ua = _USER_AGENTS[attempt % len(_USER_AGENTS)]
            headers = dict(_DEFAULT_HEADERS)
            headers["User-Agent"] = ua
            headers["Referer"] = referer
            headers["Origin"] = parsed.netloc

            resp = session.get(
                url,
                headers=headers,
                timeout=(10, 30),  # (connect_timeout, read_timeout)
                allow_redirects=True,
                stream=True,
            )

            if resp.status_code == 429:
                # Rate limited - wait and retry with different UA
                wait = 2 ** attempt  # exponential backoff: 1, 2, 4 seconds
                print(f"[link_extractor] rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue

            if resp.status_code != 200:
                print(f"[link_extractor] HTTP {resp.status_code} on attempt {attempt + 1}")
                if attempt < max_attempts - 1:
                    time.sleep(1)
                continue

            # Read content with size limit
            content = b""
            for chunk in resp.iter_content(chunk_size=65536):
                content += chunk
                if len(content) >= max_bytes:
                    break

            if not content:
                continue

            text = content.decode("utf-8", errors="replace")

            # Check if we got useful data
            if "isWebCollectionShareId" in text or "data-fn-args" in text:
                print(f"[link_extractor] fetched {len(text)} bytes, found markers")
                return text

            # Check for trae.cn documentation page
            if "docs.trae.cn" in text and ("topic-markdown" in text or "data-topic-doc" in text):
                print(f"[link_extractor] fetched {len(text)} bytes trae doc page")
                return text

            # Sometimes the page loads data dynamically; check for page structure
            if "<html" in text.lower() and ("doubao" in text.lower() or "thread" in text.lower()):
                # Valid page but data may be in different format
                if len(text) > 50000:
                    print(f"[link_extractor] fetched {len(text)} bytes HTML but no data markers")
                    return text  # Return anyway, parser might find it

            # For trae.cn, return even if no markers found (page is SSR)
            if "<html" in text.lower() and "trae" in text.lower() and len(text) > 50000:
                print(f"[link_extractor] fetched {len(text)} bytes trae page (no markers)")
                return text

            # Try next attempt
            if attempt < max_attempts - 1:
                time.sleep(0.5)

        except requests.exceptions.Timeout:
            print(f"[link_extractor] timeout on attempt {attempt + 1}")
            if attempt < max_attempts - 1:
                time.sleep(1)

        except requests.exceptions.RequestException as e:
            print(f"[link_extractor] request error on attempt {attempt + 1}: {e}")
            if attempt < max_attempts - 1:
                time.sleep(1)

        except Exception as e:
            print(f"[link_extractor] unexpected error: {e}")
            break

    return None
