const editor = document.getElementById('editor');
const preview = document.getElementById('preview');
const fileInput = document.getElementById('fileInput');
const btnDocx = document.getElementById('btnDocx');
const btnPdf = document.getElementById('btnPdf');
const chatTitle = document.getElementById('chatTitle');
const chatBody = document.getElementById('chatBody');
const chatToggleBtn = document.getElementById('chatToggleBtn');
const viewToggle = document.getElementById('viewToggle');
const btnSync = document.getElementById('btnSync');

let syncScroll = true;
let syncSource = null;

function getTimestamp() {
  const d = new Date();
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}${pad(d.getMonth()+1)}${pad(d.getDate())}_${pad(d.getHours())}${pad(d.getMinutes())}${pad(d.getSeconds())}`;
}

function getActivePanel() {
  const isChat = chatBody.style.display !== 'none';
  return isChat ? chatBody : preview;
}

function setView(view) {
  const isChat = view === 'chat';
  preview.style.display = isChat ? 'none' : '';
  chatBody.style.display = isChat ? 'flex' : 'none';
  viewToggle.querySelectorAll('.toggle-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.view === view);
  });
}

function renderPreview() {
  const text = editor.value;
  const html = marked.parse(text);
  preview.innerHTML = html;
  if (window.renderMathInElement) {
    renderMathInElement(preview, {
      delimiters: [
        { left: '$$', right: '$$', display: true },
        { left: '$', right: '$', display: false }
      ]
    });
  }
  if (syncScroll && syncSource !== 'preview') {
    requestAnimationFrame(() => {
      const ratio = editor.scrollTop / Math.max(1, editor.scrollHeight - editor.clientHeight);
      const panel = getActivePanel();
      panel.scrollTop = ratio * (panel.scrollHeight - panel.clientHeight);
    });
  }
}

let renderTimer;
editor.addEventListener('input', () => {
  clearTimeout(renderTimer);
  renderTimer = setTimeout(renderPreview, 300);
  if (filling) return;
  clearTimeout(linkTimer);
  linkTimer = setTimeout(detectLink, 600);
});
const loadingOverlay = document.getElementById('loadingOverlay');
const loadingText = document.getElementById('loadingText');
const btnCancel = document.getElementById('btnCancel');
const statusBar = document.getElementById('statusBar');
let linkTimer;
let filling = false;
let abortController = null;
let statusTimer;
let extracting = false;
let extractUrl = '';
let cancelled = false;

viewToggle.addEventListener('click', (e) => {
  const btn = e.target.closest('.toggle-btn');
  if (!btn) return;
  setView(btn.dataset.view);
});

btnCancel.addEventListener('click', () => {
  cancelled = true;
  if (abortController) abortController.abort();
  extracting = false;
});

btnSync.addEventListener('click', () => {
  syncScroll = !syncScroll;
  btnSync.classList.toggle('active', syncScroll);
  btnSync.title = syncScroll ? '同步滚动（已开启）' : '同步滚动（已关闭）';
});

editor.addEventListener('scroll', () => {
  if (!syncScroll || syncSource === 'panel') { syncSource = null; return; }
  syncSource = 'editor';
  const ratio = editor.scrollTop / Math.max(1, editor.scrollHeight - editor.clientHeight);
  const panel = getActivePanel();
  panel.scrollTop = ratio * (panel.scrollHeight - panel.clientHeight);
  setTimeout(() => { syncSource = null; }, 50);
});

function _onPanelScroll() {
  if (!syncScroll || syncSource === 'editor') { syncSource = null; return; }
  syncSource = 'panel';
  const panel = getActivePanel();
  const ratio = panel.scrollTop / Math.max(1, panel.scrollHeight - panel.clientHeight);
  editor.scrollTop = ratio * (editor.scrollHeight - editor.clientHeight);
  setTimeout(() => { syncSource = null; }, 50);
}

preview.addEventListener('scroll', _onPanelScroll);
chatBody.addEventListener('scroll', _onPanelScroll);

function showLoading(text) {
  loadingText.textContent = text || '正在解析链接…';
  loadingOverlay.style.display = 'flex';
}

function hideLoading() {
  loadingOverlay.style.display = 'none';
}

function showStatus(msg, isError) {
  if (!statusBar) return;
  statusBar.textContent = msg;
  statusBar.className = 'status-bar' + (isError ? ' error' : '');
  statusBar.style.display = 'block';
  clearTimeout(statusTimer);
  statusTimer = setTimeout(() => { statusBar.style.display = 'none'; }, 6000);
}

function isUrl(text) {
  return /^https?:\/\/[^\s]+$/i.test(text.trim());
}

function detectLink() {
  const text = editor.value.trim();
  if (!isUrl(text)) {
    return;
  }
  if (extracting) {
    // Already extracting — if URL changed, mark for retry after current finishes
    extractUrl = text;
    return;
  }
  extractUrl = text;
  _doExtract(text, 0);
}

function _doExtract(url, attempt) {
  cancelled = false;
  extracting = true;
  abortController = new AbortController();
  const timeoutId = setTimeout(() => {
    if (!cancelled && abortController) abortController.abort();
  }, 45000);
  showLoading(attempt === 0 ? '正在解析链接…（约 5-30 秒）' : '正在重试…（第 ' + (attempt + 1) + ' 次）');
  fetch('/extract/link', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ url: url }),
    signal: abortController.signal
  })
    .then(r => r.json().then(d => ({ ok: r.ok, d })))
    .then(({ ok, d }) => {
      clearTimeout(timeoutId);
      abortController = null;
      hideLoading();
      if (!ok || !d.ai_link) {
        extracting = false;
        const msg = (d && d.error) || '未能识别为 AI 对话链接';
        showStatus(msg, true);
        if (!cancelled) _drainQueuedUrl(url);
        return;
      }
      if (!d.messages || d.messages.length === 0) {
        if (attempt === 0 && !cancelled) {
          setTimeout(() => _doExtract(url, 1), 5000);
          return;
        }
        extracting = false;
        showStatus('未解析到消息，请稍后重试', true);
        if (!cancelled) _drainQueuedUrl(url);
        return;
      }
      extracting = false;
      renderChat(d);
      fillEditorWithConversation(d);
      showStatus('已解析 ' + d.messages.length + ' 条消息并填入编辑器');
      if (!cancelled) _drainQueuedUrl(url);
    })
    .catch(e => {
      clearTimeout(timeoutId);
      abortController = null;
      hideLoading();
      if (e.name === 'AbortError') {
        extracting = false;
        showStatus(cancelled ? '已取消解析' : '解析超时，请稍后重试', true);
        return;
      }
      if (attempt === 0 && !cancelled) {
        setTimeout(() => _doExtract(url, 1), 5000);
        return;
      }
      extracting = false;
      showStatus('解析失败，请稍后重试', true);
      if (!cancelled) _drainQueuedUrl(url);
    });
}

function _drainQueuedUrl(currentUrl) {
  if (extractUrl && extractUrl !== currentUrl) {
    setTimeout(() => _doExtract(extractUrl, 0), 300);
  }
}

function fillEditorWithConversation(data) {
  if (filling) return;
  filling = true;
  const lines = [];
  if (data.title) {
    lines.push('# ' + data.title);
  }
  if (data.nick_name) {
    lines.push('');
    lines.push('> 分享者：' + data.nick_name);
  }
  (data.messages || []).forEach(m => {
    lines.push('');
    lines.push('### ' + (m.role === 'user' ? '🙂 用户' : '🤖 AI'));
    lines.push('');
    lines.push(m.text);
  });
  editor.value = lines.join('\n').trim() + '\n';
  filling = false;
  renderPreview();
}

function renderChat(data) {
  chatTitle.textContent = (data.title || 'AI 对话') + ' — ' + (data.nick_name || '');
  chatBody.innerHTML = '';
  (data.messages || []).forEach(m => {
    const row = document.createElement('div');
    row.className = 'chat-row ' + (m.role === 'user' ? 'user' : 'assistant');
    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    bubble.textContent = m.text;
    row.appendChild(bubble);
    chatBody.appendChild(row);
  });
  chatToggleBtn.style.display = '';
  setView('chat');
  chatBody.scrollTop = chatBody.scrollHeight;
}

fileInput.addEventListener('change', (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = (ev) => {
    editor.value = ev.target.result;
    renderPreview();
  };
  reader.readAsText(file);
});

function getContent() {
  return editor.value.trim() || '';
}

function exportDocx() {
  const content = getContent();
  if (!content) { alert('请输入内容'); return; }
  const form = new FormData();
  form.append('content', content);
  fetch('/convert/docx', { method: 'POST', body: form })
    .then(r => {
      if (!r.ok) throw new Error('转换失败');
      return r.blob();
    })
    .then(blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = getTimestamp() + '.docx';
      a.click();
    })
    .catch(e => alert(e.message));
}

function exportPdf() {
  const content = getContent();
  if (!content) { alert('请输入内容'); return; }
  const form = new FormData();
  form.append('content', content);
  fetch('/convert/pdf', { method: 'POST', body: form })
    .then(r => {
      if (r.status === 501) throw new Error('PDF 转换暂不可用（未配置转换服务）');
      if (!r.ok) throw new Error('转换失败');
      return r.blob();
    })
    .then(blob => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(blob);
      a.download = getTimestamp() + '.pdf';
      a.click();
    })
    .catch(e => alert(e.message));
}

btnDocx.addEventListener('click', exportDocx);
btnPdf.addEventListener('click', exportPdf);

document.addEventListener('DOMContentLoaded', () => {
  if (editor.value) renderPreview();
});
