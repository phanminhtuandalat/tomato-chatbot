const messagesEl  = document.getElementById('messages');
const inputEl     = document.getElementById('input');
const sendBtn     = document.getElementById('sendBtn');
const previewWrap = document.getElementById('previewWrap');
const previewImg  = document.getElementById('previewImg');

let pendingImage = '';
let userRegion = localStorage.getItem('region') || '';
let userLat = 0, userLon = 0;
let firstMessageSent = false;
let lastSubmissionId = null;
let activeFeedbackShownToday = localStorage.getItem('feedback-date') === new Date().toISOString().slice(0,10);

/* ── Banner mùa vụ ── */
const SEASON_INFO = {
  1:  { icon: '☀️', text: 'Tháng 1 — Mùa khô, thời điểm vàng để trồng và thu hoạch. Bón kali tăng độ ngọt quả.' },
  2:  { icon: '☀️', text: 'Tháng 2 — Thu hoạch rộ, giá thường cao. Chuẩn bị giống cho vụ tiếp theo.' },
  3:  { icon: '🌤️', text: 'Tháng 3 — Cuối mùa khô, bắt đầu có mưa nhỏ. Phun phòng nấm bệnh 10 ngày/lần.' },
  4:  { icon: '🌧️', text: 'Tháng 4 — Đầu mùa mưa, nguy cơ bệnh tăng. Phun phòng mốc sương 7 ngày/lần.' },
  5:  { icon: '🌧️', text: 'Tháng 5 — Mưa nhiều, bệnh héo rũ tăng mạnh. Thoát nước tốt, phun thuốc thường xuyên.' },
  6:  { icon: '⛈️', text: 'Tháng 6 — Mưa lớn nhất năm. Kiểm tra vườn hàng ngày, nhổ ngay cây bệnh.' },
  7:  { icon: '⛈️', text: 'Tháng 7 — Mưa kéo dài. Hạn chế trồng mới, tập trung bảo vệ vườn hiện có.' },
  8:  { icon: '🌤️', text: 'Tháng 8 — Mưa giảm dần. Làm đất, bón vôi, chuẩn bị xuống giống vụ mới.' },
  9:  { icon: '🌱', text: 'Tháng 9 — Thời tiết ổn định. Xuống giống, làm giàn, bón lót đầy đủ.' },
  10: { icon: '🌱', text: 'Tháng 10 — Mùa khô bắt đầu, thời điểm tốt nhất để trồng. Bón thúc giai đoạn ra hoa.' },
  11: { icon: '☀️', text: 'Tháng 11 — Mùa khô, năng suất cao, ít bệnh. Bón kali giai đoạn quả lớn.' },
  12: { icon: '🎄', text: 'Tháng 12 — Chuẩn bị hàng Tết. Tăng kali và canxi, thu hoạch đúng độ chín.' },
};

function showSeasonBanner() {
  const month = new Date().getMonth() + 1;
  const info = SEASON_INFO[month];
  const regionNames = {
    mekong: 'ĐBSCL', southeast: 'Đông Nam Bộ', central_highland: 'Tây Nguyên',
    south_central: 'Nam Trung Bộ', north_central: 'Bắc Trung Bộ',
    red_river: 'ĐB Sông Hồng', northeast: 'Trung du Bắc Bộ', northwest: 'Tây Bắc',
  };
  const regionTag = userRegion ? ` · <span style="color:#e65100;font-weight:600;">📍 ${regionNames[userRegion] || ''}</span>` : '';
  document.getElementById('seasonBanner').innerHTML =
    `<span>${info.icon}</span> <span><strong>Tháng ${month}:</strong> ${info.text}${regionTag}</span>`;
}
showSeasonBanner();

