import json
import re
import html as html_mod
import time
import requests
from urllib.parse import urlparse

# 支持的 AI 对话链接白名单（正则列表）
AI_LINK_PATTERNS = [
    # 豆包对话链接
    re.compile(r"^https?://(?:www\.)?doubao\.com/thread/([a-zA-Z0-9_-]+)", re.I),
    # Trae 分享链接
    re.compile(r"^https?://(?:share\.)?traecontent\.cn/share/([a-zA-Z0-9_.=-]+)", re.I),
]

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
    for pat in AI_LINK_PATTERNS:
        if pat.match(url.strip()):
            return True
    return False


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


def extract_thread(url: str) -> dict | None:
    if not is_ai_conversation_link(url):
        return None

    raw = _fetch_page(url.strip())
    if not raw:
        print("[link_extractor] fetch failed")
        return None

    payload = _parse_payload(raw)
    if not payload:
        print("[link_extractor] parse failed - no payload found")
        return None

    # Try to extract messages using multiple strategies
    messages = _extract_messages(payload)
    if not messages:
        print("[link_extractor] no messages found in payload")
        return None

    # Try to extract metadata
    meta = _extract_metadata(payload)

    return {
        "title": meta.get("title", ""),
        "nick_name": meta.get("nick_name", ""),
        "create_time": meta.get("create_time"),
        "messages": messages,
    }


def _extract_messages(payload: dict) -> list[dict]:
    """Extract messages from various payload formats."""
    messages = []

    # Strategy A: doubao format (message_snapshot.message_list)
    msg_list = payload.get("message_snapshot", {}).get("message_list", [])
    if not msg_list:
        # Try alternative paths
        for key_path in [
            ("message_snapshot", "message_list"),
            ("messageList",),
            ("messages",),
            ("chat_history", "messages"),
            ("chatHistory", "messages"),
            ("conversation", "messages"),
            ("conversation", "message_list"),
            ("data", "message_list"),
            ("data", "messages"),
        ]:
            obj = payload
            found = True
            for key in key_path:
                if isinstance(obj, dict) and key in obj:
                    obj = obj[key]
                else:
                    found = False
                    break
            if found and isinstance(obj, list) and len(obj) > 0:
                msg_list = obj
                break

    for msg in msg_list:
        if not isinstance(msg, dict):
            continue
        role = _determine_role(msg)
        text = _extract_msg_text(msg)
        if text:
            messages.append({"role": role, "text": text})

    return messages


def _determine_role(msg: dict) -> str:
    """Determine if a message is from user or assistant."""
    # doubao format
    if msg.get("user_type") == 2 or msg.get("userType") == 2:
        return "assistant"
    # trae format
    role_val = msg.get("role", "")
    if isinstance(role_val, str):
        r = role_val.lower()
        if "assistant" in r or "bot" in r or "ai" in r:
            return "assistant"
        if "user" in r or "human" in r:
            return "user"
    if msg.get("is_assistant") or msg.get("isAssistant"):
        return "assistant"
    if msg.get("from") in ("assistant", "bot", "ai"):
        return "assistant"
    if msg.get("from") in ("user", "human"):
        return "user"
    # heuristic: has 'text' key and is not empty -> likely user
    return "assistant" if msg.get("type") in ("assistant", "bot", "ai") else "user"


def _extract_msg_text(msg: dict) -> str:
    """Extract text from a message object."""
    # Try common text keys
    for key in ["text", "content", "message", "msg", "answer", "question"]:
        val = msg.get(key)
        if not val:
            continue
        if isinstance(val, str) and val.strip():
            return val.strip()
        if isinstance(val, list):
            # List of content blocks
            parts = []
            for item in val:
                if isinstance(item, dict):
                    t = item.get("text", "") or item.get("content", "")
                    if t:
                        parts.append(str(t))
                elif isinstance(item, str):
                    parts.append(item)
            if parts:
                return "\n".join(parts).strip()
        if isinstance(val, dict):
            # Nested content structure
            text = _extract_text_from_content(val)
            if text:
                return text

    # Try content blocks
    blocks = msg.get("blocks", []) or msg.get("content_blocks", [])
    if blocks:
        parts = []
        for block in blocks:
            if isinstance(block, dict):
                for bk in ["text", "content"]:
                    if block.get(bk):
                        parts.append(str(block[bk]))
                        break
        if parts:
            return "\n".join(parts).strip()

    return ""


