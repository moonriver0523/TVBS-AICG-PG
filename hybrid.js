/* 混合版型原型（階段0）：AI 生成無文字背景，APP 用 SVG 繪製全部文字與數字。
   驗證目標：繁中字型清晰度、版面/安全區穩定、1280×720 PNG 匯出。

   整段包在 IIFE 內：本檔與 app.js 在 index.html 第三分頁會同時載入，
   兩邊都有 state / IMAGE_BACKEND_URL 等頂層宣告，不隔離會直接 SyntaxError。
   對外只露出 window.initHybrid()（重複呼叫安全，元素不存在時直接跳過）。 */
(function () {

const IMAGE_BACKEND_URL = 'http://127.0.0.1:8787/api/images/generate';
const SVG_NS = 'http://www.w3.org/2000/svg';

/* 版型定義：內容(放什麼) / 版型(放哪裡) / AI圖(背景長怎樣) 三者分離。
   AI 不得產生座標——座標只存在這裡。 */
const TEMPLATE = {
  id: 'market-three-column',
  name: '大標題＋三欄比較',
  canvas: { width: 1280, height: 720 },
  safeArea: { top: 72, left: 80, right: 80, bottom: 144 },
  slots: {
    title:    { cx: 640, baseline: 118, fontSize: 52, maxWidth: 1120 },
    subtitle: { cx: 640, baseline: 162, fontSize: 24 },
    cards:    { x: 80, y: 196, width: 1120, height: 324, columns: 3, gap: 24 },
    source:   { x: 1200, baseline: 560, fontSize: 18 }
  }
};

const state = {
  content: null,      // 由表單收集
  bgDataUri: null,    // AI 背景（data URI），重生背景不會清內容
  bgModel: ''
};

/* ---- 表單 ---- */

const DEFAULT_ITEMS = [
  { label: '道瓊', value: '44,023.29', change: '0.98%', direction: 'down' },
  { label: 'NASDAQ', value: '22,682.73', change: '0.31%', direction: 'down' },
  { label: 'S&P 500', value: '6,861.89', change: '0.28%', direction: 'down' }
];

function buildItemRows() {
  const host = document.getElementById('items');
  DEFAULT_ITEMS.forEach((it, i) => {
    const row = document.createElement('div');
    row.className = 'item-row';
    row.innerHTML = `
      <input type="text" data-k="label" data-i="${i}" value="${it.label}">
      <input type="text" data-k="value" data-i="${i}" value="${it.value}">
      <input type="text" data-k="change" data-i="${i}" value="${it.change}">
      <select data-k="direction" data-i="${i}">
        <option value="down"${it.direction === 'down' ? ' selected' : ''}>▼跌</option>
        <option value="up"${it.direction === 'up' ? ' selected' : ''}>▲漲</option>
        <option value="flat"${it.direction === 'flat' ? ' selected' : ''}>–平</option>
      </select>`;
    host.appendChild(row);
  });
}

function readContent() {
  const items = [0, 1, 2].map(i => {
    const g = (k) => document.querySelector(`[data-k="${k}"][data-i="${i}"]`).value.trim();
    return { label: g('label'), value: g('value'), change: g('change'), direction: g('direction') };
  });
  return {
    title: document.getElementById('f-title').value.trim(),
    subtitle: document.getElementById('f-subtitle').value.trim(),
    items,
    source: document.getElementById('f-source').value.trim(),
    visual_subject: document.getElementById('f-visual').value.trim()
  };
}

/* ---- SVG 渲染 ---- */

function el(name, attrs, children) {
  const node = document.createElementNS(SVG_NS, name);
  for (const [k, v] of Object.entries(attrs || {})) node.setAttribute(k, v);
  (children || []).forEach(c => node.appendChild(c));
  return node;
}

function textEl(str, attrs) {
  const t = el('text', Object.assign({
    'font-family': '"Microsoft JhengHei", "Noto Sans TC", sans-serif'
  }, attrs));
  t.textContent = str;
  return t;
}

/* 台灣新聞慣例：紅漲綠跌 */
const DIR_STYLE = {
  up:   { color: '#ff4d4d', arrow: '▲' },
  down: { color: '#2ee06e', arrow: '▼' },
  flat: { color: '#b9c2d8', arrow: '—' }
};

function render() {
  const c = state.content = readContent();
  const { width: W, height: H } = TEMPLATE.canvas;
  const S = TEMPLATE.slots;

  const svg = el('svg', {
    xmlns: SVG_NS, width: W, height: H, viewBox: `0 0 ${W} ${H}`,
    id: 'compose-svg'
  });

  // defs：漸層與陰影
  const defs = el('defs');
  defs.innerHTML = `
    <linearGradient id="g-fallback" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#101a33"/><stop offset="1" stop-color="#070b16"/>
    </linearGradient>
    <linearGradient id="g-top" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="rgba(4,8,18,0.88)"/><stop offset="1" stop-color="rgba(4,8,18,0)"/>
    </linearGradient>
    <linearGradient id="g-card" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="rgba(13,22,44,0.86)"/><stop offset="1" stop-color="rgba(7,12,26,0.86)"/>
    </linearGradient>
    <filter id="f-shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="3" stdDeviation="4" flood-color="#000" flood-opacity="0.65"/>
    </filter>`;
  svg.appendChild(defs);

  // Layer 1：AI 背景（無背景時用深藍漸層墊底）
  const bgLayer = el('g', { id: 'layer-bg' });
  if (state.bgDataUri) {
    bgLayer.appendChild(el('image', {
      href: state.bgDataUri, x: 0, y: 0, width: W, height: H,
      preserveAspectRatio: 'xMidYMid slice'
    }));
  } else {
    bgLayer.appendChild(el('rect', { x: 0, y: 0, width: W, height: H, fill: 'url(#g-fallback)' }));
  }
  svg.appendChild(bgLayer);

  // Layer 2：遮罩——標題區壓暗，確保白字對比
  const scrim = el('g', { id: 'layer-scrim' });
  scrim.appendChild(el('rect', { x: 0, y: 0, width: W, height: 200, fill: 'url(#g-top)' }));
  svg.appendChild(scrim);

  // Layer 3：三欄資訊卡
  const cards = el('g', { id: 'layer-cards' });
  const cardW = (S.cards.width - S.cards.gap * (S.cards.columns - 1)) / S.cards.columns;
  c.items.forEach((it, i) => {
    const x = S.cards.x + i * (cardW + S.cards.gap);
    const y = S.cards.y;
    const dir = DIR_STYLE[it.direction] || DIR_STYLE.flat;
    const cx = x + cardW / 2;
    cards.appendChild(el('rect', {
      x, y, width: cardW, height: S.cards.height, rx: 14,
      fill: 'url(#g-card)', stroke: 'rgba(120,150,220,0.35)', 'stroke-width': 1.5
    }));
    cards.appendChild(el('rect', { x, y, width: cardW, height: 5, rx: 2.5, fill: dir.color }));
    cards.appendChild(textEl(it.label, {
      x: cx, y: y + 76, 'font-size': 30, 'font-weight': 'bold',
      fill: '#dfe7f7', 'text-anchor': 'middle'
    }));
    // 長數值自動縮字級，避免撐出卡片（文字溢位精細檢查留待階段1）
    const vLen = it.value.length;
    const vSize = vLen > 12 ? 28 : vLen > 8 ? 36 : 48;
    const hasChange = it.change || it.direction !== 'flat';
    cards.appendChild(textEl(it.value, {
      x: cx, y: hasChange ? y + 172 : y + 190, 'font-size': vSize,
      'font-weight': 'bold', fill: '#ffffff', 'text-anchor': 'middle'
    }));
    if (hasChange) {
      cards.appendChild(textEl(`${dir.arrow} ${it.change}`.trim(), {
        x: cx, y: y + 252, 'font-size': 34, 'font-weight': 'bold',
        fill: dir.color, 'text-anchor': 'middle'
      }));
    }
  });
  svg.appendChild(cards);

  // Layer 4：標題／次標題／資料來源（全部真字型，非 AI 像素）
  const texts = el('g', { id: 'layer-text' });
  texts.appendChild(textEl(c.title, {
    x: S.title.cx, y: S.title.baseline, 'font-size': S.title.fontSize,
    'font-weight': 'bold', fill: '#ffffff', 'text-anchor': 'middle',
    filter: 'url(#f-shadow)'
  }));
  if (c.subtitle) {
    texts.appendChild(textEl(c.subtitle, {
      x: S.subtitle.cx, y: S.subtitle.baseline, 'font-size': S.subtitle.fontSize,
      fill: '#ffc843', 'text-anchor': 'middle', filter: 'url(#f-shadow)'
    }));
  }
  if (c.source) {
    texts.appendChild(textEl(c.source, {
      x: S.source.x, y: S.source.baseline, 'font-size': S.source.fontSize,
      fill: 'rgba(215,225,245,0.8)', 'text-anchor': 'end'
    }));
  }
  svg.appendChild(texts);

  // Layer 5：安全區輔助線（僅預覽，匯出時移除）
  if (document.getElementById('f-guides').checked) {
    const sa = TEMPLATE.safeArea;
    const guides = el('g', { id: 'layer-guides' });
    guides.appendChild(el('rect', {
      x: sa.left, y: sa.top, width: W - sa.left - sa.right, height: H - sa.top - sa.bottom,
      fill: 'none', stroke: '#00e5ff', 'stroke-width': 2, 'stroke-dasharray': '10 6'
    }));
    guides.appendChild(el('rect', {
      x: 0, y: H - sa.bottom, width: W, height: sa.bottom,
      fill: 'rgba(255,60,60,0.14)', stroke: 'none'
    }));
    guides.appendChild(textEl('底部安全區（下標蓋台區）', {
      x: 16, y: H - sa.bottom + 30, 'font-size': 20, fill: '#ff8080'
    }));
    svg.appendChild(guides);
  }

  const host = document.getElementById('svgHost');
  host.innerHTML = '';
  host.appendChild(svg);
}

/* ---- AI 背景生成：只給視覺，鐵律禁文字 ---- */

function buildBgPrompt(c) {
  return `Generate a text-free broadcast news background image.

Subject:
${c.visual_subject}

Requirements:
- 16:9 wide cinematic composition, professional TV news studio quality
- Absolutely NO text, NO numbers, NO letters, NO logos, NO watermarks, NO captions, NO user interface elements of any kind
- Keep the top fifth of the frame relatively dark and visually calm (a headline will be overlaid there)
- Keep the central band visually quiet with soft depth of field (three information panels will be overlaid there)
- Keep the bottom fifth simple and dark
- Dark navy blue overall tone, subtle atmospheric lighting, pure background imagery only`;
}

async function generateBackground() {
  const btn = document.getElementById('btnBg');
  const status = document.getElementById('status');
  const c = readContent();
  btn.disabled = true;
  status.textContent = '背景生成中…（約 30–120 秒）';
  try {
    const res = await fetch(IMAGE_BACKEND_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        prompt: buildBgPrompt(c),
        provider: document.getElementById('f-provider').value,
        aspect_ratio: '16:9',
        image_size: '1K'
      })
    });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();
    state.bgDataUri = `data:${data.mime_type};base64,${data.image_data_base64}`;
    state.bgModel = data.model;
    status.textContent = `背景完成（${data.model}）— 文字與數字未受影響`;
    render();
  } catch (e) {
    status.textContent = '背景生成失敗：' + e.message;
  } finally {
    btn.disabled = false;
  }
}