/* ── Helpers ── */
function scrollBottom() { messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: 'smooth' }); }
function autoResize(el) { el.style.height = 'auto'; el.style.height = Math.min(el.scrollHeight, 110) + 'px'; }
function handleKey(e) { if (e.key === 'Enter' && !e.shiftKey && window.innerWidth > 600) { e.preventDefault(); sendMessage(); } }
function now() { return new Date().toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' }); }
function esc(text) {
  return text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
    .replace(/\n/g, '<br>');
}

// Wrap bảng vào div cuộn ngang để không vỡ layout trên mobile
const _mdRenderer = typeof marked !== 'undefined' ? new marked.Renderer() : null;
if (_mdRenderer) {
  _mdRenderer.table = (header, body) =>
    `<div class="table-wrap"><table><thead>${header}</thead><tbody>${body}</tbody></table></div>`;
}

function renderBot(text) {
  if (typeof marked !== 'undefined') {
    return marked.parse(text, { breaks: true, gfm: true, renderer: _mdRenderer });
  }
  return esc(text);
}

/* ── Ảnh ── */
function handleImage(e) {
  const file = e.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = ev => {
    pendingImage = ev.target.result;
    previewImg.src = pendingImage;
    previewWrap.classList.add('show');
    inputEl.placeholder = 'Thêm câu hỏi về ảnh (tuỳ chọn)...';
    inputEl.focus();
  };
  reader.readAsDataURL(file);
  e.target.value = '';
}

function removeImage() {
  pendingImage = '';
  previewImg.src = '';
  previewWrap.classList.remove('show');
  inputEl.placeholder = 'Nhắn tin hoặc gửi ảnh sâu bệnh...';
}

/* ── Tin nhắn ── */
function addUserMessage(text, imageUrl) {
  const div = document.createElement('div');
  div.className = 'msg-user';
  let content = '';
  if (imageUrl) content += `<img src="${imageUrl}" alt="ảnh" />`;
  if (text)     content += esc(text);
  div.innerHTML = `<div class="bubble">${content}</div>`;
  messagesEl.appendChild(div);
  const time = document.createElement('div');
  time.className = 'msg-time';
  time.textContent = now();
  messagesEl.appendChild(time);
  scrollBottom();
}

function addBotMessage(text, question = '', submissionId = null, showActiveFeedback = false) {
  const msgId = 'msg-' + Date.now();
  const div = document.createElement('div');
  div.className = 'msg-bot';
  div.innerHTML = `<div class="bot-avatar">🍅</div><div class="bubble md-content">${renderBot(text)}</div>`;
  messagesEl.appendChild(div);

  if (showActiveFeedback) {
    const card = document.createElement('div');
    card.className = 'feedback-card';
    card.id = msgId;
    card.innerHTML = `
      <div class="fc-text">🙏 Câu trả lời này có giúp ích cho bà con không?<br>
        <span style="font-size:12px;color:#888;">Phản hồi giúp bot ngày càng chính xác hơn — và bà con được <b>thưởng thêm lượt hỏi</b>!</span>
      </div>
      <div class="fc-btns">
        <button class="fc-up"   onclick="sendActiveFeedback('${msgId}', 1)">👍 Có ích (+1 câu)</button>
        <button class="fc-down" onclick="sendActiveFeedback('${msgId}', -1)">👎 Chưa đúng (+2 câu)</button>
      </div>
      <div class="reason-wrap" id="reason-${msgId}">
        <textarea class="reason-input" id="reasonText-${msgId}" placeholder="Bà con thấy câu trả lời còn thiếu gì? (tuỳ chọn)..." rows="2"></textarea>
        <button class="reason-submit" onclick="submitReason('${msgId}')">Gửi góp ý (+2 câu hỏi)</button>
        <button class="reason-skip"   onclick="submitReasonSkip('${msgId}')">Bỏ qua (+1 câu hỏi)</button>
      </div>`;
    card.dataset.question = question;
    card.dataset.answer = text;
    if (submissionId) card.dataset.submissionId = submissionId;
    messagesEl.appendChild(card);
  } else {
    const fbRow = document.createElement('div');
    fbRow.className = 'feedback-row';
    fbRow.id = msgId;
    fbRow.innerHTML = `
      <button class="fb-btn" onclick="sendFeedback('${msgId}', 1, this)">👍 Hữu ích</button>
      <button class="fb-btn" onclick="reportWrong('${msgId}', this)">👎 Chưa đúng</button>`;
    fbRow.dataset.question = question;
    fbRow.dataset.answer = text;
    if (submissionId) fbRow.dataset.submissionId = submissionId;
    messagesEl.appendChild(fbRow);
  }
  scrollBottom();
}

function showTyping() {
  const div = document.createElement('div');
  div.className = 'msg-bot typing'; div.id = 'typing';
  div.innerHTML = `<div class="bot-avatar">🍅</div><div class="bubble"><div class="dots">
    <span class="dot"></span><span class="dot"></span><span class="dot"></span>
  </div></div>`;
  messagesEl.appendChild(div); scrollBottom();
}
function removeTyping() { document.getElementById('typing')?.remove(); }

/* ── Feedback ── */
/* ── Context-aware toast + confetti + progress bar ── */

const _TOAST_CTX = {
  feedback:            { icon: '🙏', sub: 'Phản hồi của bà con giúp bot ngày càng thông minh hơn!' },
  correction_verified: { icon: '🎉', sub: 'Thông tin đã được xác nhận và bổ sung vào kho kiến thức!' },
  correction_pending:  { icon: '📝', sub: 'Cảm ơn! Admin sẽ xem xét và cập nhật sớm.' },
  tip:                 { icon: '🌱', sub: 'Cảm ơn kinh nghiệm quý báu của bà con!' },
  tip_approved:        { icon: '✨', sub: 'Kinh nghiệm được xác nhận ngay và thêm vào kho kiến thức!' },
};

function showBonusToast(points, questionsAdded, action, currentPts, perQuestion) {
  if (!points && !questionsAdded) return;
  const ctx = _TOAST_CTX[action] || { icon: '⭐', sub: 'Cảm ơn đóng góp của bà con' };
  const mainText = questionsAdded > 0
    ? `+${points} điểm → 🎁 thêm ${questionsAdded} lượt hỏi!`
    : `+${points} điểm`;

  const toast = document.getElementById('bonusToast');
  toast.className = 'bonus-toast' + (questionsAdded > 0 ? ' unlock' : '');
  toast.innerHTML = `<div class="toast-icon">${ctx.icon}</div><div class="toast-body"><strong>${mainText}</strong><span>${ctx.sub}</span></div>`;
  toast.classList.add('show');
  clearTimeout(toast._t);
  toast._t = setTimeout(() => toast.classList.remove('show'), 4800);

  if (questionsAdded > 0) showConfetti();
  if (currentPts != null) showPointsProgress(currentPts, perQuestion || 20);
  updateQuota();
}

function showConfetti() {
  const emojis = ['🎉', '🍅', '⭐', '🌟', '✨', '🎊', '🥳'];
  for (let i = 0; i < 15; i++) {
    const el = document.createElement('div');
    el.className = 'confetti-piece';
    el.textContent = emojis[i % emojis.length];
    el.style.left = `${4 + Math.random() * 92}%`;
    el.style.fontSize = `${16 + Math.random() * 20}px`;
    el.style.animationDelay = `${Math.random() * 0.7}s`;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 2800);
  }
}

