/* ============================================================
   TVBS 新聞AICG產生器
   資料模型：頂層為「圖表類型」，各類型下有 styles / structures / visual 三層
   ============================================================ */

const SYSTEM_DISCLAIMER = '"< >" "[ ]" 是給你的指令 不要生成在結果上';
const DEFAULT_VARIABLE_TEMPLATE = '[標題]\n[內文]';

/* ---------- 共用：品牌風格包（四類共用同一組視覺語言） ---------- */
const LIGHT_LUXURY_TECH_STYLE = {
    zh: '銀藍香檳金',
    en: 'Professional Taiwanese broadcast infographic in a light-luxury technology aesthetic: overall high-brightness, low-to-medium saturation; misty blue-grey, silver-blue and pearl-white background tones (#B4C7D5, #D1DADB, #A3B8CA); semi-transparent ice-blue, silvery-white and cool-grey glass information panels; champagne-gold, soft-gold and restrained antique-bronze accents (#CBA352, #D6CDAF, #966F30); all text in deep steel-grey or deep blue-grey; never use pure black text, a large dark-blue or black background, neon colours or saturated tech blue; use translucent glass, brushed metal, fine line-grid textures and soft high-key studio lighting for a clean upscale broadcast finish. Taiwan directional colour convention is mandatory: rise and increase use red, fall and decrease use green; do not use red or green as unrelated decoration.'
};
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
    ],
    '淺色風格': [LIGHT_LUXURY_TECH_STYLE]
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
            ],
            '淺色風格': [LIGHT_LUXURY_TECH_STYLE]
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
            ],
            '淺色風格': [LIGHT_LUXURY_TECH_STYLE]
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
            ],
            '淺色風格': [LIGHT_LUXURY_TECH_STYLE]
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
    // 2026-09-03：三檔（verbatim=不消化／simplified=字少／standard=字多），預設字少
    digestDensity: 'simplified',
    // 蓋章由使用者決定（2026-09-03）。以前是消化階段自己決定，同一個產品三種行為。
    // 2026-09-07 起預設 OFF（使用者裁決）；指令欄若提到蓋章，後端以指令欄為準（見 main.py 的優先序規則）。
    stamp: false,
    // 播出鏡面白色壓框（2026-09-07 使用者裁決：預設 OFF）。OFF＝不蓋白框，底圖完整交給
    // 後製自己放影片；ON＝置框後蓋白框給後製對位。只在播出鏡面版型顯示這顆。
    hole: false,
    // 播出鏡面挖空側（2026-09-08 WP1：左切／右切合併成一個版型後，方向改成版型內的
    // 一組按鈕）。預設左，切版型時重置——換版型還記著上一次的方向只會讓人選錯邊。
    holeSide: 'left',
    // 色調（2026-09-04）。預設暗色調＝維持既有畫面風格，改成亮色調是使用者的主動選擇。
    // 兩檔都會送給後端並注入 prompt（不是「預設不注入」），因為只寫亮不寫暗時，
    // 樣板裡本來就偏暗的措辭會跟亮色調各聽一半，出半亮半暗的圖。
    tone: 'dark',
    // 最近一次消化查到的地圖座標；非地圖類一律空陣列
    mapPoints: [],
    // 編輯專屬版型（2026-09-03）。切回記者角色時一律重置成 default——
    // 這是「記者不可能誤用」的第二層防呆（第一層是下拉根本不顯示，第三層在後端）。
    // 寫字面值而不是 EDITOR_FORMAT_DEFAULT：那個 const 宣告在 state 之後，
    // 引用它會在載入時就 ReferenceError（TDZ）。
    editorFormat: 'default',
    currentTab: 'style',
    // 2026-08-17 改以 GPT 為預設引擎（UI 上 GPT 也排在 Gemini 前面）
    engine: 'gpt',
    imageSize: '1K',
    // 安全框置框：滿版生成後由後端 safe_frame.py 數學置入 TVBS 安全框
    safeFrame: true,
    activeParent: null,
    currentPage: 1,
    // 第一頁「自動生成」專用的圖表類型，與第二頁模板庫的 chartType 完全獨立
    // 'auto' = 懶人機制，交給 AI 依新聞內容自行判斷版型
    digestChartType: 'auto',
    // 自動判斷模式下，AI 實際選了哪一類（由後端 chart_type 回報）
    digestResolvedType: null,
    // 最近一次消化回傳的具名真人，生圖時交給後端查參考照
    portraitSubjects: [],
    // 同順序的英文原名，生圖時一併送給後端當查圖備援：
    // 臺灣譯名常常不是中文維基的條目名（2026-08-18）
    portraitSubjectsEn: [],
    // 最終 Prompt 的類型標籤聽誰的：'digest'（第一頁自動生成）或 'library'（第二頁調版型）
    // 由「最後一次動作」決定
    promptTypeSource: 'library',
    // selected 依 chartType 分開存，避免切類型互相污染
    selectedByType: {},
    // ② 使用者上傳的參考圖：[{dataUrl, purpose:'map'|'scene', name}]
    userRefImages: [],
    // 十點封面左右上傳位（2026-09-07）：{left:{dataUrl,name}|null, right:...}
    coverAsis: { left: null, right: null },
    // ③ 追加修改用：**置框前**原圖（不是顯示中的成品——成品餵回去會二次拉伸）
    // refineSource = {base64, mimeType}；refineDisplay = 顯示中成品的原始回傳；
    // refineStack 供「退回上一版」
    refineSource: null,
    refineDisplay: null,
    // YT 直播封面：上一次的無文字底圖是不是 AI 生的（重疊文字時決定要不要標 AI示意圖）。
    // 底圖本身走 refineSource（語意相同：給改圖用的原圖）。
    ytCoverBackgroundIsAi: false,
    // 目前成品是哪種標題模式（來自後端回應）：追加修改與重疊固定元素要跟成品一致，不看勾選框
    ytCoverTitleMode: 'ai',
    // 十點封面：目前成品是 ai 還是 composite（來自後端回應）。只有 ai 版能追加修改。
    tenCoverMode: 'ai',
    // 十點封面（滿版合成版）的「只改文字」：上一次的壓字前底圖 {base64, mimeType, isAi}。
    // 刻意不共用 refineSource——那格的語意是「餵回 /api/images/refine 的原圖」，合成版
    // 沒有那種東西；混用會讓「修改」鈕誤以為合成版可以 refine（見 handleRefine）。
    tenCoverBackground: null,
    // 十點 AI 整張版的標題設計感（2026-09-08）：plain＝現行排版、designed＝滿框放大關鍵字。
    // 預設 plain——designed 讓模型大改版面，錯字與版面走鐘的風險比較高，要使用者自己開。
    coverTitleStyle: 'plain',
    // YT 封面底部壓色框：2026-09-08 晚使用者裁決預設**開**（60% 半透明、第二行上緣起羽化，見 compose）。
    // 整點直播的版面沒有底帶，按鈕不顯示。
    ytBottomBand: true,
    // YT 直播直標（2026-09-08 WP3）的五組開關。刻意**不**在 setEditorFormat 重置：
    // 直標是同一位導播一整場重複用的東西，換版型回來還要再選一次靠左／Logo 右上很煩。
    vstrip: {
        variant: 'normal',        // normal／original_audio／ai_translation
        titleSide: 'left',        // 直標貼哪一側
        logoCorner: 'tr',         // Logo 角落，不能跟直標同側
        sourceCorner: 'tl',       // 來源句角落（2026-09-09 起四角可選，取代 sourceFollowLogo）
        live: true,               // LIVE 章可取消
    },
    refineStack: []
};

function curType() { return CHART_TYPES[state.chartType]; }

/* ============================================================
   編輯專屬版型（2026-09-03）
   記者沒有這些需求，切到編輯角色才會出現這個下拉。
   key 與 label 需與 editor_formats.py 一致（test_prompt_parity 守著）。

   為什麼不併進「版面形式」：那組在後端是 strict JSON schema enum，
   而「AI 自動判斷」就是叫模型從那組裡自己挑——加進去等於模型會主動挑給記者，
   UI 藏得掉、模型挑不掉。
   為什麼不另開分頁：編輯的工作流是連貫的（同一則新聞先出鏡面、再做封面），
   而且輸入區以外的東西（產出、下載、追加修改）全部共用。
   改成「同一頁、選了格式就換裝輸入區」。

   inputs：'news'＝現行的新聞原文那組；'cover'＝左右標題那組
   presets：切到這個版型時**幫忙調好**的開關——調完使用者仍可自己改
   locks ：真的不准動的開關（只剩版面形式：它跟挖空框互相打架）
   hides ：這個版型用不到、整組收起來的控制項（收起來勝過鎖起來——
           留一排點不動的灰按鈕，使用者只會以為壞了；2026-09-04 使用者回報）
   hole  ：播出鏡面的挖空側，生圖時送給後端由程式數學貼框
   ============================================================ */
const EDITOR_FORMATS = {
    default: {
        label: '預設（現行）',
        hint: '',
        inputs: 'news',
        locks: {},
        hole: null,
    },
    // 2026-09-08 WP1：左切／右切合併成一個版型，方向改由下方那組按鈕（state.holeSide）
    // 決定，送 API 時當欄位帶過去。表裡的 hole 是預設方向，不是唯一方向。
    broadcast: {
        label: '播出鏡面',
        hint: '畫面其中半邊、垂直置中留一塊 16:9 空位給後製合成影片，內容自動編排到另一半。方向用下方按鈕選。',
        inputs: 'news',
        // 2026-09-07：preset 不再碰蓋章——原本 stamp:true 會把使用者關掉的蓋章切回 ON
        presets: { safeFrame: true, density: 'simplified' },
        locks: { chartType: true },
        hole: 'left',
    },
    // 十點不一樣封面：「標題由 AI 生成」勾選框切換 ai／composite（比照 YT 直播封面）。
    // 開＝整張由生圖模型畫（含節目名、標題、日期、標籤），只有 Logo 後製貼上；
    // 關＝AI 只生左右兩張無文字底圖，所有文字由程式壓字，零錯字。
    // 2026-09-08 WP1：滿版／雙切合併成一個版型，版面由「第二標題有沒有填」自動判定
    // （coverLayout: 'auto'，實際值一律問 coverLayoutNow()）。
    ten_cover: {
        label: '十點不一樣',
        hint: '只填第一標題＝滿版一張圖；再填第二標題＝左右雙切、兩格各一個標題與附圖位。有附圖的格直接上版，沒附圖的格 AI 生底圖。預設整張由生圖模型設計；關閉「標題由 AI 生成」則所有文字由程式壓字，零錯字。Logo 與節目標籤一律由程式貼正版檔。',
        coverLayout: 'auto',
        inputs: 'cover',
        coverMode: 'ai',
        // 封面沒有消化這道程序：/api/editor/cover 不收 density／stamp／safe_frame／tone，
        // 留著只會是四顆按了沒反應的按鈕，所以收起來而不是鎖起來
        locks: {},
        hides: { digestControls: true, safeFrame: true, stamp: true },
        hole: null,
    },
    // YT 直播封面：底圖來自附圖（原圖放置）或 AI，LIVE 章／日期／Logo／兩行標題全由程式疊。
    // 沿用主流程的附圖上傳區（用途：原圖放置＝直接當底圖；其他＝生圖參考）。
    yt_live_cover: {
        label: 'YT國內外新聞直播',
        hint: '標題用半形空格分兩段（分不出來時由 AI 判斷）。有「原圖放置」附圖就直接當底圖，否則 AI 生底圖並標示 AI示意圖。原音呈現／AI即時翻譯可勾可並存。文字與 Logo 全由程式疊，零錯字。',
        inputs: 'yt_cover',
        ytLayout: 'news',
        locks: {},
        hides: { digestControls: true, safeFrame: true, stamp: true },
        hole: null,
    },
    // YT 整點直播：同一條底圖流程，版面換成整點版（Logo 左上、LIVE 章右上＋選填整點時間、
    // 紅底日期、沒有副標）。
    yt_hourly_cover: {
        label: 'YT整點直播',
        hint: '整點直播封面：標題半形空格分兩段，整點時間（如 20:00）選填、有填才出現。第二標題填了就是「雙則」：上白＝第一則、下黃＝第二則，每行一整句不拆、最多 18 字，底圖左右兩張羽化拼成一張。附圖與底圖規則同國內外新聞直播。',
        inputs: 'yt_cover',
        ytLayout: 'hourly',
        locks: {},
        hides: { digestControls: true, safeFrame: true, stamp: true },
        hole: null,
    },
    // YT 直播直標（2026-09-08 WP3）：不是封面，是疊在直播訊號上的透明底 PNG。
    // 沒有底圖就沒有生圖、沒有附圖、沒有引擎、沒有「只改文字」與追加修改，
    // 所以 hides 收得比封面更多（連引擎與指令欄都收）。
    yt_vstrip: {
        label: 'YT直播直標',
        hint: '直播用的垂直標題條，透明底 PNG，直接疊在直播訊號上。第一標題最多 12 格、第二標題最多 14 格（連續英數字算一格）。不生圖、不打 AI。',
        inputs: 'yt_vstrip',
        locks: {},
        hides: { digestControls: true, safeFrame: true, stamp: true, engine: true, instruction: true, refUpload: true, refine: true },
        hole: null,
    },
    // YT 今日熱搜（2026-09-06 型錄 H 類）：紅色系「今日熱搜」標籤＋紅色 Logo 斜標，
    // 議題型版面，沒有日期、沒有 LIVE。底圖與標題規則同國內外新聞直播。
    yt_hot_cover: {
        label: 'YT今日熱搜',
        hint: '今日熱搜封面：標題半形空格分兩段，沒有日期與 LIVE。附圖與底圖規則同國內外新聞直播。',
        inputs: 'yt_cover',
        ytLayout: 'hot',
        locks: {},
        hides: { digestControls: true, safeFrame: true, stamp: true },
        hole: null,
    },
};
const EDITOR_FORMAT_DEFAULT = 'default';

function editorFormat() {
    return EDITOR_FORMATS[state.editorFormat] || EDITOR_FORMATS[EDITOR_FORMAT_DEFAULT];
}

/* 十點不一樣這一刻是滿版還是雙切（2026-09-08 WP1）。
   判定只有一條規則：第二標題有值＝雙切、空＝滿版。版型表寫死的 coverLayout
   只剩 'auto' 這個標記，實際值一律問這支——散在各處各自判斷，遲早會有一處忘了改。 */
function coverLayoutNow() {
    if (editorFormat().coverLayout !== 'auto') return editorFormat().coverLayout || '';
    const right = (document.getElementById('coverTitleRight')?.value || '').trim();
    return right ? 'split' : 'full';
}

/* YT 整點直播這一刻是單則還是雙則（2026-09-08 WP2）。判定只有一條規則：
   第二標題有值＝雙則（同一張底圖上下兩行，上白＝第一則、下黃＝第二則）。
   國內外新聞直播與今日熱搜沒有這個版面，一律 single。 */
const YT_HOURLY_LINE_MAX_CHARS = 18;
// 顯示寬度：全形算 1、半形算 0.5，跟後端 compose.title_display_width 同一套
function displayWidth(text) {
    let w = 0;
    for (const ch of (text || '').trim()) w += /[ᄀ-ᅟ⺀-꓏가-힣豈-﫿︰-﹏＀-｠￠-￦]/.test(ch) ? 1 : 0.5;
    return w;
}

