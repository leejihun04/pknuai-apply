'use strict';
// The page talks to the local server only. Every state-changing call carries
// the X-Pknuai-Apply header the server insists on, which a cross-site form
// cannot set.

const $ = (id) => document.getElementById(id);
let state = null;
let query = '';
let pendingCode = '';

async function api(path, options = {}) {
  const headers = Object.assign({ 'X-Pknuai-Apply': '1' }, options.headers || {});
  const response = await fetch(path, Object.assign({}, options, { headers }));
  const type = response.headers.get('Content-Type') || '';
  if (!type.includes('application/json')) return { ok: response.ok };
  return response.json();
}

function toast(message) {
  const box = $('toast');
  box.textContent = message;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { box.hidden = true; }, 4200);
}

function relative(epoch) {
  if (!epoch) return '';
  let seconds = Math.round(epoch - Date.now() / 1000);
  if (seconds <= 0) return '지금';
  const days = Math.floor(seconds / 86400); seconds -= days * 86400;
  const hours = Math.floor(seconds / 3600); seconds -= hours * 3600;
  const minutes = Math.floor(seconds / 60);
  if (days) return `${days}일 ${hours}시간 뒤`;
  if (hours) return `${hours}시간 ${minutes}분 뒤`;
  if (minutes) return `${minutes}분 ${seconds % 60}초 뒤`;
  return `${seconds % 60}초 뒤`;
}

function badge(text, tone) {
  const span = document.createElement('span');
  span.className = 'badge' + (tone ? ' ' + tone : '');
  span.textContent = text;
  return span;
}

function button(label, tone, handler) {
  const element = document.createElement('button');
  element.type = 'button';
  if (tone) element.className = tone;
  element.textContent = label;
  element.addEventListener('click', async () => {
    element.disabled = true;
    try { await handler(); } finally { element.disabled = false; }
  });
  return element;
}

function renderPills() {
  const sessionPill = $('pill-session');
  const stored = state.session.stored;
  sessionPill.textContent = stored ? '세션 저장됨' : '세션 없음';
  sessionPill.className = 'pill ' + (stored ? 'ok' : 'bad');
  if (state.error) { sessionPill.textContent = '세션 확인 필요'; sessionPill.className = 'pill bad'; }

  const watcherPill = $('pill-watcher');
  const watcher = state.watcher;
  watcherPill.textContent = watcher.running ? '감시자 실행 중'
    : (watcher.installed ? '감시자 정지됨' : '감시자 미등록');
  watcherPill.className = 'pill ' + (watcher.running ? 'ok' : 'warn');
  watcherPill.title = watcher.running ? watcher.label
    : '터미널에서 `pknuai-apply install-agent` 를 실행하면 로그인할 때마다 자동으로 켜집니다.';

  $('session-card').hidden = stored && !state.error;
  if (state.error) $('session-result').textContent = state.error;
  const browsers = state.browsers || [];
  const importBtn = $('import-session');
  if (importBtn) {
    importBtn.disabled = browsers.length === 0;
    $('browser-hint').textContent = browsers.length
      ? `가져올 수 있는 브라우저: ${browsers.join(', ')} · 처음 한 번은 키체인 접근을 '허용'하면 됩니다.`
      : '설치된 브라우저를 찾지 못했습니다. 아래 "직접 붙여넣기"를 사용하세요.';
  }
}

