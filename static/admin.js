const log = document.getElementById('log');

function writeLog(msg, color) {
  log.classList.add('show');
  log.textContent += (color === 'error' ? '✗ ' : '✓ ') + msg + '\n';
  log.scrollTop = log.scrollHeight;
}

// Kéo thả file
const dropZone = document.getElementById('dropZone');
dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag'); });
dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag'));
dropZone.addEventListener('drop', e => {
  e.preventDefault();
  dropZone.classList.remove('drag');
  const file = e.dataTransfer.files[0];
  if (file) sendFile(file);
});

// Kéo thả ảnh
const imgDropZone = document.getElementById('imgDropZone');
imgDropZone.addEventListener('dragover', e => { e.preventDefault(); imgDropZone.classList.add('drag'); });
imgDropZone.addEventListener('dragleave', () => imgDropZone.classList.remove('drag'));
imgDropZone.addEventListener('drop', e => {
  e.preventDefault(); imgDropZone.classList.remove('drag');
  const file = e.dataTransfer.files[0];
  if (file) processImage(file);
});

async function uploadImage(e) {
  const file = e.target.files[0];
  if (file) await processImage(file);
  e.target.value = '';
}

async function processImage(file) {
  const title = document.getElementById('imgTitle').value.trim();
  const preview = document.getElementById('imgPreviewWrap');
  const previewImg = document.getElementById('imgPreview');
  const previewName = document.getElementById('imgPreviewName');

  previewImg.src = URL.createObjectURL(file);
  previewName.textContent = file.name;
  preview.style.display = 'flex';

  writeLog(`Đang phân tích ảnh: ${file.name} (AI đang đọc...)`);

  const form = new FormData();
  form.append('file', file);
  if (title) form.append('title', title);

  try {
    const res = await fetch('/admin/upload-image', { method: 'POST', body: form });
    const data = await res.json();
    preview.style.display = 'none';
    if (data.ok) {
      writeLog(`Đã trích xuất: ${data.filename} (${data.chars.toLocaleString()} ký tự)`);
      if (data.preview) writeLog(`Nội dung: ${data.preview}...`);
      loadDocs();
    } else {
      writeLog(data.error || 'Lỗi không xác định', 'error');
    }
  } catch { preview.style.display = 'none'; writeLog('Lỗi kết nối', 'error'); }
}

async function uploadFile(e) {
  const file = e.target.files[0];
  if (file) await sendFile(file);
  e.target.value = '';
}

async function sendFile(file) {
  writeLog(`Đang upload: ${file.name}`);
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch('/admin/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (data.ok) {
      writeLog(`Đã thêm: ${data.filename} (${data.chars.toLocaleString()} ký tự)`);
      loadDocs();
    } else {
      writeLog(data.error || 'Lỗi không xác định', 'error');
    }
  } catch { writeLog('Lỗi kết nối', 'error'); }
}

async function uploadUrl() {
  const url = document.getElementById('urlInput').value.trim();
  if (!url) return;
  writeLog(`Đang tải URL: ${url}`);
  try {
    const res = await fetch('/admin/upload-url', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url }),
    });
    const data = await res.json();
    if (data.ok) {
      writeLog(`Đã thêm: ${data.filename} (${data.chars.toLocaleString()} ký tự)`);
      document.getElementById('urlInput').value = '';
      loadDocs();
    } else {
      writeLog(data.error || 'Lỗi không xác định', 'error');
    }
  } catch { writeLog('Lỗi kết nối', 'error'); }
}

async function deleteDoc(filename) {
  if (!confirm(`Xoá tài liệu "${filename}"?`)) return;
  const res = await fetch('/admin/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ filename }),
  });
  const data = await res.json();
  if (data.ok) { writeLog(`Đã xoá: ${filename}`); loadDocs(); }
}

const ICONS = { pdf: '📕', docx: '📘', txt: '📄', md: '📗', default: '📄' };

async function loadDocs() {
  const res = await fetch('/admin/docs');
  const data = await res.json();
  const list = document.getElementById('docList');
  document.getElementById('docCount').textContent = data.docs.length;

  // Kiểm tra coverage vector index
  try {
    const es = await fetch('/admin/embed-status', { credentials: 'include' });
    const ed = await es.json();
    const statusEl = document.getElementById('reindexStatus');
    if (ed.embed_enabled) {
      const docCount = data.docs.length;
      // Mỗi tài liệu trung bình ~3-5 chunks; nếu chunks < docs thì có file chưa được index
      if (ed.indexed_chunks === 0 && docCount > 0) {
        statusEl.style.color = '#ef5350';
        statusEl.innerHTML = `<b>Cảnh báo:</b> ${docCount} tài liệu chưa được vector-index — nhấn Re-index`;
      } else {
        statusEl.style.color = '#888';
        statusEl.textContent = `${ed.indexed_chunks} chunks đã index từ ${docCount} tài liệu`;
      }
    }
  } catch {}

  if (!data.docs.length) {
    list.innerHTML = '<div class="empty">Chưa có tài liệu nào</div>';
    return;
  }

  list.innerHTML = data.docs.map(d => {
    const ext = d.name.split('.').pop();
    const icon = ICONS[ext] || ICONS.default;
    return `
      <div class="doc-item">
        <span class="doc-icon">${icon}</span>
        <div class="doc-info">
          <div class="doc-name">${d.name}</div>
          <div class="doc-meta">${d.size_kb} KB · ${d.modified}</div>
        </div>
        <button class="doc-delete" onclick="deleteDoc('${d.name}')" title="Xoá">🗑</button>
      </div>`;
  }).join('');
}

