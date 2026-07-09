/* ============================================================
   T阿模 新聞CG Prompt 生成器 V8
   資料模型：頂層為「圖表類型」，各類型下有 styles / structures / visual 三層
   ============================================================ */

const SYSTEM_DISCLAIMER = '"< >" "[ ]" 是給你的指令 不要生成在結果上';
const DEFAULT_VARIABLE_TEMPLATE = '[標題]\n[內文]';

/* ---------- 共用：品牌風格包（四類共用同一組視覺語言） ---------- */
const SHARED_STYLES = {
    '標準電視': [
        { zh:'TVBS紫橘', en:'TV news infographic illustration with analysis-driven visual layout, broadcast-friendly arrangement, 16:9 widescreen, strong left-right division, TVBS signature blue/purple (#4A3C91) primary with accent orange (#F36F21).' },
        { zh:'TVBS藍黃', en:'TV news infographic illustration with analysis-driven visual layout, broadcast-friendly arrangement, 16:9 widescreen, TVBS signature blue (#003690) primary with accent yellow (#FFCC00).' },
        { zh:'ABC藍金', en:'News infographic layout, centered composition, rounded rectangular panels, modular broadcast cards, polished flat-modern design, ABC signature color palette with royal blue primary and golden highlight accents.' },
        { zh:'TVBS簡明', en:'TV news infographic illustration with analysis-driven visual layout, 16:9 format, balanced information zones, clean digital aesthetic, high-contrast broadcast color palette featuring TVBS signature blue.' },
        { zh:'CNN紅黑', en:'CNN-style news infographic layout, sharp icons, high visual weight headlines, bold flat design, signature CNN red palette with charcoal black and bright white contrast.' },
        { zh:'CNBC藍', en:'CNBC-style financial infographic, modular data panels, market-dashboard aesthetic, vibrant cobalt blue primary with bright finance green accents.' },
        { zh:'Bloomberg黑', en:'Bloomberg-style financial infographic, minimalist market-dashboard, high-data-density, deep charcoal black background with Bloomberg purple (#6320EE) accents.' },
        { zh:'ABC鐵灰', en:'ABC white-background infographic layout, two-column comparison, ABC iron-gray theme palette with bright red highlight blocks, professional broadcast aesthetic.' },
        { zh:'桌遊創意', en:'Creative board-game inspired infographic, styled like a train-adventure strategy board game with playful game-card panels, tactile 3D depth, high-end commercial polish, small game-piece style icons (tokens, route markers, meeples) used as decorative icons, warm tabletop lighting. Use themed map or city elements as background motifs. Do NOT include any real board-game brand name or logo.' }
    ],
    'Art Deco': [
        { zh:'Metal Art Deco', en:'Metallic Art Deco textures, Gold and Silver accents, Dark Blue background, high-gloss polished metal finish, elegant geometric structure.' },
        { zh:'Contemporary Art Deco', en:'Contemporary Art Deco, Dark Blue background, Gold accents, Silver secondary text, polished metal surfaces, elegant geometric lines.' },
        { zh:'Fintech Aesthetic', en:'Modernized Art Deco integrated with Fintech Aesthetic, professional data-driven UI, neon-accented borders, clean minimalist financial layout.' },
        { zh:'Streamline Moderne', en:'Streamline Moderne Art Deco style, aerodynamic curves, horizontal long lines, Dark Blue canvas, Gold primary accents, Silver body text.' },
        { zh:'Neo-Art Deco', en:'Neo-Art Deco aesthetic, futuristic revival of deco elements, Dark Blue and Gold palette, Silver typography, crisp geometric patterns.' },
        { zh:'Luxury Art Deco', en:'Luxury / High-End Art Deco, opulent metallic textures, Dark Blue velvet background, Gold leaf accents, Silver highlights, high-contrast premium feel.' },
        { zh:'Soft Art Deco', en:'Soft Art Deco, subtle geometric patterns, diffused lighting, Dark Blue, Gold, and Silver color scheme, balanced broadcast composition.' },
        { zh:'Minimal Art Deco', en:'Minimal Art Deco, stripped-back geometric structure, clean lines, Dark Blue, Gold, Silver palette, essential data focus.' }
    ]
};