function showPointsProgress(current, perQuestion) {
  let bar = document.getElementById('ptsProgressBar');
  if (!bar) {
    bar = document.createElement('div');
    bar.id = 'ptsProgressBar';
    bar.className = 'pts-progress';
    bar.innerHTML = `<span class="pts-label" id="ptsLabel"></span><div class="pts-bar"><div class="pts-fill" id="ptsFill"></div></div>`;
    document.body.appendChild(bar);
  }
  const pct = Math.min(100, Math.round((current / perQuestion) * 100));
  document.getElementById('ptsLabel').textContent = `⭐ ${current} / ${perQuestion} điểm`;
  document.getElementById('ptsFill').style.width = pct + '%';
  bar.classList.add('show');
  clearTimeout(bar._t);
  bar._t = setTimeout(() => bar.classList.remove('show'), 3800);
}

async function _postFeedback(payload) {
  const res = await fetch('/api/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  }).catch(() => null);
  if (res?.ok) {
    const data = await res.json();
    if (data.points) showBonusToast(data.points, data.questions_added || 0, 'feedback', data.current_points, 20);
  }
}

async function sendFeedback(msgId, rating, btnEl) {
  const row = document.getElementById(msgId);
  row.querySelectorAll('.fb-btn').forEach(b => b.disabled = true);
  btnEl.classList.add(rating === 1 ? 'voted-up' : 'voted-down');
  await _postFeedback({
    question: row.dataset.question, answer: row.dataset.answer, rating,
    submission_id: row.dataset.submissionId ? parseInt(row.dataset.submissionId) : null,
  });
}

/* ── Simple Correction Report ── */
function reportWrong(msgId, btnEl) {
  const row = document.getElementById(msgId);
  row.querySelectorAll('.fb-btn').forEach(b => b.disabled = true);
  if (btnEl) btnEl.classList.add('voted-down');

  _postFeedback({
    question: row.dataset.question, answer: row.dataset.answer, rating: -1,
    submission_id: row.dataset.submissionId ? parseInt(row.dataset.submissionId) : null,
  });

  const wrap = document.createElement('div');
  wrap.className = 'simple-correction';
  wrap.id = `sc-${msgId}`;
  wrap.innerHTML = `
    <div class="sc-prompt">Bà con thấy thông tin nào chưa đúng? (tuỳ chọn — giúp admin bổ sung kiến thức)</div>
    <textarea class="sc-input" id="sc-text-${msgId}" placeholder="Mô tả ngắn gọn điều bà con biết đúng hơn..." rows="3"></textarea>
    <div class="sc-actions">
      <button class="sc-submit" onclick="submitReport('${msgId}')">📤 Gửi góp ý</button>
      <button class="sc-skip"   onclick="skipReport('${msgId}')">Bỏ qua</button>
    </div>`;
  row.after(wrap);
  document.getElementById(`sc-text-${msgId}`).focus();
  scrollBottom();
}

async function submitReport(msgId) {
  const row  = document.getElementById(msgId);
  const wrap = document.getElementById(`sc-${msgId}`);
  const correction = document.getElementById(`sc-text-${msgId}`)?.value.trim() || '';
  wrap.querySelectorAll('button').forEach(b => b.disabled = true);
  try {
    const res = await fetch('/api/correct', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        question:      row?.dataset?.question || '',
        wrong_answer:  row?.dataset?.answer   || '',
        correction,
        submission_id: row?.dataset?.submissionId ? parseInt(row.dataset.submissionId) : null,
      }),
    });
    const data = await res.json();
    wrap.innerHTML = '<div class="sc-thanks">✓ Đã ghi nhận. Cảm ơn bà con! Admin sẽ xem xét và bổ sung kiến thức.</div>';
    if (data.points) showBonusToast(data.points, data.questions_added || 0, 'correction_pending', data.current_points, 20);
  } catch {
    wrap.innerHTML = '<div class="sc-thanks">✓ Đã ghi nhận. Cảm ơn bà con!</div>';
  }
}