function renderReservations() {
  const card = $('reservations-card');
  const rows = state.reservations || [];
  card.hidden = rows.length === 0;
  $('reservation-count').textContent = rows.length ? `${rows.length}건` : '';
  const box = $('reservations');
  box.textContent = '';
  rows.forEach((row) => {
    const item = document.createElement('div');
    item.className = 'item reserved';
    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = row.title || row.code;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.appendChild(document.createTextNode(
      row.opensAt ? `모집 시작 ${row.opensLabel} · ${relative(row.opensAt)}` : '모집 시작 시각 미확인'
    ));
    if (row.lastKind) meta.appendChild(badge(row.lastDetail || row.lastKind, 'warn'));
    if (row.attachment) meta.appendChild(badge(
      row.withAttachment ? `첨부 ${row.attachment}` : `첨부 ${row.attachment} (제출 꺼짐)`,
      row.withAttachment ? 'ok' : 'warn'
    ));
    const actions = document.createElement('div');
    actions.className = 'actions';
    actions.appendChild(button('지금 시도', 'ghost', () => applyNow(row.code, false)));
    actions.appendChild(button('가능 여부만 확인', 'ghost', () => applyNow(row.code, true)));
    actions.appendChild(button('예약 취소', 'danger', () => reserve(row.code, false)));
    const link = document.createElement('a');
    link.href = row.url; link.target = '_blank'; link.rel = 'noreferrer noopener';
    link.textContent = '원문';
    actions.appendChild(link);
    item.append(title, meta, actions);
    box.appendChild(item);
  });
}

function renderPrograms() {
  const box = $('programs');
  box.textContent = '';
  const rows = state.programs || [];
  if (!rows.length) {
    const empty = document.createElement('div');
    empty.className = 'empty';
    empty.textContent = state.session.stored ? '표시할 프로그램이 없습니다.' : '세션을 저장하면 목록이 나타납니다.';
    box.appendChild(empty);
    return;
  }
  rows.forEach((program) => {
    const item = document.createElement('div');
    item.className = 'item' + (program.reserved ? ' reserved' : '');
    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = program.title;
    const meta = document.createElement('div');
    meta.className = 'meta';
    meta.appendChild(document.createTextNode(`${program.id} · 모집 ${program.recruit_text || '-'}`));
    if (program.reserved) meta.appendChild(badge('예약됨', 'ok'));
    if (program.seat) meta.appendChild(badge(program.seat === '수강중' ? '수강 중' : '신청함', 'ok'));
    if (program.record) {
      const status = program.record.status;
      meta.appendChild(badge(
        status === 'applied' ? '신청 완료' : status === 'already' ? '이미 신청됨'
          : `${program.record.reason || status}`,
        status === 'applied' || status === 'already' ? 'ok' : 'warn'
      ));
    }
    if (program.attachment) meta.appendChild(badge(`첨부 ${program.attachment}`, 'ok'));

    const actions = document.createElement('div');
    actions.className = 'actions';
    if (program.reserved) {
      actions.appendChild(button('예약 취소', 'danger', () => reserve(program.id, false)));
      actions.appendChild(button(
        program.withAttachment ? '첨부 제출 끄기' : '첨부 제출 켜기', 'ghost',
        () => reserve(program.id, true, !program.withAttachment)
      ));
    } else if (!program.record) {
      actions.appendChild(button('예약', '', () => reserve(program.id, true)));
    }
    // A programme already settled cannot take a new file through this tool,
    // so offering the upload there would be a button that does nothing useful.
    if (!program.record) {
      actions.appendChild(button(program.attachment ? '첨부 교체' : '첨부 올리기', 'ghost',
        () => pickFile(program.id)));
    }
    if (program.attachment) {
      const download = document.createElement('a');
      download.href = `/api/attachment/${encodeURIComponent(program.id)}`;
      download.textContent = '첨부 열기';
      actions.appendChild(download);
      actions.appendChild(button('첨부 삭제', 'danger', () => deleteAttachment(program.id)));
    }
    const link = document.createElement('a');
    link.href = program.url; link.target = '_blank'; link.rel = 'noreferrer noopener';
    link.textContent = '원문';
    actions.appendChild(link);
    item.append(title, meta, actions);
    box.appendChild(item);
  });
}

function render() {
  if (!state) return;
  renderPills();
  renderReservations();
  renderPrograms();
  $('log').textContent = (state.log || []).join('\n');
  $('fetched').textContent = state.fetchedAt
    ? `목록 갱신 ${new Date(state.fetchedAt * 1000).toLocaleTimeString('ko-KR')}` : '';
}

async function load(refresh) {
  const url = `/api/state?q=${encodeURIComponent(query)}${refresh ? '&refresh=1' : ''}`;
  try {
    state = await (await fetch(url)).json();
    render();
  } catch (error) {
    toast('로컬 서버에 연결하지 못했습니다.');
  }
}