function ytLayoutNow() {
    if ((editorFormat().ytLayout || '') !== 'hourly') return 'single';
    return (document.getElementById('ytCoverTitleSecond')?.value || '').trim() ? 'dual' : 'single';
}

/* ============================================================
   下載檔名（2026-09-08 使用者回饋 A）：全站所有版型共用一支。
   留空 → YYYYMMDD_<版型短名>_<標題前 8 字>；有填 → 使用者字串。
   檔名非法字元（Windows 不接受的那幾個）與換行一律去掉，收尾去空白。
   ============================================================ */
// 2026-09-08 WP1：兩個版型合併後，短名不再是一個 key 一個字串——十點看判定出來的
// 版面、播出鏡面看選的挖空側，所以那兩筆是巢狀的。
const DOWNLOAD_FORMAT_NAMES = {
    default: '編輯CG',
    broadcast: { left: '播出鏡面左', right: '播出鏡面右' },
    ten_cover: { full: '十點滿版', split: '十點雙切' },
    yt_live_cover: 'YT直播',
    yt_hourly_cover: { single: 'YT整點', dual: 'YT整點雙則' },
    yt_vstrip: 'YT直標',
    yt_hot_cover: 'YT熱搜',
};
const DOWNLOAD_NAME_ILLEGAL = /[\\/:*?"<>|\r\n]/g;
const DOWNLOAD_TITLE_MAX = 8;

function downloadFormatName(kind) {
    const key = kind || state.editorFormat || EDITOR_FORMAT_DEFAULT;
    // 記者角色沒有版型下拉，一律 default——短名跟編輯的 default 要分得開
    if (key === EDITOR_FORMAT_DEFAULT && state.currentRole !== '編輯') return 'CG';
    const name = DOWNLOAD_FORMAT_NAMES[key] || DOWNLOAD_FORMAT_NAMES[EDITOR_FORMAT_DEFAULT];
    if (typeof name === 'string') return name;
    // 巢狀：十點與 YT 整點用判定後的版面、播出鏡面用挖空側
    if (key === 'ten_cover') return name[coverLayoutNow()] || name.full;
    if (key === 'yt_hourly_cover') return name[ytLayoutNow()] || name.single;
    return name[state.holeSide] || name.left || name.full;
}

/* 標題來源：封面用左標題／YT 用標題欄／一般 CG 用消化出的 [標題] 行 */
function downloadTitleSource(kind) {
    const key = kind || state.editorFormat || EDITOR_FORMAT_DEFAULT;
    const val = id => (document.getElementById(id)?.value || '').trim();
    if (key === 'ten_cover') return val('coverTitleLeft');
    if (key === 'yt_live_cover' || key === 'yt_hourly_cover' || key === 'yt_hot_cover') {
        return val('ytCoverTitle');
    }
    const match = val('field-variable').match(/\[標題\]\s*([^\n]+)/);
    return match ? match[1].trim() : '';
}

/* 使用者填的檔名。第二頁（進階微調）有自己的欄位，避免第一頁的殘值誤用 */
function customDownloadName() {
    const id = state.currentPage === 2 ? 'downloadNameAdvanced' : 'downloadName';
    return document.getElementById(id)?.value || '';
}

function downloadDateStamp() {
    const d = new Date();
    const pad = n => String(n).padStart(2, '0');
    return `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}`;
}

/* 檔名欄在結果區裡，生圖當下還是空的——使用者是看到圖之後才打字。
   所以下載當下再算一次；同步在 click handler 裡改 download 屬性，瀏覽器吃得到。 */
function wireDownloadNames() {
    ['oneClickDownload', 'downloadGeneratedImage'].forEach(id => {
        const link = document.getElementById(id);
        if (!link) return;
        link.addEventListener('click', () => {
            const ext = (link.href || '').startsWith('data:image/png') ? 'png' : 'jpg';
            link.download = downloadFileName(state.editorFormat, undefined, ext);
        });
    });
}

function downloadFileName(kind, title, ext) {
    const clean = s => String(s == null ? '' : s).replace(DOWNLOAD_NAME_ILLEGAL, '').trim();
    const extension = clean(ext) || 'png';
    const custom = clean(customDownloadName());
    if (custom) return `${custom}.${extension}`;
    const name = clean(title === undefined ? downloadTitleSource(kind) : title)
        .slice(0, DOWNLOAD_TITLE_MAX)
        .trim();
    const parts = [downloadDateStamp(), clean(downloadFormatName(kind))];
    if (name) parts.push(name);
    return `${parts.filter(Boolean).join('_')}.${extension}`;
}

/* 消化程度三檔。key 與後端 DigestDensity 一致，改這裡要同步改 main.py */
const DENSITY_LABELS = {
    verbatim: '不改字',   // 2026-09-07 使用者裁決：UI 顯示改「不改字」，key 與後端 verbatim 不動
    simplified: '字少',
    standard: '字多',
};

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
    syncEngineSizeButtons();
    updateAspectBadge();
    ["btnSafeFrame", "p1-btnSafeFrame"].forEach(id => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.className = "px-3 py-1 rounded text-[9px] font-black transition-all " + (state.safeFrame ? "border border-emerald-600 bg-emerald-600 text-white" : "border border-emerald-600 text-slate-400 hover:text-white");
        btn.innerText = state.safeFrame ? "安全框 ON" : "安全框 OFF";
    });
    updateStampButton();
    updateToneButtons();
    renderEditorFormats();
    document.querySelectorAll('[data-density]').forEach(btn => {
        const isActive = btn.dataset.density === state.digestDensity;
        btn.classList.toggle('density-active', isActive);
        btn.classList.toggle('text-slate-500', !isActive);
    });
    wireDownloadNames();
    switchPage(1);
};

/* ============================================================
   頁面切換（第一頁 快速生成 / 第二頁 進階微調 / 第三頁 混合版型）
   Final Prompt Output 面板為共用單一實例，切頁時搬到當前頁的掛載點，
   避免重複 id 造成 getElementById 取到錯誤的節點。
   第三頁不走 Prompt 流程，沒有 outputMount-3，面板會留在隱藏的前頁裡
   ============================================================ */
function switchPage(page) {
    state.currentPage = page;

    [1, 2, 3].forEach(n => {
        const section = document.getElementById(`page-${n}`);
        const tab = document.getElementById(`pageTab-${n}`);
        section.classList.toggle('hidden', n !== page);
        tab.classList.toggle('page-tab-active', n === page);
    });

    const panel = document.getElementById('outputPanel');
    if (panel) {
        if (page === 2) {
            const mount = document.getElementById('outputMount-2');
            if (mount && panel.parentElement !== mount) mount.appendChild(panel);
            panel.classList.remove('hidden');
        } else {
            panel.classList.add('hidden');
        }
    }

    // 混合版型延後初始化：hidden 狀態下先 render 沒有意義，重複呼叫由 initHybrid 自行擋掉
    if (page === 3 && typeof window.initHybrid === 'function') window.initHybrid();

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
    const c = document.getElementById('digestTypeSelect');
    if (!c) return;
    c.innerHTML = '';
    // 懶人機制擺第一個並為預設
    const entries = [[AUTO_TYPE_KEY, AUTO_TYPE], ...Object.entries(CHART_TYPES)];
    entries.forEach(([key, t]) => {
        const opt = document.createElement('option');
        const isAuto = key === AUTO_TYPE_KEY;
        opt.value = key;
        // 自動判斷完成後，選項顯示 AI 選了什麼
        opt.text = (isAuto && key === state.digestChartType && state.digestResolvedType)
            ? `AI 自動判斷：${CHART_TYPES[state.digestResolvedType].label}`
            : t.label;
        c.appendChild(opt);
    });
    c.value = state.digestChartType;
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
        // 未選態的紅字由 .role-btn 提供，不再套 text-slate-500
        btn.classList.toggle('role-active', isActive);
    });
    state.currentTab = 'style';
    state.activeParent = Object.keys(curType().styles)[0];
    renderTabs();
    renderAll();
    // 記者沒有編輯專屬版型，切回去一律重置，免得開關卡在被鎖住的狀態
    if (role !== '編輯' && state.editorFormat !== EDITOR_FORMAT_DEFAULT) {
        state.editorFormat = EDITOR_FORMAT_DEFAULT;
    }
    // 換角色＝換一則要做的東西，上一則的 AI 判定結果不該跟著過來。
    // 2026-09-05 實測：記者那則被判為「情境示意圖」，切到編輯分頁後版面下拉
    // 仍顯示「AI 自動判斷：情境示意圖」，新稿還沒消化就先掛著舊類型。
    if (state.digestResolvedType) {
        state.digestResolvedType = null;
        renderDigestTypes();
        updateActiveTypeBadge();
        syncOutput();
    }
    renderEditorFormats();
    applyEditorFormatInputs();
    applyEditorFormatLocks();
    updateAIBtnRoleHint();
    updateAspectBadge();
    updateImageGenerationControls();
    showToast(`已切換至 ${role} 模式`);
}

/* ============================================================
   編輯專屬版型：下拉、鎖開關、換裝輸入區
   ============================================================ */
function renderEditorFormats() {
    const row = document.getElementById('editorFormatRow');
    const select = document.getElementById('editorFormatSelect');
    if (!row || !select) return;
    row.classList.toggle('hidden', state.currentRole !== '編輯');
    if (!select.options.length) {
        Object.entries(EDITOR_FORMATS).forEach(([key, fmt]) => {
            const opt = document.createElement('option');
            opt.value = key;
            opt.text = fmt.label;
            select.appendChild(opt);
        });
    }
    select.value = state.editorFormat;
    // 2026-09-08 使用者裁決：下拉底下的斜體版型說明拿掉（手冊有寫），欄位內的短提示留著
}

// 鎖住的開關要看得出來是「這個版型規定的」而不是壞掉。淡化＋擋點擊是外觀，
// 真正生效的是 state——applyEditorFormatLocks 會先把 state 改成版型要求的值。
function _lock(el, locked) {
    if (el) el.classList.toggle('locked-by-format', locked);
}

function applyEditorFormatLocks() {
    const format = editorFormat();
    const presets = format.presets || {};
    const locks = format.locks || {};
    const hides = format.hides || {};

    // 預設值：幫忙調好，但不擋——2026-09-04 使用者回報「全都不能選」，查下來
    // 播出鏡面四個鎖裡只有版面形式是真的必要，其餘三個鎖過頭了。
    if (typeof presets.safeFrame === 'boolean' && state.safeFrame !== presets.safeFrame) toggleSafeFrame();
    if (typeof presets.stamp === 'boolean' && state.stamp !== presets.stamp) toggleStamp();
    if (presets.density && state.digestDensity !== presets.density) switchDigestDensity(presets.density);

    _hide(document.getElementById('digestControlsRow'), !!hides.digestControls);
    // 指令欄全版型都顯示（2026-09-08 下午裁決，推翻同日早上的隱藏）：封面／YT 的
    // 端點現在收 instruction，內容當畫面提示餵給推導步驟。畫面描述欄同時被移除，
    // 指令欄因此是封面唯一的自由輸入。
    // ——例外只有一個（2026-09-08 WP3）：直標不打任何模型，指令欄沒有東西可以餵，
    // 留著只會是一格填了不生效的輸入。所以由版型的 hides.instruction 決定。
    _hide(document.getElementById('instructionRow'), !!hides.instruction);
    // 引擎 GPT／Gemini 同理：直標沒有生圖這一步，選哪個引擎都一樣
    _hide(document.getElementById('p1EngineRow'), !!hides.engine);
    // 追加修改整區：直標沒有底圖可改。別只靠 refineBtn.disabled——結果區一顯示，
    // 那個輸入框就在那裡等人打字，打完按下去卻什麼都不會發生。
    _hide(document.getElementById('refineBox'), !!hides.refine);
    _hide(document.getElementById('p1-btnSafeFrame'), !!hides.safeFrame);
    _hide(document.getElementById('p1-btnStamp'), !!hides.stamp);
    // 壓框開關與挖空方向都只對有挖空側的版型有意義
    _hide(document.getElementById('p1-btnHole'), !format.hole);
    updateHoleSideButtons();

    // 唯一真的鎖著的：版面由挖空框決定，讓使用者再選一次只會互相打架
    _lock(document.getElementById('digestTypeRow'), !!locks.chartType);
}

function _hide(el, hidden) {
    if (el) el.classList.toggle('hidden', hidden);
}

// 換裝輸入區：同一頁、同一個位置，只有上半部欄位跟著版型換
function todayText() {
    const now = new Date();
    const pad = n => String(n).padStart(2, '0');
    return `${now.getFullYear()}/${pad(now.getMonth() + 1)}/${pad(now.getDate())}`;
}

function applyEditorFormatInputs() {
    const inputs = editorFormat().inputs;
    const wantsCover = inputs === 'cover';
    const wantsYt = inputs === 'yt_cover';
    // YT 直播直標（2026-09-08 WP3）：獨立一塊欄位，不跟 ytCoverInputs 共用——
    // 那一塊裡面有附圖／AI 消化／只改文字，直標一個都不要
    const wantsVstrip = inputs === 'yt_vstrip';
    const special = wantsCover || wantsYt || wantsVstrip;
    const news = document.getElementById('newsInputs');
    const cover = document.getElementById('coverInputs');
    const yt = document.getElementById('ytCoverInputs');
    const vstrip = document.getElementById('ytVstripInputs');
    const refBox = document.getElementById('refUploadBox');
    const digestRow = document.getElementById('digestTypeRow');
    if (news) news.classList.toggle('hidden', special);
    if (cover) cover.classList.toggle('hidden', !wantsCover);
    // 滿版／雙切（2026-09-08 WP1）：不再是兩個版型，改由第二標題有沒有值即時判定。
    // 右附圖位、「只改文字」鈕與指示器全部跟著跑，見 updateCoverLayoutIndicator。
    updateCoverLayoutIndicator();
    updateCoverTitleStyleButton();
    updateYtBottomBandButton();
    if (yt) yt.classList.toggle('hidden', !wantsYt);
    if (vstrip) vstrip.classList.toggle('hidden', !wantsVstrip);
    updateVstripButtons();
    // 附圖上傳區：主流程、YT 直播封面、十點不一樣（2026-09-06 起收原圖放置）都用。
    // 封面版型時把它搬到該組欄位下面——留在原位會跑到角色鈕正下方，看起來像消失了。
    // 直標沒有底圖也沒有生圖，附圖無處可去，整區收起來（hides.refUpload）。
    if (refBox) {
        refBox.classList.toggle('hidden', !!(editorFormat().hides || {}).refUpload);
        const host = wantsVstrip ? vstrip : (wantsYt ? yt : (wantsCover ? cover : news));
        if (host && refBox.previousElementSibling !== host) host.insertAdjacentElement('afterend', refBox);
    }
    // 指令欄同理（2026-09-08 WP1）：它原本住在 newsInputs 裡面，而封面／YT 版型會把
    // 整個 newsInputs 藏起來——不搬出來，欄位「顯示」了也還是看不到。
    const instructionRow = document.getElementById('instructionRow');
    if (instructionRow) {
        const anchor = refBox || (wantsYt ? yt : (wantsCover ? cover : news));
        if (anchor && instructionRow.previousElementSibling !== anchor) {
            anchor.insertAdjacentElement('afterend', instructionRow);
        }
    }
    // 整點直播：沒有原音呈現／AI即時翻譯、多一格整點時間；今日熱搜：連日期都沒有
    const ytLayout = wantsYt ? editorFormat().ytLayout : '';
    const hourly = ytLayout === 'hourly';
    const hot = ytLayout === 'hot';
    const flagRow = document.getElementById('ytCoverFlags');
    const timeField = document.getElementById('ytCoverTime');
    const ytDateField = document.getElementById('ytCoverDate');
    if (flagRow) flagRow.classList.toggle('hidden', hourly || hot);
    if (timeField) timeField.classList.toggle('hidden', !hourly);
    // 整點雙則（2026-09-08 WP2）：第二標題欄與指示器只有整點版型看得到
    const secondRow = document.getElementById('ytCoverTitleSecondRow');
    if (secondRow) secondRow.classList.toggle('hidden', !hourly);
    updateYtLayoutIndicator();
    if (ytDateField) ytDateField.classList.toggle('hidden', hot);
    // 封面模式完全沒有消化這一段，版面形式用不到，整組收起來
    if (digestRow) digestRow.classList.toggle('hidden', special);
    // 直標是透明底 PNG：預覽區底下鋪深灰格紋，不然白字疊在白底上等於看不到
    const preview = document.getElementById('oneClickImage');
    if (preview) preview.classList.toggle('transparent-preview', wantsVstrip);
    for (const id of ['coverDate', 'ytCoverDate']) {
        const dateField = document.getElementById(id);
        if ((wantsCover || wantsYt) && dateField && !dateField.value) dateField.value = todayText();
    }
}