/* ---------- 卡牌陳列（資料圖表類共用） ---------- */
const CARD_LAYOUT_ITEMS = [
    { zh:'直向雙分割', en:'Vertical dual split layout. Title at the very top. Content area occupies the bottom 55%-60% of the screen. Split into two equal vertical columns (Left and Right) with uniform spacing. Each block features a professional card-based design.',
      template: '[標題]\n\n[左側卡片內容]\n<數據點 1>\n\n[右側卡片內容]\n<數據點 2>' },
    { zh:'直向三分割', en:'Vertical triple split layout. Title at the very top. Content area occupies the bottom 55%-60% of the screen. Split into three equal vertical columns (Left, Middle, Right) with uniform spacing. Each block features a professional card-based design.',
      template: '[標題]\n\n[左側卡片]\n<數據 A>\n\n[中間卡片]\n<數據 B>\n\n[右側卡片]\n<數據 C>' },
    { zh:'混合三分割', en:'Mixed triple split layout. Title at the very top. Content area occupies the bottom 55%-60% of the screen. Left side is a single vertical column. Right side is split into two stacked horizontal blocks. Each block features a professional card-based design.',
      template: '[標題]\n\n[左側主卡片]\n<主要數據>\n\n[右上方卡片]\n<次要數據 A>\n\n[右下方卡片]\n<次要數據 B>' }
];

/* ============================================================
   四大圖表類型定義
   每一類型 = { label, hint, aspect, tabs, styles, structures, visual }
   tabs 決定左側顯示哪幾個分頁；不同類型可有不同分頁組合
   ============================================================ */