async function reserve(code, reserved, withAttachment) {
  const body = { code, reserved };
  if (withAttachment !== undefined) body.withAttachment = withAttachment;
  const result = await api('/api/reserve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  toast(result.ok ? (reserved ? '예약했습니다.' : '예약을 취소했습니다.')
    : (result.reason || '처리하지 못했습니다.'));
  await load(false);
}

async function applyNow(code, dryRun) {
  toast(dryRun ? '확인 중…' : '신청 중…');
  const result = await api('/api/apply', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code, dryRun }),
  });
  if (!result.ok) { toast(result.reason || '시도하지 못했습니다.'); await load(false); return; }
  const outcome = result.outcome || {};
  const labels = {
    applied: '✅ 신청했습니다', already: 'ℹ️ 이미 신청되어 있습니다',
    would_apply: '🧪 지금 신청할 수 있는 상태입니다', skipped: '⏭️ 건너뛰었습니다',
    failed: '⚠️ 실패했습니다', login_required: '🔑 세션이 만료되었습니다',
  };
  toast(`${labels[outcome.status] || outcome.status}${outcome.reason ? ' — ' + outcome.reason : ''}`);
  await load(false);
}

function pickFile(code) {
  pendingCode = code;
  $('file-input').click();
}

async function deleteAttachment(code) {
  await api(`/api/attachment/${encodeURIComponent(code)}`, { method: 'DELETE' });
  toast('첨부파일을 삭제했습니다.');
  await load(false);
}

$('file-input').addEventListener('change', async (event) => {
  const file = event.target.files[0];
  event.target.value = '';
  if (!file || !pendingCode) return;
  const form = new FormData();
  form.append('file', file, file.name);
  const result = await api(`/api/attachment/${encodeURIComponent(pendingCode)}`,
    { method: 'POST', body: form });
  toast(result.ok ? `첨부파일을 저장했습니다: ${result.name}` : (result.reason || '올리지 못했습니다.'));
  pendingCode = '';
  await load(false);
});

const importBtn = $('import-session');
if (importBtn) {
  importBtn.addEventListener('click', async () => {
    importBtn.disabled = true;
    $('session-result').textContent = '브라우저에서 세션을 찾는 중… (키체인 팝업이 뜨면 허용)';
    try {
      const result = await api('/api/session/import', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      });
      $('session-result').textContent = result.reason || '';
      toast(result.ok ? '세션을 가져왔습니다.' : (result.reason || '가져오지 못했습니다.'));
      await load(true);
    } finally {
      importBtn.disabled = false;
    }
  });
}

const openLoginBtn = $('open-login');
if (openLoginBtn) {
  openLoginBtn.addEventListener('click', async () => {
    const result = await api('/api/session/open-login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
    $('session-result').textContent = result.reason || '';
    toast('브라우저에서 로그인을 마치면 자동으로 연결됩니다.');
    // Poll a little faster while we wait for the login to land.
    let tries = 0;
    const timer = setInterval(async () => {
      await load(false);
      if ((state && state.session && state.session.stored && !state.error) || ++tries > 100) {
        clearInterval(timer);
      }
    }, 3000);
  });
}

$('save-session').addEventListener('click', async () => {
  const cookie = $('cookie').value.trim();
  if (!cookie) { toast('쿠키를 붙여넣어 주세요.'); return; }
  $('session-result').textContent = '확인 중…';
  const result = await api('/api/session', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ cookie }),
  });
  $('session-result').textContent = result.reason || '';
  if (result.ok) { $('cookie').value = ''; toast('세션을 저장했습니다.'); }
  await load(true);
});

$('refresh').addEventListener('click', () => load(true));
$('query').addEventListener('input', (event) => {
  query = event.target.value;
  clearTimeout($('query').timer);
  $('query').timer = setTimeout(() => load(false), 220);
});

load(false);
setInterval(() => load(false), 15000);
// The countdowns move every second without asking the server anything.
setInterval(() => { if (state) renderReservations(); }, 1000);