function skipReport(msgId) {
  document.getElementById(`sc-${msgId}`)?.remove();
}

async function submitReason(msgId) {
  const row = document.getElementById(msgId);
  const reason = document.getElementById(`reasonText-${msgId}`)?.value.trim() || '';
  document.getElementById(`reason-${msgId}`)?.classList.remove('show');
  await _postFeedback({
    question: row?.dataset?.question || '', answer: row?.dataset?.answer || '',
    rating: -1, reason,
    submission_id: row?.dataset?.submissionId ? parseInt(row.dataset.submissionId) : null,
  });
}
async function submitReasonSkip(msgId) { await submitReason(msgId); }

async function sendActiveFeedback(msgId, rating) {
  const card = document.getElementById(msgId);
  card.querySelectorAll('.fc-up, .fc-down').forEach(b => b.disabled = true);
  if (rating === 1) {
    card.querySelector('.fc-btns').innerHTML = '<span style="font-size:13px;color:#2e7d32;">✓ Cảm ơn bà con! 🙏</span>';
    document.getElementById(`reason-${msgId}`)?.remove();
    await _postFeedback({
      question: card.dataset.question, answer: card.dataset.answer, rating: 1,
      submission_id: card.dataset.submissionId ? parseInt(card.dataset.submissionId) : null,
    });
  } else {
    card.querySelector('.fc-btns').innerHTML = '<span style="font-size:13px;color:#e65100;">Bà con thấy còn thiếu gì?</span>';
    document.getElementById(`reason-${msgId}`).classList.add('show');
    scrollBottom();
  }
  localStorage.setItem('feedback-date', new Date().toISOString().slice(0,10));
  activeFeedbackShownToday = true;
}