/* ---- 匯出 PNG：SVG（含內嵌背景）→ canvas 1280×720 → 下載 ---- */

async function exportPNG() {
  const status = document.getElementById('status');
  const { width: W, height: H } = TEMPLATE.canvas;

  const svg = document.getElementById('compose-svg').cloneNode(true);
  const guides = svg.querySelector('#layer-guides');
  if (guides) guides.remove();

  const svgText = new XMLSerializer().serializeToString(svg);
  const svgUri = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(svgText);

  const img = new Image();
  await new Promise((ok, bad) => {
    img.onload = ok;
    img.onerror = () => bad(new Error('SVG 轉圖失敗'));
    img.src = svgUri;
  });

  const canvas = document.createElement('canvas');
  canvas.width = W; canvas.height = H;
  canvas.getContext('2d').drawImage(img, 0, 0, W, H);

  const ts = new Date().toISOString().replace(/[-:T]/g, '').slice(0, 14);
  const a = document.createElement('a');
  a.download = `hybrid-${TEMPLATE.id}-${ts}.png`;
  a.href = canvas.toDataURL('image/png');
  a.click();
  status.textContent = '已匯出 ' + a.download;
}

/* ---- AI 一鍵成圖：新聞原文 → 消化 → 填格 → 背景 → 自動下載 ----
   使用情境：記者外勤只有手機，貼文字下令，不做細部調整。 */