let _reindexPoll = null;
async function reindexAll() {
  const status = document.getElementById('reindexStatus');
  status.style.color = '#888';
  status.textContent = '⏳ Đang khởi động...';
  try {
    const res = await fetch('/admin/reindex', { method: 'POST', credentials: 'include' });
    if (res.status === 401) { status.style.color='#ef5350'; status.textContent='✗ Cần đăng nhập lại'; return; }
    const data = await res.json();
    if (!data.ok) { status.style.color='#ef5350'; status.textContent='✗ ' + (data.error||'Lỗi'); return; }
    status.textContent = `⏳ Đang index ${data.total} file nền — tự động cập nhật...`;
    clearInterval(_reindexPoll);
    _reindexPoll = setInterval(async () => {
      const r2 = await fetch('/admin/reindex-status', { credentials: 'include' });
      const d2 = await r2.json();
      if (d2.running) {
        status.textContent = `⏳ Đang index: ${d2.done}/${d2.total} file... (${d2.indexed_chunks} chunks)`;
      } else {
        clearInterval(_reindexPoll);
        status.style.color = '#2e7d32';
        status.textContent = `✓ Xong — ${d2.indexed_chunks} chunks từ ${d2.done} nguồn`;
      }
    }, 3000);
  } catch (e) {
    status.style.color = '#ef5350';
    status.textContent = '✗ ' + (e.message || 'Lỗi kết nối');
  }
}

function fillCode(code, requests, images, maxUses, note) {
  document.getElementById('codeInput').value    = code;
  document.getElementById('codeRequests').value = requests;
  document.getElementById('codeImages').value   = images;
  document.getElementById('codeMaxUses').value  = maxUses;
  document.getElementById('codeNote').value     = note;
}

async function createCode() {
  const code       = document.getElementById('codeInput').value.trim().toUpperCase();
  const requests   = parseInt(document.getElementById('codeRequests').value) || 0;
  const images     = parseInt(document.getElementById('codeImages').value) || 0;
  const max_uses   = parseInt(document.getElementById('codeMaxUses').value) || 1;
  const note       = document.getElementById('codeNote').value.trim();
  const expires_at = document.getElementById('codeExpiry').value || null;
  const result     = document.getElementById('codeResult');
  if (!code || requests < 1) { alert('Nhập mã và số câu hỏi'); return; }
  const res  = await fetch('/admin/premium-code', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, requests, images, max_uses, note, expires_at }),
  });
  const data = await res.json();
  if (data.ok) {
    result.innerHTML = `<span style="color:#2e7d32">✓ Đã tạo mã <b>${data.code}</b></span>`;
    loadCodes();
  } else {
    result.innerHTML = `<span style="color:#ef5350">✗ ${data.error}</span>`;
  }
}

async function loadCodes() {
  const res  = await fetch('/admin/premium-codes');
  const data = await res.json();
  const list = document.getElementById('codeList');
  if (!data.codes.length) { list.innerHTML = '<div class="empty">Chưa có mã nào</div>'; return; }
  list.innerHTML = data.codes.map(c => {
    const full = c.used_count >= c.max_uses;
    const statusBg = full ? '#ffebee' : (c.used_count > 0 ? '#fff8e1' : '#e8f5e9');
    const statusColor = full ? '#ef5350' : (c.used_count > 0 ? '#f57c00' : '#2e7d32');
    const statusText = full ? `Hết lượt (${c.used_count}/${c.max_uses})` : (c.used_count > 0 ? `${c.used_count}/${c.max_uses} lượt` : 'Chưa dùng');
    const ips = c.redemptions.map(r =>
      `<div style="font-size:11px;color:#aaa;padding-left:4px;">· <span style="font-family:monospace;cursor:pointer;" onclick="navigator.clipboard.writeText('${r.ip}');this.style.color='#2e7d32';" title="Click để copy device_id">${r.ip.slice(0,16)}…</span> <span style="color:#bbb;">${r.ts}</span></div>`
    ).join('');
    return `
    <div class="doc-item" style="flex-direction:column;align-items:flex-start;gap:4px;">
      <div style="display:flex;justify-content:space-between;width:100%;align-items:center;gap:8px;">
        <span style="font-size:15px;font-weight:700;font-family:monospace;color:#1b5e20;">${c.code}</span>
        <span style="font-size:11px;padding:2px 8px;border-radius:10px;background:${statusBg};color:${statusColor};white-space:nowrap;">${statusText}</span>
      </div>
      <div style="font-size:12px;color:#555;">+${c.requests} câu hỏi · +${c.images} ảnh · tối đa ${c.max_uses} người${c.note ? ' · ' + c.note : ''}${c.expires_at ? ' · HH: ' + c.expires_at.slice(0,10) : ''}</div>
      ${ips}
      <div style="display:flex;gap:6px;margin-top:4px;">
        ${full ? `<button onclick="resetCode('${c.code}')" style="font-size:11px;padding:3px 10px;border:1px solid #f57c00;border-radius:12px;background:#fff8e1;color:#e65100;cursor:pointer;">↺ Reset lượt</button>` : ''}
        <button onclick="inspectCode('${c.code}')" style="font-size:11px;padding:3px 10px;border:1px solid #90caf9;border-radius:12px;background:#e3f2fd;color:#1565c0;cursor:pointer;">🔍 Debug</button>
        <button onclick="deleteCode('${c.code}')" style="font-size:11px;padding:3px 10px;border:1px solid #ef9a9a;border-radius:12px;background:#ffebee;color:#c62828;cursor:pointer;">✕ Xóa</button>
      </div>
    </div>`;
  }).join('');
}

async function resetCode(code) {
  if (!confirm(`Reset lượt dùng của mã ${code}? Người đã dùng mã này có thể dùng lại.`)) return;
  const res = await fetch(`/admin/premium-code/${code}/reset`, { method: 'POST' });
  const data = await res.json();
  if (data.ok) loadCodes();
  else alert('Reset thất bại');
}