function setEditorFormat(key) {
    state.editorFormat = EDITOR_FORMATS[key] ? key : EDITOR_FORMAT_DEFAULT;
    // 換版型就把挖空方向重置回左：還記著上一個版型選的右切，只會讓人選錯邊
    state.holeSide = 'left';
    // 換版型就丟掉上一版的壓字前底圖：滿版的底圖送進雙切會被後端擋（400），留著只會誤導。
    // 只在這裡清——applyEditorFormatInputs 換角色也會走，放那邊會把還能用的底圖洗掉。
    state.tenCoverBackground = null;
    // 換版型也丟掉上一版 YT 封面的 refine 來源：不清的話切到整點後「只改文字」會對著
    // 一張國內外版的底圖亮起來（審查建議 2026-09-08）。
    state.refineSource = null;
    state.refineDisplay = null;
    const coverRecompose = document.getElementById('coverRecomposeBtn');
    if (coverRecompose) coverRecompose.disabled = true;
    renderEditorFormats();
    applyEditorFormatInputs();
    applyEditorFormatLocks();
    updateAIBtnRoleHint();
    if (state.editorFormat !== EDITOR_FORMAT_DEFAULT) {
        showToast(`已切換版型：${editorFormat().label}`);
    }
}

function switchDigestDensity(density) {
    state.digestDensity = density;
    document.querySelectorAll('[data-density]').forEach(btn => {
        const isActive = btn.dataset.density === density;
        btn.classList.toggle('density-active', isActive);
        btn.classList.toggle('text-slate-500', !isActive);
    });
    updateAIBtnRoleHint();
    const label = DENSITY_LABELS[density] || density;
    showToast(density === 'verbatim'
        ? '已切換至「不改字」：貼上的內文一字不改，AI 只做版面'
        : `AI 消化已切換至「${label}」`);
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
    // 生成中按鈕正顯示進度，切角色／密度不該把進度文字蓋掉
    if (_genTicker) return;
    if (!buttonText) return;
    if (editorFormat().inputs === 'yt_vstrip') {
        buttonText.innerText = '生成直標（透明 PNG）';
        return;
    }
    if (editorFormat().inputs === 'cover' || editorFormat().inputs === 'yt_cover') {
        buttonText.innerText = `生成${editorFormat().label}`;
        return;
    }
    const densityLabel = DENSITY_LABELS[state.digestDensity] || state.digestDensity;
    const formatLabel = state.editorFormat === EDITOR_FORMAT_DEFAULT
        ? '' : `・${editorFormat().label}`;
    buttonText.innerText = `一鍵生成（${state.currentRole}・${densityLabel}${formatLabel}）`;
}

/* ============================================================
   一鍵生成進度顯示
   後端兩段都是一次性的同步請求，沒有任何進度可回報，所以這裡的百分比
   是「依經過時間推估」而非真實進度。兩個原則避免它變成假訊號：
   1. 只有真的拿到圖才會走到 100%；推估值以指數趨近該階段上限，
      逾時只會愈走愈慢，永遠碰不到上限，不會出現「99% 卡住」以外的謊。
   2. 文字同時標出目前階段，使用者看得出來卡在消化還是生圖。
   ============================================================ */
const GEN_STAGES = {
    digest: { label: '消化新聞中', from: 0, to: 35, seconds: 20 },
    image: { label: '生成圖片中', from: 35, to: 95, seconds: 75 },
};

let _genTicker = null;
let _genStage = null;
let _genStageStart = 0;
let _genStageBudget = 0;

// budgetScale：2K／GPT 這類本來就慢的組合把預估時間拉長，免得早早貼到上限乾等
function beginGenerationProgress(stageKey, budgetScale = 1) {
    _genStage = GEN_STAGES[stageKey];
    _genStageStart = Date.now();
    _genStageBudget = _genStage.seconds * budgetScale;
    if (!_genTicker) {
        const btn = document.getElementById('aiBtn');
        if (btn) btn.classList.add('generating');
        _genTicker = setInterval(paintGenerationProgress, 250);
    }
    paintGenerationProgress();
}

function paintGenerationProgress() {
    if (!_genStage) return;
    const elapsed = (Date.now() - _genStageStart) / 1000;
    // 指數趨近：預估時間到時約走完該階段的 89%，之後持續變慢但不會停住
    const ratio = 1 - Math.exp(-elapsed / (_genStageBudget / 2.2));
    const pct = _genStage.from + (_genStage.to - _genStage.from) * ratio;
    renderGenerationProgress(pct, `${_genStage.label} ${Math.round(pct)}%`);
}

function renderGenerationProgress(pct, text) {
    const btn = document.getElementById('aiBtn');
    const btnText = document.getElementById('aiBtnText');
    if (btn) btn.style.setProperty('--gen-progress', `${pct}%`);
    if (btnText) btnText.innerText = text;
}

function endGenerationProgress(completed = false) {
    if (_genTicker) { clearInterval(_genTicker); _genTicker = null; }
    _genStage = null;
    const btn = document.getElementById('aiBtn');
    if (!btn) return;
    const restore = () => {
        btn.classList.remove('generating');
        btn.style.removeProperty('--gen-progress');
        updateAIBtnRoleHint();
    };
    if (completed) {
        // 成功才有 100%，短暫停留讓使用者看見「跑完了」再還原按鈕文字
        renderGenerationProgress(100, '完成 100%');
        setTimeout(restore, 700);
    } else {
        restore();
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

function _setToggle(id, on) {
    const el = document.getElementById(id);
    if (!el) return;
    el.className = 'px-3 py-1 rounded text-[9px] font-black transition-all ' + (on ? 'border border-blue-600 bg-blue-600 text-white' : 'border border-blue-600 text-slate-400 hover:text-white');
}

function syncEngineSizeButtons() {
    ['', 'p1-'].forEach(prefix => {
        _setToggle(prefix + 'engine-gemini', state.engine === 'gemini');
        _setToggle(prefix + 'engine-gpt', state.engine === 'gpt');
        _setToggle(prefix + 'size-1K', state.imageSize === '1K');
        _setToggle(prefix + 'size-2K', state.imageSize === '2K');
    });
}

function switchEngine(engine) {
    state.engine = engine;
    syncEngineSizeButtons();
    updateAspectBadge();
    syncOutput();
}

function switchImageSize(size) {
    state.imageSize = size;
    syncEngineSizeButtons();
    updateAspectBadge();
}

function toggleSafeFrame() {
    state.safeFrame = !state.safeFrame;
    ['btnSafeFrame', 'p1-btnSafeFrame'].forEach(id => {
        const btn = document.getElementById(id);
        if (!btn) return;
        btn.className = 'px-3 py-1 rounded text-[9px] font-black transition-all ' + (state.safeFrame ? 'border border-emerald-600 bg-emerald-600 text-white' : 'border border-emerald-600 text-slate-400 hover:text-white');
        btn.innerText = state.safeFrame ? '安全框 ON' : '安全框 OFF';
    });
    updateAspectBadge();
    syncOutput();
}

// 蓋章開關（2026-09-03）。安全框是綠的，這顆用琥珀色，避免兩個開關看起來同一組。
function updateStampButton() {
    const btn = document.getElementById('p1-btnStamp');
    if (!btn) return;
    btn.className = 'px-2.5 py-1 rounded text-[9px] font-black transition-all '
        + (state.stamp ? 'border border-amber-600 bg-amber-600 text-white' : 'border border-amber-600 text-slate-400 hover:text-white');
    btn.innerText = state.stamp ? '蓋章 ON' : '蓋章 OFF';
}

function toggleStamp() {
    state.stamp = !state.stamp;
    updateStampButton();
    updateInstructionOverrideHint();
    showToast(state.stamp ? '蓋章：開（最後一行加結論條）' : '蓋章：關（不放結論條）');
}

// YT 封面「底色框」開關（2026-09-08）。琥珀色。國內外新聞直播與今日熱搜才有底帶；
// 整點直播的版面本來就沒有底帶（compose_yt_hourly_cover 不畫），按鈕在那個版型不顯示。
function updateYtBottomBandButton() {
    const btn = document.getElementById('ytBottomBandBtn');
    if (!btn) return;
    const layout = editorFormat().ytLayout || '';
    const applies = editorFormat().inputs === 'yt_cover' && layout !== 'hourly';
    btn.classList.toggle('hidden', !applies);
    const on = state.ytBottomBand;
    btn.className = (applies ? '' : 'hidden ')
        + 'px-2.5 py-1 rounded text-[9px] font-black transition-all '
        + (on ? 'border border-amber-600 bg-amber-600 text-white' : 'border border-amber-600 text-slate-400 hover:text-white');
    btn.innerText = on ? '底色框 ON' : '底色框 OFF';
}

function toggleYtBottomBand() {
    state.ytBottomBand = !state.ytBottomBand;
    updateYtBottomBandButton();
    showToast(state.ytBottomBand ? '底色框：開（半透明，照片透得出來）' : '底色框：關（標題靠描邊立在照片上）');
}

/* 十點的「滿版／雙切」指示器（2026-09-08 WP1）。
   這是**判定結果**不是輸入：版面由第二標題有沒有值決定，所以點「雙切」不會切版面，
   只是把游標移到第二標題——真正要做的就是去填那一欄。 */
function updateCoverLayoutIndicator() {
    const row = document.getElementById('coverLayoutIndicator');
    const isCover = editorFormat().inputs === 'cover';
    if (row) {
        row.classList.toggle('hidden', !isCover);
        const layout = coverLayoutNow();
        row.querySelectorAll('[data-cover-layout]').forEach(btn => {
            const active = btn.dataset.coverLayout === layout;
            btn.className = 'px-2.5 py-1 rounded text-[9px] font-black transition-all '
                + (active ? 'border border-violet-600 bg-violet-600 text-white'
                          : 'border border-violet-600 text-slate-500 hover:text-white');
        });
    }
    if (isCover) applyCoverLayoutFields();
}

// 指示器不是開關，點「雙切」只是把游標帶去第二標題；點「滿版」要清空第二標題才會變，
// 那是使用者自己的決定，不由按鈕代勞——所以兩顆都只做「把游標移過去」。
function focusCoverLayoutField() {
    document.getElementById('coverTitleRight')?.focus();
}

/* YT 整點的「單則／雙則」指示器（2026-09-08 WP2），做法與十點那個逐字對齊：
   這是判定結果不是輸入，點「雙則」只把游標移到第二標題。 */
function updateYtLayoutIndicator() {
    const row = document.getElementById('ytLayoutIndicator');
    if (!row) return;
    const applies = editorFormat().inputs === 'yt_cover' && (editorFormat().ytLayout || '') === 'hourly';
    row.classList.toggle('hidden', !applies);
    if (!applies) return;
    const layout = ytLayoutNow();
    row.querySelectorAll('[data-yt-layout]').forEach(btn => {
        const active = btn.dataset.ytLayout === layout;
        btn.className = 'px-2.5 py-1 rounded text-[9px] font-black transition-all '
            + (active ? 'border border-violet-600 bg-violet-600 text-white'
                      : 'border border-violet-600 text-slate-500 hover:text-white');
    });
    // 雙則的底圖是拼好的一張，「只改文字」與追加修改都跟單則走同一條路
    const recompose = document.getElementById('ytCoverRecomposeBtn');
    if (recompose) recompose.disabled = !state.refineSource;
}

function focusYtLayoutField() {
    document.getElementById('ytCoverTitleSecond')?.focus();
}

/* 消化按鈕的 target：整點直播要判定 1／2 個主題（回兩個標題），其餘維持單標題。 */
function ytCoverDigestTarget() {
    return (editorFormat().ytLayout || '') === 'hourly' ? 'yt_hourly' : 'yt_cover';
}

/* 版面一變，跟著版面走的三件事要同步：右附圖位、「只改文字」鈕、下載短名。
   換版型會走 applyEditorFormatInputs，但打字改第二標題不會——所以獨立成一支，
   coverTitleRight 的 oninput 也叫它。 */
function applyCoverLayoutFields() {
    const fullLayout = coverLayoutNow() === 'full';
    document.querySelectorAll('.cover-split-only').forEach(el => el.classList.toggle('hidden', fullLayout));
    const leftBtn = document.getElementById('coverAsisLeftBtn');
    if (leftBtn) leftBtn.textContent = fullLayout ? '＋ 附圖（選填）' : '＋ 第一附圖（選填）';
    // 「只改文字」只有滿版合成版有：雙切的成品是左右兩張底圖拼的，拼完分不回去。
    const recompose = document.getElementById('coverRecomposeBtn');
    if (recompose) {
        recompose.classList.toggle('hidden', !fullLayout);
        recompose.disabled = !(fullLayout && state.tenCoverBackground);
    }
}

// 十點封面「設計標題」開關（2026-09-08）。紫色，與安全框（綠）／蓋章（琥珀）／壓框（青）區分。
// 只有十點版型＋AI 整張模式看得到：合成版的字是程式用 Pillow 壓的，這個開關對它沒有意義。
function updateCoverTitleStyleButton() {
    const btn = document.getElementById('coverTitleStyleBtn');
    if (!btn) return;
    const aiMode = document.getElementById('coverAiTitle')?.checked !== false;
    btn.classList.toggle('hidden', editorFormat().inputs !== 'cover' || !aiMode);
    const on = state.coverTitleStyle === 'designed';
    btn.className = (btn.classList.contains('hidden') ? 'hidden ' : '')
        + 'px-2.5 py-1 rounded text-[9px] font-black transition-all '
        + (on ? 'border border-violet-600 bg-violet-600 text-white' : 'border border-violet-600 text-slate-400 hover:text-white');
    btn.innerText = on ? '設計標題 ON' : '設計標題 OFF';
}

function toggleCoverTitleStyle() {
    state.coverTitleStyle = state.coverTitleStyle === 'designed' ? 'plain' : 'designed';
    updateCoverTitleStyleButton();
    showToast(state.coverTitleStyle === 'designed'
        ? '設計標題：開（標題撐滿整格、關鍵字放大）'
        : '設計標題：關（維持現行排版）');
}

// 播出鏡面白色壓框開關（2026-09-07）。青色，與安全框（綠）／蓋章（琥珀）區分。
function updateHoleButton() {
    const btn = document.getElementById('p1-btnHole');
    if (!btn) return;
    btn.className = 'px-2.5 py-1 rounded text-[9px] font-black transition-all '
        + (state.hole ? 'border border-cyan-600 bg-cyan-600 text-white' : 'border border-cyan-600 text-slate-400 hover:text-white');
    btn.innerText = state.hole ? '壓框 ON' : '壓框 OFF';
}

function toggleHole() {
    state.hole = !state.hole;
    updateHoleButton();
    showToast(state.hole ? '壓框：開（影片位置蓋白框給後製對位）' : '壓框：關（底圖完整，後製自己放影片）');
}

// 播出鏡面要送給後端的挖空側：版型有挖空側且壓框開著才送，否則後端不蓋框。
// 方向來自使用者選的 state.holeSide（2026-09-08 WP1），不再是版型表寫死的那一側。
function broadcastHoleForApi() {
    if (!state.hole || !editorFormat().hole) return '';
    return state.holeSide;
}

/* 挖空方向（2026-09-08 WP1）：左切／右切從兩個版型變成同一個版型裡的一組按鈕。
   消化與生圖兩端都吃這個值——消化要把內容趕到影片那半邊的對面，方向講錯等於重點被蓋掉。 */
function updateHoleSideButtons() {
    const row = document.getElementById('holeSideRow');
    if (!row) return;
    row.classList.toggle('hidden', !editorFormat().hole);
    row.querySelectorAll('[data-hole-side]').forEach(btn => {
        const active = btn.dataset.holeSide === state.holeSide;
        btn.className = 'px-2.5 py-1 rounded text-[9px] font-black transition-all '
            + (active ? 'border border-cyan-600 bg-cyan-600 text-white'
                      : 'border border-cyan-600 text-slate-400 hover:text-white');
    });
}

function setHoleSide(side) {
    if (side !== 'left' && side !== 'right') return;
    state.holeSide = side;
    updateHoleSideButtons();
    showToast(side === 'left' ? '挖空：左側（內容自動靠右編排）' : '挖空：右側（內容自動靠左編排）');
}

// 色調切換（2026-09-04）。取代原本擺在這個位置的角色選擇——角色已移到最上方，
// 因為它決定底下所有選項的可用範圍，要先選。
function updateToneButtons() {
    document.querySelectorAll('.tone-btn').forEach(btn => {
        btn.classList.toggle('tone-active', btn.dataset.tone === state.tone);
        btn.classList.toggle('text-slate-500', btn.dataset.tone !== state.tone);
        btn.classList.toggle('hover:text-white', btn.dataset.tone !== state.tone);
    });
}

function switchTone(tone) {
    if (tone !== 'light' && tone !== 'dark') return;
    state.tone = tone;
    updateToneButtons();
    updateInstructionOverrideHint();
    invalidateGeneratedImage();
    showToast(tone === 'dark' ? '色調：暗（深底亮字）' : '色調：亮（淺底深字）');
}

/* 置框模式送 21:9 生成：官方安全區本身是 2.176:1，用 21:9（2.333）去塞，
   FIT 零裁切下左右留白就會落在官方需求（7.29/7.60%）附近；沿用 16:9 則左右
   會多出一倍留白。已用 4 張真實生成圖驗證（左右 4/4 落在需求 ±1pp 內）。
   ⚠️ 這兩個值與 main.py 的 SAFE_FRAME_ASPECT_RATIO／DEFAULT_ASPECT_RATIO 同義，
   改動要同步——後端那條是 LINE／WorkCord 用的，這條是網頁版第一頁用的。 */
const SAFE_FRAME_ASPECT_RATIO = '21:9';
const DEFAULT_ASPECT_RATIO = '16:9';

function currentAspectRatio() {
    // 編輯對位框接近 16:9；記者官方框才用 21:9 塞底部跑馬燈留白
    if (state.safeFrame && state.currentRole === '編輯') return DEFAULT_ASPECT_RATIO;
    return state.safeFrame ? SAFE_FRAME_ASPECT_RATIO : DEFAULT_ASPECT_RATIO;
}

// GPT 固定 1280×720（忽略解析度切換）；Gemini 才依 1K／2K 變動
function updateAspectBadge() {
    // 編輯版兩檔都會後製，只是出來的東西不一樣，所以兩檔都要標出成品尺寸。
    // 對位框那檔的成品是 1748×924（拉伸後的那一塊本身），不是 1920×1080——
    // 舊文案寫 1920×1080 是錯的，2026-08-19 一併更正。
    const isEditor = state.currentRole === '編輯';
    let text;
    if (isEditor) {
        text = state.safeFrame
            ? `${currentAspectRatio()} → 編輯安全框（四邊 4%）1920×1080`
            : `${currentAspectRatio()} → 編輯對位框 1748×924`;
    } else if (state.safeFrame) {
        text = `${currentAspectRatio()} → 記者安全框 1920×1080`;
    } else {
        text = state.engine === 'gpt'
            ? `${DEFAULT_ASPECT_RATIO} / 720p`
            : `${DEFAULT_ASPECT_RATIO} / ${state.imageSize}`;
    }
    ['aspectBadge', 'p1-aspectBadge'].forEach(id => {
        const badge = document.getElementById(id);
        if (badge) badge.innerText = text;
    });
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
        variable: processedVariable,
        safeFrame: state.safeFrame,
        aspectRatio: currentAspectRatio()
    });
    updatePromptCounter();
}