/* ── Voice Input ── */
const micBtn = document.getElementById('micBtn');
let recognition = null, isRecording = false;

function initVoice() {
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SR) return null;
  const r = new SR();
  r.lang = 'vi-VN'; r.continuous = false; r.interimResults = true;
  r.onstart = () => { isRecording = true; micBtn.classList.add('recording'); micBtn.title = 'Đang nghe... (bấm để dừng)'; inputEl.placeholder = '🎙️ Đang nghe...'; };
  r.onresult = e => { inputEl.value = Array.from(e.results).map(r => r[0].transcript).join(''); autoResize(inputEl); };
  r.onend = () => { isRecording = false; micBtn.classList.remove('recording'); micBtn.title = 'Nói'; inputEl.placeholder = 'Nhắn tin hoặc gửi ảnh sâu bệnh...'; if (inputEl.value.trim()) sendMessage(); };
  r.onerror = e => { isRecording = false; micBtn.classList.remove('recording'); inputEl.placeholder = 'Nhắn tin hoặc gửi ảnh sâu bệnh...'; if (e.error === 'not-allowed') addBotMessage('⚠️ Vui lòng cho phép truy cập microphone trong cài đặt trình duyệt.'); };
  return r;
}

function toggleVoice() {
  if (!(window.SpeechRecognition || window.webkitSpeechRecognition)) {
    addBotMessage('⚠️ Trình duyệt của bạn chưa hỗ trợ nhận dạng giọng nói. Hãy dùng Chrome hoặc Edge.');
    return;
  }
  if (isRecording) { recognition?.stop(); return; }
  recognition = initVoice();
  recognition?.start();
}

/* ── PWA Install ── */
let deferredPrompt = null;
const installBanner = document.getElementById('installBanner');
const installBtn    = document.getElementById('installBtn');
const installHint   = document.getElementById('installHint');

function isIOS() { return /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream; }
function isInStandaloneMode() { return window.matchMedia('(display-mode: standalone)').matches || window.navigator.standalone; }

if ('serviceWorker' in navigator) navigator.serviceWorker.register('/static/sw.js').catch(() => {});

window.addEventListener('beforeinstallprompt', e => {
  e.preventDefault(); deferredPrompt = e;
  if (!localStorage.getItem('pwa-dismissed')) installBanner.style.display = 'flex';
});

if (isIOS() && !isInStandaloneMode() && !localStorage.getItem('pwa-dismissed')) {
  installHint.textContent = 'Cài như app, mở nhanh hơn, dùng được offline';
  installBtn.textContent  = 'Xem cách cài';
  installBtn.onclick = () => document.getElementById('iosOverlay').classList.add('show');
  installBanner.style.display = 'flex';
}