async function deleteCode(code) {
  if (!confirm(`Xóa mã ${code}? Hành động này không thể hoàn tác.`)) return;
  const res = await fetch(`/admin/premium-code/${code}`, { method: 'DELETE' });
  if (res.ok) loadCodes();
}

async function inspectCode(code) {
  const res = await fetch(`/admin/inspect-code/${code}`);
  const d = await res.json();
  const redemptionLines = (d.redemptions || []).map(r => {
    const q = (d.quota_per_device || {})[r.device_id] || {};
    return `  • device_id: ${r.device_id}\n    Lúc: ${r.ts} | Quota còn: ${q.requests ?? '?'} câu, ${q.images ?? '?'} ảnh`;
  }).join('\n') || '  (chưa ai dùng)';
  alert(`=== DEBUG: ${code} ===\nused_count: ${d.used_count} / max_uses: ${d.max_uses}\nCó thể dùng: ${d.redeemable ? 'CÓ' : 'KHÔNG'}\n\nLượt dùng:\n${redemptionLines}\n\nExpires: ${d.expires_at || 'không giới hạn'}`);
}

async function giftQuota() {
  const deviceId = prompt('Nhập device_id (cookie "did") hoặc IP của người dùng:');
  if (!deviceId?.trim()) return;
  const requests = parseInt(prompt('Tặng bao nhiêu câu hỏi?', '30')) || 0;
  const images   = parseInt(prompt('Tặng bao nhiêu lượt ảnh?', '0')) || 0;
  if (!requests && !images) return;
  const res = await fetch('/admin/gift-quota', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ device_id: deviceId.trim(), requests, images }),
  });
  const data = await res.json();
  alert(data.ok ? `✓ Đã tặng ${requests} câu hỏi + ${images} ảnh cho ${deviceId}` : 'Tặng thất bại');
}

async function checkPushEnabled() {
  const res = await fetch('/api/vapid-public-key').catch(() => null);
  if (!res?.ok) return;
  const { enabled } = await res.json();
  if (!enabled) {
    document.getElementById('pushCard').innerHTML = `
      <h2>🔔 Gửi thông báo đẩy</h2>
      <div style="background:#fff8e1;border-left:4px solid #f9a825;padding:12px 16px;border-radius:8px;font-size:13px;color:#5d4037;">
        <strong>Chưa cấu hình VAPID keys.</strong><br>
        Thêm 2 biến môi trường vào Railway:<br><br>
        <code style="background:#f5f5f5;padding:2px 6px;border-radius:4px;">VAPID_PUBLIC_KEY</code> và
        <code style="background:#f5f5f5;padding:2px 6px;border-radius:4px;">VAPID_PRIVATE_KEY</code><br><br>
        Chạy lệnh sau để tạo keys: <code style="background:#f5f5f5;padding:2px 6px;border-radius:4px;">python generate_vapid.py</code>
      </div>`;
  }
}

function fillPush(title, body) {
  document.getElementById('pushTitle').value = title;
  document.getElementById('pushBody').value = body;
}

async function sendPush() {
  const title = document.getElementById('pushTitle').value.trim();
  const body  = document.getElementById('pushBody').value.trim();
  if (!title || !body) { alert('Vui lòng nhập tiêu đề và nội dung'); return; }

  const btn = document.getElementById('pushBtn');
  const result = document.getElementById('pushResult');
  btn.disabled = true;
  btn.textContent = 'Đang gửi...';
  result.textContent = '';

  try {
    const res = await fetch('/admin/push-send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, body, url: '/' }),
    });
    const data = await res.json();
    if (data.ok) {
      if (data.reason === 'no_subscribers') {
        result.innerHTML = '<span style="color:#f57c00;">⚠️ Chưa có thiết bị nào đăng ký nhận thông báo.</span>';
      } else {
        result.innerHTML = `<span style="color:#2e7d32;">✓ Đã gửi thành công đến <b>${data.sent}</b> thiết bị${data.failed ? ` (${data.failed} lỗi)` : ''}.</span>`;
      }
    } else {
      result.innerHTML = `<span style="color:#ef5350;">✗ ${data.detail || 'Lỗi không xác định'}</span>`;
    }
  } catch {
    result.innerHTML = '<span style="color:#ef5350;">✗ Lỗi kết nối</span>';
  } finally {
    btn.disabled = false;
    btn.textContent = '📤 Gửi thông báo';
  }
}

async function loadAnalytics() {
  const res = await fetch('/admin/analytics');
  const d = await res.json();

  document.getElementById('aTotalQ').textContent   = d.total_questions;
  document.getElementById('aTotalImg').textContent = d.total_with_image;

  // Bar chart 7 ngày
  const maxCount = Math.max(1, ...d.daily.map(x => x.count));
  const chart  = document.getElementById('barChart');
  const labels = document.getElementById('barLabels');

  const days = {};
  for (let i = 6; i >= 0; i--) {
    const dt = new Date(); dt.setDate(dt.getDate() - i);
    const key = dt.toISOString().slice(0,10);
    days[key] = 0;
  }
  d.daily.forEach(x => { if (days[x.day] !== undefined) days[x.day] = x.count; });

  chart.innerHTML = Object.entries(days).map(([day, cnt]) => {
    const h = Math.max(4, Math.round((cnt / maxCount) * 72));
    return `<div class="bar-col">
      <div class="bar-val">${cnt || ''}</div>
      <div class="bar" style="height:${h}px" title="${cnt} câu hỏi ngày ${day}"></div>
    </div>`;
  }).join('');

  labels.innerHTML = Object.keys(days).map(day =>
    `<div style="flex:1;text-align:center;font-size:10px;color:#999;">${day.slice(5)}</div>`
  ).join('');

  // Từ khoá
  const cloud = document.getElementById('keywordCloud');
  if (!d.top_keywords.length) {
    cloud.innerHTML = '<div class="empty">Chưa có dữ liệu</div>';
  } else {
    const maxKw = d.top_keywords[0].count;
    cloud.innerHTML = d.top_keywords.map(k =>
      `<span class="kw-tag ${k.count >= maxKw * 0.6 ? 'big' : ''}">${k.word} <b>${k.count}</b></span>`
    ).join('');
  }

  // Câu hỏi gần nhất
  const recent = document.getElementById('recentQuestions');
  if (!d.recent.length) {
    recent.innerHTML = '<div class="empty">Chưa có câu hỏi nào</div>';
  } else {
    recent.innerHTML = d.recent.map(q => `
      <div class="q-item">
        <div class="q-text">${q.has_image ? '📷 ' : ''}${q.question}</div>
        <div class="q-meta">${q.ts.replace('T', ' ')}</div>
      </div>`).join('');
  }
}