const DIGEST_BACKEND_URL = 'http://127.0.0.1:8787/api/hybrid/digest';

function fillContent(d) {
  document.getElementById('f-title').value = d.title || '';
  document.getElementById('f-subtitle').value = d.subtitle || '';
  document.getElementById('f-source').value = d.source || '';
  document.getElementById('f-visual').value = d.visual_subject || '';
  (d.items || []).slice(0, 3).forEach((it, i) => {
    const set = (k, v) => { document.querySelector(`[data-k="${k}"][data-i="${i}"]`).value = v; };
    set('label', it.label || '');
    set('value', it.value || '');
    set('change', it.change || '');
    set('direction', ['up', 'down', 'flat'].includes(it.direction) ? it.direction : 'flat');
  });
}

async function autoPilot() {
  const btn = document.getElementById('btnAuto');
  const status = document.getElementById('status');
  const news = document.getElementById('f-news').value.trim();
  if (!news) { status.textContent = '請先貼上新聞原文'; return; }
  btn.disabled = true;
  try {
    status.textContent = '1/3 AI 消化新聞中…';
    const res = await fetch(DIGEST_BACKEND_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ news_text: news })
    });
    if (!res.ok) throw new Error('消化失敗 HTTP ' + res.status);
    fillContent(await res.json());
    render();

    status.textContent = '2/3 內容就緒，生成背景中…';
    state.bgDataUri = null;
    await generateBackground();
    if (!state.bgDataUri) throw new Error('背景生成失敗');

    status.textContent = '3/3 匯出中…';
    await exportPNG();
    status.textContent = '✅ 完成！PNG 已下載（內容可再手動微調後重新匯出）';
  } catch (e) {
    status.textContent = '一鍵成圖失敗：' + e.message;
  } finally {
    btn.disabled = false;
  }
}

/* ---- 啟動 ----
   獨立頁 hybrid.html 載入後立即呼叫；index.html 第三分頁則等使用者第一次
   切過去才呼叫（首次切頁前 section 是 hidden，提早 render 沒意義）。 */

let booted = false;

function init() {
  if (booted) return;
  if (!document.getElementById('svgHost')) return;   // 頁面沒有混合版型區塊
  booted = true;

  buildItemRows();
  render();
  document.getElementById('btnAuto').addEventListener('click', autoPilot);
  document.getElementById('btnBg').addEventListener('click', generateBackground);
  document.getElementById('btnExport').addEventListener('click', () => {
    exportPNG().catch(e => { document.getElementById('status').textContent = '匯出失敗：' + e.message; });
  });
  document.getElementById('f-guides').addEventListener('change', render);
  document.querySelector('.controls').addEventListener('input', (e) => {
    if (e.target.id !== 'f-guides') render();
  });
}

window.initHybrid = init;

})();