function closeIosModal(e) {
  if (e && e.target !== document.getElementById('iosOverlay')) return;
  document.getElementById('iosOverlay').classList.remove('show');
}
async function doInstall() {
  if (!deferredPrompt) return;
  deferredPrompt.prompt();
  const { outcome } = await deferredPrompt.userChoice;
  deferredPrompt = null;
  if (outcome === 'accepted') installBanner.style.display = 'none';
}
function dismissBanner() { installBanner.style.display = 'none'; localStorage.setItem('pwa-dismissed', '1'); }
window.addEventListener('appinstalled', () => { installBanner.style.display = 'none'; });

/* ── Push Notifications ── */
async function initPush() {
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) return;
  if (localStorage.getItem('push-declined')) return;
  const res = await fetch('/api/vapid-public-key').catch(() => null);
  if (!res?.ok) return;
  const { enabled, key } = await res.json();
  if (!enabled) return;
  const reg = await navigator.serviceWorker.ready;
  if (await reg.pushManager.getSubscription()) return;
  setTimeout(async () => {
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') { localStorage.setItem('push-declined', '1'); return; }
    try {
      const sub = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(key) });
      await fetch('/api/push-subscribe', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(sub.toJSON()) });
    } catch {}
  }, 10000);
}
function urlBase64ToUint8Array(b64) {
  const padding = '='.repeat((4 - b64.length % 4) % 4);
  const base64 = (b64 + padding).replace(/-/g, '+').replace(/_/g, '/');
  return Uint8Array.from([...atob(base64)].map(c => c.charCodeAt(0)));
}
initPush();

/* ── Premium ── */
function showQuotaExceeded(type) {
  const msg = type === 'image'
    ? '📷 Bạn đã dùng hết 2 ảnh miễn phí hôm nay.\n\nNhập mã để gửi thêm ảnh, hoặc hỏi bằng văn bản mô tả triệu chứng nhé!'
    : '🍅 Bạn đã dùng hết 5 câu hỏi miễn phí hôm nay.\n\nNhập mã để tiếp tục, hoặc quay lại vào ngày mai!';
  const div = document.createElement('div');
  div.className = 'msg-bot';
  div.innerHTML = `<div class="bot-avatar">🍅</div><div class="bubble">${msg.replace(/\n/g,'<br>')}<br><br>
    <button onclick="openRedeemModal()" style="background:#2e7d32;color:white;border:none;border-radius:20px;padding:8px 18px;font-size:13px;font-weight:700;cursor:pointer;">🎟️ Nhập mã kích hoạt</button>
  </div>`;
  messagesEl.appendChild(div); scrollBottom();
}
function openRedeemModal() {
  document.getElementById('redeemInput').value = '';
  document.getElementById('redeemMsg').textContent = '';
  document.getElementById('redeemOverlay').classList.add('show');
  setTimeout(() => document.getElementById('redeemInput').focus(), 100);
}
function closeRedeemModal() { document.getElementById('redeemOverlay').classList.remove('show'); }
async function submitCode() {
  const code = document.getElementById('redeemInput').value.trim();
  const msg  = document.getElementById('redeemMsg');
  if (!code) return;
  msg.style.color = '#888'; msg.textContent = 'Đang kiểm tra...';
  try {
    const res = await fetch('/api/redeem', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ code }) });
    const data = await res.json();
    if (res.ok) {
      msg.style.color = '#2e7d32';
      msg.textContent = `✓ Kích hoạt thành công! +${data.requests} câu hỏi${data.images ? ` · +${data.images} ảnh` : ''}.`;
      setTimeout(closeRedeemModal, 2000);
    } else { msg.style.color = '#ef5350'; msg.textContent = '✗ ' + (data.detail || 'Mã không hợp lệ'); }
  } catch { msg.style.color = '#ef5350'; msg.textContent = '✗ Lỗi kết nối'; }
}