function buildPrompt({ role, engine, typeLabel, style, structure, variable, safeFrame = false, aspectRatio = '16:9' }) {
    // 共用的正文區塊（style / structure / variable）
    const textRules = role === '編輯' ? EDITOR_TEXT_RULES : REPORTER_TEXT_RULES;
    // 分流的依據是「後端會不會水平拉伸」，不是安全框開關本身：
    //   編輯 OFF → 拉伸填滿對位框，要上下背景帶把拉伸失真吃掉
    //   編輯 ON  → 2% 薄框走 FIT 不拉伸，再留背景帶會讓實際邊界遠超過 2%
    //   記者 ON  → 21:9 FIT，同理不留帶
    // 編輯版自 2026-08-19 起兩檔都是滿版生成，沒有「叫模型自己縮小置中」那條路。
    const marginRules = (role === '編輯' && !safeFrame)
        ? EDITOR_FULL_BLEED_RULES
        : ((role === '編輯' || safeFrame) ? FULL_BLEED_RULES : REPORTER_SAFE_AREA);
    const canvasLine = (role === '編輯' || safeFrame) ? CANVAS_FULL_BLEED_LINE : CANVAS_MARGIN_LINE;

    // 視覺忠實度區塊：地圖規則只在已解析的類型是地圖時注入
    // （typeLabel 來自 activeType()，自動判斷模式下已是 AI 解析後的具體類型）
    const extraBlocks = [REAL_WORLD_RENDERING_RULES, TW_DIRECTIONAL_COLOR_RULES, TEXT_PLACEMENT_RULES];
    if (typeLabel === MAP_TYPE_LABEL) {
        extraBlocks.push(MAP_ACCURACY_IMAGE_RULES);
    }
    const extras = extraBlocks.join('\n\n');

    const body =
`==================================================
CANVAS
==================================================
- Aspect ratio: ${aspectRatio}
- Centred composition, single continuous full-frame background
${canvasLine}

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

${marginRules}

${extras}

==================================================
FINAL OUTPUT RULE
==================================================
- The final generated image must NOT contain any "[" "]" or "<" ">" characters.
- All bracketed variable fields are instructions only.
- Use only Traditional Chinese (Taiwan standard).
- Ensure all characters are correct with proper stroke forms.
- CONTENT FIDELITY (NON-NEGOTIABLE): render ONLY the words, figures and facts supplied in VARIABLE FIELDS. You are a renderer, not an author.
  -> NEVER invent additional numbers, percentages, dates, quarters, years, axis values, data points, or trend series that are not written in VARIABLE FIELDS.
  -> If a chart or graph is called for but no series of values was supplied, draw it as a plain schematic shape (a simple rising or falling line, an arrow, a bar silhouette) with NO numeric labels and NO axis tick values.
  -> NEVER add a data-source line, organisation name, agency, publisher, wire service, logo, watermark, URL, timestamp, or "updated on" note unless that exact text appears in VARIABLE FIELDS.
  -> NEVER add extra captions, bullet points, sub-headings, or explanatory sentences of your own.
  -> Empty space is correct and acceptable. If the layout looks sparse, enlarge or space out the supplied elements — do NOT fill the gap with invented content.`;

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

/* ---- 滿版模式常數（safe_frame=true）----
   四輪實驗證實模型量不出比例、底部安全區 0 次合格，但「畫滿」做得很好。
   所以要求從「精準留邊」換成「別切到自己的內容」，精準留白交給 safe_frame.py。
   ⚠️ 這三個常數與 news_prompt.py 必須逐字一致（tests/test_prompt_parity.py 會驗）。*/
const CANVAS_MARGIN_LINE = `- Scale the whole design down so it fills only the central region, surrounded by a thick empty margin on every side (deeper at the bottom); when unsure, make the margin bigger, never smaller`;

const CANVAS_FULL_BLEED_LINE = `- Use the whole frame: the design fills the canvas completely, with only a slim even breathing space inside the frame edge so that no element is clipped`;

const FULL_BLEED_RULES =
`==================================================
FULL-FRAME RULES (CRITICAL — MUST PRESERVE)
==================================================
- Use the entire canvas. The design fills the frame; there is no reserved margin, no empty band, and no letterboxing anywhere.
- Leave only a slim, even breathing space just inside the frame edge, enough that no letter, icon, card border, or chart element is cut off by the edge. Do not turn that breathing space into a thick border.
- Keep the breathing space roughly even on all four sides. Do NOT make the bottom deeper than the other sides.
- These full-frame rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction asks you to scale the design down, centre it in a smaller region, or reserve an empty margin or band, ignore that instruction and use the whole frame instead.
- The background is ONE single continuous image covering the whole canvas. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, or dimmed / tinted / shaded band anywhere.
- Every element must be fully inside the canvas: nothing may run off the edge or be sliced by it.
- SELF-CHECK before finalizing: if any element is clipped by the frame edge, nudge it inward; if a wide empty band has appeared along any edge, enlarge the design to fill it.`;

/* 只給編輯，**取代** FULL_BLEED_RULES（不是附加——附加版實測只留 0-8px，
   因為 FULL_BLEED_RULES 自己就寫著不准留白且聲明 OVERRIDE 衝突指令）。
   上下留的背景帶會被後端裁掉，換取更小的水平拉伸失真（6.4% → 約 1%）。
   ⚠️ 與 news_prompt.py 必須逐字一致（tests/test_prompt_parity.py 會驗）。 */
const EDITOR_FULL_BLEED_RULES =
`==================================================
EDGE-SAFE FULL-FRAME RULES (CRITICAL — MUST PRESERVE)
==================================================
- The background artwork is ONE single continuous image running right to all four edges of the canvas. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, dimmed / tinted / shaded band, or letterbox anywhere.
- Across the very TOP of the canvas and across the very BOTTOM of the canvas, leave a clear horizontal strip where ONLY the background artwork appears. Each strip is about as tall as one character of the main headline. No headline, card, chart, icon, banner, arrow, source line or border may enter either strip.
- The closing banner must sit fully above the bottom strip, with an obvious run of plain background visible beneath it all the way to the bottom edge.
- Left and right: keep a similar clear gap of background between the outermost element and the side edge.
- Do NOT shrink the design into a small central box and do NOT draw a visible border. These strips are plain continuous background, not a frame.
- These rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction asks you to run the design edge to edge, ignore that instruction and keep the strips clear.
- Nothing may touch, run off, or be sliced by any edge.
- SELF-CHECK before finalizing: look at the topmost and bottommost pixels of the design. If any element reaches into the top or bottom strip, move the whole design inward until both strips are clear.`;

/* ---- 視覺忠實度常數（2026-07-31）----
   ⚠️ 與 news_prompt.py 必須逐字一致（tests/test_prompt_parity.py 會驗）。
   MAP_TYPE_LABEL 對應 news_prompt.MAP_TYPE_LABEL，同樣由 parity 測試釘住。*/
const MAP_TYPE_LABEL = '地圖／位置';

const REAL_WORLD_RENDERING_RULES =
`==================================================
REAL-WORLD ACCURACY (CRITICAL)
==================================================
- Real, verifiable places and objects (skylines, specific buildings, highways and interchanges, airports, facilities, and specific models of aircraft, ship, vehicle or equipment) must look like the real thing: correct shape, layout, proportions and distinguishing features as far as they are known. Faithful, realistic rendering is welcome — do not distort reality for style.
- Do not fabricate identifying detail you do not know and present it as real. If the rendering is a generic stand-in or a reconstruction rather than the real thing, the 示意圖 label supplied in VARIABLE FIELDS must be clearly visible — never drop or hide it.
- BRANDS: ONLY THOSE IN THE SOURCE. A brand that VARIABLE FIELDS or STRUCTURE names may be shown with its real logo, wordmark or brand text, rendered as faithfully to the real mark as your knowledge allows, and plain typeset text is equally acceptable. Place it ONLY on the objects that belong to that brand — its own signage, packaging, product body, vehicle livery, screen or jersey — and never put one brand's mark on another brand's object. Every OTHER sign, storefront, banner, package, product body, vehicle livery, screen, badge and building facade must be blank or carry a generic non-readable mark: do NOT draw any real company logo, wordmark, trademark, ticker symbol, exchange name or brand text for a brand the source material does not name — not even a small, faint, distant or background one, and never invent one.
- NAMED REAL PEOPLE: how to depict a named real person is governed by the NAMED REAL PERSON block below whenever one is present — follow that block, not your own judgement. If no such block is present, do NOT draw a recognisable face for a named real person: use a back view or a plain silhouette and keep the 示意圖 label visible. Never show the person in a scene, action or context that STRUCTURE does not describe.
- A STATED QUANTITY IS A NUMBER, NOT A HEADCOUNT TO DRAW. Where you do draw the individual items, the count on the canvas must equal the stated figure exactly, background and secondary items included — a graphic saying 4車追撞 with five vehicles in it is wrong. Only draw them individually while the figure is small enough to take in at a glance, up to about four. Beyond that do not attempt the instances at all: 12箱走私菸 is one representative crate with the figure 12 set beside it, never a heap the viewer would count as twenty, and 10部機組 is a figure rather than a row you would miscount.
- SELF-CHECK before finalizing: look at every surface in the image for text or marks you added yourself. If any sign, screen, package or vehicle carries readable branding for a brand the source material does not name, blank it.`;

const TEXT_PLACEMENT_RULES =
`==================================================
TEXT PLACEMENT (CRITICAL)
==================================================
- EVERY LINE OF VARIABLE FIELDS IS RENDERED EXACTLY ONCE. One line, one place on the canvas. Do not repeat a headline, a subhead or a callout in a second card, a second column, a corner block or a summary strip, and do not restate it in different words elsewhere. An empty region is not a reason to duplicate: leave it to the background rather than fill it with a copy.
- THE <蓋章> LINE BELONGS TO THE STAMP BAR AND NOWHERE ELSE — never also as a body line, a subhead row, a card or a callout. It is the closing conclusion, so seeing it twice on one graphic reads as two separate statements of the same fact.
- Add no text of your own. Every word on the canvas comes from VARIABLE FIELDS; if a layout region has nothing assigned to it, it carries no text.`;

const TW_DIRECTIONAL_COLOR_RULES =
`==================================================
DIRECTIONAL COLOUR CONVENTION (TAIWAN)
==================================================
- Rise, gain, increase, positive = RED. Fall, loss, decrease, negative = GREEN. This is the Taiwanese market convention and it is the opposite of the Western one. Never render a rise in green or a fall in red.
- Apply the same pairing to every arrow, triangle, bar, line, highlight block and emphasised figure in the graphic, including when one graphic shows a riser and a faller side by side.
- An up arrow means up and a down arrow means down: match every arrow to the direction stated in VARIABLE FIELDS.
- Do not use red and green decoratively for unrelated purposes in a graphic that shows a rise or a fall.`;

const MAP_ACCURACY_IMAGE_RULES =
`==================================================
MAP ACCURACY RULES (CRITICAL)
==================================================
- Geographic accuracy overrides visual balance. Do not relocate, compress, distort, rotate or rearrange any coastline, island, border, city or marker to improve the composition.
- North is up, east is right, west is left, south is at the bottom. Include a north arrow and a scale bar.
- Coordinates, degree values and bearings given in STRUCTURE are positioning instructions: put the markers at those positions. You are not asked to print them as labels; place-name text and supplied callout wording are the labels that matter.
- Distances stated in STRUCTURE must be drawn proportionally to the map scale and along the stated bearing.
- Simplify coastline styling only. Never simplify or alter geographic positions, distances, bearings or relative scale.
- Do not invent islands, coastlines, landmasses or maritime boundaries. If an accurate coastline cannot be maintained, draw a clean ocean coordinate grid with accurate point markers rather than fabricated geography.
- EVERY MARKER CARRIES ITS OWN PLACE NAME, AND EVERY CALLOUT GOES TO THE MARKER THAT NAMES THE SAME PLACE. Set the place name beside its own marker, close enough that no reader has to guess which marker it belongs to. When a callout box names a place, its leader line must end at the marker for that place and no other; never let two leader lines cross each other on their way to markers whose names they do not match. A marker drawn in exactly the right spot still misreports the story if the box wired to it describes what happened somewhere else, and with no name on the marker itself the viewer has no way to catch it.
- A FACT THAT NAMES NO PLACE BELONGS TO NONE OF THEM. Only wording that itself names a place may go into that place's marker label or callout. When a VARIABLE line does not itself name a place — 「最深積水40公分 多輛機車熄火」 sitting on its own line — do not attach it to one marker and do not spread it across several: deciding which of the marked places is the deepest, or which had the stalled scooters, is a claim the source never made, and on a map it reads as reported fact. Put such a line where it belongs to the whole graphic: a shared strip, a summary block, or a caption that points at nothing.
- Claimed or disputed zones must read as schematic and carry only the label supplied in VARIABLE FIELDS, never as a settled international border.`;

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
- Any <底帶> marker:
  -> Remove the marker and set the text as an ordinary information bar, NOT a coloured stamp
  -> Place it as a single bar along the very bottom of the design, spanning the full width

Visual Elements:
- Include high-quality flat icons or 3D data charts relevant to the content
- Background: professional broadcast news style, subtle glow / tech lines, strictly NO plain gradients`;

const REPORTER_SAFE_AREA =
`==================================================
EMPTY MARGIN RULES (CRITICAL — MUST PRESERVE)
==================================================
- These are layout guides only. The final image is ONE single continuous background with the subject centred; the margins are visually identical to the centre — same colour, tone and brightness everywhere. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, or dimmed / tinted / shaded band to mark the empty area. The empty margin must be completely invisible.
- SCALE THE WHOLE LAYOUT INWARD: treat the entire infographic as one group and shrink it so it is clearly smaller than the frame, leaving a thick empty border of plain background on all sides (deeper at the bottom). The content group must NOT fill the frame. When in doubt, make the margin bigger, never smaller.
- These empty-margin rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction places content in a reserved margin, ignore that placement and keep the margin empty.
- All core text, logos, icons, and charts must stay inside the central area, leaving a wide, even empty margin on the top, left, and right sides; that margin must be COMPLETELY EMPTY on all three sides — not a thin border, not a partial inset.
- The top margin must contain: NO title text, NO headline, NO icons, NO logos, NO decorative elements.
- The left margin must contain: NO stat cards, NO numerical modules, NO icons, NO borders, NO text.
- The right margin must contain: NO indicators, NO boxes, NO icons, NO leader lines, NO text.
- The bottom margin, kept noticeably deeper than the side margins, must contain:
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
- SELF-CHECK before finalizing: if any text block, card, icon, or box touches or comes close to any frame edge, you MUST redesign the layout to add visible gutter space before output.`;

const EDITOR_SAFE_AREA =
`==================================================
EMPTY MARGIN RULES (CRITICAL — MUST PRESERVE)
==================================================
- These are layout guides only. The final image is ONE single continuous background with the subject centred; the margins are visually identical to the centre — same colour, tone and brightness everywhere. Do NOT render any frame, rectangle, outline, border line, guide line, crop mark, corner bracket, or dimmed / tinted / shaded band to mark the empty area. The empty margin must be completely invisible.
- SCALE THE WHOLE LAYOUT INWARD: treat the entire infographic as one group and shrink it so it is clearly smaller than the frame, leaving a thick empty border of plain background on all sides (deeper at the bottom). The content group must NOT fill the frame. When in doubt, make the margin bigger, never smaller.
- These empty-margin rules OVERRIDE any conflicting instruction in STYLE, STRUCTURE, or VARIABLE FIELDS. If a layout instruction places content in a reserved margin, ignore that placement and keep the margin empty.
- All core text, logos, icons, and charts must stay inside the central area, leaving a wide, even empty margin on all four sides (with the bottom margin kept a little deeper), and every one of those four margins must be COMPLETELY EMPTY — not a thin border, not a partial inset.
- Every reserved margin (top, bottom, left, right) must contain:
  - NO text
  - NO logos
  - NO icons
  - NO charts
  - NO divider lines
  - NO decorative elements
  - NO data-source line
  - NO <蓋章> stamp banner
- The background color or background image MUST extend seamlessly into all reserved margins — no change in color, texture, brightness, or visual tone; no hard edges, no visual breaks, no overlays, no gradients.
- FORBIDDEN terms/effects in the final composition: full-width, edge-to-edge, flush left, flush right, flush top, flush bottom, spans the entire width, corner-to-corner, bleed, touching the frame boundary.
- SELF-CHECK before finalizing: if any text block, card, icon, or box touches or comes close to any frame edge, you MUST redesign the layout to add visible gutter space before output.`;

/* ============================================================
   AI 消化：透過本地後端代理呼叫 Claude（見 main.py）
   ============================================================ */
const API_BASE = (location.hostname === "127.0.0.1" || location.hostname === "localhost") && location.port === "3000"
    ? "http://127.0.0.1:8787"
    : "";
const AI_BACKEND_URL = `${API_BASE}/api/generate`;
const IMAGE_BACKEND_URL = `${API_BASE}/api/images/generate`;
const REFINE_BACKEND_URL = `${API_BASE}/api/images/refine`;

function _apiError(data, status) {
    const detail = data && data.detail;
    if (typeof detail === "string") return detail;
    return "HTTP " + status;
}

// 後端 /api/generate、/api/images/generate 現在要求 X-API-Key（見 main.py
// verify_internal_api_key）。這個值直接烙在這裡，等於這個頁面公開就等於
// Key 公開——是使用者確認過取捨後選的方案，換來不用手動輸入。
// 這裡放的是占位符，容器啟動時由 entrypoint.sh 換成 Secret Manager 的真實值，
// 真實 Key 不進 git（公開 repo）。
const _INTERNAL_API_KEY = "__NEWS_IMAGE_API_KEY__";
function _apiHeaders() {
    return { "Content-Type": "application/json", "X-API-Key": _INTERNAL_API_KEY };
}

async function digestNewsText(input) {
    const response = await fetch(AI_BACKEND_URL, {
        method: "POST",
        headers: _apiHeaders(),
        body: JSON.stringify({
            news_text: input,
            type_label: digestTypeLabelForApi(),
            role: state.currentRole,
            density: state.digestDensity,
            stamp: state.stamp,
            tone: state.tone,
            editor_format: state.editorFormat,
            // 挖空側要在消化階段就講清楚（2026-09-08 WP1）：內容得趕到影片那半邊的
            // 對面，只在生圖端決定的話，重點會剛好被影片蓋掉。
            hole_side: state.holeSide,
            safe_frame: state.safeFrame,
            user_instruction: currentUserInstruction(),
            portrait_photo_count: uploadedPortraitCount(),
            asis_reference_count: uploadedAsisCount(),
        }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
        throw new Error(_apiError(data, response.status));
    }
    return data;
}

// 指令欄可蓋過版面形式（2026-09-03），AI 回報的類型因此可能跟下拉選的不一樣。
// 指定類型時把實際採用的類型講出來，免得下拉顯示 A、圖卻是 B。
function noteChartTypeOverride(data) {
    if (state.digestChartType === AUTO_TYPE_KEY) return;
    const label = data && data.chart_type;
    if (!label || label === digestType().label) return;
    showToast(`依指令欄改用「${label}」版面`);
}

function applyDigestToForm(data) {
    state.mapPoints = Array.isArray(data.map_points) ? data.map_points : [];
    // 地圖類：查不到座標的地名要講出來（2026-09-08）。不足 2 點時後端不做真實底圖，
    // 以前畫面完全沒提示，使用者重打六次都拿到一樣的結果。
    if (Array.isArray(data.map_missing) && data.map_missing.length) {
        const found = state.mapPoints.length;
        showToast(found >= 2
            ? `地圖：${data.map_missing.join('、')} 查不到座標，底圖只標 ${found} 點`
            : `地圖：${data.map_missing.join('、')} 查不到座標，只剩 ${found} 點，這次不會附真實底圖（改寫成行政區名再消化一次）`);
    }
    const s = curSelected();
    s.style = {};
    s.structure = {};
    document.getElementById("field-style").value = data.style || "";
    document.getElementById("field-structure").value = data.structure || "";
    document.getElementById("field-variable").value = (data.variable || "").replace(SYSTEM_DISCLAIMER, "").trim();
    applyPortraitSubjects(data);
    if (state.digestChartType === AUTO_TYPE_KEY) {
        const resolvedKey = Object.keys(CHART_TYPES).find(k => CHART_TYPES[k].label === data.chart_type);
        state.digestResolvedType = resolvedKey || null;
        renderDigestTypes();
    } else {
        noteChartTypeOverride(data);
    }
    renderTags();
    updateCounter();
    claimPromptType("digest");
}

const COVER_BACKEND_URL = `${API_BASE}/api/editor/cover`;

// 追加修改後重貼固定元素用（2026-09-07，比照 recomposeYtCover）：AI 版的成品是
// 「模型畫的整張圖＋程式後貼的 Logo／節目標籤／AI示意圖」，refine 改的是後貼前的
// 模型原圖，改完要再走一次後貼才是成品。欄位取現況，所以順便改標題也會生效。
function tenCoverFields() {
    const val = id => (document.getElementById(id)?.value || '').trim();
    const fullLayout = coverLayoutNow() === 'full';
    return {
        title_left: val('coverTitleLeft'),
        title_right: fullLayout ? '' : val('coverTitleRight'),
        layout: fullLayout ? 'full' : 'split',
        // 畫面描述欄已移除（2026-09-08 WP1），改送共用的指令欄當畫面提示
        instruction: coverInstructionForApi(),
        date_text: val('coverDate'),
        badge: document.getElementById('coverBadge')?.value || 'on_air',
        title_style: state.coverTitleStyle,
        provider: effectiveImageProvider(),
    };
}

async function recomposeTenCover(refined) {
    const source = refineSourceFromResponse(refined);
    if (!source) throw new Error('沒有可重貼的底圖');
    const res = await fetch(COVER_BACKEND_URL, {
        method: 'POST',
        headers: _apiHeaders(),
        body: JSON.stringify({
            ...tenCoverFields(),
            mode: 'ai',
            background_image_base64: source.base64,
            background_mime_type: source.mimeType,
        }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(_apiError(data, res.status));
    return data;
}

// 只改文字（2026-09-08，滿版合成版）：底圖不重生，用目前欄位重壓一次標題，零 API。
// 底圖走 state.tenCoverBackground，不是 refineSource——見該欄位的註解。
function setTenCoverBackground(data) {
    const usable = coverLayoutNow() === 'full'
        && data.mode === 'composite' && !!data.background_image_base64;
    state.tenCoverBackground = usable ? {
        base64: data.background_image_base64,
        mimeType: data.background_mime_type || 'image/png',
        isAi: !!data.background_is_ai,
    } : null;
    const btn = document.getElementById('coverRecomposeBtn');
    if (btn) btn.disabled = !usable;
}

async function recomposeTenCoverText() {
    const background = state.tenCoverBackground;
    if (!background) throw new Error('還沒有底圖，請先生成一次');
    const res = await fetch(COVER_BACKEND_URL, {
        method: 'POST',
        headers: _apiHeaders(),
        body: JSON.stringify({
            ...tenCoverFields(),
            mode: 'composite',
            background_image_base64: background.base64,
            background_mime_type: background.mimeType,
            background_is_ai: background.isAi,
        }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(_apiError(data, res.status));
    return data;
}

// 十點不一樣封面：使用者直接給兩個標題，中間沒有消化這一段，所以走自己的端點。
// 下拉、產出區、下載都還在同一頁同一個位置，編輯不用切分頁。
// recomposeOnly=true：滿版合成版的「只改文字」，底圖不重生（比照 handleYtCoverGenerate）。
async function handleTenCoverGenerate(recomposeOnly = false) {
    const val = id => (document.getElementById(id)?.value || '').trim();
    const titleLeft = val('coverTitleLeft');
    const titleRight = val('coverTitleRight');
    const fullLayout = coverLayoutNow() === 'full';
    if (!titleLeft) return showToast('第一標題要填');
    // 只改文字只做滿版合成版：AI 版的字是模型畫的、雙切拼完分不回去（後端也會回 400）
    if (recomposeOnly && !state.tenCoverBackground) return showToast('還沒有底圖，請先生成一次');

    const btn = document.getElementById('aiBtn');
    const loading = document.getElementById('aiLoading');
    btn.disabled = true;
    loading.classList.remove('hidden');
    let completed = false;
    try {
        let data;
        if (recomposeOnly) {
            showToast('用現有底圖重壓文字…');
            data = await recomposeTenCoverText();
        } else {
            const slots = coverAsisSlots();
            if (fullLayout) slots.right = false;   // 滿版只有一個附圖位
            const slotCount = (slots.left ? 1 : 0) + (slots.right ? 1 : 0);
            const asisCount = slotCount || uploadedAsisCount();
            // 有原圖放置一律程式壓字（後端也會強制），這裡只是把提示講對
            const composite = document.getElementById('coverAiTitle')?.checked === false || asisCount > 0;
            const deriving = true;   // 畫面描述欄移除後一律由 AI 推導（2026-09-08 WP1）
            showToast(fullLayout ? (slots.left ? '附圖鋪滿，合成中…' : (composite ? '生成底圖中，約 30–90 秒…' : '設計封面中，約 30–120 秒…'))
                : slots.left && slots.right ? '兩格都用附圖，合成中…'
                : slots.left ? '左格用附圖，右格生底圖中，約 30–90 秒…'
                : slots.right ? '右格用附圖，左格生底圖中，約 30–90 秒…'
                : asisCount >= 2 ? '兩格都用附圖，合成中…'
                : asisCount === 1 ? '單張附圖整版鋪滿，合成中…'
                : composite
                    ? '生成左右底圖中，兩張平行跑，約 60–120 秒…'
                    : (deriving ? 'AI 補畫面描述後開始設計封面，約 40–140 秒…' : '設計封面中，約 30–120 秒…'));
            beginGenerationProgress('image', asisCount >= 2 ? 0.3 : slotCount === 1 ? 1.0 : asisCount === 1 ? 0.3 : (composite ? 1.6 : 1.3));
            const res = await fetch(COVER_BACKEND_URL, {
                method: 'POST',
                headers: _apiHeaders(),
                body: JSON.stringify({
                    title_left: titleLeft,
                    title_right: fullLayout ? '' : titleRight,
                    layout: fullLayout ? 'full' : 'split',
                    instruction: coverInstructionForApi(),
                    date_text: val('coverDate'),
                    badge: document.getElementById('coverBadge')?.value || 'on_air',
                    title_style: state.coverTitleStyle,
                    mode: composite ? 'composite' : 'ai',
                    provider: effectiveImageProvider(),
                    reference_images: userRefImagesPayload(),
                    asis_left: state.coverAsis.left?.dataUrl || '',
                    asis_right: fullLayout ? '' : (state.coverAsis.right?.dataUrl || ''),
                }),
            });
            data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(_apiError(data, res.status));
        }

        const imageUrl = `data:${data.mime_type};base64,${data.image_data_base64}`;
        document.getElementById('oneClickImage').src = imageUrl;
        const download = document.getElementById('oneClickDownload');
        download.href = imageUrl;
        download.download = downloadFileName(state.editorFormat);
        download.innerText = '下載 PNG';
        // 追加修改只在 AI 版適用（2026-09-07）：AI 版的源圖是後貼 Logo 前的模型原圖，
        // 改完再走一次後貼就是新成品。合成版的成品是程式用 Pillow 拼的，沒有可以餵回
        // 生圖模型的原圖——把拼好的成品餵回去，模型會把 Logo 與標題一起重畫。
        state.tenCoverMode = data.mode || 'ai';
        const tenCoverSource = data.mode === 'ai' ? refineSourceFromResponse(data) : null;
        resetRefineState(tenCoverSource, tenCoverSource ? data : null);
        // 滿版合成版：把壓字前底圖記下來，「只改文字」才有東西可以帶回去（零 API 重壓）
        setTenCoverBackground(data);
        document.getElementById('oneClickLabel').innerText = editorFormat().label;
        document.getElementById('oneClickMeta').innerText = fullLayout ? titleLeft : `${titleLeft}｜${titleRight}`;
        document.getElementById('oneClickEmpty').classList.add('hidden');
        document.getElementById('oneClickResult').classList.remove('hidden');
        completed = true;
        showToast('封面已完成');
    } catch (err) {
        showToast(`封面生成失敗：${err.message}`);
    } finally {
        btn.disabled = false;
        loading.classList.add('hidden');
        endGenerationProgress(completed);
    }
}

const COVER_TITLES_BACKEND_URL = `${API_BASE}/api/editor/cover-titles`;

// 封面標題自動消化（2026-09-06）：貼新聞內文 → 文字模型出標題 → 回填欄位。
// 刻意不接著生圖：使用者裁決要讓編輯看過標題再自己按「生成」。
async function handleCoverTitleDigest(target) {
    // 2026-09-08 WP1：不再依版型改 target——版面由消化結果決定，不是反過來。
    // AI 判定內文是 1 個還是 2 個主題，單主題只回第一標題（回填後即為滿版）。
    const ten = target === 'ten_cover';
    // 2026-09-08 WP2：整點直播用自己的 target，回兩個標題＋主題數（同十點的判定）
    const ytHourly = target === 'yt_hourly';
    const textarea = document.getElementById(ten ? 'coverNewsText' : 'ytCoverNewsText');
    const newsText = (textarea?.value || '').trim();
    if (newsText.length < 10) return showToast('先貼新聞內文（至少 10 個字）');
    const btn = document.getElementById('aiBtn');
    btn.disabled = true;
    try {
        showToast('AI 消化標題中，約 10–30 秒…');
        const res = await fetch(COVER_TITLES_BACKEND_URL, {
            method: 'POST',
            headers: _apiHeaders(),
            body: JSON.stringify({ news_text: newsText, target }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(_apiError(data, res.status));
        if (ten) {
            document.getElementById('coverTitleLeft').value = data.title_left || '';
            document.getElementById('coverTitleRight').value = data.title_right || '';
            // 回填完版面就跟著變（第二標題空＝滿版），指示器與右附圖位一起更新
            updateCoverLayoutIndicator();
        } else {
            document.getElementById('ytCoverTitle').value = data.title || '';
            if (ytHourly) {
                const second = document.getElementById('ytCoverTitleSecond');
                if (second) second.value = data.title_second || '';
                // 回填完版面就跟著變（第二標題空＝滿版），指示器與下載短名一起更新
                updateYtLayoutIndicator();
            }
        }
        const single = ten ? !(data.title_right || '').trim()
            : ytHourly ? !(data.title_second || '').trim() : false;
        showToast((ten || ytHourly) && single
            ? `判定為單一主題（${ten ? '滿版' : '單則'}），標題已回填，看過沒問題再按「生成」`
            : '標題已回填，看過沒問題再按「生成」');
    } catch (err) {
        showToast(`消化標題失敗：${err.message}`);
    } finally {
        btn.disabled = false;
    }
}

const YT_COVER_BACKEND_URL = `${API_BASE}/api/editor/yt-cover`;

function ytCoverFields() {
    const val = id => (document.getElementById(id)?.value || '').trim();
    const layout = editorFormat().ytLayout || 'news';
    return {
        title: val('ytCoverTitle'),
        // 整點直播＋這一欄有值＝雙則（後端 editor_formats.yt_cover_is_dual）
        title_second: layout === 'hourly' ? val('ytCoverTitleSecond') : '',
        layout,
        title_mode: document.getElementById('ytCoverAiTitle')?.checked === false ? 'composite' : 'ai',
        original_audio: layout === 'news' && !!document.getElementById('ytCoverOriginalAudio')?.checked,
        ai_translation: layout === 'news' && !!document.getElementById('ytCoverAiTranslation')?.checked,
        date_text: val('ytCoverDate'),
        time_text: layout === 'hourly' ? val('ytCoverTime') : '',
        bottom_band: layout !== 'hourly' && state.ytBottomBand,
        // 指令欄（2026-09-08 WP1）：餵給底圖推導當畫面提示
        instruction: coverInstructionForApi(),
    };
}

// 用既有底圖重疊文字（追加修改後、或只改標題／副標／日期）。
// background 從 refineSource 來——那格語意就是「給改圖用的原圖」，這條線上它是無文字底圖。
async function recomposeYtCover(refined) {
    const source = refineSourceFromResponse(refined);
    const res = await fetch(YT_COVER_BACKEND_URL, {
        method: 'POST',
        headers: _apiHeaders(),
        body: JSON.stringify({
            // ytCoverFields() 帶著第二標題，所以雙則的「只改文字」照樣是雙則
            ...ytCoverFields(),
            title_mode: state.ytCoverTitleMode,
            provider: effectiveImageProvider(),
            background_image_base64: source.base64,
            background_mime_type: source.mimeType,
            background_is_ai: state.ytCoverBackgroundIsAi,
        }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(_apiError(data, res.status));
    return data;
}

function showYtCoverResult(data, fields) {
    const imageUrl = `data:${data.mime_type};base64,${data.image_data_base64}`;
    document.getElementById('oneClickImage').src = imageUrl;
    const download = document.getElementById('oneClickDownload');
    download.href = imageUrl;
    download.download = downloadFileName(state.editorFormat, fields.title);
    download.innerText = '下載 PNG';
    state.ytCoverBackgroundIsAi = !!data.background_is_ai;
    state.ytCoverTitleMode = data.title_mode || 'ai';
    // 追加修改：以無文字底圖為源，改完由 handleRefine 再疊一次文字。
    // 雙則的底圖是左右兩張羽化拼好的那一張，這裡沒有分別。
    resetRefineState(refineSourceFromResponse(data), data);
    const recompose = document.getElementById('ytCoverRecomposeBtn');
    if (recompose) recompose.disabled = false;
    document.getElementById('oneClickLabel').innerText = editorFormat().label;
    document.getElementById('oneClickMeta').innerText =
        [data.line1, data.line2,
         data.dual ? '雙則' : '',
         fields.original_audio ? '原音呈現' : '', fields.ai_translation ? 'AI即時翻譯' : '',
         fields.time_text].filter(Boolean).join('｜');
    document.getElementById('oneClickEmpty').classList.add('hidden');
    document.getElementById('oneClickResult').classList.remove('hidden');
}

// YT 直播封面。recomposeOnly=true：底圖不重生，只用目前欄位重疊文字。
async function handleYtCoverGenerate(recomposeOnly = false) {
    const fields = ytCoverFields();
    if (!fields.title) return showToast('請輸入直播標題');
    // 雙則每行最多 YT_HOURLY_LINE_MAX_CHARS 個全形字寬（半形算半字），送出前先擋，別燒完兩次生圖才被後端退
    if (fields.title_second && fields.title_mode !== 'ai') {
        const tooLong = [['第一標題', fields.title], ['第二標題', fields.title_second]]
            .find(([, t]) => displayWidth(t) > YT_HOURLY_LINE_MAX_CHARS);
        if (tooLong) return showToast(`${tooLong[0]}超過 ${YT_HOURLY_LINE_MAX_CHARS} 字，請縮短這一行`);
    }
    if (recomposeOnly && !state.refineSource) return showToast('還沒有底圖，請先生成一次');
    // AI 標題模式的成品沒有「只改文字」這回事——字是模型畫的，改字就是整張重生
    if (recomposeOnly && state.ytCoverTitleMode === 'ai') {
        showToast('標題由 AI 生成，改字要整張重生…');
        recomposeOnly = false;
    }

    const btn = document.getElementById('aiBtn');
    const loading = document.getElementById('aiLoading');
    btn.disabled = true;
    loading.classList.remove('hidden');
    let completed = false;
    try {
        let data;
        if (recomposeOnly) {
            showToast('用現有底圖重疊文字…');
            data = await recomposeYtCover(state.refineDisplay || {
                image_data_base64: state.refineSource.base64, mime_type: state.refineSource.mimeType,
            });
        } else {
            const asis = state.userRefImages.some(ref => ref.purpose === 'asis');
            const aiTitle = fields.title_mode === 'ai';
            showToast(aiTitle ? 'AI 整張生成（含標題），約 30–120 秒…'
                : asis ? '用附圖當底圖，合成中…' : 'AI 生底圖後合成，約 30–120 秒…');
            beginGenerationProgress('image', (asis && !aiTitle) ? 0.3 : 1.3);
            const res = await fetch(YT_COVER_BACKEND_URL, {
                method: 'POST',
                headers: _apiHeaders(),
                body: JSON.stringify({
                    ...fields,
                    provider: effectiveImageProvider(),
                    image_size: state.imageSize,
                    reference_images: userRefImagesPayload(),
                }),
            });
            data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(_apiError(data, res.status));
        }
        showYtCoverResult(data, fields);
        completed = true;
    } catch (err) {
        console.error(err);
        showToast(err.message || '封面生成失敗，請稍後再試');
    } finally {
        btn.disabled = false;
        loading.classList.add('hidden');
        endGenerationProgress(completed);
    }
}

/* ============================================================
   YT 直播「直標」（2026-09-08 WP3）
   透明底 PNG，疊在直播訊號上。沒有底圖＝沒有生圖、沒有附圖、沒有引擎、
   沒有「只改文字」、沒有追加修改。五組按鈕的狀態存在 state.vstrip。
   ============================================================ */
const YT_OVERLAY_BACKEND_URL = `${API_BASE}/api/editor/yt-overlay`;
const VSTRIP_MAIN_MAX_CELLS = 12;
const VSTRIP_SUB_MAX_CELLS = 14;
// Logo 角落與直標同側的**上**角會壓到 LIVE 章與色框頂：靠左的直標不能放 tl，靠右的不能放 tr。
// 2026-09-09 使用者裁決：直標縮短後同側的下角（bl／br）開放，色框會自己讓開 Logo。
const VSTRIP_BLOCKED_CORNERS = { left: ['tl'], right: ['tr'] };
// 換邊時把 Logo 移到對側**同高**的角落，不是一律回右上
const VSTRIP_MIRROR_CORNER = { tl: 'tr', bl: 'br', tr: 'tl', br: 'bl' };
const VSTRIP_CORNER_LABELS = { tl: '左上', tr: '右上', bl: '左下', br: '右下' };

/* 直排的「格數」。與 compose._vertical_cells 等價：連續英數字併成一格（縱中橫）、
   空白不算、其餘一字一格。標點只是換字形不影響數量，所以這裡不做替換。
   用 for...of 逐 code point 走，不是 UTF-16 單元——表情符號會被拆成兩格。 */
function vstripCells(text) {
    const cells = [];
    let run = '';
    for (const ch of String(text || '')) {
        if (/^[A-Za-z0-9]$/.test(ch)) { run += ch; continue; }
        if (run) { cells.push(run); run = ''; }
        if (/\s/.test(ch)) continue;
        cells.push(ch);
    }
    if (run) cells.push(run);
    return cells;
}

function vstripFields() {
    const val = id => (document.getElementById(id)?.value || '').trim();
    const v = state.vstrip;
    return {
        title: val('vstripTitle'),
        title_second: val('vstripTitleSecond'),
        source_text: val('vstripSource'),
        variant: v.variant,
        title_side: v.titleSide,
        logo_corner: v.logoCorner,
        source_corner: v.sourceCorner,
        live: !!v.live,
    };
}

function setVstripVariant(variant) {
    state.vstrip.variant = variant;
    updateVstripButtons();
}

function setVstripTitleSide(side) {
    const previous = state.vstrip.titleSide;
    state.vstrip.titleSide = side;
    // Logo 還停在直標那一側的上角就會被壓到：自動搬到對側同高的角落，不用使用者自己發現
    if (VSTRIP_BLOCKED_CORNERS[side].includes(state.vstrip.logoCorner)) {
        state.vstrip.logoCorner = VSTRIP_MIRROR_CORNER[state.vstrip.logoCorner];
    }
    // 來源句一起鏡射（2026-09-09）：預設 tl 是「LIVE 章旁邊」，換成靠右卻還停在 tl
    // 就變成孤零零貼在對角，跟舊版「跟 LIVE 章」的行為對不上。
    if (previous !== side) {
        state.vstrip.sourceCorner = VSTRIP_MIRROR_CORNER[state.vstrip.sourceCorner];
    }
    updateVstripButtons();
}

function setVstripLogoCorner(corner) {
    if (VSTRIP_BLOCKED_CORNERS[state.vstrip.titleSide].includes(corner)) {
        return showToast('這個角落會壓到直標，請選另一邊');
    }
    state.vstrip.logoCorner = corner;
    updateVstripButtons();
}

function setVstripSourceCorner(corner) {
    state.vstrip.sourceCorner = corner;
    updateVstripButtons();
}

function toggleVstripLive(checkbox) {
    state.vstrip.live = !!checkbox.checked;
}

// 按鈕外觀：選中的填色、沒選中的只有邊框；會壓到直標的角落直接 disabled
function _vstripPick(selector, value) {
    document.querySelectorAll(selector).forEach(btn => {
        const on = btn.dataset.vstripValue === value;
        btn.classList.toggle('bg-violet-600', on);
        btn.classList.toggle('text-white', on);
        btn.classList.toggle('text-slate-400', !on);
    });
}

function updateVstripButtons() {
    if (editorFormat().inputs !== 'yt_vstrip') return;
    const v = state.vstrip;
    _vstripPick('[data-vstrip-variant]', v.variant);
    _vstripPick('[data-vstrip-side]', v.titleSide);
    _vstripPick('[data-vstrip-corner]', v.logoCorner);
    _vstripPick('[data-vstrip-source]', v.sourceCorner);
    const blocked = VSTRIP_BLOCKED_CORNERS[v.titleSide];
    document.querySelectorAll('[data-vstrip-corner]').forEach(btn => {
        const bad = blocked.includes(btn.dataset.vstripValue);
        btn.disabled = bad;
        btn.classList.toggle('opacity-40', bad);
        btn.title = bad ? '這個角落有 LIVE 章與直標頂，會打架' : 'TVBS NEWS 白色字標放這個角落';
    });
    // 來源句四角：跟 Logo 同一角時後端會自動讓開，所以不 disabled，只在提示裡講清楚
    document.querySelectorAll('[data-vstrip-source]').forEach(btn => {
        const corner = btn.dataset.vstripValue;
        btn.title = corner === v.logoCorner
            ? `跟 Logo 同一角（${VSTRIP_CORNER_LABELS[corner]}）：會自動排在 Logo 的另一邊，不會重疊`
            : `來源句放${VSTRIP_CORNER_LABELS[corner]}`;
    });
    // 來源句空白時「跟 LIVE 章／跟 Logo」沒有意義，整列收起來
    const sourceRow = document.getElementById('vstripSourceRow');
    const hasSource = !!(document.getElementById('vstripSource')?.value || '').trim();
    if (sourceRow) sourceRow.classList.toggle('hidden', !hasSource);
    const live = document.getElementById('vstripLive');
    if (live) live.checked = !!v.live;
    updateVstripCellHint();
}

// 欄位下方的格數提示：邊打邊算，不用等生成才知道超了
function updateVstripCellHint() {
    const hint = document.getElementById('vstripCellHint');
    if (!hint) return;
    const main = vstripCells(document.getElementById('vstripTitle')?.value || '').length;
    const sub = vstripCells(document.getElementById('vstripTitleSecond')?.value || '').length;
    const over = main > VSTRIP_MAIN_MAX_CELLS || sub > VSTRIP_SUB_MAX_CELLS;
    hint.innerText = `第一標題 ${main} 格／${VSTRIP_MAIN_MAX_CELLS}　第二標題 ${sub} 格／${VSTRIP_SUB_MAX_CELLS}`;
    hint.classList.toggle('text-red-400', over);
    hint.classList.toggle('text-slate-600', !over);
}

function onVstripInput() {
    updateVstripButtons();
}

function showVstripResult(data, fields) {
    const imageUrl = `data:${data.mime_type};base64,${data.image_base64}`;
    document.getElementById('oneClickImage').src = imageUrl;
    const download = document.getElementById('oneClickDownload');
    download.href = imageUrl;
    download.download = downloadFileName(state.editorFormat, fields.title, 'png');
    download.innerText = '下載 PNG';
    // 直標沒有底圖，追加修改與「只改文字」都不適用——清成 null，refine 鈕自然不會亮
    resetRefineState(null, null);
    document.getElementById('oneClickLabel').innerText = editorFormat().label;
    const layout = data.layout || {};
    document.getElementById('oneClickMeta').innerText = [
        `第一標題 ${layout.main_cells_count} 格`,
        layout.sub_cells_count ? `第二標題 ${layout.sub_cells_count} 格` : '',
        fields.title_side === 'left' ? '靠左' : '靠右',
        VSTRIP_VARIANT_LABELS[fields.variant] || '',
        fields.live ? 'LIVE' : '無 LIVE 章',
    ].filter(Boolean).join('｜');
    document.getElementById('oneClickEmpty').classList.add('hidden');
    document.getElementById('oneClickResult').classList.remove('hidden');
}

const VSTRIP_VARIANT_LABELS = { original_audio: '原音呈現', ai_translation: 'AI即時翻譯' };

async function handleYtVstripGenerate() {
    const fields = vstripFields();
    if (!fields.title) return showToast('請輸入第一標題');
    // 格數在送出前先擋：後端也會擋（400），但白跑一趟沒有必要
    const mainCells = vstripCells(fields.title).length;
    if (mainCells > VSTRIP_MAIN_MAX_CELLS) {
        return showToast(`第一標題超過 ${VSTRIP_MAIN_MAX_CELLS} 格（目前 ${mainCells} 格）`);
    }
    const subCells = vstripCells(fields.title_second).length;
    if (subCells > VSTRIP_SUB_MAX_CELLS) {
        return showToast(`第二標題超過 ${VSTRIP_SUB_MAX_CELLS} 格（目前 ${subCells} 格）`);
    }

    const btn = document.getElementById('aiBtn');
    const loading = document.getElementById('aiLoading');
    btn.disabled = true;
    loading.classList.remove('hidden');
    try {
        const res = await fetch(YT_OVERLAY_BACKEND_URL, {
            method: 'POST',
            headers: _apiHeaders(),
            body: JSON.stringify(fields),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(_apiError(data, res.status));
        showVstripResult(data, fields);
    } catch (err) {
        console.error(err);
        showToast(err.message || '直標生成失敗，請稍後再試');
    } finally {
        btn.disabled = false;
        loading.classList.add('hidden');
    }
}

async function handleOneClickGenerate() {
    if (editorFormat().inputs === 'cover') return handleTenCoverGenerate();
    if (editorFormat().inputs === 'yt_cover') return handleYtCoverGenerate();
    if (editorFormat().inputs === 'yt_vstrip') return handleYtVstripGenerate();
    const input = document.getElementById("aiInput").value.trim();
    if (!input) return showToast("請輸入欲生成的新聞內容");

    const btnText = document.getElementById("aiBtnText");
    const loading = document.getElementById("aiLoading");
    const btn = document.getElementById("aiBtn");
    btn.disabled = true;
    // 進度文字取代原本的「整段藏起來只留轉圈」，轉圈保留在旁邊當活著的訊號
    btnText.classList.remove("hidden");
    loading.classList.remove("hidden");
    let completed = false;

    try {
        showToast("消化中…");
        beginGenerationProgress("digest");
        const digest = await digestNewsText(input);
        applyDigestToForm(digest);
        const variable = (digest.variable || "").replace(SYSTEM_DISCLAIMER, "").trim();
        const prompt = buildPrompt({
            role: state.currentRole,
            engine: effectiveImageProvider(),
            typeLabel: digest.chart_type || digestTypeLabelForApi(),
            style: digest.style || "[No Style Defined]",
            structure: digest.structure || "[No Structure Defined]",
            variable: variable ? `${SYSTEM_DISCLAIMER}\n${variable}` : "[No Variables Defined]",
            safeFrame: state.safeFrame,
            aspectRatio: currentAspectRatio(),
        });
        showToast("生圖中，約 30–120 秒…");
        // 2K 與 GPT 都明顯較慢，預估時間拉長免得進度早早貼上限乾等
        const slowCombo = (state.imageSize === "2K" ? 1.5 : 1)
            * (effectiveImageProvider() === "gpt" ? 1.3 : 1);
        beginGenerationProgress("image", slowCombo);
        const imgRes = await fetch(IMAGE_BACKEND_URL, {
            method: "POST",
            headers: _apiHeaders(),
            body: JSON.stringify({
                prompt,
                provider: effectiveImageProvider(),
                aspect_ratio: currentAspectRatio(),
                image_size: state.imageSize,
                safe_frame: state.safeFrame,
                safe_frame_profile: state.currentRole,
                // 播出鏡面的挖空側。框由後端在**置框之後**用數學貼上，不寫進 prompt——
                // 模型會把數字當文字畫進圖裡（見 compose.py 開頭的實驗紀錄）。
                broadcast_hole: broadcastHoleForApi(),
                // 地圖類的真實座標（消化端列地名、後端實查 Nominatim）。後端據此
                // 拼一張真實底圖、把標點畫在正確位置再當參考圖附上——模型記憶裡的
                // 經緯度實測差到 2.3 公里，冷門地名尤其不準。
                map_points: state.mapPoints,
                portrait_subjects: state.portraitSubjects,
                portrait_subjects_en: state.portraitSubjectsEn,
                reference_images: userRefImagesPayload(),
            }),
        });
        const data = await imgRes.json().catch(() => ({}));
        if (!imgRes.ok) {
            throw new Error(_apiError(data, imgRes.status));
        }

        const imageUrl = `data:${data.mime_type};base64,${data.image_data_base64}`;
        const isPng = data.mime_type === "image/png";
        document.getElementById("oneClickImage").src = imageUrl;
        const download = document.getElementById("oneClickDownload");
        download.href = imageUrl;
        download.download = downloadFileName(state.editorFormat, undefined, isPng ? "png" : "jpg");
        download.innerText = `下載 ${isPng ? "PNG" : "JPEG"}`;
        // ③ 記住「置框前」原圖供追加修改；未置框時成品本身就是原圖
        resetRefineState(refineSourceFromResponse(data), data);
        document.getElementById("oneClickLabel").innerText = data.model || "AI Generated";
        const titleMatch = variable.match(/\[標題\]\s*([^\n]+)/);
        document.getElementById("oneClickMeta").innerText = titleMatch ? titleMatch[1].trim() : "";
        document.getElementById("oneClickEmpty").classList.add("hidden");
        document.getElementById("oneClickResult").classList.remove("hidden");
        completed = true;
        showToast(titleMatch ? `已生成：${titleMatch[1].trim()}` : "已完成圖片生成");
    } catch (err) {
        console.error(err);
        showToast(err.message || "生成失敗，請稍後再試");
    } finally {
        btn.disabled = false;
        btnText.classList.remove("hidden");
        loading.classList.add("hidden");
        endGenerationProgress(completed);
    }
}

/* ============================================================
   圖片生成：僅在使用者確認最終 Prompt 後呼叫後端代理
   ============================================================ */
function getFinalPrompt() {
    return document.getElementById('displayPrompt').innerText.trim();
}

function effectiveImageProvider() {
    return state.currentRole === '編輯' || state.engine === 'gpt' ? 'gpt' : 'gemini';
}

function updateImageGenerationControls() {
    const confirmed = document.getElementById('promptConfirmed');
    const button = document.getElementById('generateImageBtn');
    const buttonText = document.getElementById('generateImageBtnText');
    const hint = document.getElementById('imageGenerationHint');
    if (!confirmed || !button || !buttonText || !hint) return;

    const hasPrompt = !getFinalPrompt().includes('Waiting for data');
    const providerName = effectiveImageProvider() === 'gpt' ? 'GPT' : 'Gemini';
    button.disabled = !confirmed.checked || !hasPrompt;
    buttonText.innerText = `使用 ${providerName} 生成圖片`;

    if (!hasPrompt) {
        hint.innerText = '請先填寫內容，產生最終 Prompt';
    } else if (!confirmed.checked) {
        hint.innerText = `確認後可使用 ${providerName} 一鍵生成 ${currentAspectRatio()} 圖片`;
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

    const provider = effectiveImageProvider();
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
            headers: _apiHeaders(),
            body: JSON.stringify({
                prompt,
                provider,
                aspect_ratio: currentAspectRatio(),
                image_size: state.imageSize,
                safe_frame: state.safeFrame,
                safe_frame_profile: state.currentRole,
                // 播出鏡面的挖空側。框由後端在**置框之後**用數學貼上，不寫進 prompt——
                // 模型會把數字當文字畫進圖裡（見 compose.py 開頭的實驗紀錄）。
                broadcast_hole: broadcastHoleForApi(),
                // 地圖類的真實座標（消化端列地名、後端實查 Nominatim）。後端據此
                // 拼一張真實底圖、把標點畫在正確位置再當參考圖附上——模型記憶裡的
                // 經緯度實測差到 2.3 公里，冷門地名尤其不準。
                map_points: state.mapPoints,
                portrait_subjects: state.portraitSubjects,
                portrait_subjects_en: state.portraitSubjectsEn
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
        download.download = downloadFileName(state.editorFormat, undefined, isPng ? 'png' : 'jpg');
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
   ① 專用指令欄位
   ============================================================ */
function currentUserInstruction() {
    const el = document.getElementById('aiInstruction');
    return el ? el.value.trim() : '';
}

// 封面／YT 端點的 instruction 上限是 500 字，指令欄本身放到 2000（主流程用得到），
// 超過直接送會被 pydantic 擋成 422，所以在這裡先截斷（2026-09-08 WP1）。
const COVER_INSTRUCTION_MAX = 500;

function coverInstructionForApi() {
    return currentUserInstruction().slice(0, COVER_INSTRUCTION_MAX);
}

// 指令欄的需求蓋過 UI 按鈕（2026-09-03 使用者裁決），後端已明文寫進優先序規則。
// 前端只負責讓使用者看得出來「你在指令欄寫的會贏過旁邊那顆按鈕」，刻意不自動去
// 翻開關——「不要蓋章／蓋章拿掉／要有蓋章」這類否定句用關鍵字判，翻錯比不翻更糟。
const INSTRUCTION_OVERRIDE_HINTS = [
    { re: /蓋章/, text: '蓋章' },
    { re: /逐字|不要刪|不刪|完全依照|原文照|一字不|精簡|濃縮|字數|簡短|多一點字/, text: '消化程度' },
    { re: /版面|版型|圖表|地圖|流程|示意|長條|折線|圓餅/, text: '版面形式' },
    { re: /色調|亮一點|暗一點|亮色|暗色|淺底|深底|白底|黑底/, text: '色調' },
    { re: /風格|手繪|寫實|扁平|質感/, text: '風格' },
    { re: /附圖|參考圖|原圖|照片/, text: '參考附圖' },
];

function updateInstructionOverrideHint() {
    const hint = document.getElementById('instructionOverrideHint');
    if (!hint) return;
    const text = currentUserInstruction();
    const hits = text ? INSTRUCTION_OVERRIDE_HINTS.filter(h => h.re.test(text)).map(h => h.text) : [];
    if (!hits.length) {
        hint.classList.add('hidden');
        hint.innerText = '';
        return;
    }
    hint.classList.remove('hidden');
    hint.innerText = `指令欄提到${hits.join('、')}：以指令欄為準，會蓋過上面的按鈕設定。`;
}

/* ============================================================
   ② 使用者上傳參考圖（地圖底稿／實景參考）
   肖像照仍由後端 resolve_portrait 自動查，這裡刻意不開人臉上傳。
   ============================================================ */
const REF_MAX_FILES = 3;
// 後端 data_url 上限約 2MB base64；1.5MB 原檔編碼後約 2MB，貼著上限
const REF_MAX_BYTES = 1.5 * 1024 * 1024;
// portrait＝肖像照：使用者親自上傳時，「兩位以上具名真人不畫臉」鐵律解除
// （2026-08-17 使用者裁決）；沒附照片的人後端規則仍要求不畫臉。
const REF_PURPOSES = { map: '地圖底稿', scene: '實景參考', portrait: '肖像照片', asis: '原圖放置' };

// data URL 的 base64 部分解碼回原始 bytes 的實際大小（含 padding 校正）。
function dataUrlByteLength(dataUrl) {
    const base64 = dataUrl.slice(dataUrl.indexOf(',') + 1);
    const padding = (base64.endsWith('==') ? 2 : base64.endsWith('=') ? 1 : 0);
    return Math.floor(base64.length * 0.75) - padding;
}

// 超過 REF_MAX_BYTES 時自動壓縮，不再直接擋掉使用者：
// 依序降 JPEG 品質，再不行就等比縮小長邊，兩層都到底仍超標就取最後一次結果
// （交給後端的 max_length 校驗把關，不在前端硬擋）。
// 轉檔統一輸出 JPEG——參考圖（地圖底稿／實景／肖像／原圖放置）不需要透明度。
function compressImageFile(file, maxBytes) {
    return new Promise((resolve, reject) => {
        const img = new Image();
        const objectUrl = URL.createObjectURL(file);
        img.onload = () => {
            URL.revokeObjectURL(objectUrl);
            const canvas = document.createElement('canvas');
            const ctx = canvas.getContext('2d');
            let scale = 1;
            const qualitySteps = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4];
            let best = null;
            const renderAt = (currentScale) => {
                canvas.width = Math.max(1, Math.round(img.naturalWidth * currentScale));
                canvas.height = Math.max(1, Math.round(img.naturalHeight * currentScale));
                ctx.clearRect(0, 0, canvas.width, canvas.height);
                ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
            };
            outer:
            for (let round = 0; round < 6; round += 1) {
                renderAt(scale);
                for (const quality of qualitySteps) {
                    const dataUrl = canvas.toDataURL('image/jpeg', quality);
                    const size = dataUrlByteLength(dataUrl);
                    if (!best || size < dataUrlByteLength(best)) best = dataUrl;
                    if (size <= maxBytes) break outer;
                }
                scale *= 0.75; // 品質降到底仍超標，縮小長邊再重試
            }
            resolve(best);
        };
        img.onerror = () => { URL.revokeObjectURL(objectUrl); reject(new Error('圖片讀取失敗')); };
        img.src = objectUrl;
    });
}

async function handleRefFilesSelected(input) {
    const files = Array.from(input.files || []);
    input.value = '';
    for (const file of files) {
        if (state.userRefImages.length >= REF_MAX_FILES) {
            showToast(`參考圖最多 ${REF_MAX_FILES} 張`);
            break;
        }
        if (file.size <= REF_MAX_BYTES) {
            const reader = new FileReader();
            reader.onload = () => {
                state.userRefImages.push({ dataUrl: reader.result, purpose: 'scene', name: file.name });
                renderRefUploads();
            };
            reader.readAsDataURL(file);
            continue;
        }
        try {
            const dataUrl = await compressImageFile(file, REF_MAX_BYTES);
            if (dataUrlByteLength(dataUrl) > REF_MAX_BYTES) {
                showToast(`「${file.name}」壓縮後仍過大，請換一張較小的圖`);
                continue;
            }
            showToast(`「${file.name}」已自動壓縮上傳`);
            state.userRefImages.push({ dataUrl, purpose: 'scene', name: file.name });
            renderRefUploads();
        } catch (err) {
            showToast(`「${file.name}」壓縮失敗：${err.message}`);
        }
    }
}

function renderRefUploads() {
    const list = document.getElementById('refUploadList');
    if (!list) return;
    list.innerHTML = '';
    state.userRefImages.forEach((ref, index) => {
        const row = document.createElement('div');
        row.className = 'flex items-center gap-2 bg-slate-950/60 border border-slate-800 rounded-lg px-2 py-1.5';
        const img = document.createElement('img');
        img.src = ref.dataUrl;
        img.className = 'w-10 h-10 object-cover rounded';
        const name = document.createElement('span');
        name.className = 'flex-1 text-[10px] text-slate-400 truncate';
        name.textContent = ref.name;
        const select = document.createElement('select');
        select.className = 'bg-slate-900 border border-slate-700 rounded text-[10px] text-slate-200 px-1.5 py-1';
        for (const [value, label] of Object.entries(REF_PURPOSES)) {
            // 十點封面有自己的左右附圖位（2026-09-07），通用清單不再提供「原圖放置」，
            // 免得又出現分不清左右的附圖
            if (value === 'asis' && editorFormat().inputs === 'cover' && ref.purpose !== 'asis') continue;
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            option.selected = ref.purpose === value;
            select.appendChild(option);
        }
        select.onchange = () => { ref.purpose = select.value; };
        const remove = document.createElement('button');
        remove.className = 'text-[10px] font-black text-slate-500 hover:text-red-400 px-1';
        remove.textContent = '✕';
        remove.onclick = () => { state.userRefImages.splice(index, 1); renderRefUploads(); };
        row.append(img, name, select, remove);
        list.appendChild(row);
    });
}

// 具名真人名單與英文原名**必須成對處理**：兩個陣列各自過濾會錯位，
// 第 2 個人就會拿到第 3 個人的英文名去查照片，等於用別人的臉。
function applyPortraitSubjects(data) {
    const names = Array.isArray(data.portrait_subjects) ? data.portrait_subjects : [];
    const english = Array.isArray(data.portrait_subjects_en) ? data.portrait_subjects_en : [];
    const pairs = names
        .map((name, index) => ({
            name: typeof name === 'string' ? name.trim() : '',
            en: typeof english[index] === 'string' ? english[index].trim() : ''
        }))
        .filter(pair => pair.name);
    state.portraitSubjects = pairs.map(pair => pair.name);
    state.portraitSubjectsEn = pairs.map(pair => pair.en);
}

function userRefImagesPayload() {
    return state.userRefImages.map(ref => ({ data_url: ref.dataUrl, purpose: ref.purpose }));
}

// 消化階段只需要知道使用者上傳了幾張肖像照（圖本身在生圖階段才送）：
// 後端據此判斷維基查不到的人是不是其實有照片，不會把他排出版面。
function uploadedPortraitCount() {
    return state.userRefImages.filter(ref => ref.purpose === 'portrait').length;
}

// 消化階段同樣只需要知道張數（圖本身在生圖階段才送）：後端據此讓 STRUCTURE
// 明確交代這塊版位放使用者原圖，避免消化端隨手寫成「插畫式描繪」蓋掉生圖階段
// 的原圖放置規則（2026-08-23 記者/編輯版各出過一次附圖被忽略的案例）。
function uploadedAsisCount() {
    return state.userRefImages.filter(ref => ref.purpose === 'asis').length;
}

// 十點封面左右上傳位：單張，超過大小自動壓縮（與參考圖同一套）。
async function handleCoverAsisSelected(side, input) {
    const file = (input.files || [])[0];
    input.value = '';
    if (!file) return;
    try {
        let dataUrl;
        if (file.size <= REF_MAX_BYTES) {
            dataUrl = await new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result);
                reader.onerror = () => reject(new Error('圖片讀取失敗'));
                reader.readAsDataURL(file);
            });
        } else {
            dataUrl = await compressImageFile(file, REF_MAX_BYTES);
            if (dataUrlByteLength(dataUrl) > REF_MAX_BYTES) return showToast(`「${file.name}」壓縮後仍過大，請換一張較小的圖`);
            showToast(`「${file.name}」已自動壓縮上傳`);
        }
        state.coverAsis[side] = { dataUrl, name: file.name };
    } catch (err) {
        return showToast(`「${file.name}」讀取失敗：${err.message}`);
    }
    renderCoverAsis();
}

function clearCoverAsis(side) {
    state.coverAsis[side] = null;
    renderCoverAsis();
}

function renderCoverAsis() {
    for (const [side, cap] of [['left', 'Left'], ['right', 'Right']]) {
        const ref = state.coverAsis[side];
        const preview = document.getElementById(`coverAsis${cap}Preview`);
        const hint = document.getElementById(`coverAsis${cap}Hint`);
        if (!preview) continue;
        preview.classList.toggle('hidden', !ref);
        preview.classList.toggle('flex', !!ref);
        if (hint) hint.textContent = ref ? '這格直接用附圖' : '沒圖＝這格由 AI 生底圖';
        if (ref) {
            document.getElementById(`coverAsis${cap}Img`).src = ref.dataUrl;
            document.getElementById(`coverAsis${cap}Name`).textContent = ref.name;
        }
    }
}

function coverAsisSlots() {
    return { left: !!state.coverAsis.left, right: !!state.coverAsis.right };
}

/* ============================================================
   ③ 追加指令修改既有圖（/api/images/refine）
   一律送置框前原圖（refineSource），成品只拿來顯示與下載——
   把成品餵回去會二次拉伸（6.4% → 13.2% → 20.5% 疊上去）。
   ============================================================ */
function refineSourceFromResponse(data) {
    // 後端置框時回傳置框前原圖與其實際 MIME；未置框時成品本身就是原圖
    if (data.source_image_base64) {
        return { base64: data.source_image_base64, mimeType: data.source_mime_type || 'image/png' };
    }
    return { base64: data.image_data_base64, mimeType: data.mime_type };
}

function resetRefineState(source, display) {
    state.refineSource = source || null;
    // 顯示中的成品也記在 state（退回上一版用），不從 DOM 反解
    state.refineDisplay = display || null;
    state.refineStack = [];
    const input = document.getElementById('refineInput');
    if (input) input.value = '';
    updateRefineControls();
}

function updateRefineControls() {
    const undoBtn = document.getElementById('refineUndoBtn');
    if (undoBtn) undoBtn.disabled = state.refineStack.length === 0;
    const btn = document.getElementById('refineBtn');
    if (btn) btn.disabled = !state.refineSource;
}

function showRefinedImage(data) {
    const imageUrl = `data:${data.mime_type};base64,${data.image_data_base64}`;
    const isPng = data.mime_type === 'image/png';
    document.getElementById('oneClickImage').src = imageUrl;
    const download = document.getElementById('oneClickDownload');
    download.href = imageUrl;
    download.download = downloadFileName(state.editorFormat, undefined, isPng ? 'png' : 'jpg');
    document.getElementById('oneClickLabel').innerText = data.model || 'AI Generated';
}

async function handleRefine() {
    const input = document.getElementById('refineInput');
    const instruction = input.value.trim();
    if (!instruction) return showToast('請輸入要修改的內容');
    if (!state.refineSource) return showToast('沒有可修改的圖，請先生成一張');

    const btn = document.getElementById('refineBtn');
    const btnText = document.getElementById('refineBtnText');
    const loading = document.getElementById('refineLoading');
    btn.disabled = true;
    btnText.innerText = '修改中…';
    loading.classList.remove('hidden');

    // YT 直播封面：不置框、不挖洞、固定 16:9。壓字模式改的是無文字底圖（text_free）；
    // AI 標題模式改的是含標題的模型圖，走一般 refine 規則（字要保留）。
    const isYtCover = editorFormat().inputs === 'yt_cover';
    const ytTextFree = isYtCover && state.ytCoverTitleMode !== 'ai';
    // 十點封面的 AI 版：與 YT 的 AI 標題模式同一條路——改的是含標題的模型圖，
    // 走一般 refine 規則（字要保留），不置框、不挖洞、固定 16:9。
    const isTenCover = editorFormat().inputs === 'cover' && state.tenCoverMode === 'ai';
    const isCover = isYtCover || isTenCover;
    try {
        const response = await fetch(REFINE_BACKEND_URL, {
            method: 'POST',
            headers: _apiHeaders(),
            body: JSON.stringify({
                source_image_base64: state.refineSource.base64,
                source_mime_type: state.refineSource.mimeType,
                instruction,
                provider: effectiveImageProvider(),
                aspect_ratio: isCover ? '16:9' : currentAspectRatio(),
                image_size: state.imageSize,
                safe_frame: isCover ? false : state.safeFrame,
                safe_frame_profile: state.currentRole,
                // 播出鏡面的挖空側。框由後端在**置框之後**用數學貼上，不寫進 prompt——
                // 模型會把數字當文字畫進圖裡（見 compose.py 開頭的實驗紀錄）。
                broadcast_hole: isCover ? '' : broadcastHoleForApi(),
                text_free: ytTextFree,
            }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(_apiError(data, response.status));

        // 封面兩條線：refine 只改了模型那張圖，要再走一次程式後貼才是成品。
        // 回來的 data 帶著 source_image_base64＝新的模型圖，refineSource 因此自動接上。
        const shown = isYtCover ? await recomposeYtCover(data)
            : isTenCover ? await recomposeTenCover(data)
            : data;

        // 退回上一版用：存目前這一版的置框前原圖與顯示中成品（都在 state，不碰 DOM）
        state.refineStack.push({
            source: state.refineSource,
            display: state.refineDisplay,
        });
        // 下一輪修改要用**新的**置框前原圖，不是成品
        state.refineSource = refineSourceFromResponse(shown);
        state.refineDisplay = shown;
        showRefinedImage(shown);
        // 封面的成品標籤維持版型名，不顯示內部的 recomposite 模型字串
        if (isCover) document.getElementById('oneClickLabel').innerText = editorFormat().label;
        input.value = '';
        showToast('修改完成');
    } catch (err) {
        console.error(err);
        showToast(err.message || '修改失敗，請稍後再試');
    } finally {
        btnText.innerText = '修改';
        loading.classList.add('hidden');
        updateRefineControls();
    }
}

function undoRefine() {
    const previous = state.refineStack.pop();
    if (!previous) return;
    state.refineSource = previous.source;
    state.refineDisplay = previous.display;
    showRefinedImage(previous.display);
    updateRefineControls();
    showToast('已退回上一版');
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