const CHART_TYPES = {

    /* ---------- 1. 資料圖表（沿用舊版，最完整） ---------- */
    'data': {
        label: '資料圖表',
        hint: '數據視覺化：股市、物價、長條/折線/圓餅等。選構圖會自動帶入對應資料格式。',
        aspect: '16:9 / 2K',
        tabs: ['style', 'structure', 'visual'],
        styles: SHARED_STYLES,
        structures: {
            '自訂': [ { zh:'預設', en:'Manual layout specification', template: DEFAULT_VARIABLE_TEMPLATE } ],
            '儀表板': [
                { zh:'美股大盤',
                  en:'TV news financial infographic composition in 16:9 widescreen, featuring strong left–right information zones, balanced modular data panels, a bold top headline bar, clear visual hierarchy, broadcast-safe margins, and an uncluttered layout with clean divider lines. Includes three index blocks for "DOW" / "Nasdaq" / "S&P 500", each displaying closing index (smaller text size), daily change in points (even smaller text size), and a percentage change value as the largest, primary visual element. Use red with ▲ for gains and green with ▼ for losses. Maintain generous spacing and high readability, emphasizing the percentage change as the dominant indicator of market movement. no logo.',
                  template: '[標題] 美股三大指數 00/00 收盤\n[結果]\nDow  ▼0.54%  39395.16  ▼267.50\nNASDAQ  ▼0.31%  22682.73  ▼70.91\nS&P 500  ▼0.28%  6861.89  ▼19.42' },
                { zh:'美股個股',
                  en:'TV news stock-performance infographic composition in 16:9 widescreen, featuring a clean modular layout with strong left–right information zones, a bold top headline bar, balanced data blocks, broadcast-safe margins, and clear divider lines. Each stock panel includes: a company logo icon, the company short name paired with its ticker symbol in small, lightweight text, the closing price (medium text size), the daily point change (smaller text size), and the percentage change displayed as the largest and primary visual element. Use red with ▲ for gains and green with ▼ for losses. Maintain wide spacing, high readability, and a clear hierarchy that emphasizes the percentage change as the dominant signal of individual stock movement. no Logo.',
                  template: '[標題] 美股個股 00/00 收盤\n[結果]\nNVIDIA  182.41  ▼0.97 (0.53%)\nApple Inc. 278.78  ▼1.92 (0.68%)\nTSMC(ADR)  294.72  ▲1.79 (0.61%)' },
                { zh:'物價',
                  en:'TV news infographic composition in a 16:9 horizontal layout, featuring a clean grid of evenly spaced item panels arranged in a row. Each panel contains a top label bar displaying the item name, a colorful vector illustration placed inside a soft circular badge, and a bottom section showing the price change. Use a bold red upward ▲ symbol for increases and a bold green downward ▼ symbol for decreases, placed directly before the percentage. Panels use structured spacing, clear alignment, safe margins, subtle dividers, and a broadcast-style modular layout emphasizing clarity and comparability across categories. do not show "-" or "+" no Logo.',
                  template: '[標題] 11月美國物價變動 \n[標題下方置右小字]  資料來源: \n[結果]\n能源 +2.8%\n肉類 +5.25%\n雞蛋 +12.72%\n麵包 +2.97%' }
            ],
            '統計圖': [
                { zh:'長條圖',
                  en:'TV news bar chart infographic in 16:9 widescreen. A clean vertical bar chart occupies the central data zone, with a bold top headline bar. Each bar is clearly labeled with its category name below and its value on top. Bars use a consistent broadcast color scheme with the highest or most significant bar highlighted in an accent color. Include a labeled baseline and subtle horizontal gridlines for readability. Generous spacing, broadcast-safe margins. no logo.',
                  template: '[標題] <主題> 統計\n[Y軸單位] \n[資料]\n類別A  35\n類別B  52\n類別C  28\n類別D  41' },
                { zh:'折線圖',
                  en:'TV news line chart infographic in 16:9 widescreen. A single clear trend line spans the central data zone from left to right, with data point markers and value labels at key points. Bold top headline bar. X-axis shows time periods, Y-axis shows values with subtle gridlines. The line uses a high-contrast accent color with a soft gradient fill beneath it. Emphasize the overall trend direction. Broadcast-safe margins, clean and legible. no logo.',
                  template: '[標題] <主題> 趨勢\n[X軸] 月份  [Y軸] 數值\n[資料]\n1月 120\n2月 145\n3月 138\n4月 167\n5月 190' },
                { zh:'圓餅圖',
                  en:'TV news pie chart infographic in 16:9 widescreen. A single clean pie or donut chart placed on one side of the frame, with a legend and percentage labels on the other side. Bold top headline bar. Each segment uses a distinct broadcast-friendly color, with the most significant segment slightly pulled out or highlighted. Percentage values are the dominant visual element on each segment. Broadcast-safe margins, high readability. no logo.',
                  template: '[標題] <主題> 佔比\n[資料]\n項目A 45%\n項目B 30%\n項目C 15%\n其他 10%' },
                { zh:'對比圖',
                  en:'TV news comparison infographic in 16:9 widescreen. The frame is split into two symmetric halves (Left vs Right) for head-to-head comparison, divided by a bold central "VS" or divider line. Each side has its own header, representative icon or portrait area, and a stacked list of comparable data points aligned across both sides for easy scanning. Use contrasting accent colors for each side. Broadcast-safe margins, clear alignment. no logo.',
                  template: '[標題] <A> VS <B>\n[左側] <A名稱>\n項目1: 數值\n項目2: 數值\n\n[右側] <B名稱>\n項目1: 數值\n項目2: 數值' }
            ],
            '摘要卡片': [
                { zh:'要點卡片',
                  en:'TV news summary-card infographic in 16:9 widescreen. A bold top headline bar spans the top, with an optional small right-aligned data-source line beneath it. The main content area presents several key-point cards arranged in a balanced grid or row. Each card contains a short label tag paired with a small themed icon, followed by a concise one-line explanation beneath. Cards share a consistent professional design with clear visual separation, generous spacing, and broadcast-safe margins. The layout stays locked regardless of the number of points. no logo.',
                  template: '[大標題] <主題>\n[標題下方置右小字] 資料來源: \n\n[小標籤 + 小icon] <要點1>\n[內文] <說明1>\n\n[小標籤 + 小icon] <要點2>\n[內文] <說明2>\n\n[小標籤 + 小icon] <要點3>\n[內文] <說明3>\n\n[小標籤 + 小icon] <要點4>\n[內文] <說明4>\n\n[小標籤 + 小icon] <要點5>\n[內文] <說明5>' },
                { zh:'重點摘要',
                  en:'TV news key-summary infographic in 16:9 widescreen. A dominant headline area introduces the topic, with a small number of concise takeaway points displayed as clean stacked rows, each led by a highlighted keyword or short tag and followed by supporting detail. Emphasis on scannability and hierarchy, broadcast-safe margins, uncluttered composition. no logo.',
                  template: '[大標題] <主題>\n[重點1] <說明>\n[重點2] <說明>\n[重點3] <說明>' }
            ],
            '卡牌陳列': CARD_LAYOUT_ITEMS
        },
        visual: {
            '背景': [ { zh:'背景刷淡', en:'Background elements should be faded or low-opacity to ensure foreground text maximum readability, subtle backdrop.' } ],
            '視感': [
                { zh:'向量', en:'Vector art style, clean flat shapes, sharp outline edges, minimal ornamentation, editorial news aesthetic.' },
                { zh:'立體', en:'3D dimensional visual feel, depth layering with soft shadows, subtle embossed effects, polished studio textures.' }
            ]
        }
    },

    /* ---------- 2. 情境示意圖 / 新聞配圖 ---------- */
    'scene': {
        label: '情境示意圖',
        hint: '事故、災害、人物場景等新聞配圖。以寫實或半寫實示意呈現事件現場，非真實照片。',
        aspect: '16:9 / 2K',
        tabs: ['style', 'structure', 'visual'],
        styles: {
            '寫實示意': [
                { zh:'新聞寫實', en:'Photorealistic news illustration, documentary broadcast quality, realistic lighting and proportions, editorial photojournalism aesthetic, neutral and factual tone, no sensationalism.' },
                { zh:'半寫實插畫', en:'Semi-realistic editorial illustration, painterly rendering with clear detail, broadcast news graphic style, cleaner than a photo but grounded in realism.' },
                { zh:'夜間現場', en:'Nighttime scene lighting, emergency vehicle lights and street lamps, high contrast, dramatic but factual broadcast documentary mood.' },
                { zh:'日間現場', en:'Clear daytime scene, natural overcast broadcast lighting, even exposure, neutral documentary realism.' }
            ],
            '示意氛圍': [
                { zh:'災害示意', en:'Disaster scene depiction for news illustration, restrained and non-graphic, focus on environment and scale rather than casualties, informative broadcast tone.' },
                { zh:'事故示意', en:'Accident scene reconstruction illustration, clear depiction of the location and objects involved, arrows or highlight markers optional, broadcast-safe non-graphic treatment.' },
                { zh:'天氣示意', en:'Weather-driven scene illustration, atmospheric conditions clearly rendered (storm, flood, snow, heat), environmental focus, broadcast news aesthetic.' }
            ]
        },
        structures: {
            '自訂': [ { zh:'預設', en:'Manual scene description', template: '[標題]\n[場景描述]\n<重點標記>' } ],
            '場景構圖': [
                { zh:'現場全景',
                  en:'Wide establishing shot of the scene, showing the full environment and spatial context. Camera positioned to capture the overall situation. Optional label callouts pointing to key elements. A clear headline bar at the top.',
                  template: '[標題] <事件名稱>\n[地點] \n[場景描述] 描述現場環境與主要物件\n<標記1> 說明\n<標記2> 說明' },
                { zh:'重點特寫',
                  en:'Medium close-up focusing on the key subject or object of the news event, with the surrounding context softly visible. Callout labels highlight the critical detail. Headline bar at the top.',
                  template: '[標題] <重點>\n[主體描述] 聚焦的人物或物件\n<關鍵細節> 說明' },
                { zh:'俯視示意',
                  en:'Top-down or high-angle aerial view of the scene, useful for showing layout, spread, or the relationship between multiple locations. Overlay arrows or zone markers. Headline bar at the top.',
                  template: '[標題] <事件範圍>\n[俯視描述] 由上而下呈現的空間關係\n<區域A> 說明\n<區域B> 說明' }
            ]
        },
        visual: {
            '背景': [ { zh:'背景刷淡', en:'If overlaying text, background elements should be slightly darkened or blurred to ensure caption readability.' } ],
            '視感': [
                { zh:'寫實', en:'Photorealistic rendering with natural textures and lighting.' },
                { zh:'插畫', en:'Editorial illustration rendering, cleaner and more graphic than a photograph.' }
            ]
        }
    },

    /* ---------- 3. 地圖 / 位置示意 ---------- */
    'map': {
        label: '地圖／位置',
        hint: '標示地點、路線、範圍。呈現地理關係，非可導航的精確地圖。',
        aspect: '16:9 / 2K',
        tabs: ['style', 'structure', 'visual'],
        styles: {
            '地圖風格': [
                { zh:'新聞平面地圖', en:'Clean flat broadcast news map style, simplified geography, muted land and water colors, clear borders, editorial cartography aesthetic optimized for TV readability.' },
                { zh:'衛星擬真', en:'Satellite-style realistic terrain map, subtle relief and texture, broadcast overlay graphics on top, high-contrast labels.' },
                { zh:'暗色主題地圖', en:'Dark-theme broadcast map, deep navy or charcoal base, glowing accent routes and markers, high-tech news graphics aesthetic.' },
                { zh:'極簡示意地圖', en:'Minimalist schematic map, abstracted shapes and simplified coastlines, focus on relationships rather than accuracy, clean editorial style.' }
            ]
        },
        structures: {
            '自訂': [ { zh:'預設', en:'Manual map specification', template: '[標題]\n[地區]\n<地點標記>' } ],
            '地圖類型': [
                { zh:'單點標示',
                  en:'News map highlighting a single key location with a prominent pin or marker and a label callout. The surrounding region provides geographic context. Inset mini-map optional to show the location within a larger area. Headline bar at the top.',
                  template: '[標題] <地點名稱>\n[所屬地區] \n<地點標記> 名稱與說明' },
                { zh:'多點標示',
                  en:'News map with multiple labeled location markers, each with a distinct pin and short label. A legend distinguishes marker types if needed. Clear geographic context. Headline bar at the top.',
                  template: '[標題] <主題>\n[地區] \n<地點1> 說明\n<地點2> 說明\n<地點3> 說明' },
                { zh:'路線示意',
                  en:'News map showing a route or movement path with a clear directional line and arrows connecting an origin and destination, with intermediate waypoints labeled. Distance or time annotations optional. Headline bar at the top.',
                  template: '[標題] <路線主題>\n[起點] <地點A>\n[終點] <地點B>\n<途經點> 說明' },
                { zh:'範圍示意',
                  en:'News map showing an affected area or zone with a clearly shaded or outlined region, a legend indicating intensity or category, and labels for key places inside or near the zone. Headline bar at the top.',
                  template: '[標題] <範圍主題>\n[範圍描述] 影響或涵蓋區域\n<區域> 程度或類別\n<關鍵地點> 說明' }
            ]
        },
        visual: {
            '標記': [
                { zh:'發光標記', en:'Markers and routes use a glowing high-contrast accent color for broadcast visibility.' },
                { zh:'扁平標記', en:'Flat solid markers with clear labels, editorial map style.' }
            ]
        }
    },

    /* ---------- 4. 3D示意 / 流程重建 ---------- */
    'process': {
        label: '3D示意／流程',
        hint: '事件經過、物理過程的分步重建。以序列或分解圖呈現「怎麼發生的」。',
        aspect: '16:9 / 2K',
        tabs: ['style', 'structure', 'visual'],
        styles: {
            '3D風格': [
                { zh:'技術示意', en:'Technical 3D diagram style, clean isometric or cutaway rendering, engineering-illustration clarity, neutral broadcast palette with accent highlights on key parts.' },
                { zh:'寫實3D', en:'Photorealistic 3D reconstruction, accurate materials and lighting, documentary broadcast quality, focus on plausibility.' },
                { zh:'剖面透視', en:'Cutaway cross-section 3D illustration revealing internal structure or hidden mechanics, labeled layers, technical broadcast aesthetic.' },
                { zh:'簡潔圖解', en:'Clean simplified 3D infographic style, reduced detail, strong shapes and arrows, optimized for quick comprehension on TV.' }
            ]
        },
        structures: {
            '自訂': [ { zh:'預設', en:'Manual process specification', template: '[標題]\n[步驟]\n<步驟1>\n<步驟2>' } ],
            '流程類型': [
                { zh:'分步序列',
                  en:'Step-by-step sequence diagram laid out left to right (or top to bottom), each step in its own numbered panel with a 3D illustration and a short caption, connected by directional arrows showing progression. Headline bar at the top.',
                  template: '[標題] <事件經過>\n[步驟1] <說明>\n[步驟2] <說明>\n[步驟3] <說明>\n[步驟4] <說明>' },
                { zh:'物理過程',
                  en:'Diagram illustrating a physical or mechanical process with a 3D cutaway or before/after comparison, force/direction arrows, and labeled components showing cause and effect. Headline bar at the top.',
                  template: '[標題] <過程名稱>\n[前] <初始狀態>\n[過程] <發生什麼>\n[後] <結果狀態>\n<關鍵作用力> 說明' },
                { zh:'時間軸重建',
                  en:'Timeline reconstruction combining a horizontal time axis with 3D scene snapshots at each key moment, timestamps labeled, arrows connecting the moments to convey chronological progression. Headline bar at the top.',
                  template: '[標題] <事件時間軸>\n[時間1] <發生什麼>\n[時間2] <發生什麼>\n[時間3] <發生什麼>' },
                { zh:'結構分解',
                  en:'Exploded-view 3D diagram separating an object or system into its components, each labeled and spaced apart along an axis, showing how parts fit together. Headline bar at the top.',
                  template: '[標題] <結構主題>\n[整體] <物件名稱>\n<部件1> 說明\n<部件2> 說明\n<部件3> 說明' }
            ]
        },
        visual: {
            '背景': [ { zh:'背景刷淡', en:'Background kept clean and low-contrast so the 3D diagram and labels stay dominant.' } ],
            '標註': [
                { zh:'箭頭引導', en:'Use clear directional arrows and numbered callouts to guide reading order.' },
                { zh:'標籤引線', en:'Use leader lines connecting labels to their corresponding parts.' }
            ]
        }
    }
};