async function loadFlywheel() {
  const res = await fetch('/admin/flywheel');
  const d = await res.json();

  // Câu hỏi xấu
  const badEl = document.getElementById('badQuestions');
  if (!d.bad_questions.length) {
    badEl.innerHTML = '<div class="empty">✅ Chưa có câu hỏi bị đánh giá 👎 nhiều lần.</div>';
  } else {
    badEl.innerHTML = d.bad_questions.map(q => `
      <div class="bad-item">
        <div class="bad-q">❓ ${q.question}</div>
        <div class="bad-a">💬 ${q.answer || '(không có câu trả lời)'}</div>
        <div class="bad-meta">
          <span style="background:#ffebee;color:#ef5350;border-radius:10px;padding:2px 8px;font-weight:700;">👎 ${q.bad_count} lần</span>
          <span>${q.last_seen.replace('T',' ')}</span>
          <button class="btn" style="font-size:11px;padding:3px 10px;margin-left:auto;" onclick="prefillUrl('${q.question.replace(/'/g,"\\'").replace(/"/g,'\\"')}')">+ Thêm tài liệu</button>
        </div>
      </div>`).join('');
  }

  // Gap analysis
  const gapCloud = document.getElementById('gapCloud');
  const gapEmpty = document.getElementById('gapEmpty');
  if (!d.gaps.length) {
    gapCloud.style.display = 'none';
    gapEmpty.style.display = 'block';
  } else {
    gapCloud.style.display = 'flex';
    gapEmpty.style.display = 'none';
    const maxCount = d.gaps[0]?.count || 1;
    gapCloud.innerHTML = d.gaps.map(g => {
      const size = g.count >= maxCount * 0.7 ? '15px' : '13px';
      const badge = g.is_bigram ? ' 🔗' : '';
      return `<span class="gap-tag" style="font-size:${size};cursor:pointer;" title="${g.count} lần hỏi — bấm để AI tạo bài" onclick="generateGapContent('${g.word.replace(/'/g,"\\'")}', this)">
        ${g.word}${badge} <b style="font-size:11px;opacity:0.7;">${g.count}</b>
      </span>`;
    }).join('');
  }
}

async function generateGapContent(topic, el) {
  if (el._loading) return;
  el._loading = true;
  const orig = el.innerHTML;
  el.innerHTML = `⏳ Đang tạo...`;
  el.style.opacity = '0.7';
  try {
    const res = await fetch('/admin/generate-gap-content', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ topic }),
    });
    const data = await res.json();
    if (data.ok) {
      el.innerHTML = `✅ ${topic}`;
      el.style.background = '#e8f5e9'; el.style.borderColor = '#4caf50';
      el.style.color = '#2e7d32'; el.style.cursor = 'default';
      el.title = `Đã tạo: ${data.filename}\n\n${data.preview}`;
      loadDocs(); // refresh danh sách docs
    } else {
      el.innerHTML = orig;
      alert('Lỗi: ' + data.error);
    }
  } catch(e) {
    el.innerHTML = orig;
    alert('Lỗi kết nối');
  } finally {
    el.style.opacity = '1';
    el._loading = false;
  }
}

function prefillUrl(question) {
  document.getElementById('urlInput').value = '';
  document.getElementById('urlInput').placeholder = `Tìm tài liệu về: ${question}`;
  document.getElementById('urlInput').focus();
  document.getElementById('urlInput').scrollIntoView({ behavior: 'smooth', block: 'center' });
}

