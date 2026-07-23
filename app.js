/* ============================================================
   TVBS 新聞AICG產生器
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
      template: '[標題]\n\n[左側主卡片]\n<主要數據>\n\n[右上方卡片]\n<次要數據 A>\n\n[右下方卡片]\n<次要數據 B>' },
    { zh:'四分割', en:'Quad split layout. Title at the very top, split into two lines. Content area is a 2x2 grid of four equal cards with uniform spacing. Each card contains a numbered circle badge, a short label paired with a themed icon or small illustration, and two to three lines of concise explanation. All cards share a consistent professional card-based design.',
      template: '[標題] <主題>\n\n[卡片1 編號+小標+icon] <小標1>\n<說明1>\n\n[卡片2 編號+小標+icon] <小標2>\n<說明2>\n\n[卡片3 編號+小標+icon] <小標3>\n<說明3>\n\n[卡片4 編號+小標+icon] <小標4>\n<說明4>' },
    { zh:'半版示意圖+資訊', en:'Half-scene layout. One half of the frame is a large thematic illustration or scene serving as the main visual anchor; the other half carries the headline and stacked information blocks. The scene and information zones blend with a soft transition rather than a hard divider, keeping a unified broadcast look.',
      template: '[標題] <主題>\n[示意圖側] <場景或主視覺描述>\n[資訊側]\n<要點1> 說明\n<要點2> 說明\n<要點3> 說明' }
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
        aspect: '16:9',
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
            ],
            '後製預留': [
                { zh:'左側留1/3', en:'在畫面左側預留1/3空間 讓我後製放圖片，該區域只延伸背景，不放任何文字或元素。' }
            ]
        }
    },

    /* ---------- 2. 情境示意圖 / 新聞配圖 ---------- */
    'scene': {
        label: '情境示意圖',
        hint: '事故、災害、人物場景等新聞配圖。以寫實或半寫實示意呈現事件現場，非真實照片。',
        aspect: '16:9',
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
            ],
            '實戰風格包': [
                { zh:'WPA Poster', en:'WPA Poster 向量插畫風格。Color palette: parchment cream base (#EBE4D1), tan shading (#D8C7A5), navy blue title blocks (#1D2A38), classic gold accents (#B79440), steel blue icon backgrounds (#ADC2D1), white text on dark backgrounds.' },
                { zh:'UE5電影渲染', en:'UE5電影等級精緻渲染風格。' },
                { zh:'軍事UI', en:'軍事科幻UI風格，標籤有飄浮的科技UI立體感，字體立體、統一的UI風格配色。' }
            ]
        },
        structures: {
            '自訂': [ { zh:'預設', en:'Manual scene description', template: '[標題]\n[場景描述]\n<重點標記>' } ],
            '實戰構圖': [
                { zh:'要件情境圖解',
                  en:'<大標題置頂置中> <第二行小標題 顏色醒目> <大標題 小標題 都不要太大> 構圖1: 背景是相關場景或地圖，顏色刷淡。構圖2: 各要件分別放在相對應位置，圓圈內放向量ICON，圓圈下方放小標與內文。',
                  template: '[大標題] <標題>\n[小標題] <時間或補充>\n\n[要件小標1 + ICON 1] <名稱>\n[要件1 內文] <說明>\n\n[要件小標2 + ICON 2] <名稱>\n[要件2 內文] <說明>\n\n[要件小標3 + ICON 3] <名稱>\n[要件3 內文] <說明>' },
                { zh:'概念連結示意',
                  en:'空中俯瞰主體，主體拉出科幻UI風格的亮線，連接其他物件（都要出現在畫面上），表示連結關係，物件旁放相對應標籤。',
                  template: '[主體] <主體名稱>\n[連結物件 標籤]\n<物件1>\n<物件2>\n<物件3>' }
            ],
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
        aspect: '16:9',
        tabs: ['style', 'structure', 'visual'],
        styles: {
            '新聞地圖': [
                { zh:'TVBS向量地圖', en:'TVBS-style Google Maps vector map aesthetic. Land: muted gray-blue (#DDE2EA / #C8CFD9). Water: soft blue-gray (#AFC4D6 / #B8D0E0). Subtle hillshade terrain (not strong), clean and crisp, no clutter. Main-country border: bold dark line (#1A1A1A); neighbor borders: thin iron-gray (#6C6C6C). Country name shown as Traditional Chinese + English (English in TVBS blue #1E4FC7, Chinese in dark gray #333333); neighbor countries labeled in thin iron-gray Traditional Chinese only. Smooth vector rendering, soft gradients.' },
                { zh:'簡明世界地圖', en:'Flat vector map design, broadcast news graphic style, professional geopolitical visualization, minimal shapes with sharp borders. Neutral grey base map, bright red highlighted regions, white and dark blue text elements, soft light-blue ocean background. Bold sans-serif headline, clean sans-serif labels, smooth digital vector texture, flat color fields, no gradients or minimal gradients.' }
            ],
            '軍事風格': [
                { zh:'軍事UI 戰情室', en:'風格是白宮戰情室由上而下俯瞰戰情地圖，全息投影，標籤有飄浮的科技UI立體感，正進行軍事兵推戰棋，有戰機飛彈的小模型或圖標。' },
                { zh:'軍事戰棋 立體模型', en:'精緻的立體模型地圖，標示的地點依照現實地理位置標出來，小模型isometric。風格是精緻兵推戰棋軍事科技風格。' },
                { zh:'軍事戰棋 夜景', en:'精緻的立體模型地圖，俯瞰，夜晚微光，有燈火亮光，標示的地點依照現實地理位置標出來，小模型isometric。風格是精緻兵推戰棋軍事科技風格。' },
                { zh:'全息投影地形', en:'精緻圓形全息投影立體地形圖，觀者視角isometric，放在黑暗的戰情室的正中間，標籤UI也是全息投影漂浮立體感。' }
            ],
            '復古插畫': [
                { zh:'WPA Poster', en:'WPA Poster 向量插畫風格，適合用在地圖的風格與配色。Color palette: parchment cream base (#EBE4D1), tan land shading (#D8C7A5), navy blue title blocks (#1D2A38), ocean blue water (#446E82), classic gold accents (#B79440), steel blue icon backgrounds (#ADC2D1), white text on dark backgrounds.' },
                { zh:'威權宣傳向量', en:'威權國家宣傳向量插畫風格，不要明顯的國家標誌元素(如 紅星)。' }
            ]
        },
        structures: {
            '自訂': [ { zh:'預設', en:'Manual map specification', template: '[標題]\n[地區]\n<地點標記>' } ],
            '地圖類型': [
                { zh:'單點定位（國家+地點）',
                  en:'Vector map of the specified country. All geographic markers MUST be placed strictly according to actual coordinates; no beautification adjustment or repositioning is allowed. Mark the capital with a black star EXACTLY at its true coordinate, labeled 「首都 + 名稱」 in a white label box. Mark the user-specified location with a red dot (#E53935) EXACTLY at the given coordinates, label placed near the dot without replacing it. The whole map may be shifted for layout, but marker positions must never move independently of the map. Do NOT display coordinate numbers or English names of the specified location.',
                  template: '[國家名稱（中文）] <國家>\n[指定地點名稱（中文）] <地點>\n[指定地點座標 lat,long] <座標>\n[地點標籤（可留白）] <標籤>' },
                { zh:'多點標示（模型註解）',
                  en:'製作新聞圖表，主視覺是大地圖，標出相對應的實際地理位置。每個地點有標籤，配 isometric 小模型或圖標與內文註解。',
                  template: '[左上方國旗、右上方國旗]\n[大標題] <標題>\n\n[地點1 標籤] <地名>\n[地點1 isometric模型 + 內文] <說明>\n\n[地點2 標籤] <地名>\n[地點2 isometric模型 + 內文] <說明>\n\n[地點3 標籤] <地名>\n[地點3 isometric模型 + 內文] <說明>' },
                { zh:'世界地圖 多國套色',
                  en:'世界地圖並依序將指定國家套色，並標出各國名稱。國家的位置要核對正確的資訊，根據網路資料重複驗證。Central world map layout, color-coded highlighted regions, text labels anchored to countries, title banner at the top, clean grid-aligned information blocks.',
                  template: '[標題] <標題>\n[套色國家清單]\n<國家1>、<國家2>、<國家3>' },
                { zh:'部署／設施標示',
                  en:'底圖是指定區域地圖，稍微刷淡。以簡單向量插圖在對應的實際位置標出艦艇、部隊或設施，插圖下方或旁邊放名稱與說明文字。',
                  template: '[標題] <國旗> <標題>\n<向量插圖 放在實際位置> <名稱>\n[內文] <說明>' },
                { zh:'航跡／路線圖',
                  en:'重新繪製航跡圖，地圖風格為簡單向量，航跡線要明顯可辨識，有細黑線框。交通工具 ICON 放在指定的位置，時間與說明文字跟著 ICON 放置。',
                  template: '[大標題] <標題>\n[大標題底下 小小字] <日期/時區>\n\n[ICON地點: <位置>]\n[放在ICON上面 字大] <時間>\n[內文] <說明>' },
                { zh:'地震速報',
                  en:'TV news "Earthquake Breaking Alert" infographic. From the pasted USGS input, automatically: translate ALL place names into Traditional Chinese; convert the location string into 「{地名}{方位}{距離}公里」 (N→以北 S→以南 E→以東 W→以西 NE→東北方 NW→西北方 SE→東南方 SW→西南方); extract country for the main title 「{國家} M {規模} 地震」; convert UTC to Taiwan time (UTC+8) formatted MM-DD HH:MM:SS; extract depth and epicenter coordinates. Main map: Google-Maps-style clean vector map around the epicenter, marked with vivid red (#E53935) concentric rings, map occupies the majority of the frame. Secondary line: 「震源深度 {深度} km」 centered + 「台灣時間 MM-DD HH:MM:SS」 small right-aligned. Right-side info box: 「震央位置：{方位距離}」. Bottom-right small font: 「資料來源：USGS」. All visible text must be Traditional Chinese.',
                  template: '[USGS原文貼上]\nM 6.4 - 27 km E of Santiago, Philippines\n2026-01-07 03:02:58 (UTC)\n7.254°N 126.823°E\n58.5 km depth' },
                { zh:'天氣／數據地圖',
                  en:'文字有立體感，不要新增沒給的文字或內容。內文跟插圖同樣 isometric 的立體視角 UI，不要照觀者視角，就像立體模型上的標示，對應地理位置，可用拉線延伸避免視覺擁擠，標出各地點數字，以主題 ICON 填滿比例來表示百分比，數字寫在 ICON 內。',
                  template: '[標題] <標題>\n[次標題 字小] <單位說明>\n\n<地點1> <數值> <百分比>\n<地點2> <數值> <百分比>\n<地點3> <數值> <百分比>' }
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
        aspect: '16:9',
        tabs: ['style', 'structure', 'visual'],
        styles: {
            '3D風格': [
                { zh:'技術示意', en:'Technical 3D diagram style, clean isometric or cutaway rendering, engineering-illustration clarity, neutral broadcast palette with accent highlights on key parts.' },
                { zh:'寫實3D', en:'Photorealistic 3D reconstruction, accurate materials and lighting, documentary broadcast quality, focus on plausibility.' },
                { zh:'剖面透視', en:'Cutaway cross-section 3D illustration revealing internal structure or hidden mechanics, labeled layers, technical broadcast aesthetic.' },
                { zh:'簡潔圖解', en:'Clean simplified 3D infographic style, reduced detail, strong shapes and arrows, optimized for quick comprehension on TV.' }
            ],
            '實戰風格包': [
                { zh:'TVBS藍', en:'TVBS-style news infographic aesthetic, using signature TVBS blue (pure blue, not purple) as the primary accent color, combined with contrasting highlight accents in a different hue such as TVBS orange for emphasis. Modern bold sans-serif typography for high readability, clean semi-flat vector rendering, soft controlled shadows, balanced contrast, subtle light-gray reflective background texture with a smooth, faint mirror-like finish that is not distracting, minimal ornamentation, crisp edges, polished broadcast-screen look, clean white and gray UI elements, high-clarity digital finish, no clutter, no metallic textures, no TVBS logo.' },
                { zh:'夜藍檳金', en:'Modernized Art Deco combined with Fintech Aesthetic. Deep navy background (#010B13), metallic gold titles and icons (#D4AF37), champagne gold text highlights (#F5E1A4), royal blue node containers (#0B2545), glowing orange arrows and flow lines (#FFB347), grid cyan decorative lines (#0077B6). High contrast between cold navy and warm gold, glow effects on arrows to suggest motion, low-saturation dark background keeping foreground data as the sole visual focus.' },
                { zh:'線索板', en:'警方調查辦案的線索board，每一個時間點都是單獨的線索卡，有立體感。' },
                { zh:'New Deal立體', en:'New Deal Graphic Style 有立體感。' },
                { zh:'教科書立體', en:'設計精緻、極度有視覺創意、有立體感的資訊圖表，風格是國家地理雜誌的精緻資訊圖表。' },
                { zh:'UE5電影渲染', en:'UE5電影等級精緻渲染風格。' }
            ]
        },
        structures: {
            '自訂': [ { zh:'預設', en:'Manual process specification', template: '[標題]\n[步驟]\n<步驟1>\n<步驟2>' } ],
            '實戰構圖': [
                { zh:'步驟流程圖',
                  en:'製作一張流程圖，每個步驟配一張照片或簡單向量插圖，以箭頭連接。步驟編號用主色底＋白字＋圓圈呈現。',
                  template: '[標題] <標題>\n\n<步驟1 主色底+白字+圓圈> 1\n<步驟1 說明>\n\n<步驟2 主色底+白字+圓圈> 2\n<步驟2 說明>\n\n<步驟3 主色底+白字+圓圈> 3\n<步驟3 說明>' },
                { zh:'報導精簡流程圖',
                  en:'以流程圖的方式解說事件機制，繁體中文，字精簡不要太多。將原報導內容精簡設計成流程解說圖，節點之間以箭頭連接表示流向。',
                  template: '[大標題] <標題>\n[左節點] <主體A>\n[右節點] <主體B>\n[以下是原報導 幫我精簡 設計流程解說圖]\n<貼上報導段落>' },
                { zh:'左圖右時間軸',
                  en:'最上方標題。左邊是相關地圖或圖片（重點元素加小icon），右邊是有設計感的時間軸，年份數字都用標籤呈現。',
                  template: '[標題] <標題>\n[左圖] <地圖或照片說明>\n[時間軸 年份數字都用標籤 <>內強調變色]\n<年份1> <事件1>\n<年份2> <事件2>\n<年份3> <事件3>' },
                { zh:'線索卡時間軸',
                  en:'每一個時間點都是單獨的線索卡，日期改成日曆icon上面寫日期，可搭配指定照片放在側邊。',
                  template: '[標題] <標題>\n[標題第二行 字小] <副標>\n[左邊] <照片或主圖說明>\n[右內文區 日期改成日曆icon上面寫日期]\n<日期1> <事件1>\n<日期2> <事件2>\n<日期3> <事件3>' }
            ],
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
    digestDensity: 'standard',
    currentTab: 'style',
    engine: 'gemini',
    imageSize: '1K',
    activeParent: null,
    currentPage: 1,
    // 第一頁「自動生成」專用的圖表類型，與第二頁模板庫的 chartType 完全獨立
    // 'auto' = 懶人機制，交給 AI 依新聞內容自行判斷版型
    digestChartType: 'auto',
    // 自動判斷模式下，AI 實際選了哪一類（由後端 chart_type 回報）
    digestResolvedType: null,
    // 最終 Prompt 的類型標籤聽誰的：'digest'（第一頁自動生成）或 'library'（第二頁調版型）
    // 由「最後一次動作」決定
    promptTypeSource: 'library',
    // selected 依 chartType 分開存，避免切類型互相污染
    selectedByType: {}
};

function curType() { return CHART_TYPES[state.chartType]; }

/* 第一頁「AI 自動判斷版型」的懶人選項，非真實 CHART_TYPES 成員 */
const AUTO_TYPE_KEY = 'auto';
const AUTO_TYPE_LABEL = '自動判斷';   // 需與 main.py 的 AUTO_TYPE_LABEL 一致
const AUTO_TYPE = {
    label: 'AI 自動判斷',
    hint: '不確定用哪種就選這個：AI 會讀完新聞後，自行從四大類型挑一個最合適的來設計版型。',
    aspect: '16:9'
};

// 第一頁自動生成所用的圖表類型
function digestType() {
    if (state.digestChartType === AUTO_TYPE_KEY) {
        // AI 已判斷過就顯示它選的那一類，否則顯示「AI 自動判斷」
        return state.digestResolvedType ? CHART_TYPES[state.digestResolvedType] : AUTO_TYPE;
    }
    return CHART_TYPES[state.digestChartType];
}

// 送給後端的類型標籤：自動判斷模式一律送 sentinel，由 AI 選型
function digestTypeLabelForApi() {
    return state.digestChartType === AUTO_TYPE_KEY ? AUTO_TYPE_LABEL : digestType().label;
}

// 目前生效於最終 Prompt 的圖表類型（依 promptTypeSource）
function activeType() {
    if (state.promptTypeSource !== 'digest') return curType();
    // 選了自動判斷但 AI 還沒判斷過，沒有具體類型可寫進 Prompt，退回第二頁的類型
    if (state.digestChartType === AUTO_TYPE_KEY && !state.digestResolvedType) return curType();
    return digestType();
}

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
    renderDigestTypes();
    resetToType('data');
    updateAIBtnRoleHint();
    switchPage(1);
};

/* ============================================================
   頁面切換（第一頁 快速生成 / 第二頁 進階微調）
   Final Prompt Output 面板為共用單一實例，切頁時搬到當前頁的掛載點，
   避免重複 id 造成 getElementById 取到錯誤的節點
   ============================================================ */
function switchPage(page) {
    state.currentPage = page;

    [1, 2].forEach(n => {
        const section = document.getElementById(`page-${n}`);
        const tab = document.getElementById(`pageTab-${n}`);
        section.classList.toggle('hidden', n !== page);
        tab.classList.toggle('page-tab-active', n === page);
    });

    const panel = document.getElementById('outputPanel');
    const mount = document.getElementById(`outputMount-${page}`);
    if (panel && mount && panel.parentElement !== mount) mount.appendChild(panel);

    updateActiveTypeBadge();
    window.scrollTo({ top: 0, behavior: 'smooth' });
}

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

/* 第二頁：調整版型用的圖表類型（只影響模板庫，不動第一頁） */
function resetToType(key) {
    state.chartType = key;
    state.currentTab = 'style';
    const t = curType();
    state.activeParent = Object.keys(t.styles)[0];
    document.getElementById('typeHint').innerText = t.hint;
    renderChartTypes();
    renderTabs();
    renderAll();
    // 在第二頁選類型＝以調版型為準
    claimPromptType('library');
}

/* ============================================================
   第一頁：自動生成專用的圖表類型（與第二頁模板庫完全脫鉤）
   切換它不會重置第二頁已選的版型與已填的矩陣
   ============================================================ */
function renderDigestTypes() {
    const c = document.getElementById('digestTypeSelector');
    if (!c) return;
    c.innerHTML = '';
    // 懶人機制擺第一個並為預設
    const entries = [[AUTO_TYPE_KEY, AUTO_TYPE], ...Object.entries(CHART_TYPES)];
    entries.forEach(([key, t]) => {
        const btn = document.createElement('button');
        const isAuto = key === AUTO_TYPE_KEY;
        const isActive = key === state.digestChartType;
        btn.className = `px-3 py-2 rounded-lg text-[10px] font-black border transition-all tracking-wide ${isActive ? 'type-active' : 'text-slate-400 bg-slate-900/50 border-slate-700 hover:bg-slate-800'}`;
        // 自動判斷完成後，按鈕顯示 AI 選了什麼
        btn.innerText = (isAuto && isActive && state.digestResolvedType)
            ? `AI 自動判斷：${CHART_TYPES[state.digestResolvedType].label}`
            : t.label;
        btn.onclick = () => setDigestType(key);
        c.appendChild(btn);
    });
    const hint = document.getElementById('digestTypeHint');
    if (hint) {
        hint.innerText = (state.digestChartType === AUTO_TYPE_KEY && !state.digestResolvedType)
            ? AUTO_TYPE.hint
            : digestType().hint;
    }
}

function setDigestType(key) {
    const changed = state.digestChartType !== key;
    state.digestChartType = key;
    // 換選項就讓上一次 AI 的判斷結果失效
    if (changed) state.digestResolvedType = null;
    renderDigestTypes();
    // 自動判斷但尚未真的生成過，還沒有具體類型可寫進 Prompt，不搶；
    // 但仍要重算輸出，否則 Prompt 會殘留上一個類型、與徽章不一致
    if (key === AUTO_TYPE_KEY && !state.digestResolvedType) {
        updateActiveTypeBadge();
        syncOutput();
        return;
    }
    // 在第一頁選類型＝以自動生成為準
    claimPromptType('digest');
}

/* 記錄「最後動作」是哪一頁，決定最終 Prompt 用哪個類型標籤 */
function claimPromptType(source) {
    state.promptTypeSource = source;
    updateActiveTypeBadge();
    syncOutput();
}

function updateActiveTypeBadge() {
    const t = activeType();
    const aspect = document.getElementById('aspectBadge');
    if (aspect) aspect.innerText = t.aspect;
    const badge = document.getElementById('activeTypeBadge');
    if (badge) {
        badge.innerText = t.label;
        badge.title = state.promptTypeSource === 'digest'
            ? '目前 Prompt 類型來自第一頁（自動生成）'
            : '目前 Prompt 類型來自第二頁（調整版型）';
    }
    const source = document.getElementById('activeTypeSource');
    if (source) {
        // 自動判斷但尚未生成時，activeType() 已退回第二頁的類型，來源也要跟著標第二頁
        const digestUsable = !(state.digestChartType === AUTO_TYPE_KEY && !state.digestResolvedType);
        const fromDigest = state.promptTypeSource === 'digest' && digestUsable;
        source.innerText = fromDigest ? '第一頁' : '第二頁';
    }
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

function switchRole(role) {
    state.currentRole = role;
    document.querySelectorAll('[data-role]').forEach(btn => {
        const isActive = btn.dataset.role === role;
        btn.classList.toggle('role-active', isActive);
        btn.classList.toggle('text-slate-500', !isActive);
    });
    state.currentTab = 'style';
    state.activeParent = Object.keys(curType().styles)[0];
    renderTabs();
    renderAll();
    updateAIBtnRoleHint();
    showToast(`已切換至 ${role} 模式`);
}

function switchDigestDensity(density) {
    state.digestDensity = density;
    document.querySelectorAll('[data-density]').forEach(btn => {
        const isActive = btn.dataset.density === density;
        btn.classList.toggle('density-active', isActive);
        btn.classList.toggle('text-slate-500', !isActive);
    });
    updateAIBtnRoleHint();
    showToast(`AI 消化已切換至${density === 'simplified' ? '簡化' : '標準'}模式`);
}

// Prompt 顯示區高度壓低後，用字元數讓使用者確認 Prompt 已生成、長度多少
function updatePromptCounter() {
    const counter = document.getElementById('promptCounter');
    if (!counter) return;
    const text = document.getElementById('displayPrompt').innerText.trim();
    const len = (text && text !== 'Waiting for data input…') ? text.length : 0;
    counter.innerText = `${len.toLocaleString()} 字元`;
    counter.classList.toggle('text-blue-400', len > 0);
    counter.classList.toggle('text-slate-600', len === 0);
}

// 新聞輸入框高度壓低後，用字數提示讓使用者確認貼上的量
function updateNewsCounter() {
    const input = document.getElementById('aiInput');
    const counter = document.getElementById('newsCounter');
    if (!input || !counter) return;
    const len = input.value.trim().length;
    counter.innerText = `${len.toLocaleString()} 字`;
    counter.classList.toggle('text-blue-400', len > 0);
    counter.classList.toggle('text-slate-600', len === 0);
}

// AI 消化按鈕顯示目前角色與文字密度，避免用錯模式
function updateAIBtnRoleHint() {
    const buttonText = document.getElementById('aiBtnText');
    const densityLabel = state.digestDensity === 'simplified' ? '簡化' : '標準';
    if (buttonText) {
        buttonText.innerText = `開始 AI 自動消化整理（${state.currentRole}・${densityLabel}）`;
    }
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
    updateAspectBadge();
    syncOutput();
}

function switchImageSize(size, el) {
    state.imageSize = size;
    document.getElementById('size-1K').className = 'px-3 py-1 rounded text-[9px] font-black transition-all ' + (size === '1K' ? 'bg-blue-600 text-white' : 'text-slate-500 hover:text-white');
    document.getElementById('size-2K').className = 'px-3 py-1 rounded text-[9px] font-black transition-all ' + (size === '2K' ? 'bg-blue-600 text-white' : 'text-slate-500 hover:text-white');
    updateAspectBadge();
}

// GPT 固定 1280×720（忽略解析度切換）；Gemini 才依 1K／2K 變動
function updateAspectBadge() {
    const badge = document.getElementById('aspectBadge');
    if (!badge) return;
    badge.innerText = state.engine === 'gpt' ? '16:9 / 720p' : `16:9 / ${state.imageSize}`;
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
            renderTags(); updateCounter();
            // 在第二頁選版型＝以調版型為準（claimPromptType 內含 syncOutput）
            claimPromptType('library');
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

    invalidateGeneratedImage();

    if (!style && !structure && !variableInput && !visual) {
        display.innerText = "Waiting for data input…";
        updatePromptCounter();
        return;
    }

    const processedVariable = variableInput ? `${SYSTEM_DISCLAIMER}\n${variableInput}` : '[No Variables Defined]';
    const styleContent = style || '[No Style Defined]';
    const structureContent = structure || '[No Structure Defined]';
    const combinedStyle = visual ? styleContent + '\nVISUAL REQUIREMENTS:\n' + visual : styleContent;

    display.innerText = buildPrompt({
        role: state.currentRole,
        engine: state.engine,
        typeLabel: activeType().label,
        style: combinedStyle,
        structure: structureContent,
        variable: processedVariable
    });
    updatePromptCounter();
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
- Centred composition, single continuous full-frame background
- Scale the whole design so it fills the central content zone defined in EMPTY MARGIN RULES generously — margins stay within their stated ranges, neither thinner nor dramatically thicker

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
- The final generated image must NOT contain any "[" "]" or "<" ">" characters — every bracket in this prompt is a markup delimiter, never content.
- The markup tag words themselves (標題, 內文小標, 蓋章) are instructions, NEVER content: none of them may appear anywhere in the image.
- No English instruction text from this prompt may appear in the image; the only visible text is the actual content from VARIABLE FIELDS.
- Use only Traditional Chinese (Taiwan standard).
- Ensure all characters are correct with proper stroke forms.
- SELF-CHECK before finalizing: if any bracket character or any markup tag word is visible anywhere in the image, remove it and re-render that text before output.`;

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

Text Markup Rules (apply to VARIABLE FIELDS):
- The user text uses inline markup. Bracket characters are markup delimiters ONLY and are NEVER drawn in the image.
- Line-type tags: a line may START with a tag word wrapped in square brackets (the tag words are 標題 and 內文小標). The tag only declares the line's role (title line / subtitle line). Drop the tag and its brackets completely — the tag word itself must NEVER appear in the image; render only the text that follows it.
- Emphasis marks: a word or phrase wrapped in angle brackets INSIDE a line is emphasized content. Drop the brackets, keep the inner text, and apply a highlight color such as yellow gold or cyan, with optional glow effect.
- Stamp command: a line starting with the word 蓋章 wrapped in angle brackets is a command line. The word 蓋章 must NEVER appear in the image. Apply a strong full-box highlight style to the text that follows on that line: solid background color (e.g. red background with white text).

Subtitles:
- A subtitle line (tagged 內文小標 in the markup) whose text is fewer than 6 full-width characters (中文字) should be rendered as a "Tag" (Label) visual representation (e.g., pill-shaped background, high-contrast block).`;

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

Text Markup Rules (apply to VARIABLE FIELDS):
- The user text uses inline markup. Bracket characters are markup delimiters ONLY and are NEVER drawn in the image.
- Line-type tags: a line may START with a tag word wrapped in square brackets (the tag words are 標題 and 內文小標). The tag only declares the line's role (title line / subtitle line). Drop the tag and its brackets completely — the tag word itself must NEVER appear in the image; render only the text that follows it.
- Emphasis marks: a word or phrase wrapped in angle brackets INSIDE a line is emphasized content. Drop the brackets, keep the inner text, and apply a highlight color such as yellow gold or cyan, with optional glow effect.
- Stamp command: a line starting with the word 蓋章 wrapped in angle brackets is a command line. The word 蓋章 must NEVER appear in the image. Apply a strong full-box highlight style to the text that follows on that line: solid background color (e.g. red background with white text).

Subtitles:
- A subtitle line (tagged 內文小標 in the markup) whose text is fewer than 6 full-width characters (中文字) should be rendered as a "Tag" (Label) visual representation.

Visual Elements:
- Include high-quality flat icons or 3D data charts relevant to the content
- Background: professional broadcast news style, subtle glow / tech lines, strictly NO plain gradients`;

/* 安全框百分比設定（實驗中，feat/percent-safe-area）：調整數值只需改這裡 */
const SAFE_MARGIN_PCT = { side: '8–10%', top: '8–10%', bottom: '22–26%', zoneW: '80–84%', zoneH: '64–70%' };

const SAFE_PCT_HEADER =
`- PROPORTIONAL MARGIN REFERENCE: the margins below are proportions of the frame dimensions. These percentage values are internal layout measurements ONLY — they are instructions, NEVER content: do NOT draw, print, or render any of these numbers, the "%" character, or any measurement annotation anywhere in the final image.
- RESERVED EMPTY MARGINS (measured inward from each frame edge):
  - Left margin: approximately ${SAFE_MARGIN_PCT.side} of frame width — completely empty
  - Right margin: approximately ${SAFE_MARGIN_PCT.side} of frame width — completely empty
  - Top margin: approximately ${SAFE_MARGIN_PCT.top} of frame height — completely empty
  - Bottom reserved band: approximately ${SAFE_MARGIN_PCT.bottom} of frame height (deliberately deeper than the sides) — completely empty
  - The bottom reserved band is the lowest slice of the frame: treat it as if it will be physically cropped away after generation, so design the ENTIRE layout for only the remaining upper portion of the canvas. EVERYTHING — including any closing banner, summary strip, stamp banner, or lowest row of content — must end well above the band, within roughly the upper 70 percent of the frame height. The closing/summary banner is the element that most often violates this rule: deliberately place it noticeably HIGHER than feels visually natural. Nothing may sit in, touch, or overlap the band.
- CENTRAL CONTENT ZONE: all content must fit entirely inside the remaining central zone (approximately ${SAFE_MARGIN_PCT.zoneW} of frame width, ${SAFE_MARGIN_PCT.zoneH} of frame height).
- MARGINS ARE BOUNDED ON BOTH SIDES, AND THE MINIMUM WINS: first guarantee every margin meets its stated minimum — this takes absolute priority over everything else. Only after the minimum margins are secured, size the content group to use the central content zone well; do not leave the design floating small in the middle with borders far thicker than the stated ranges. If filling the zone would ever conflict with the minimum margins, KEEP THE MARGINS and shrink the content instead.`;

const REPORTER_SAFE_AREA =
`==================================================
EMPTY MARGIN RULES (CRITICAL — MUST PRESERVE)
==================================================
${SAFE_PCT_HEADER}
- These are layout guides only. The final image is ONE single continuous background with the subject centred; the margins are visually identical to the centre — same colour, tone and brightness everywhere. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, or dimmed / tinted / shaded band to mark the empty area. The empty margin must be completely invisible.
- SCALE THE WHOLE LAYOUT INWARD: treat the entire infographic as one group and shrink it so it fits the central content zone defined above. The content group must NOT fill the frame.
- These empty-margin rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction places content in a reserved margin, ignore that placement and keep the margin empty.
- The top margin must contain: NO title text, NO headline, NO icons, NO logos, NO decorative elements.
- The left margin must contain: NO stat cards, NO numerical modules, NO icons, NO borders, NO text.
- The right margin must contain: NO indicators, NO boxes, NO icons, NO leader lines, NO text.
- The bottom reserved band must contain:
  - NO text
  - NO logos
  - NO icons
  - NO charts
  - NO divider lines
  - NO decorative elements
  - NO data-source line
- This bottom strip simply stays empty so on-air lower-third graphics never cover any content.
- The background color or background image from the active content area above MUST extend seamlessly into all four reserved margins — no change in color, texture, brightness, or visual tone; no hard edges, no visual breaks, no overlays, no gradients.
- FORBIDDEN terms/effects in the final composition: full-width, edge-to-edge, flush left, flush right, flush top, spans the entire width, corner-to-corner, bleed, touching the frame boundary.
- SELF-CHECK before finalizing: if any text block, card, icon, or box crosses into any reserved margin defined above, you MUST redesign the layout so everything fits the central content zone before output.`;

const EDITOR_SAFE_AREA =
`==================================================
EMPTY MARGIN RULES (CRITICAL — MUST PRESERVE)
==================================================
${SAFE_PCT_HEADER}
- These are layout guides only. The final image is ONE single continuous background with the subject centred; the margins are visually identical to the centre — same colour, tone and brightness everywhere. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, or dimmed / tinted / shaded band to mark the empty area. The empty margin must be completely invisible.
- SCALE THE WHOLE LAYOUT INWARD: treat the entire infographic as one group and shrink it so it fits the central content zone defined above. The content group must NOT fill the frame.
- These empty-margin rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction places content in a reserved margin, ignore that placement and keep the margin empty.
- Every reserved margin (top, bottom, left, right) must contain:
  - NO text
  - NO logos
  - NO icons
  - NO charts
  - NO divider lines
  - NO decorative elements
  - NO data-source line
  - NO stamp banner (the full-box highlight banner produced by the stamp command)
- The background color or background image MUST extend seamlessly into all reserved margins — no change in color, texture, brightness, or visual tone; no hard edges, no visual breaks, no overlays, no gradients.
- FORBIDDEN terms/effects in the final composition: full-width, edge-to-edge, flush left, flush right, flush top, flush bottom, spans the entire width, corner-to-corner, bleed, touching the frame boundary.
- SELF-CHECK before finalizing: if any text block, card, icon, or box crosses into any reserved margin defined above, you MUST redesign the layout so everything fits the central content zone before output.`;

/* ============================================================
   AI 消化：透過本地後端代理呼叫 Claude（見 main.py）
   ============================================================ */
const AI_BACKEND_URL = "http://127.0.0.1:8787/api/generate";
const IMAGE_BACKEND_URL = "http://127.0.0.1:8787/api/images/generate";

async function handleAIDigestion() {
    const input = document.getElementById('aiInput').value.trim();
    if (!input) return showToast("請輸入欲消化整理的新聞內容");

    const btnText = document.getElementById('aiBtnText');
    const loading = document.getElementById('aiLoading');
    const btn = document.getElementById('aiBtn');
    btn.disabled = true; btnText.classList.add('hidden'); loading.classList.remove('hidden');

    // 自動生成一律用第一頁自己的圖表類型（'auto' 時送 sentinel 交由 AI 選型）
    const typeLabel = digestTypeLabelForApi();

    try {
        const response = await fetch(AI_BACKEND_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                news_text: input,
                type_label: typeLabel,
                role: state.currentRole,
                density: state.digestDensity
            })
        });
        if (!response.ok) throw new Error("HTTP " + response.status);
        const data = await response.json();

        const s = curSelected();
        s.style = {}; s.structure = {};
        document.getElementById('field-style').value = data.style || '';
        document.getElementById('field-structure').value = data.structure || '';
        document.getElementById('field-variable').value = (data.variable || '').replace(SYSTEM_DISCLAIMER, '').trim();

        // 自動判斷模式：記下 AI 實際選了哪一類，供徽章與按鈕顯示
        if (state.digestChartType === AUTO_TYPE_KEY) {
            const resolvedKey = Object.keys(CHART_TYPES)
                .find(k => CHART_TYPES[k].label === data.chart_type);
            state.digestResolvedType = resolvedKey || null;
            renderDigestTypes();
        }

        renderTags(); updateCounter();
        // 剛做完自動生成＝以第一頁的類型為準（claimPromptType 內含 syncOutput）
        claimPromptType('digest');
        showToast(state.digestResolvedType
            ? `AI 判斷為「${CHART_TYPES[state.digestResolvedType].label}」並完成佈局規劃`
            : "AI 已完成佈局規劃與視覺輔助設計");
    } catch (err) {
        console.error(err);
        showToast("AI 服務連線失敗，請稍後再試");
    } finally {
        btn.disabled = false; btnText.classList.remove('hidden'); loading.classList.add('hidden');
    }
}

/* ============================================================
   圖片生成：僅在使用者確認最終 Prompt 後呼叫後端代理
   ============================================================ */
function getFinalPrompt() {
    return document.getElementById('displayPrompt').innerText.trim();
}

function updateImageGenerationControls() {
    const confirmed = document.getElementById('promptConfirmed');
    const button = document.getElementById('generateImageBtn');
    const buttonText = document.getElementById('generateImageBtnText');
    const hint = document.getElementById('imageGenerationHint');
    if (!confirmed || !button || !buttonText || !hint) return;

    const hasPrompt = !getFinalPrompt().includes('Waiting for data');
    const providerName = state.engine === 'gpt' ? 'GPT' : 'Gemini';
    button.disabled = !confirmed.checked || !hasPrompt;
    buttonText.innerText = `使用 ${providerName} 生成圖片`;

    if (!hasPrompt) {
        hint.innerText = '請先填寫內容，產生最終 Prompt';
    } else if (!confirmed.checked) {
        hint.innerText = `確認後可使用 ${providerName} 一鍵生成 16:9 圖片`;
    } else {
        hint.innerText = `將以目前顯示的 Prompt 送至 ${providerName} 生成圖片`;
    }
}

function invalidateGeneratedImage() {
    const confirmed = document.getElementById('promptConfirmed');
    const result = document.getElementById('generatedImageResult');
    const image = document.getElementById('generatedImage');
    const download = document.getElementById('downloadGeneratedImage');

    if (confirmed) confirmed.checked = false;
    if (result) result.classList.add('hidden');
    if (image) image.removeAttribute('src');
    if (download) download.removeAttribute('href');
    updateImageGenerationControls();
}

async function handleImageGeneration() {
    const confirmed = document.getElementById('promptConfirmed');
    const prompt = getFinalPrompt();
    if (!confirmed.checked || prompt.includes('Waiting for data')) {
        updateImageGenerationControls();
        return;
    }

    const provider = state.engine === 'gpt' ? 'gpt' : 'gemini';
    const providerName = provider === 'gpt' ? 'GPT' : 'Gemini';
    const button = document.getElementById('generateImageBtn');
    const buttonText = document.getElementById('generateImageBtnText');
    const loading = document.getElementById('generateImageLoading');
    button.disabled = true;
    buttonText.classList.add('hidden');
    loading.classList.remove('hidden');

    try {
        const response = await fetch(IMAGE_BACKEND_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                prompt,
                provider,
                aspect_ratio: '16:9',
                image_size: state.imageSize
            })
        });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || `HTTP ${response.status}`);

        const image = document.getElementById('generatedImage');
        const download = document.getElementById('downloadGeneratedImage');
        const result = document.getElementById('generatedImageResult');
        const resultLabel = document.getElementById('generatedImageProviderLabel');
        const imageUrl = `data:${data.mime_type};base64,${data.image_data_base64}`;
        const isPng = data.mime_type === 'image/png';
        image.src = imageUrl;
        download.href = imageUrl;
        download.download = `tvbs-news-cg.${isPng ? 'png' : 'jpg'}`;
        download.innerText = `下載 ${isPng ? 'PNG' : 'JPEG'}`;
        resultLabel.innerText = `${providerName} Generated Preview`;
        image.alt = `${providerName} 生成的新聞 CG 預覽`;
        result.classList.remove('hidden');
        showToast(`${providerName} 已完成圖片生成`);
    } catch (err) {
        console.error(err);
        showToast(err.message || '圖片生成失敗，請稍後再試');
    } finally {
        buttonText.classList.remove('hidden');
        loading.classList.add('hidden');
        updateImageGenerationControls();
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