/* ============================================================
   狀態
   ============================================================ */
const TAB_META = {
    style:     { name: '風格包 / 子風格', field: 'style',    labelZh: '子風格 (Sub-Style)' },
    structure: { name: '構圖 / 子結構',   field: 'structure', labelZh: '子結構 (Sub-Structure)' },
    visual:    { name: '視覺要求',        field: 'visual',   labelZh: '視覺要求 (Visual)' }
};

let state = {
    chartType: 'data',
    currentRole: '記者',
    currentTab: 'style',
    engine: 'gemini',
    activeParent: null,
    // selected 依 chartType 分開存，避免切類型互相污染
    selectedByType: {}
};

function curType() { return CHART_TYPES[state.chartType]; }

function curSelected() {
    if (!state.selectedByType[state.chartType]) {
        state.selectedByType[state.chartType] = { style: {}, structure: {}, visual: {} };
    }
    return state.selectedByType[state.chartType];
}

/* 編輯模式：只保留風格 + 自訂/卡牌，隱藏預設構圖模板（沿用舊版精神） */
function libFor(tab) {
    const t = curType();
    if (tab === 'style') return t.styles;
    if (tab === 'visual') return t.visual;
    if (tab === 'structure') {
        if (state.currentRole === '編輯') {
            const s = { '自訂': t.structures['自訂'] };
            if (t.structures['卡牌陳列']) s['卡牌陳列'] = t.structures['卡牌陳列'];
            return s;
        }
        return t.structures;
    }
    return {};
}