async function loadCommunityTips() {
  const res = await fetch('/admin/community-tips');
  const data = await res.json();
  const list = document.getElementById('communityList');
  if (!data.tips.length) {
    list.innerHTML = '<div class="empty">✅ Không có góp ý nào cần xem xét.</div>';
    return;
  }
  const CATEGORY_LABELS = { disease:'Sâu bệnh', technique:'Kỹ thuật', fertilizer:'Phân bón', harvest:'Thu hoạch', other:'Khác', evolution:'🧬 Evolution Engine', '': '' };
  list.innerHTML = data.tips.map(t => {
    const pct = t.ai_confidence != null ? Math.round(t.ai_confidence * 100) : null;
    const badgeClass = pct >= 70 ? 'high' : pct >= 40 ? 'mid' : 'low';
    const badgeHtml = pct != null
      ? `<span class="ai-badge ${badgeClass}">🤖 AI: ${pct}% tin cậy</span>`
      : '';
    const reasonHtml = t.ai_reason
      ? `<div class="ai-reason">🤖 ${t.ai_reason}</div>`
      : '';
    const evoTag = t.category === 'evolution'
      ? `<div style="background:#e3f2fd;color:#1565c0;border-radius:6px;padding:3px 10px;font-size:11px;font-weight:600;display:inline-block;margin-bottom:4px;">🧬 Tự động tạo bởi Evolution Engine — cần review trước khi thêm vào KB</div>`
      : '';
    return `
    <div class="tip-item" id="tip-${t.id}">
      ${evoTag}
      <div class="tip-title">${t.title}</div>
      ${badgeHtml}
      ${reasonHtml}
      <div class="tip-content">${t.content.slice(0, 400)}${t.content.length > 400 ? '...' : ''}</div>
      <div class="tip-meta">
        ${CATEGORY_LABELS[t.category] ? `<span style="background:#e8f5e9;color:#2e7d32;border-radius:8px;padding:1px 8px;">${CATEGORY_LABELS[t.category]}</span>` : ''}
        ${t.region ? `<span>📍 ${t.region}</span>` : ''}
        <span>${t.created_at.replace('T',' ')}</span>
      </div>
      <div class="tip-actions">
        <button class="btn-approve" onclick="approveTip(${t.id})">✓ Duyệt &amp; thêm vào KB</button>
        <button class="btn-reject"  onclick="rejectTip(${t.id})">✗ Từ chối</button>
      </div>
    </div>`;
  }).join('');
}

async function approveTip(id) {
  const res = await fetch(`/admin/community-approve/${id}`, { method: 'POST' });
  const data = await res.json();
  if (data.ok) {
    document.getElementById(`tip-${id}`).innerHTML = `<div style="color:#2e7d32;font-size:13px;">✓ Đã duyệt — tạo file <b>${data.filename}</b> và cập nhật knowledge base.</div>`;
    setTimeout(loadDocs, 500);
  } else {
    alert(data.error || 'Lỗi');
  }
}

async function rejectTip(id) {
  if (!confirm('Từ chối góp ý này?')) return;
  await fetch(`/admin/community-reject/${id}`, { method: 'POST', headers: {'Content-Type':'application/json'}, body: '{}' });
  document.getElementById(`tip-${id}`).style.opacity = '0.4';
  document.getElementById(`tip-${id}`).innerHTML += '<div style="font-size:12px;color:#ef5350;margin-top:6px;">✗ Đã từ chối</div>';
}

async function loadImageDataset() {
  const res = await fetch('/admin/image-submissions');
  const data = await res.json();
  const list = document.getElementById('imageDatasetList');
  if (!data.submissions.length) {
    list.innerHTML = '<div class="empty">Chưa có ảnh nào được gửi.</div>';
    return;
  }
  const fbIcon = f => f === 1 ? '👍' : f === -1 ? '👎' : '—';
  list.innerHTML = data.submissions.map(s => `
    <div class="img-item">
      <div style="width:70px;height:70px;background:#f0f0f0;border-radius:8px;display:flex;align-items:center;justify-content:center;font-size:28px;flex-shrink:0;">📷</div>
      <div class="img-info">
        <div class="img-diagnosis">${s.diagnosis || '(chưa có chẩn đoán)'}</div>
        <div class="img-meta">
          <span>Feedback: ${fbIcon(s.feedback)}</span>
          ${s.label ? `<span style="background:#e3f2fd;color:#1565c0;border-radius:6px;padding:1px 6px;">${s.label}</span>` : ''}
          <span>${s.created_at.replace('T',' ')}</span>
        </div>
      </div>
    </div>`).join('');
}

async function testTelegram() {
  const btn = document.getElementById('telegramTestBtn');
  const result = document.getElementById('telegramResult');
  btn.disabled = true; btn.textContent = 'Đang gửi...';
  result.textContent = '';
  try {
    const res = await fetch('/admin/test-notify', { method: 'POST' });
    const data = await res.json();
    if (data.ok) {
      result.style.color = '#2e7d32';
      result.textContent = '✓ Đã gửi! Kiểm tra Telegram của bạn.';
    } else {
      result.style.color = '#ef5350';
      result.textContent = '✗ ' + (data.reason || 'Lỗi không xác định');
    }
  } catch {
    result.style.color = '#ef5350';
    result.textContent = '✗ Lỗi kết nối';
  } finally {
    btn.disabled = false; btn.textContent = '📤 Gửi tin test';
  }
}

// ── Self-Evolution Engine ────────────────────────────────────────────────────

async function loadEvolution() {
  const res  = await fetch('/admin/evolution-log');
  const data = await res.json();
  const s    = data.stats || {};

  document.getElementById('evoTotalFilled').textContent = s.total_filled ?? '-';
  document.getElementById('evoTotalCycles').textContent = s.total_cycles ?? '-';
  document.getElementById('evoLastCycle').textContent   = s.last_cycle
    ? s.last_cycle.replace('T', ' ')
    : 'Chưa chạy lần nào';

  const histEl = document.getElementById('evoHistory');
  const history = data.history || [];
  if (!history.length) {
    histEl.innerHTML = '<span style="color:#aaa;">Chưa có lịch sử. Bấm "Chạy ngay" để thử.</span>';
    return;
  }

  const ICONS = {
    cycle_complete: '🔄',
    gap_filled:     '✍️',
  };
  const COLORS = { success: '#2e7d32', failed: '#ef5350', skipped: '#888' };

  histEl.innerHTML = history.map(r => {
    const icon  = ICONS[r.action] || 'ℹ️';
    const color = COLORS[r.result] || '#555';
    const time  = r.ts.replace('T', ' ').slice(0, 16);
    const topic = r.topic ? ` <b>${r.topic}</b>` : '';
    const detail = r.detail ? ` — <span style="color:#888;">${r.detail.slice(0, 80)}</span>` : '';
    return `<div style="color:${color};">${icon} [${time}]${topic}${detail}</div>`;
  }).join('');
}