def _extract_metadata(payload: dict) -> dict:
    """Extract metadata (title, nick_name, create_time) from payload."""
    title = ""
    nick_name = ""
    create_time = None

    # Try direct access
    share = payload.get("share_info", {}) or payload.get("shareInfo", {})
    if share:
        title = share.get("share_name", "") or share.get("shareName", "") or ""
        user_info = share.get("user", {}) or share.get("userInfo", {})
        if isinstance(user_info, dict):
            nick_name = user_info.get("nick_name", "") or user_info.get("nickName", "") or user_info.get("name", "") or ""
        create_time = share.get("share_time") or share.get("shareTime")

    # Fallback: look in data sub-object
    if not title:
        data = payload.get("data", {})
        if isinstance(data, dict):
            if not share:
                share = data.get("share_info", {}) or data.get("shareInfo", {})
                if share:
                    title = share.get("share_name", "") or share.get("shareName", "") or ""
                    user_info = share.get("user", {}) or share.get("userInfo", {})
                    if isinstance(user_info, dict):
                        nick_name = user_info.get("nick_name", "") or user_info.get("nickName", "") or user_info.get("name", "") or ""
                    create_time = share.get("share_time") or share.get("shareTime")

    # Global fallback
    if not title:
        title = payload.get("title", "") or payload.get("share_name", "") or ""
    if not nick_name:
        nick_name = payload.get("nick_name", "") or payload.get("nickName", "") or ""

    return {"title": title, "nick_name": nick_name, "create_time": create_time}


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

    # Strategy 4: Trae share format
    payload = _parse_trae_format(raw)
    if payload:
        return payload

    # Strategy 5: Generic JSON search fallback
    payload = _parse_generic_format(raw)
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


def _parse_trae_format(raw: str):
    """Parse Trae share page format."""
    # Trae share pages may contain __NEXT_DATA__ or similar JSON blobs
    # Look for message-related keys in embedded JSON
    search_keys = ["message_list", "messageList", "messages", "chat_history",
                    "chatHistory", "conversation", "share_info", "shareInfo"]
    
    for key in search_keys:
        for marker in [f'"{key}":', f'"{key}": {{', f'"{key}":[']:
            idx = raw.find(marker)
            if idx < 0:
                continue
            # Walk backward to find the enclosing JSON object
            obj_start = raw.rfind('{', 0, idx)
            if obj_start < 0:
                continue
            try:
                obj, _ = json.JSONDecoder().raw_decode(raw, obj_start)
                # Validate: must have at least some message-like content
                obj_str = json.dumps(obj)
                if any(k in obj_str for k in search_keys) and len(obj_str) > 100:
                    return obj
            except Exception:
                pass
    return None


def _parse_generic_format(raw: str):
    """Generic fallback: find any JSON blob with message-like structure."""
    # Unescape HTML entities first
    try:
        un = html_mod.unescape(raw)
    except Exception:
        un = raw

    # Look for large JSON blocks containing message/text patterns
    patterns = [
        # Try window.__DATA__ or window.__NEXT_DATA__ style
        r'window\.__[A-Z_]*DATA__\s*=\s*',
        # Try script type="application/json"
        r'<script[^>]*type="application/json"[^>]*>(.*?)</script>',
        # Try data-* attributes
        r'data-json="([^"]+)"',
    ]
    
    for pat in patterns:
        matches = list(re.finditer(pat, un, re.I | re.S))
        for m in matches:
            try:
                if m.groups():
                    json_str = m.group(1)
                else:
                    json_str = un[m.end():m.end()+500000]
                    # Find the start of JSON
                    brace_pos = json_str.find('{')
                    if brace_pos < 0:
                        continue
                    json_str = json_str[brace_pos:]
                
                obj = json.loads(json_str)
                obj_str = json.dumps(obj)
                # Check if it looks like a message/conversation payload
                if any(k in obj_str.lower() for k in ['message', 'content', 'text', 'role', 'user', 'assistant']):
                    return obj
            except Exception:
                continue
    
    # Last resort: try to extract from <meta> or <title> tags and build
    # a minimal payload from visible text
    title_match = re.search(r'<title[^>]*>([^<]+)</title>', un, re.I)
    if title_match:
        title = html_mod.unescape(title_match.group(1)).strip()
        # Try to extract paragraph text
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', un, re.I | re.S)
        text_parts = []
        for p in paragraphs[:50]:
            clean = re.sub(r'<[^>]+>', '', p)
            clean = html_mod.unescape(clean).strip()
            if clean and len(clean) > 5:
                text_parts.append(clean)
        
        if text_parts or title:
            # Build a synthetic payload
            messages = []
            if text_parts:
                # Split into messages by user/assistant patterns
                full_text = '\n\n'.join(text_parts)
                messages.append({"role": "user", "text": title or "分享内容"})
                messages.append({"role": "assistant", "text": full_text})
            
            return {
                "share_info": {"share_name": title, "user": {"nick_name": ""}},
                "message_snapshot": {"message_list": []},
                "messages": messages,
                "_synthetic": True,
            }
    
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

            # Sometimes the page loads data dynamically; check for page structure
            domain_lower = parsed.netloc.lower()
            if "<html" in text.lower() and any(k in text.lower() or k in domain_lower for k in ("doubao", "thread", "traecontent", "trae")):
                # Valid page but data may be in different format
                if len(text) > 50000:
                    print(f"[link_extractor] fetched {len(text)} bytes HTML but no data markers")
                    return text  # Return anyway, parser might find it

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