/* ============================================================
   初始化
   ============================================================ */
window.onload = () => {
    document.getElementById('field-variable').value = DEFAULT_VARIABLE_TEMPLATE;
    renderChartTypes();
    resetToType('data');
};

function renderChartTypes() {
    const c = document.getElementById('chartTypeSelector');
    c.innerHTML = '';
    Object.entries(CHART_TYPES).forEach(([key, t]) => {
        const btn = document.createElement('button');
        btn.className = `px-4 py-2 rounded-lg text-[11px] font-black border transition-all uppercase tracking-wide ${key === state.chartType ? 'type-active' : 'text-slate-400 bg-slate-900/50 border-slate-700 hover:bg-slate-800'}`;
        btn.innerText = t.label;
        btn.onclick = () => resetToType(key);
        c.appendChild(btn);
    });
}

function resetToType(key) {
    state.chartType = key;
    state.currentTab = 'style';
    const t = curType();
    state.activeParent = Object.keys(t.styles)[0];
    document.getElementById('typeHint').innerText = t.hint;
    document.getElementById('aspectBadge').innerText = t.aspect;
    renderChartTypes();
    renderTabs();
    renderAll();
}

/* ============================================================
   分頁（依圖表類型動態產生）
   ============================================================ */
function renderTabs() {
    const bar = document.getElementById('tabBar');
    bar.innerHTML = '';
    curType().tabs.forEach(tab => {
        const btn = document.createElement('button');
        btn.className = `py-4 px-5 text-[10px] font-black uppercase tracking-widest whitespace-nowrap ${tab === state.currentTab ? 'tab-active' : 'text-slate-500'}`;
        btn.innerText = TAB_META[tab].name;
        btn.onclick = () => switchTab(tab, btn);
        bar.appendChild(btn);
    });
}