async function runEvolution() {
  const btn    = document.getElementById('runEvoBtn');
  const result = document.getElementById('evoRunResult');
  btn.disabled = true;
  btn.textContent = '⏳ Đang chạy...';
  result.textContent = '';

  try {
    const res  = await fetch('/admin/run-evolution', { method: 'POST' });
    const data = await res.json();
    result.style.color = '#2e7d32';
    result.innerHTML =
      `✓ Hoàn tất — tìm thấy <b>${data.gaps_found}</b> gap, ` +
      `đã tạo <b>${data.gaps_filled}</b> bài, ` +
      `bỏ qua <b>${data.skipped}</b>, lỗi <b>${data.errors}</b>.`;
    await loadEvolution();
    await loadDocs();
  } catch {
    result.style.color = '#ef5350';
    result.textContent = '✗ Lỗi kết nối';
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Chạy ngay';
  }
}

async function saveEvoConfig() {
  const body = {
    gap_min_count:     parseInt(document.getElementById('cfgMinCount').value)    || 3,
    gap_max_per_cycle: parseInt(document.getElementById('cfgMaxPerCycle').value) || 5,
    evolution_hour:    parseInt(document.getElementById('cfgHour').value)        || 2,
  };
  const res  = await fetch('/admin/evolution-config', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json();
  document.getElementById('evoHour').textContent = data.evolution_hour;
  document.getElementById('evoMax').textContent  = data.gap_max_per_cycle;
  writeLog(`Config đã lưu: gap ≥ ${data.gap_min_count} lần, tối đa ${data.gap_max_per_cycle} bài/chu kỳ, chạy lúc ${data.evolution_hour}h`);
}

async function loadFeedback() {
  const res = await fetch('/admin/feedback');
  const data = await res.json();
  document.getElementById('fbGood').textContent  = data.good;
  document.getElementById('fbBad').textContent   = data.bad;
  document.getElementById('fbTotal').textContent = data.total;

  const list = document.getElementById('feedbackList');
  if (!data.items.length) {
    list.innerHTML = '<div class="empty">Chưa có đánh giá nào</div>';
    return;
  }
  list.innerHTML = data.items.map(i => `
    <div class="doc-item" style="flex-direction:column;align-items:flex-start;gap:6px;">
      <div style="display:flex;justify-content:space-between;width:100%;">
        <span style="font-size:18px;">${i.rating === 1 ? '👍' : '👎'}</span>
        <span style="font-size:11px;color:#aaa;">${i.ts}</span>
      </div>
      <div style="font-size:13px;font-weight:600;color:#333;">❓ ${i.question || '(ảnh)'}</div>
      <div style="font-size:12px;color:#666;line-height:1.5;">💬 ${i.answer.slice(0, 150)}${i.answer.length > 150 ? '...' : ''}</div>
    </div>`).join('');
}

// ── Tạo bài KB bằng AI ───────────────────────────────────────────────────────

async function generateKbArticle() {
  const topic = document.getElementById('aiTopicInput').value.trim();
  if (!topic) { alert('Vui lòng nhập chủ đề trước'); return; }

  const btn    = document.getElementById('generateBtn');
  const status = document.getElementById('aiGenStatus');
  btn.disabled = true;
  btn.textContent = 'Đang tạo...';
  status.style.color = '#888';
  status.textContent = 'AI đang viết bài — thường mất 15-30 giây...';
  document.getElementById('aiPreviewArea').style.display = 'none';

  try {
    const res = await fetch('/admin/generate-kb-article', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ topic }),
    });
    if (res.status === 401) {
      status.style.color = '#c62828';
      status.textContent = 'Lỗi xác thực — tải lại trang và đăng nhập lại.';
      return;
    }
    if (!res.ok) {
      const errText = await res.text();
      status.style.color = '#c62828';
      status.textContent = `Lỗi server HTTP ${res.status}: ${errText.slice(0, 150)}`;
      return;
    }

    // Stream plain text — hiện dần vào textarea
    const contentEl = document.getElementById('aiContentInput');
    const titleEl   = document.getElementById('aiTitleInput');
    document.getElementById('aiPreviewArea').style.display = 'block';
    contentEl.value = '';
    titleEl.value   = '';

    const reader  = res.body.getReader();
    const decoder = new TextDecoder();
    let full = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      full += decoder.decode(value, { stream: true });
      contentEl.value = full;
      // Tự động điền tiêu đề từ dòng # đầu tiên
      const m = full.match(/^#+ (.+)/m);
      if (m) titleEl.value = m[1].trim();
    }

    status.style.color = '#2e7d32';
    status.textContent = 'Bài đã tạo xong — xem lại, chỉnh sửa nếu cần, rồi bấm Lưu vào KB.';
  } catch (e) {
    status.style.color = '#c62828';
    status.textContent = 'Lỗi: ' + e.message;
    document.getElementById('aiPreviewArea').style.display = 'none';
  } finally {
    btn.disabled = false;
    btn.textContent = 'Tạo bài';
  }
}

async function saveKbArticle() {
  const title   = document.getElementById('aiTitleInput').value.trim();
  const content = document.getElementById('aiContentInput').value.trim();
  if (!title || content.length < 100) {
    alert('Tiêu đề hoặc nội dung quá ngắn (tối thiểu 100 ký tự)');
    return;
  }

  const btn = document.getElementById('saveKbBtn');
  btn.disabled = true;
  btn.textContent = 'Đang lưu...';

  try {
    const res = await fetch('/admin/save-kb-article', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ title, content }),
    });
    const data = await res.json();
    if (data.ok) {
      writeLog(`Đã lưu bài KB: ${data.filename} (${data.chars.toLocaleString()} ký tự)`);
      document.getElementById('aiPreviewArea').style.display = 'none';
      document.getElementById('aiGenStatus').textContent = '';
      document.getElementById('aiTopicInput').value = '';
      loadDocs();
    } else {
      alert('Lưu thất bại: ' + (data.error || 'Không xác định'));
    }
  } catch (e) {
    alert('Lỗi kết nối: ' + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = 'Lưu vào KB';
  }
}

