import json
import re
import html as html_mod
import time
import requests
from urllib.parse import urlparse

# 可选的 Playwright 支持（用于渲染 SPA 页面）
try:
    from playwright.sync_api import sync_playwright
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

# 支持的 AI 对话链接白名单（正则列表）
AI_LINK_PATTERNS = [
    # 豆包对话链接
    re.compile(r"^https?://(?:www\.)?doubao\.com/thread/([a-zA-Z0-9_-]+)", re.I),
    # Trae 分享链接
    re.compile(r"^https?://(?:www\.|share\.)?traecontent\.cn/share/([a-zA-Z0-9_.=-]+)", re.I),
    # opncd.ai 分享链接
    re.compile(r"^https?://(?:www\.)?opncd\.ai/share/([a-zA-Z0-9_.=-]+)", re.I),
    # 通义千问分享链接
    re.compile(r"^https?://(?:www\.)?qianwen\.my\.cn/share/chat/([a-zA-Z0-9_.=-]+)", re.I),
    # TraeWork / work.trae.cn 分享链接
    re.compile(r"^https?://(?:www\.)?work\.trae\.cn/share/([a-zA-Z0-9_.=-]+)", re.I),
    re.compile(r"^https?://(?:www\.)?trae\.com\.cn/share/([a-zA-Z0-9_.=-]+)", re.I),
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

    url = url.strip()
    
    # Check link types
    is_trae = bool(re.search(r'traecontent\.cn|work\.trae\.cn|trae\.com\.cn|trae\.cn', url, re.I))
    is_qianwen = bool(re.search(r'qianwen\.my\.cn', url, re.I))
    
    # Step 0: For Trae links, use official API-based extraction directly
    if is_trae:
        print("[link_extractor] Trae link - using API extraction...")
        trae_result = _extract_trae_via_api(url)
        if trae_result and trae_result.get("messages"):
            return trae_result
        print("[link_extractor] Trae API extraction failed, trying HTML/Playwright...")
    
    # Step 1: For qianwen links, use API-based extraction directly
    if is_qianwen:
        print("[link_extractor] Qianwen link - using API extraction...")
        qw_result = _extract_qianwen_via_api(url)
        if qw_result and qw_result.get("messages"):
            return qw_result
        print("[link_extractor] Qianwen API extraction failed, trying HTML parsing...")
    
    # Step 2: Try standard HTTP fetch
    raw = _fetch_page(url)
    payload = None
    
    if raw:
        payload = _parse_payload(raw)
    
    # Step 3: If Trae and standard parsing still failed, try Playwright
    if is_trae and (not raw or not payload or not _extract_messages(payload)):
        print("[link_extractor] Trae link - trying Playwright renderer...")
        pw_result = _extract_trae_via_playwright(url)
        if pw_result and pw_result.get("messages"):
            return pw_result
        print("[link_extractor] Playwright also failed for Trae link")
    
    if not raw:
        print("[link_extractor] fetch failed")
        return None

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


def _extract_qianwen_via_api(url: str) -> dict | None:
    """Extract Qianwen (通义千问) share content via official API."""
    # Extract share ID from URL
    match = re.search(r'/share/chat/([a-zA-Z0-9_.=-]+)', url, re.I)
    if not match:
        print("[link_extractor] qianwen: could not extract share_id from URL")
        return None
    
    share_id = match.group(1)
    
    api_base = "https://chat2-api.qianwen.com"
    headers = {
        "User-Agent": _USER_AGENTS[0],
        "Accept": "application/json",
        "Content-Type": "application/json",
        "Origin": "https://qianwen.my.cn",
        "Referer": "https://qianwen.my.cn/",
    }
    
    try:
        resp = requests.post(
            f"{api_base}/api/v1/share/info?pr=qwen&fr=mac",
            headers=headers,
            json={"share_id": share_id},
            timeout=(10, 30),
        )
        
        if resp.status_code != 200:
            print(f"[link_extractor] qianwen API: HTTP {resp.status_code}")
            return None
        
        data = resp.json()
        
        if data.get("code") != 0:
            print(f"[link_extractor] qianwen API error: {data.get('msg')}")
            return None
        
        payload = data.get("data", {})
        title = payload.get("title", "")
        
        # Extract messages from session.record_list
        session = payload.get("session", {})
        record_list = session.get("record_list", [])
        
        messages = []
        for record in record_list:
            # User messages from request_messages
            for req in record.get("request_messages", []):
                content = req.get("content", "")
                if content and isinstance(content, str) and content.strip():
                    messages.append({"role": "user", "text": content.strip()})
            
            # Assistant messages from response_messages (filter non-content types)
            for resp_msg in record.get("response_messages", []):
                mime = resp_msg.get("mime_type", "")
                content = resp_msg.get("content", "")
                
                # Skip signal/progress messages, keep actual content
                if mime in ("signal/post", "bar/progress"):
                    continue
                
                if content and isinstance(content, str) and content.strip():
                    messages.append({"role": "assistant", "text": content.strip()})
        
        if not messages:
            print("[link_extractor] qianwen: no messages in API response")
            return None
        
        # Get create_time from session
        create_time = session.get("create_time")
        
        print(f"[link_extractor] qianwen: extracted {len(messages)} messages, title='{title}'")
        
        return {
            "title": title,
            "nick_name": "",
            "create_time": create_time,
            "messages": messages,
        }
        
    except Exception as e:
        print(f"[link_extractor] qianwen API error: {e}")
        return None


def _extract_trae_via_api(url: str) -> dict | None:
    """Extract Trae share content via official API.
    
    Trae exposes two REST endpoints:
      GET /api/remote/v1/share/{id}
      GET /api/remote/v1/share/{id}/messages?page_size=100
    
    This method is much faster and more reliable than Playwright rendering.
    """
    # Extract share ID from URL
    match = re.search(r'/share/([a-zA-Z0-9_.=-]+)', url, re.I)
    if not match:
        print("[link_extractor] trae: could not extract share_id from URL")
        return None
    
    share_id = match.group(1)
    
    # Build API base URL - use the share domain from the URL
    parsed = urlparse(url)
    api_base = f"{parsed.scheme}://{parsed.netloc}"
    
    headers = {
        "User-Agent": _USER_AGENTS[0],
        "Accept": "application/json",
        "Origin": api_base,
        "Referer": url,
    }
    
    # Step 1: Get share metadata (title, creator, etc.)
    print(f"[link_extractor] trae: fetching share metadata...")
    try:
        resp = requests.get(
            f"{api_base}/api/remote/v1/share/{share_id}",
            headers=headers,
            timeout=(10, 30),
        )
        
        if resp.status_code != 200:
            print(f"[link_extractor] trae metadata API: HTTP {resp.status_code}")
            return None
        
        data = resp.json()
        if data.get("code") != 0:
            print(f"[link_extractor] trae metadata API error: {data.get('message')}")
            return None
        
        share_data = data.get("data", {})
        title = share_data.get("title", "")
        creator_name = share_data.get("creator_name", "")
        created_at = share_data.get("created_at")
        
        print(f"[link_extractor] trae: title='{title}', creator='{creator_name}'")
    except Exception as e:
        print(f"[link_extractor] trae metadata fetch error: {e}")
        return None
    
    # Step 2: Get messages
    print(f"[link_extractor] trae: fetching messages...")
    try:
        resp = requests.get(
            f"{api_base}/api/remote/v1/share/{share_id}/messages",
            params={"page_size": 100},
            headers=headers,
            timeout=(10, 30),
        )
        
        if resp.status_code != 200:
            print(f"[link_extractor] trae messages API: HTTP {resp.status_code}")
            return None
        
        data = resp.json()
        if data.get("code") != 0:
            print(f"[link_extractor] trae messages API error: {data.get('message')}")
            return None
        
        items = data.get("data", {}).get("items", [])
        
        messages = []
        for item in items:
            role = item.get("role", "user")
            content_raw = item.get("content", "")
            
            # Content may be JSON-encoded
            text_content = ""
            if content_raw:
                try:
                    content_data = json.loads(content_raw)
                    if isinstance(content_data, list):
                        # Array of content blocks: [{type: "text", text_content: "..."}]
                        text_parts = []
                        for block in content_data:
                            if isinstance(block, dict):
                                if block.get("type") == "text" and block.get("text_content"):
                                    text_parts.append(block["text_content"])
                                elif block.get("text_content"):
                                    text_parts.append(block["text_content"])
                        text_content = "\n".join(text_parts)
                    elif isinstance(content_data, dict):
                        text_content = content_data.get("text_content", "") or content_data.get("content", "")
                except (json.JSONDecodeError, TypeError):
                    # Plain text
                    text_content = str(content_raw)
            
            if text_content.strip():
                messages.append({
                    "role": role,
                    "text": text_content.strip(),
                })
        
        if not messages:
            print("[link_extractor] trae: no messages found")
            return None
        
        print(f"[link_extractor] trae: extracted {len(messages)} messages")
        
        return {
            "title": title,
            "nick_name": creator_name,
            "create_time": created_at,
            "messages": messages,
        }
        
    except Exception as e:
        print(f"[link_extractor] trae messages fetch error: {e}")
        return None


def _extract_trae_via_playwright(url: str) -> dict | None:
    """Extract Trae share content using Playwright (renders SPA page).
    
    Tries multiple domains (share.traecontent.cn → work.trae.cn) and
    captures API responses for share data extraction.
    """
    if not _PLAYWRIGHT_AVAILABLE:
        print("[link_extractor] Playwright not available - install with: pip install playwright && playwright install chromium")
        return None

    share_id_match = re.search(r'/share/([a-zA-Z0-9_.=-]+)', url, re.I)
    share_id = share_id_match.group(1) if share_id_match else ""
    
    # Build candidate URLs for different Trae domains
    candidate_urls = [url]
    if share_id:
        candidate_urls.extend([
            f"https://work.trae.cn/share/{share_id}",
            f"https://www.trae.com.cn/share/{share_id}",
        ])
    
    for try_url in candidate_urls:
        print(f"[link_extractor] Playwright trying: {try_url[:80]}")
        result = _playwright_extract_from_url(try_url, share_id)
        if result and result.get("messages"):
            return result
    
    return None


def _playwright_extract_from_url(url: str, share_id: str) -> dict | None:
    """Try to extract share content from a single URL via Playwright."""
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-infobars',
                    '--disable-gpu',
                    '--window-size=1280,900',
                ]
            )
            context = browser.new_context(
                user_agent=_USER_AGENTS[0],
                viewport={"width": 1280, "height": 900},
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            
            # Override navigator.webdriver to avoid bot detection
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                window.chrome = { runtime: {} };
            """)
            
            page = context.new_page()
            
            # Block unnecessary resources for faster loading
            def route_handler(route, request):
                if request.resource_type in ('image', 'media', 'font', 'stylesheet'):
                    route.abort()
                elif 'marscode' in request.url or 'lf-cdn' in request.url:
                    route.abort()
                else:
                    route.continue_()
            
            page.route("**/*", route_handler)
            
            # Capture API responses for share data
            share_data = None
            api_responses = []
            
            def on_response(response):
                nonlocal share_data
                resp_url = response.url.lower()
                # Track all API-like responses
                if any(kw in resp_url for kw in ['share', 'thread', 'conversation', 'session']):
                    if 'lf-cdn' not in resp_url and 'marscode' not in resp_url and 'static' not in resp_url:
                        try:
                            body = response.text()
                            if body and len(body) > 20:
                                api_responses.append((response.url, body))
                                try:
                                    data = json.loads(body)
                                    data_str = str(data).lower()
                                    if any(kw in data_str for kw in ['message', 'content', 'share_info', 'share_session', 'record', 'role', 'parts']):
                                        share_data = data
                                        print(f"[link_extractor] Captured share API: {response.url[:100]}")
                                except:
                                    pass
                        except:
                            pass
            
            page.on("response", on_response)
            
            # Navigate with commit mode (faster, waits for load event)
            try:
                page.goto(url, wait_until="commit", timeout=45000)
            except Exception as e:
                print(f"[link_extractor] Playwright navigation failed: {e}")
                browser.close()
                return None
            
            # Wait for content to render (up to 5 attempts × 4 seconds)
            messages = []
            title = ""
            nick_name = ""
            
            for attempt in range(5):
                time.sleep(4)
                
                # Check for API-captured data first
                if share_data:
                    msgs = _extract_messages(share_data)
                    if msgs:
                        messages = msgs
                        meta = _extract_metadata(share_data)
                        title = meta.get("title", "")
                        nick_name = meta.get("nick_name", "")
                        print(f"[link_extractor] Extracted {len(messages)} messages from API response")
                        break
                
                # Also check all captured responses for any usable data
                for resp_url, body in reversed(api_responses):
                    try:
                        data = json.loads(body)
                        msgs = _extract_messages(data)
                        if msgs:
                            messages = msgs
                            meta = _extract_metadata(data)
                            title = meta.get("title", "")
                            nick_name = meta.get("nick_name", "")
                            print(f"[link_extractor] Extracted {len(messages)} messages from captured response: {resp_url[:80]}")
                            break
                    except:
                        pass
                    if messages:
                        break
                
                if messages:
                    break
                
                # Try DOM extraction
                try:
                    body_text = page.inner_text("body")
                    if body_text and len(body_text.strip()) > 50:
                        dom_messages = _extract_trae_messages_from_dom(page)
                        if dom_messages:
                            messages = dom_messages
                            break
                except Exception:
                    pass
            
            browser.close()
            
            if not messages:
                print(f"[link_extractor] Playwright: no messages extracted from {url[:60]}")
                return None
            
            return {
                "title": title,
                "nick_name": nick_name,
                "create_time": None,
                "messages": messages,
            }
            
    except Exception as e:
        print(f"[link_extractor] Playwright error on {url[:60]}: {e}")
        return None


def _extract_trae_messages_from_dom(page) -> list[dict]:
    """Extract messages from Trae's rendered DOM."""
    messages = []
    
    # Trae likely renders messages with these patterns:
    # - Elements with class containing 'message', 'Message', 'chat', 'bubble', 'assistant', 'user'
    # - Role indicators
    selectors_to_try = [
        # Common message container patterns
        "[class*='message-content']",
        "[class*='MessageContent']", 
        "[class*='message-content']",
        "[class*='bubble']",
        "[class*='Bubble']",
        "[class*='chat-message']",
        "[class*='ChatMessage']",
        "[class*='assistant-message']",
        "[class*='user-message']",
        "[class*='message-item']",
        "[class*='conversation-item']",
        # Data attributes
        "[data-role='assistant']",
        "[data-role='user']",
        "[data-testid*='message']",
        "[data-testid*='chat']",
        # Role-based
        "[class*='role-assistant']",
        "[class*='role-user']",
        # Generic markdown/rendered content
        "[class*='markdown']",
        "[class*='Markdown']",
        "[class*='prose']",
        "[class*='Prose']",
    ]
    
    for selector in selectors_to_try:
        try:
            elements = page.query_selector_all(selector)
            if elements and len(elements) >= 1:
                for el in elements:
                    try:
                        text = el.inner_text().strip()
                        if text and len(text) > 5:
                            # Determine role from class/id/attributes
                            cls = (el.get_attribute("class") or "").lower()
                            role_attr = (el.get_attribute("role") or "").lower()
                            data_role = (el.get_attribute("data-role") or "").lower()
                            
                            if any(k in cls or k in role_attr or k in data_role for k in ['assistant', 'bot', 'ai']):
                                role = "assistant"
                            elif any(k in cls or k in role_attr or k in data_role for k in ['user', 'human']):
                                role = "user"
                            else:
                                # Heuristic: alternating pattern
                                role = "assistant" if len(messages) % 2 == 1 else "user"
                            
                            messages.append({"role": role, "text": text})
                    except:
                        pass
                
                if messages:
                    return messages
        except:
            pass
    
    # Fallback: try to extract all text from the main content area
    try:
        # Look for the main content container
        for container_sel in ["main", "article", "[class*='content']", "[class*='Content']"]:
            containers = page.query_selector_all(container_sel)
            if containers:
                for container in containers:
                    try:
                        text = container.inner_text().strip()
                        if text and len(text) > 50:
                            # Split by common patterns
                            lines = text.split('\n')
                            current_role = "user"
                            current_text = []
                            
                            for line in lines:
                                line = line.strip()
                                if not line:
                                    if current_text:
                                        messages.append({"role": current_role, "text": "\n".join(current_text)})
                                        current_role = "assistant" if current_role == "user" else "user"
                                        current_text = []
                                else:
                                    current_text.append(line)
                            
                            if current_text:
                                messages.append({"role": current_role, "text": "\n".join(current_text)})
                            
                            if messages:
                                return messages
                    except:
                        pass
    except:
        pass
    
    return messages


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
            if "<html" in text.lower() and any(k in text.lower() or k in domain_lower for k in ("doubao", "thread", "traecontent", "trae", "opncd", "qianwen")):
                # Valid page but data may be in different format — always return for recognized domains
                print(f"[link_extractor] fetched {len(text)} bytes HTML for recognized domain, returning for parsing")
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