function switchRole(role, el) {
    state.currentRole = role;
    document.querySelectorAll('button[onclick^="switchRole"]').forEach(btn => {
        btn.classList.remove('role-active');
        btn.classList.add('text-slate-500');
    });
    el.classList.add('role-active');
    el.classList.remove('text-slate-500');
    state.currentTab = 'style';
    state.activeParent = Object.keys(curType().styles)[0];
    renderTabs();
    renderAll();
    showToast(`已切換至 ${role} 模式`);
}

function switchTab(tab, el) {
    state.currentTab = tab;
    document.querySelectorAll('#tabBar button').forEach(b => {
        b.classList.remove('tab-active'); b.classList.add('text-slate-500');
    });
    el.classList.add('tab-active'); el.classList.remove('text-slate-500');
    state.activeParent = Object.keys(libFor(tab))[0];
    renderAll();
}

function switchEngine(engine, el) {
    state.engine = engine;
    document.getElementById('engine-gemini').className = 'px-3 py-1 rounded text-[9px] font-black transition-all ' + (engine === 'gemini' ? 'bg-blue-600 text-white' : 'text-slate-500 hover:text-white');
    document.getElementById('engine-gpt').className = 'px-3 py-1 rounded text-[9px] font-black transition-all ' + (engine === 'gpt' ? 'bg-blue-600 text-white' : 'text-slate-500 hover:text-white');
    syncOutput();
}

/* ============================================================
   渲染
   ============================================================ */
function renderAll() {
    renderParents();
    renderTags();
    syncOutput();
    updateCounter();
    // 更新右側 label
    document.getElementById('label-structure').innerText = TAB_META.structure.labelZh;
}

function renderParents() {
    const container = document.getElementById('parentSelector');
    container.innerHTML = '';
    const list = Object.keys(libFor(state.currentTab));
    if (!list.includes(state.activeParent)) state.activeParent = list[0];
    list.forEach(item => {
        const btn = document.createElement('button');
        btn.className = `px-4 py-2 rounded-md text-[10px] font-bold border border-slate-700 transition-all uppercase tracking-widest whitespace-nowrap ${item === state.activeParent ? 'parent-active' : 'text-slate-400 bg-slate-900/50 hover:bg-slate-800'}`;
        btn.innerText = item;
        btn.onclick = () => { state.activeParent = item; renderAll(); };
        container.appendChild(btn);
    });
}

function renderTags() {
    const grid = document.getElementById('tagsGrid');
    grid.innerHTML = '';
    const tags = libFor(state.currentTab)[state.activeParent] || [];
    const sel = curSelected()[state.currentTab][state.activeParent];
    tags.forEach(tag => {
        const btn = document.createElement('button');
        const isSelected = sel && sel.zh === tag.zh;
        btn.className = `tag-btn flex items-center justify-center p-4 rounded-lg text-center border overflow-hidden min-h-[64px] transition-all ${isSelected ? 'tag-active' : ''}`;
        btn.innerHTML = `<span class="text-[11px] font-black uppercase tracking-wider">${tag.zh}</span>`;
        btn.onclick = () => {
            const s = curSelected();
            if (isSelected) delete s[state.currentTab][state.activeParent];
            else s[state.currentTab][state.activeParent] = tag;
            updateSpecificField(state.currentTab);
            renderTags(); syncOutput(); updateCounter();
        };
        grid.appendChild(btn);
    });
}