// ── Quản lý Chuyên gia ───────────────────────────────────────────────────────

async function loadExperts() {
  const el = document.getElementById('expertList');
  if (!el) return;
  try {
    const res  = await fetch('/admin/experts');
    const data = await res.json();
    const experts = data.experts || [];
    if (!experts.length) { el.innerHTML = '<div class="empty">Chưa có đơn đăng ký nào</div>'; return; }
    const statusLabel = { pending: '⏳ Chờ duyệt', approved: '✅ Đã duyệt', rejected: '❌ Từ chối' };
    el.innerHTML = experts.map(e => `
      <div style="display:flex;align-items:center;gap:10px;padding:10px;background:#f9f9f9;border-radius:8px;margin-bottom:8px;flex-wrap:wrap;">
        <div style="flex:1;min-width:0;">
          <div style="font-size:13px;font-weight:600;">${e.name}</div>
          <div style="font-size:12px;color:#666;">${e.specialty || 'Không có chuyên môn'}</div>
          <div style="font-size:11px;color:#999;">ID: ${e.device_id.slice(0,12)}… · ${statusLabel[e.status] || e.status} · ${e.applied_at?.slice(0,10) || ''}</div>
        </div>
        ${e.status === 'pending' ? `
          <button onclick="expertAction('${e.device_id}','approve')" style="padding:5px 12px;border:none;border-radius:12px;background:#2e7d32;color:white;font-size:12px;cursor:pointer;">Duyệt</button>
          <button onclick="expertAction('${e.device_id}','reject')" style="padding:5px 12px;border:none;border-radius:12px;background:#ef5350;color:white;font-size:12px;cursor:pointer;">Từ chối</button>
        ` : ''}
      </div>
    `).join('');
  } catch { el.innerHTML = '<div class="empty">Lỗi tải dữ liệu</div>'; }
}

async function expertAction(deviceId, action) {
  try {
    const res  = await fetch(`/admin/expert-${action}/${encodeURIComponent(deviceId)}`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) { writeLog(`Chuyên gia ${action === 'approve' ? 'đã duyệt' : 'đã từ chối'}`); loadExperts(); }
  } catch (e) { alert('Lỗi: ' + e.message); }
}

// ── Nhiệm vụ cộng đồng ───────────────────────────────────────────────────────

async function createMission() {
  const title   = document.getElementById('missionTitle').value.trim();
  const topic   = document.getElementById('missionTopic').value.trim();
  const desc    = document.getElementById('missionDesc').value.trim();
  const pts     = parseInt(document.getElementById('missionRewardPts').value) || 10;
  const target  = parseInt(document.getElementById('missionTarget').value) || 5;
  const expires = document.getElementById('missionExpires').value || null;
  const msgEl   = document.getElementById('missionCreateMsg');

  if (!title) { msgEl.style.color = '#ef5350'; msgEl.textContent = 'Tiêu đề không được để trống'; return; }
  msgEl.style.color = '#888'; msgEl.textContent = 'Đang tạo...';

  try {
    const res  = await fetch('/admin/mission', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, description: desc, topic, reward_points: pts, target_count: target, expires_at: expires }),
    });
    const data = await res.json();
    if (data.ok) {
      msgEl.style.color = '#2e7d32';
      msgEl.textContent = `✓ Đã tạo nhiệm vụ #${data.id}`;
      loadMissions();
    } else {
      msgEl.style.color = '#ef5350';
      msgEl.textContent = '✗ ' + (data.detail || 'Lỗi tạo nhiệm vụ');
    }
  } catch (e) { msgEl.style.color = '#ef5350'; msgEl.textContent = '✗ ' + e.message; }
}

async function loadMissions() {
  const el = document.getElementById('missionList');
  if (!el) return;
  try {
    const res  = await fetch('/admin/missions');
    const data = await res.json();
    const missions = data.missions || [];
    if (!missions.length) { el.innerHTML = '<div class="empty">Chưa có nhiệm vụ nào</div>'; return; }
    const statusLabel = { active: '🟢 Đang hoạt động', completed: '✅ Hoàn thành', expired: '⏰ Hết hạn' };
    el.innerHTML = missions.map(m => `
      <div style="padding:10px;background:#f9f9f9;border-radius:8px;margin-bottom:8px;font-size:13px;">
        <div style="font-weight:600;">${m.title} <span style="font-size:11px;font-weight:400;">${statusLabel[m.status] || m.status}</span></div>
        <div style="color:#666;font-size:12px;margin-top:2px;">${m.description || ''}</div>
        <div style="font-size:11px;color:#888;margin-top:4px;">Chủ đề: ${m.topic || '—'} · Tiến độ: ${m.current_count}/${m.target_count} · Thưởng: ${m.reward_points} điểm${m.expires_at ? ` · Hết hạn: ${m.expires_at.slice(0,10)}` : ''}</div>
      </div>
    `).join('');
  } catch { el.innerHTML = '<div class="empty">Lỗi tải dữ liệu</div>'; }
}

// ── Báo cáo dịch bệnh ────────────────────────────────────────────────────────