/* ── Quota badge ── */
async function updateQuota() {
  try {
    const res = await fetch('/api/quota');
    if (!res.ok) return;
    const { free, premium, points } = await res.json();
    const badge = document.getElementById('quotaBadge');
    const totalPremium = premium.requests || 0;
    const pts = points?.current || 0;
    const perQ = points?.per_question || 20;

    if (totalPremium > 0) {
      badge.textContent = `🎟️ ${totalPremium} câu premium`;
      badge.className = 'quota-badge premium';
    } else if (free.requests <= 0) {
      badge.textContent = pts > 0 ? `⛔ Hết quota · ⭐${pts}/${perQ}đ` : '⛔ Hết quota hôm nay';
      badge.className = 'quota-badge low';
    } else if (free.requests <= 2) {
      badge.textContent = `⚠️ Còn ${free.requests} câu · ⭐${pts}đ`;
      badge.className = 'quota-badge low';
    } else {
      badge.textContent = pts > 0 ? `💬 Còn ${free.requests} câu · ⭐${pts}đ` : `💬 Còn ${free.requests} câu`;
      badge.className = 'quota-badge';
    }
  } catch {}
}
updateQuota();

if (localStorage.getItem('region') || localStorage.getItem('region-skipped')) {
  document.getElementById('shareTipBtn').style.display = 'flex';
  firstMessageSent = true;
}

/* ── Vùng trồng ── */
function openRegionModal() {
  if (userRegion) document.getElementById('regionSelect').value = userRegion;
  document.getElementById('regionOverlay').classList.add('show');
}
function closeRegionModal() { document.getElementById('regionOverlay').classList.remove('show'); localStorage.setItem('region-skipped', '1'); }
async function saveRegion() {
  const region = document.getElementById('regionSelect').value;
  if (!region) { alert('Vui lòng chọn vùng trồng'); return; }
  userRegion = region;
  localStorage.setItem('region', region);
  localStorage.removeItem('region-skipped');
  document.getElementById('regionOverlay').classList.remove('show');
  showSeasonBanner();
  await fetch('/api/user-region', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region }) }).catch(() => {});
}
function requestGPS() {
  if (!navigator.geolocation) { alert('Trình duyệt không hỗ trợ định vị'); return; }
  navigator.geolocation.getCurrentPosition(
    pos => {
      userLat = pos.coords.latitude; userLon = pos.coords.longitude;
      localStorage.setItem('gps-lat', userLat); localStorage.setItem('gps-lon', userLon);
      document.getElementById('regionOverlay').classList.remove('show');
      showSeasonBanner();
      if (!userRegion) {
        userRegion = document.getElementById('regionSelect').value || '';
        if (userRegion) { localStorage.setItem('region', userRegion); fetch('/api/user-region', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ region: userRegion }) }).catch(() => {}); }
      }
    },
    () => alert('Không lấy được vị trí. Vui lòng chọn vùng thủ công.')
  );
}
const savedLat = parseFloat(localStorage.getItem('gps-lat') || '0');
const savedLon = parseFloat(localStorage.getItem('gps-lon') || '0');
if (savedLat && savedLon) { userLat = savedLat; userLon = savedLon; }