function updateSpecificField(tab) {
    const s = curSelected();
    if (tab === 'style') {
        document.getElementById('field-style').value = Object.values(s.style).map(x => x.en).join('\n');
    } else if (tab === 'structure') {
        const arr = [];
        Object.entries(s.structure).forEach(([parent, x]) => { if (parent !== '自訂') arr.push(`${parent}: ${x.en}`); });
        document.getElementById('field-structure').value = arr.join('\n');
        const latest = s.structure[state.activeParent];
        if (latest && latest.template) document.getElementById('field-variable').value = latest.template;
    } else if (tab === 'visual') {
        document.getElementById('field-visual').value = Object.values(s.visual).map(x => x.en).join('\n');
    }
}

function updateCounter() {
    const s = curSelected();
    const count = Object.keys(s.style).length + Object.keys(s.structure).length + Object.keys(s.visual).length;
    document.getElementById('selectionCounter').innerText = `Selected: ${count}`;
}

/* ============================================================
   輸出組合：依角色 + 引擎(gemini/gpt) 產生最終 prompt
   ============================================================ */
function syncOutput() {
    const style = document.getElementById('field-style').value.trim();
    const structure = document.getElementById('field-structure').value.trim();
    const visual = document.getElementById('field-visual').value.trim();
    const variableInput = document.getElementById('field-variable').value.trim();
    const display = document.getElementById('displayPrompt');

    if (!style && !structure && !variableInput && !visual) {
        display.innerText = "Waiting for data input…";
        return;
    }

    const processedVariable = variableInput ? `${SYSTEM_DISCLAIMER}\n${variableInput}` : '[No Variables Defined]';
    const styleContent = style || '[No Style Defined]';
    const structureContent = structure || '[No Structure Defined]';
    const combinedStyle = visual ? styleContent + '\nVISUAL REQUIREMENTS:\n' + visual : styleContent;

    display.innerText = buildPrompt({
        role: state.currentRole,
        engine: state.engine,
        typeLabel: curType().label,
        style: combinedStyle,
        structure: structureContent,
        variable: processedVariable
    });
}

function buildPrompt({ role, engine, typeLabel, style, structure, variable }) {
    // 共用的正文區塊（style / structure / variable）
    const textRules = role === '編輯' ? EDITOR_TEXT_RULES : REPORTER_TEXT_RULES;
    const safeArea = role === '編輯' ? EDITOR_SAFE_AREA : REPORTER_SAFE_AREA;

    const body =
`==================================================
CANVAS
==================================================
- Aspect ratio: 16:9
- Resolution: 2K
- Broadcast-safe composition
- All elements must remain within clear safe margins

${textRules}

==================================================
STYLE (VISUAL LANGUAGE ONLY)
==================================================
${style}

==================================================
STRUCTURE (LAYOUT RULES)
==================================================
${structure}

==================================================
VARIABLE FIELDS (USER INPUT)
==================================================
${variable}

${safeArea}

==================================================
FINAL OUTPUT RULE
==================================================
- The final generated image must NOT contain any "[" "]" or "<" ">" characters.
- All bracketed variable fields are instructions only.
- Use only Traditional Chinese (Taiwan standard).
- Ensure all characters are correct with proper stroke forms.`;

    // 依引擎切換開頭語法
    if (engine === 'gpt') {
        return `Generate an image: a professional international TV news infographic (${typeLabel}) for broadcast and digital editorial use. Follow the specification below exactly. Do not redesign or reinterpret the layout logic. Current Operating Context: ${role} Workflow.

${body}`;
    }
    // gemini（預設）
    return `Create a professional international TV news infographic (${typeLabel}) designed for broadcast and digital editorial use.
The output must strictly follow the style, structure, and data logic defined below.
Do not redesign, reinterpret, or alter the layout logic.
Current Operating Context: ${role} Workflow.

${body}`;
}

/* ---- 文字規則 / 安全區 常數 ---- */
const REPORTER_TEXT_RULES =
`==================================================
Text Rules
==================================================
Main Title:
- Positioned at the very top of the frame
- Rendered in bold 3D extruded typography with strong depth and lighting

Body Text:
- Clean and highly legible
- Do NOT use any commas or periods
- Use spaces only to separate phrases

Subtitles ([內文小標]):
- If the text length is fewer than 6 full-width characters (中文字), use a "Tag" (Label) visual representation (e.g., pill-shaped background, high-contrast block).

Text Styling Rules:
- Any text written as [text] or <text>:
  -> Remove brackets or symbols
  -> Apply highlight color such as yellow gold or cyan
  -> Optional glow effect for emphasis
- Any <蓋章> marker:
  -> Apply strong full-box highlight style to the following text
  -> Use solid background color (e.g. red background with white text)`;