async function loadDiseaseReports() {
  const el = document.getElementById('diseaseReportList');
  if (!el) return;
  try {
    const res  = await fetch('/admin/disease-reports?days=30');
    const data = await res.json();
    const reports = data.reports || [];
    if (!reports.length) { el.innerHTML = '<div class="empty">Chưa có báo cáo nào trong 30 ngày</div>'; return; }
    const sevLabel = { low: '🟡 Nhẹ', medium: '🟠 Trung bình', high: '🔴 Nặng' };
    el.innerHTML = reports.map(r => `
      <div style="display:flex;align-items:flex-start;gap:10px;padding:10px;background:#f9f9f9;border-radius:8px;margin-bottom:8px;flex-wrap:wrap;">
        <div style="flex:1;min-width:0;">
          <div style="font-size:13px;font-weight:600;">${r.disease} ${sevLabel[r.severity] || r.severity}</div>
          <div style="font-size:12px;color:#666;">${r.province || '—'} (${r.region || '—'})</div>
          <div style="font-size:11px;color:#999;">${r.note || ''} · ${r.ts?.slice(0,16) || ''} ${r.verified ? '✅ Đã xác nhận' : ''}</div>
        </div>
        ${!r.verified ? `<button onclick="verifyReport(${r.id})" style="padding:4px 10px;border:none;border-radius:10px;background:#2e7d32;color:white;font-size:11px;cursor:pointer;">Xác nhận</button>` : ''}
      </div>
    `).join('');
  } catch { el.innerHTML = '<div class="empty">Lỗi tải dữ liệu</div>'; }
}

async function verifyReport(id) {
  try {
    const res  = await fetch(`/admin/disease-report/${id}/verify`, { method: 'POST' });
    const data = await res.json();
    if (data.ok) { writeLog(`Đã xác nhận báo cáo #${id}`); loadDiseaseReports(); }
  } catch (e) { alert('Lỗi: ' + e.message); }
}

// ── Gap theo vùng ─────────────────────────────────────────────────────────────

const REGION_VI = {
  mekong: 'ĐBSCL', southeast: 'Đông Nam Bộ', central_highland: 'Tây Nguyên',
  south_central: 'Nam Trung Bộ', north_central: 'Bắc Trung Bộ',
  red_river: 'ĐB Sông Hồng', northeast: 'Trung du Bắc Bộ', northwest: 'Tây Bắc',
};

async function loadGapByRegion() {
  const el = document.getElementById('gapByRegionList');
  if (!el) return;
  try {
    const res  = await fetch('/admin/gap-by-region');
    const data = await res.json();
    const gapMap = data.gap_by_region || {};
    const regions = Object.keys(gapMap);
    if (!regions.length) { el.innerHTML = '<div class="empty">Chưa đủ dữ liệu hoặc KB đang cover tốt tất cả vùng</div>'; return; }
    el.innerHTML = regions.map(rg => `
      <div style="margin-bottom:14px;">
        <div style="font-size:13px;font-weight:600;color:#555;margin-bottom:6px;">📍 ${REGION_VI[rg] || rg}</div>
        <div style="display:flex;flex-wrap:wrap;gap:6px;">
          ${gapMap[rg].map(g => `
            <span style="display:inline-flex;align-items:center;gap:4px;background:#fff3e0;border:1px solid #ffb74d;border-radius:12px;padding:3px 10px;font-size:12px;cursor:pointer;"
              onclick="document.getElementById('aiTopicInput')?.value='${g.phrase}';document.getElementById('aiTopicInput')?.scrollIntoView({behavior:'smooth'})">
              ${g.phrase} <span style="color:#e65100;font-weight:700;">${g.count}</span>
            </span>
          `).join('')}
        </div>
      </div>
    `).join('');
  } catch { el.innerHTML = '<div class="empty">Lỗi tải dữ liệu</div>'; }
}

// ── Dán văn bản trực tiếp ────────────────────────────────────────────────────

function updatePasteCount() {
  const len = (document.getElementById('pasteContent').value || '').length;
  document.getElementById('pasteCharCount').textContent = len.toLocaleString('vi-VN') + ' ký tự';
}

async function savePasteText() {
  const content = (document.getElementById('pasteContent').value || '').trim();
  const title   = (document.getElementById('pasteTitle').value || '').trim();
  const status  = document.getElementById('pasteStatus');
  const btn     = document.getElementById('pasteSaveBtn');

  if (content.length < 20) {
    status.style.color = '#ef5350';
    status.textContent = 'Vui lòng dán ít nhất 20 ký tự nội dung.';
    return;
  }

  btn.disabled = true;
  status.style.color = '#888';
  status.textContent = 'Đang lưu...';

  try {
    const res  = await fetch('/admin/paste-text', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ title, content }),
    });
    if (res.status === 401) { status.style.color='#ef5350'; status.textContent='Cần đăng nhập lại.'; return; }
    const data = await res.json();
    if (data.ok) {
      status.style.color = '#2e7d32';
      status.textContent = `Đã lưu: ${data.filename} (${data.chars.toLocaleString('vi-VN')} ký tự)${data.indexed ? ' · đã vector-index' : ''}`;
      document.getElementById('pasteContent').value = '';
      document.getElementById('pasteTitle').value   = '';
      updatePasteCount();
      loadDocs();
    } else {
      status.style.color = '#ef5350';
      status.textContent = 'Lỗi: ' + (data.error || 'Không xác định');
    }
  } catch (e) {
    status.style.color = '#ef5350';
    status.textContent = 'Lỗi kết nối: ' + e.message;
  } finally {
    btn.disabled = false;
  }
}

// ── Init ─────────────────────────────────────────────────────────────────────
loadDocs();
loadEvolution();
loadAnalytics();
loadFlywheel();
loadCommunityTips();
loadFeedback();
loadImageDataset();
checkPushEnabled();
loadCodes();
loadExperts();
loadMissions();
loadDiseaseReports();
loadGapByRegion();