/* ── Community tips ── */
function openTipModal() {
  document.getElementById('tipTitle').value = '';
  document.getElementById('tipContent').value = '';
  document.getElementById('tipMsg').textContent = '';
  document.getElementById('tipOverlay').classList.add('show');
  setTimeout(() => document.getElementById('tipTitle').focus(), 100);
}
function closeTipModal() { document.getElementById('tipOverlay').classList.remove('show'); }
async function submitTip() {
  const title    = document.getElementById('tipTitle').value.trim();
  const content  = document.getElementById('tipContent').value.trim();
  const category = document.getElementById('tipCategory').value;
  const msgEl    = document.getElementById('tipMsg');
  if (title.length < 5)    { msgEl.style.color = '#ef5350'; msgEl.textContent = 'Tiêu đề quá ngắn'; return; }
  if (content.length < 100) { msgEl.style.color = '#ef5350'; msgEl.textContent = 'Nội dung quá ngắn (ít nhất 100 ký tự)'; return; }
  msgEl.style.color = '#888'; msgEl.textContent = 'Đang gửi...';
  try {
    const res = await fetch('/api/community-tips', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title, content, category, region: userRegion }) });
    const data = await res.json();
    if (data.ok) {
      if (data.auto_approved) {
        msgEl.style.color = '#2e7d32';
        msgEl.textContent = '✅ Kinh nghiệm của bà con đã được xác nhận và thêm vào kho kiến thức ngay!';
      } else {
        msgEl.style.color = '#2e7d32';
        msgEl.textContent = '✓ Cảm ơn bà con! Admin sẽ xem xét và bổ sung vào kho kiến thức.';
      }
      if (data.points) {
        const action = data.auto_approved ? 'tip_approved' : 'tip';
        showBonusToast(data.points, data.questions_added || 0, action, data.current_points, 20);
      }
      setTimeout(closeTipModal, 2800);
    } else {
      msgEl.style.color = '#ef5350';
      msgEl.textContent = '✗ ' + (data.reason || data.detail || 'Thông tin chưa phù hợp.');
    }
  } catch { msgEl.style.color = '#ef5350'; msgEl.textContent = '✗ Lỗi kết nối'; }
}

/* ── Quick ask ── */
function quickAsk(btn) { inputEl.value = btn.textContent.replace(/^[\p{Emoji}\s]+/u, '').trim(); sendMessage(); }

/* ── New session ── */
async function newSession() {
  await fetch('/api/new-session', { method: 'POST' }).catch(() => {});
  messagesEl.innerHTML = '';
  const sep = document.createElement('div');
  sep.className = 'msg-time';
  sep.textContent = '— Cuộc trò chuyện mới —';
  messagesEl.appendChild(sep);
  firstMessageSent = false;
  document.getElementById('shareTipBtn').style.display = 'none';
}

/* ── Gửi tin nhắn ── */
async function sendMessage() {
  const text  = inputEl.value.trim();
  const image = pendingImage;
  if (!text && !image) return;
  if (sendBtn.disabled) return;

  inputEl.value = ''; inputEl.style.height = 'auto';
  removeImage(); sendBtn.disabled = true;
  addUserMessage(text, image);
  showTyping();

  try {
    const body = { message: text, image, region: userRegion };
    if (userLat && userLon) { body.lat = userLat; body.lon = userLon; }

    const res = await fetch('/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

    if (res.status === 429) {
      const err = await res.json(); removeTyping();
      if (err.detail === 'QUOTA_EXCEEDED') showQuotaExceeded('text');
      else if (err.detail === 'IMAGE_QUOTA_EXCEEDED') showQuotaExceeded('image');
      else addBotMessage('⏳ ' + (err.detail || 'Quá nhiều yêu cầu. Vui lòng thử lại sau.'));
      return;
    }

    const data = await res.json();
    const answer = data.answer || 'Xin lỗi, có lỗi xảy ra.';
    removeTyping();
    const showActive = !activeFeedbackShownToday && !!text && !answer.startsWith('Lỗi') && !answer.startsWith('Hệ thống');
    addBotMessage(answer, text, data.submission_id || null, showActive);
    if (showActive) activeFeedbackShownToday = true;

    updateQuota();

    if (!firstMessageSent) {
      firstMessageSent = true;
      document.getElementById('shareTipBtn').style.display = 'flex';
      if (!userRegion && !localStorage.getItem('region-skipped')) setTimeout(() => openRegionModal(), 1500);
    }
  } catch (err) {
    removeTyping();
    addBotMessage('⚠️ Mất kết nối đến server. Vui lòng kiểm tra mạng và thử lại.');
  } finally {
    sendBtn.disabled = false;
    inputEl.focus();
  }
}