const EDITOR_TEXT_RULES =
`==================================================
Text Rules
==================================================
Main Title:
- Positioned at the very top of the frame
- Must be split into exactly two lines
- Font size is 2x larger than body text
- Rendered in bold 3D extruded typography with strong depth and lighting

Body Text:
- Clean and highly legible
- Do NOT use any commas or periods
- Use spaces only to separate phrases

Subtitles ([內文小標]):
- If the text length is fewer than 6 full-width characters (中文字), use a "Tag" (Label) visual representation.

Text Styling Rules:
- Any text written as [text] or <text>:
  -> Remove brackets or symbols
  -> Apply highlight color such as yellow gold or cyan
  -> Optional glow effect for emphasis
- Any <蓋章> marker:
  -> Apply strong full-box highlight style to the following text
  -> Use solid background color (e.g. red background with white text)

Visual Elements:
- Include high-quality flat icons or 3D data charts relevant to the content
- Background: professional broadcast news style, subtle glow / tech lines, strictly NO plain gradients`;

const REPORTER_SAFE_AREA =
`==================================================
BOTTOM SAFE AREA (CRITICAL — MUST PRESERVE)
==================================================
- The bottom 20% (one-fifth) of the entire image must contain:
  - NO text
  - NO logos
  - NO icons
  - NO charts
  - NO divider lines
  - NO decorative elements
- This area is reserved strictly as a broadcast-safe zone
- The background color or background image from the active content area above MUST extend downward into this area
- The extension must be seamless and continuous
- No change in color, texture, brightness, or visual tone
- No hard edges, no visual breaks, no overlays, no gradients`;

const EDITOR_SAFE_AREA =
`==================================================
SAFE AREA (CRITICAL — MUST PRESERVE)
==================================================
- All core text and logos must remain within the central 80% area, with 10–18% padding on all sides.
- The reserved zone contains NO text, logos, icons, charts, divider lines, or decorative elements.
- The background color/image MUST extend seamlessly into this area — no hard edges, no gradients, no overlays.`;

/* ============================================================
   AI 消化：透過本地後端代理呼叫 Claude（見 main.py）
   ============================================================ */
const AI_BACKEND_URL = "http://127.0.0.1:8787/api/generate";

async function handleAIDigestion() {
    const input = document.getElementById('aiInput').value.trim();
    if (!input) return showToast("請輸入欲消化整理的新聞內容");

    const btnText = document.getElementById('aiBtnText');
    const loading = document.getElementById('aiLoading');
    const btn = document.getElementById('aiBtn');
    btn.disabled = true; btnText.classList.add('hidden'); loading.classList.remove('hidden');

    const typeLabel = curType().label;

    try {
        const response = await fetch(AI_BACKEND_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ news_text: input, type_label: typeLabel })
        });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();

        const s = curSelected();
        s.style = {}; s.structure = {};
        document.getElementById('field-style').value = data.style || '';
        document.getElementById('field-structure').value = data.structure || '';
        document.getElementById('field-variable').value = (data.variable || '').replace(SYSTEM_DISCLAIMER, '').trim();

        renderTags(); syncOutput(); updateCounter();
        showToast("AI 已完成佈局規劃與視覺輔助設計");
    } catch (err) {
        console.error(err);
        showToast("AI 服務連線失敗，請稍後再試");
    } finally {
        btn.disabled = false; btnText.classList.remove('hidden'); loading.classList.add('hidden');
    }
}

/* ============================================================
   工具函式
   ============================================================ */
function copyToClipboard() {
    const text = document.getElementById('displayPrompt').innerText;
    if (text.includes("Waiting for data")) return;
    const temp = document.createElement('textarea');
    temp.value = text; document.body.appendChild(temp);
    temp.select(); document.execCommand('copy');
    document.body.removeChild(temp);
    showToast("Prompt Copied to Clipboard");
}

function showToast(msg) {
    const toast = document.getElementById('toast');
    toast.innerText = msg;
    toast.style.opacity = '1'; toast.classList.add('toast-animate');
    setTimeout(() => { toast.style.opacity = '0'; toast.classList.remove('toast-animate'); }, 3000);
}

function clearMatrix() {
    ['style', 'structure', 'visual', 'variable'].forEach(f => {
        document.getElementById(`field-${f}`).value = (f === 'variable') ? DEFAULT_VARIABLE_TEMPLATE : '';
    });
    state.selectedByType[state.chartType] = { style: {}, structure: {}, visual: {} };
    renderAll();
}

function confirmReset() {
    if (confirm("確定執行重置？所有當前數據將遺失。")) location.reload();
}
