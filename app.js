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
    density: 'simplified',
    // CG 美術創意 0–4（2026-09-10）。記者版與編輯各版型共用；封面那兩條拉桿是別的欄位。
    cgCreativity: 0,
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
    // D26（2026-09-26）：「延伸背景」勾選框，只在記者＋安全框 ON 生效，預設不勾
    modelExtension: false,
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
    // ② 使用者上傳的參考圖：[{dataUrl, purpose, name}]，purpose 見 REF_PURPOSES
    userRefImages: [],
    // 十點封面左右上傳位（2026-09-07；2026-09-13 起一格一份清單，與共用附圖區同一個
    // 資料形狀）：{left: [{dataUrl, purpose, name}], right: [...]}
    coverAsis: { left: [], right: [] },
    // 整點直播的一標一附圖（2026-09-10，對齊十點）。單則只用 left。
    ytAsis: { left: [], right: [] },
    // A8（2026-09-16）：切進封面版型把隱藏的安全框／蓋章開關歸零時，暫存原值，
    // 切回一般編輯版（該欄位不再隱藏）才恢復，不讓使用者的既有偏好被封面模式吃掉。
    // 只有在被歸零那一刻才會非 null（值恆為 true，因為只在原值是 true 時才會暫存），
    // 離開封面且沒有 preset 接手時用它復原，之後清空。
    coverSafeFrameStash: null,
    coverStampStash: null,
    // ③ 追加修改用：**置框前**原圖（不是顯示中的成品——成品餵回去會二次拉伸）
    // refineSource = {base64, mimeType}；refineDisplay = 顯示中成品的原始回傳；
    // refineStack 供「退回上一版」
    refineSource: null,
    refineDisplay: null,
    // 與 refineSource 同一版成品實際使用的置框／模型參數；事後重貼標籤不可讀當下 UI。
    refineParameters: null,
    restampRequestId: 0,
    // 成圖後標籤編輯器。base64 永遠是「固定元素完成、尚未貼標籤」的乾淨底圖；
    // 十點 split 的 items 同時帶左右兩枚，放手只送一次批次重貼。
    labelEditor: null,
    labelRestampRequestId: 0,
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
    // 十點 AI 整張版的標題設計感（2026-09-08）：plain＝現行排版（白黃紅逐行配色、版位固定）。
    // 2026-09-09 使用者：designed 升級成「完全解放」——配色、版位、字體、邊框、強調全給 AI。
    // 預設仍是 plain——解放後版面與配色都不可預期，要使用者自己開。
    coverTitleCreativity: 0,
    // 「標題由 AI 生成」勾選框的真值（2026-09-14 晚使用者裁決：0 級由鎖住改成開放，預設關閉）。
    // 1 級以上勾選框鎖成必勾（標題造型只有模型畫得出來），拉桿一動就重設成該級的預設值——
    // 手動勾的選擇不跨拉桿記憶，規則單純可預期。
    coverAiTitle: false,
    // YT 三版型創意拉桿（P5，2026-09-11）。後端 YtCoverRequest.creativity 同一個欄位，
    // 三個 layout（hourly／news／hot）共用這一顆值。
    ytCreativity: 0,
    // 同十點的 coverAiTitle：YT 四版型「標題由 AI 生成」勾選框的真值，0 級可勾、預設不勾。
    ytAiTitle: false,
    // YT 封面底部壓色框：2026-09-08 晚使用者裁決預設**開**（60% 半透明、第二行上緣起羽化，見 compose）。
    // 整點直播的版面沒有底帶，按鈕不顯示。
    ytBottomBand: false,   // 2026-09-11 使用者：預設改關閉
    live24Bg: 'blend',     // live24 底圖模式：full／blend／inset（2026-09-13）
    // YT 直播直標（2026-09-08 WP3）的五組開關。刻意**不**在 setEditorFormat 重置：
    // 直標是同一位導播一整場重複用的東西，換版型回來還要再選一次靠左／Logo 右上很煩。
    vstrip: {
        variant: 'normal',        // normal／original_audio／ai_translation
        titleSide: 'left',        // 直標貼哪一側
        logoCorner: 'tr',         // Logo 角落，不能跟直標同側
        sourceCorner: 'tl',       // 來源句角落（2026-09-09 起四角可選，取代 sourceFollowLogo）
        live: true,               // LIVE 章可取消
    },
    // B70／F43（2026-09-21）：程式端壓「示意圖」／「畫面來源：○○○」標籤。
    // **一組控制、兩種標籤**——該貼哪一種由後端 resolve_image_disclaimer 判（畫面上
    // 有 AI 生成的人臉就一律「示意圖」，沒有才看來源名有沒有填），前端不自己判，
    // 所以角落選擇器只有一組。
    // 值直接用後端的方位詞原文（lower_right／…），不做 tl/br 之類的對照層——多一層
    // 對照就多一個會對錯的地方，而這組值會原樣進 ImageGenerateRequest.disclaimer_corner。
    // 直標那組 vstrip.sourceCorner 是直標自己的狀態，兩者不共用。
    disclaimerCorner: 'lower_right',
    disclaimerSourceText: '',
    // ---- 變化池 seed（F0／D1，2026-09-14 使用者裁決）----
    // 三條線各存一顆：CG（第一頁一鍵生成）、十點不一樣、YT 封面。null＝還沒生過，
    // 後端會現抽一顆並在回應裡回報，前端存下來。
    //
    // 「重新生成」才遞增（bumpSeed）：普通重貼、只改文字、追加修改後重貼固定元素
    // 一律**原樣送回目前這顆**——那幾條路徑要的是同一種長相，換 seed 等於偷偷換版。
    // 使用者回報「這一組好」時，後台紀錄裡的 seed 就是撈回它的鑰匙。
    cgSeed: null,
    coverSeed: null,
    ytSeed: null,
    refineStack: []
};

/* 重新生成：把這條線的 seed 往前推一格。沒有前一顆就回 null，讓後端現抽。
   刻意不在前端亂數：後端抽、回應回報、前端只負責遞增與回送，這樣「同一顆 seed
   抽出同一種長相」只有一份實作，前後端不會各抽各的。 */
function bumpSeed(current) {
    return (typeof current === 'number') ? (current + 1) % 2147483648 : null;
}

/* 後端回報實際採用的 seed，存回對應那條線（line＝'cgSeed'／'coverSeed'／'ytSeed'）。 */
function rememberSeed(line, data) {
    if (data && typeof data.seed === 'number') state[line] = data.seed;
}

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
        label: '編輯CG',
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
        hint: '只填第一標題＝滿版一張圖；再填第二標題＝左右雙切、兩格各一個標題與附圖位。每格可放多張、每張自選用途：「原圖放置」直接上版，「AI改圖」交給 AI 照這張圖重畫一次；附圖原有可讀文字與品牌保留，不自行新增或挪用，只有編輯指令明確要求才移除；其餘當生圖參考。那格沒有原圖放置就由 AI 生底圖。標題創意 0（預設）所有文字由程式壓字、零錯字、原圖不動，生成後可按「只改文字」換標題不重生底圖（滿版、雙切都可）；拉到 1 以上才整張交給生圖模型設計。標頭帶整條由程式貼：Logo、節目標籤、日期與 ON AIR／精華都是正版檔，AI 只負責底圖與標題。',
        coverLayout: 'auto',
        inputs: 'cover',
        slots: true,   // 一標一附圖位（與 editor_formats.FORMAT_CAPABILITIES.slots 對齊，parity 測試釘住）
        coverMode: 'ai',
        // 封面沒有消化這道程序：/api/editor/cover 不收 density／stamp／safe_frame／tone，
        // 留著只會是四顆按了沒反應的按鈕，所以收起來而不是鎖起來
        locks: {},
        // 2026-09-10 使用者裁決：通用「附參考圖」那一區在十點整個收起來。它就貼在創意拉桿
        // 底下，跟第一／第二標題下面那兩顆附圖位功能重疊——同一張照片有兩個入口，而且上面
        // 兩顆有填時後端就完全不看下面那區（見 main.py editor_cover 的 slots 判定），
        // 使用者放了卻沒作用。十點的照片一律走上面那兩顆（含原圖放置）。
        hides: { digestControls: true, safeFrame: true, stamp: true, refUpload: true, disclaimer: true },
        hole: null,
    },
    // YT 直播封面：底圖來自附圖（原圖放置）或 AI，LIVE 章／日期／Logo／兩行標題全由程式疊。
    // 沿用主流程的附圖上傳區（用途：原圖放置＝直接當底圖；其他＝生圖參考）。
    yt_live_cover: {
        label: 'YT國內外新聞直播',
        hint: '標題用半形空格分兩段（分不出來時由 AI 判斷）。附圖位在標題底下，一格可放多張、每張自選用途：「原圖放置」1 張整版／2 張左右雙切／3 張三切，「AI改圖」由 AI 照這張圖重畫；附圖原有可讀文字與品牌保留，不自行新增或挪用，只有編輯指令明確要求才移除；其餘當參考。沒有原圖放置就 AI 生底圖並標示 AI示意圖。原音呈現／AI即時翻譯可勾可並存。創意 0（預設）文字與 Logo 全由程式疊、零錯字；1 以上才交 AI 畫標題。',
        inputs: 'yt_cover',
        ytLayout: 'news',
        slots: true,   // 2026-09-14 對齊整點：一標一附圖位，共用「附參考圖」區收起來
        locks: {},
        hides: { digestControls: true, safeFrame: true, stamp: true, refUpload: true, disclaimer: true },
        hole: null,
    },
    // YT 直播直標（2026-09-08 WP3）：不是封面，是疊在直播訊號上的透明底 PNG。
    // 2026-09-09 使用者：下拉往上移一格排在「國內外新聞直播」後面，標籤加全形減號前綴。
    // 沒有底圖就沒有生圖、沒有附圖、沒有引擎、沒有「只改文字」與追加修改，
    // 所以 hides 收得比封面更多（連引擎與指令欄都收）。
    yt_vstrip: {
        label: '－YT直播直標',
        hint: '直播用的垂直標題條，透明底 PNG，直接疊在直播訊號上。第一標題最多 12 格、第二標題最多 14 格（連續英數字算一格）。不生圖、不打 AI。',
        inputs: 'yt_vstrip',
        locks: {},
        hides: { digestControls: true, safeFrame: true, stamp: true, engine: true, instruction: true, refUpload: true, refine: true, disclaimer: true },
        hole: null,
    },
    // YT 整點直播：同一條底圖流程，版面換成整點版（Logo 左上、LIVE 章右上＋選填整點時間、
    // 紅底日期、沒有副標）。
    yt_hourly_cover: {
        label: 'YT整點直播',
        hint: '整點直播封面：標題半形空格分兩段，整點時間（如 20:00）選填、有填才出現。第二標題填了就是「雙則」：上白＝第一則、下黃＝第二則，每行一整句不拆、最多 18 字，底圖左右兩張羽化拼成一張。附圖跟十點一樣一標一格：每個標題底下各有自己的附圖位，一格可放多張、每張自選用途（原圖放置直接上版、AI改圖由 AI 照這張圖重畫；附圖原有可讀文字與品牌保留，不自行新增或挪用，只有編輯指令明確要求才移除；其餘當參考）；那格沒有原圖放置就由 AI 生底圖。',
        inputs: 'yt_cover',
        ytLayout: 'hourly',
        slots: true,   // 一標一附圖位（與後端能力矩陣對齊）
        locks: {},
        // 2026-09-10：整點改成一標一附圖（對齊十點），共用「附參考圖」那一區整個收起來。
        // 2026-09-14：國內外新聞直播與今日熱搜也跟上——當初怕一標一圖砍掉 2 張雙切／3 張三切，
        // 但 2026-09-13 起單則附圖位的整份清單會併進共用清單，切格那條路照走，顧慮不成立。
        hides: { digestControls: true, safeFrame: true, stamp: true, refUpload: true, disclaimer: true },
        hole: null,
    },
    // YT 24H LIVE（2026-09-13）：整點的鏡像——Logo 兩層版在右上、24H LIVE 角標在左上、
    // 標題一行深紅斜體。角標是定版的生成素材，程式只在它的玻璃板上壓日期。
    yt_live24_cover: {
        label: 'YT24H LIVE',
        hint: '24H LIVE 封面：標題只有一行（不拆段），深紅斜體、全形上限約 17 字。日期格式 YYYY.MM.DD。創意 0 標題與日期由程式壓字（零錯字），1 以上交 AI 畫。附圖位兩格：只放一格＝滿版，兩格都放＝左右雙切羽化拼接。',
        inputs: 'yt_cover',
        ytLayout: 'live24',
        slots: true,   // 一標一附圖位（與後端能力矩陣對齊）
        locks: {},
        // 同整點：一標一附圖，共用「附參考圖」那一區整個收起來，免得有兩個入口
        hides: { digestControls: true, safeFrame: true, stamp: true, refUpload: true, disclaimer: true },
        hole: null,
    },
    // YT 今日熱搜（2026-09-06 型錄 H 類）：紅色系「今日熱搜」標籤＋紅色 Logo 斜標，
    // 議題型版面，沒有日期、沒有 LIVE。底圖與標題規則同國內外新聞直播。
    yt_hot_cover: {
        label: 'YT今日熱搜',
        hint: '今日熱搜封面：標題半形空格分兩段，沒有日期與 LIVE。附圖位與底圖規則同國內外新聞直播（一格可放多張：原圖放置 1 整版／2 雙切／3 三切，AI改圖 重畫；附圖原有可讀文字與品牌保留，不自行新增或挪用，只有編輯指令明確要求才移除；其餘當參考）。',
        inputs: 'yt_cover',
        ytLayout: 'hot',
        slots: true,   // 2026-09-14 對齊整點：一標一附圖位
        locks: {},
        hides: { digestControls: true, safeFrame: true, stamp: true, refUpload: true, disclaimer: true },
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
    const layout = editorFormat().ytLayout || '';
    // live24 只有一行標題，判不了「有沒有第二標題」；改看底圖模式（2026-09-13 使用者裁決）
    if (layout === 'live24') return state.live24Bg === 'full' ? 'single' : 'dual';
    if (layout !== 'hourly') return 'single';
    return (document.getElementById('ytCoverTitleSecond')?.value || '').trim() ? 'dual' : 'single';
}

// live24 的底圖模式下拉：切到滿版時右格要收起來，免得填了卻不生效
function onLive24BgChange(select) {
    state.live24Bg = select.value;
    updateYtAsisSlots();
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

/* 消化程度六檔。key 與後端 DigestDensity 一致，改這裡要同步改 main.py */
const DENSITY_LABELS = {
    no_text: '無字',      // 2026-09-14 D14：六段拉桿最左端，整張圖一個字都不出現
    verbatim: '不改字',   // 2026-09-07 使用者裁決：UI 顯示改「不改字」，key 與後端 verbatim 不動
    minimal: '字極少',    // 2026-09-10 五段拉桿新增
    simplified: '字少',
    standard: '字多',
    maximum: '字超多',    // 2026-09-10 五段拉桿新增
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
    // 創意拉桿共用元件（P5）：容器在 index.html 裡只是空殼，先灌好 DOM，
    // 才輪得到後面 resetToType／renderEditorFormats 觸發的 update 函式去找
    // range／label 元素——順序反過來會找不到元素，update 函式會靜默 no-op。
    renderCreativityBar('cgCreativityBar', {
        pairs: CG_CREATIVITY,
        rangeId: 'cgCreativityRange', labelId: 'cgCreativityLabel',
        wrapperClass: 'flex items-center gap-2 bg-black/40 px-2 py-1.5 rounded-lg',
        rangeClass: 'flex-1 accent-violet-500 cursor-pointer',
        endLabelClass: 'text-[9px] font-black text-slate-500',
        currentLabelClass: 'text-[10px] font-black text-violet-300 w-12 text-right',
        oninput: 'setCgCreativity',
        title: '0＝現行成品；愈往右，版面排法愈放（分區→英雄區→破格→斜切傾斜），美術處理也跟著加重。重點的數量、安全留白與字句不受影響；不會拿真實地圖當主視覺。',
    });
    renderCreativityBar('coverTitleStyleBar', {
        pairs: COVER_TITLE_CREATIVITY,
        rangeId: 'coverTitleStyleRange', labelId: 'coverTitleStyleLabel',
        leading: '標題創意',
        wrapperClass: 'hidden flex items-center gap-2',
        rangeClass: 'w-24 accent-violet-500 cursor-pointer',
        endLabelClass: 'text-[9px] font-black text-slate-500',
        currentLabelClass: 'text-[9px] font-black text-violet-300',
        oninput: 'setCoverTitleCreativity',
        title: '最左＝白／黃／紅逐行配色、版位固定；愈往右愈放給 AI 設計（字句永遠一字不改）',
        // 2026-09-11 使用者裁決：右端刻度改「最狂」。搬家前手寫的 HTML 寫的是
        // 「奔放」（等級 3 的名字），但拉桿實際拉得到等級 4，刻度與行為對不上。
        // 拿掉 maxLabel 覆寫後就照 pairs 最後一格，跟另外兩條拉桿一致。
    });
    renderCreativityBar('ytCreativityBar', {
        pairs: YT_CREATIVITY,
        rangeId: 'ytCreativityRange', labelId: 'ytCreativityLabel',
        leading: 'YT創意',
        wrapperClass: 'hidden flex items-center gap-2',
        rangeClass: 'w-24 accent-violet-500 cursor-pointer',
        endLabelClass: 'text-[9px] font-black text-slate-500',
        currentLabelClass: 'text-[9px] font-black text-violet-300',
        oninput: 'setYtCreativity',
        title: '最左＝現行成品、版位固定；愈往右愈放給 AI 設計（塊高、字級落差、配色、配件都跟著加重，字句永遠一字不改）',
    });
    renderChartTypes();
    renderDigestTypes();
    resetToType('data');
    updateAIBtnRoleHint();
    syncEngineSizeButtons();
    syncModelExtensionControl();
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
    updateDigestDensityBar();
    updateCgCreativityBar();
    wireDownloadNames();
    switchPage(1);
};

/* ============================================================
   頁面切換（第一頁 快速生成 / 第二頁 進階微調 / 第三頁 混合版型）
   Final Prompt Output 面板為共用單一實例，切頁時搬到當前頁的掛載點，
   避免重複 id 造成 getElementById 取到錯誤的節點。
   第三頁不走 Prompt 流程，沒有 outputMount-3，面板會留在隱藏的前頁裡
   ============================================================ */
// 2026-09-15 使用者裁決：建構中的分頁一律不讓使用者進去。分頁鈕在 index.html 加了 hidden，
// 這裡再擋一次——舊書籤、殘留的 onclick 或 console 呼叫都可能繞過藏起來的按鈕。
// 要開放回來：清空這個集合，並拿掉 index.html 那兩個 hidden。
const DISABLED_PAGES = new Set([2, 3]);

function switchPage(page) {
    if (DISABLED_PAGES.has(page)) {
        showToast('這個功能還在建構中');
        page = 1;
    }
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
    syncModelExtensionControl();
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

    // A8（2026-09-16 使用者裁決）：五個封面版型把安全框／蓋章開關藏起來，但殘值
    // 不會因為切版型而消失——之前留在 state 裡的值會被 handleRefine／
    // handleImageGeneration 當成使用者「現在」的選擇偷渡進請求。開關看不見就必須
    // 一起歸零，不能讓使用者無從得知也無從更正的殘值送進後端；切回非封面（該欄位
    // 重新可見）才恢復使用者原本的偏好，presets 明確指定該版型值時 presets 優先。
    if (hides.safeFrame) {
        if (state.safeFrame) {
            state.coverSafeFrameStash = true;
            toggleSafeFrame();
        }
    } else if (state.coverSafeFrameStash) {
        state.coverSafeFrameStash = null;
        if (typeof presets.safeFrame !== 'boolean' && !state.safeFrame) toggleSafeFrame();
    }
    if (hides.stamp) {
        if (state.stamp) {
            state.coverStampStash = true;
            toggleStamp();
        }
    } else if (state.coverStampStash) {
        state.coverStampStash = null;
        if (typeof presets.stamp !== 'boolean' && !state.stamp) toggleStamp();
    }

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
    syncModelExtensionControl();
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
    updateYtCreativityBar();
    if (yt) yt.classList.toggle('hidden', !wantsYt);
    if (vstrip) vstrip.classList.toggle('hidden', !wantsVstrip);
    updateVstripButtons();
    // B70／F43：封面版型自己有 _draw_ai_note，不吃這組設定，換版型時要跟著收／放
    updateDisclaimerControls();
    // 附圖位只有整點有，換到別的版型要收起來——updateYtLayoutIndicator 只在整點時才跑到底，
    // 靠它收不掉（2026-09-10）
    updateYtAsisSlots();
    // 附圖上傳區：主流程、YT 直播封面、十點不一樣（2026-09-06 起收原圖放置）都用。
    // 封面版型時把它搬到該組欄位下面——留在原位會跑到角色鈕正下方，看起來像消失了。
    // 直標沒有底圖也沒有生圖，附圖無處可去，整區收起來（hides.refUpload）。
    if (refBox) {
        refBox.classList.toggle('hidden', !!(editorFormat().hides || {}).refUpload);
        // 國內外新聞直播與今日熱搜的原圖放置是「張數決定版面」，說明要寫明白，
        // 否則使用者不知道多放一張會變成雙切（2026-09-10）。
        const refHint = document.getElementById('refUploadHint');
        if (refHint) {
            refHint.textContent = ['news', 'hot'].includes(editorFormat().ytLayout || '')
                ? '原圖放置／AI改圖／實景參考／肖像照片／地圖底稿，單張 ≤1.5MB。原圖放置依張數決定版面：1 張整版、2 張左右雙切、3 張三切、4 張四切，順序就是由左到右'
                : '原圖放置／AI改圖／實景參考／肖像照片／地圖底稿，單張 ≤1.5MB，最多 4 張';
        }
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
    const next = EDITOR_FORMATS[key] ? key : EDITOR_FORMAT_DEFAULT;
    const changed = next !== state.editorFormat;
    state.editorFormat = next;
    // 換版型就清空十點與 YT 的附圖位（2026-09-14 使用者裁決，第八輪 U8：以前附圖位 DOM 四個
    // YT 版型共用，切到別的版型再切回來兩張圖與「AI改圖」鎖定原樣殘留）。標題欄不清。
    // 只在真的換了版型時清——重按同一個版型不能把剛上傳的圖洗掉。
    if (changed) {
        clearCoverAsis('left');
        clearCoverAsis('right');
        clearYtAsis('left');
        clearYtAsis('right');
        // B107（2026-09-26）：切到任何 YT 封面版型都回到可預期的預設值；
        // applyEditorFormatInputs 會呼叫 updateYtCreativityBar，把拉桿與勾選框同步畫回。
        if ((EDITOR_FORMATS[next] || {}).inputs === 'yt_cover') {
            state.ytCreativity = 0;
            state.ytAiTitle = false;
        }
    }
    // 換版型就把挖空方向重置回左：還記著上一個版型選的右切，只會讓人選錯邊
    state.holeSide = 'left';
    // 換版型就丟掉上一版的壓字前底圖：滿版的底圖送進雙切會被後端擋（400），留著只會誤導。
    // 只在這裡清——applyEditorFormatInputs 換角色也會走，放那邊會把還能用的底圖洗掉。
    state.tenCoverBackground = null;
    // 換版型也丟掉上一版 YT 封面的 refine 來源：不清的話切到整點後「只改文字」會對著
    // 一張國內外版的底圖亮起來（審查建議 2026-09-08）。
    state.refineSource = null;
    state.refineDisplay = null;
    state.refineParameters = null;
    state.restampRequestId += 1;
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

// 拉桿的左→右順序。左端是「不改字」——它不是「字更少」，是逐字複製（輸出長度＝
// 輸入長度，貼長稿反而比字多還長）。2026-09-09 使用者知情裁決：三檔仍放同一條拉桿。
// 2026-09-14 D14：最左端再加「無字」。兩個極端（無字／不改字）被推到拉桿兩頭，
// 不會擠在同一側被選錯——這就是使用者裁決要解決的事。預設仍是字少。
const DENSITY_ORDER = ['no_text', 'verbatim', 'minimal', 'simplified', 'standard', 'maximum'];

function updateDigestDensityBar() {
    const range = document.getElementById('digestDensityRange');
    if (range) range.value = String(Math.max(0, DENSITY_ORDER.indexOf(state.digestDensity)));
    const label = document.getElementById('digestDensityLabel');
    if (label) label.innerText = DENSITY_LABELS[state.digestDensity] || state.digestDensity;
}

/* ============================================================
   創意拉桿共用元件（P5，2026-09-11，見 docs/plan-20260911-創意拉桿模組化.md）
   三處拉桿（CG／十點不一樣／YT）原本各在 index.html 手寫一段幾乎一樣的
   「端點標籤 + range + 目前等級標籤」HTML，只差要不要一顆「XX創意」的
   leading 標籤、外框有沒有底色與內距、range 寬度。這裡抽成一個 render
   函式：index.html 只留一個空殼容器（例如 <div id="cgCreativityBar">），
   由這支函式依 opts 把 innerHTML 灌進去，三處呼叫一次即可。

   刻意不順手把三份 `[名稱, 說明]` 陣列（CG_CREATIVITY／COVER_TITLE_CREATIVITY／
   YT_CREATIVITY）也合併：那是 P2 已經裁決的分工——名稱共用（各陣列第一個
   元素理應逐字相同，靠 tests/test_creativity_module_20260911.py 的
   LevelNamesParityTests 釘住），說明文字是每支拉桿專屬的實際行為描述，
   合併等於把三段不同的行為描述串成一份誰都不精準的話。render 函式因此
   直接吃某一支拉桿自己的 pairs 陣列，只取端點與初始值需要的部分，不重寫
   陣列本身。

   行為不變：render 只建立 DOM 與初始值／初始標籤文字，每支拉桿原有的
   update 函式（updateCgCreativityBar 等）照樣用同一批 id 找元素、照樣
   自己管 value／label／hidden——這裡不接手那些邏輯，只是把原本手寫在
   index.html 裡的那幾行 HTML 換成程式生成。
   ============================================================ */
function renderCreativityBar(containerId, opts) {
    const el = document.getElementById(containerId);
    if (!el) return;
    const {
        pairs, rangeId, labelId, oninput, title = '', leading = '',
        wrapperClass, rangeClass, endLabelClass, currentLabelClass,
        // 十點那條拉桿原本手寫的右端刻度文字寫的是「奔放」（等級 3 的名字），
        // 不是等級 4 的「最狂」——沿用既有的兩份手寫 HTML 才發現這個落差，
        // 但這次重構只搬 HTML、不改使用者看得到的字，所以留一個可覆寫的
        // maxLabel，各呼叫端不給就照 pairs 最後一格的名字（CG／YT 兩條本來
        // 就跟 pairs[-1] 一致，不必覆寫）。
        maxLabel = pairs[pairs.length - 1][0],
    } = opts;
    el.className = wrapperClass;
    if (title) el.title = title;
    el.innerHTML =
        (leading ? `<span class="text-[9px] font-black text-slate-500 uppercase tracking-[0.16em]">${leading}</span>` : '')
        + `<span class="${endLabelClass}">${pairs[0][0]}</span>`
        + `<input id="${rangeId}" type="range" min="0" max="4" step="1" value="0" class="${rangeClass}" oninput="${oninput}(this.value)" />`
        + `<span class="${endLabelClass}">${maxLabel}</span>`
        + `<span id="${labelId}" class="${currentLabelClass}">${pairs[0][0]}</span>`;
}

// CG 美術創意 0–4（2026-09-10 使用者要求：播出鏡面與記者版也要）。
// 2026-09-10 改成結構性槓桿：形容詞會被圖模平均掉，所以調的是版面怎麼排
// （分區、英雄區、破格、傾斜、字級落差），不是加幾層描邊（見 main.py 的 _CG_L1–_CG_L4_EXTRA）。
// 不歸它管的只有：字句、重點的數量、安全留白，以及「不准拿真實地圖當主視覺」。
const CG_CREATIVITY = [
    ['規矩', '現行成品，完全不加設計指示'],
    ['微設計', '畫面分成一個主視覺區與一個文字區，收邊做乾淨'],
    ['有設計', '再加：挑一個英雄元素獨佔一區，卡片統一形狀語言'],
    ['奔放', '再加：破格排列、去背主體越出卡片、字級落差拉大'],
    ['最狂', '再加：斜切分割、英雄破自己的框、標題必須微傾斜'],
];

function updateCgCreativityBar() {
    const range = document.getElementById('cgCreativityRange');
    if (range) range.value = String(state.cgCreativity);
    const label = document.getElementById('cgCreativityLabel');
    if (label) label.innerText = CG_CREATIVITY[state.cgCreativity][0];
}

function setCgCreativity(value) {
    const level = Math.min(4, Math.max(0, parseInt(value, 10) || 0));
    state.cgCreativity = level;
    updateCgCreativityBar();
    showToast('CG 創意 ' + level + '　' + CG_CREATIVITY[level][0] + '：' + CG_CREATIVITY[level][1]);
}

function setDigestDensityLevel(value) {
    const index = Math.min(DENSITY_ORDER.length - 1, Math.max(0, parseInt(value, 10) || 0));
    switchDigestDensity(DENSITY_ORDER[index]);
}

function switchDigestDensity(density) {
    state.digestDensity = density;
    state.density = density;
    updateDigestDensityBar();
    updateAIBtnRoleHint();
    const label = DENSITY_LABELS[density] || density;
    showToast(density === 'verbatim'
        ? '已切換至「不改字」：貼上的內文一字不改，AI 只做版面'
        : density === 'no_text'
        ? '已切換至「無字」：整張圖不出現任何文字，標題與說明請自己加'
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
    // F42：階段切換記一筆到訊息歷史當進度時間軸，不記每 250ms 的百分比 tick——
    // 那樣只會洗版，看不出「現在到底在做什麼」。
    logMessage(`${_genStage.label}…`, 'info');
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
        logMessage('生成完成', 'success');
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
    syncModelExtensionControl();
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
                + (active ? 'border border-red-600 bg-red-600 text-white'
                          : 'border border-red-600 text-slate-500 hover:text-white');
        });
    }
    if (isCover) applyCoverLayoutFields();
    // 版型（滿版↔雙切）一變，附圖位的「半版鎖原圖放置」也要跟著重算
    if (typeof renderCoverAsis === 'function') renderCoverAsis();
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
            + (active ? 'border border-red-600 bg-red-600 text-white'
                      : 'border border-red-600 text-slate-500 hover:text-white');
    });
    updateYtAsisSlots();
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
    if (leftBtn) leftBtn.textContent = fullLayout ? '📁 ＋ 附圖（選填）' : '📁 ＋ 第一附圖（選填）';
    // 「只改文字」滿版、雙切都有（雙切 2026-09-14 補上：後端把拼好的兩格底圖帶回來）。
    // 底圖是哪個版面生的就只能用在那個版面——打了第二標題版面就換了，鈕跟著灰掉。
    const recompose = document.getElementById('coverRecomposeBtn');
    if (recompose) {
        recompose.classList.remove('hidden');
        const bg = state.tenCoverBackground;
        recompose.disabled = !(bg && bg.layout === coverLayoutNow());
        recompose.title = bg && bg.layout !== coverLayoutNow()
            ? '版面變了（滿版↔雙切），上一次的底圖對不上，請重新生成'
            : '程式壓字版專用（滿版、雙切都可）：底圖不重生，只用新的標題／日期／標籤重壓文字';
    }
}

// 十點封面「標題創意」拉桿（2026-09-08 ON/OFF → 2026-09-09 改成 0–4 五段，仿 AI effort 那條）。
// 只有十點版型＋AI 整張模式看得到：合成版的字是程式用 Pillow 壓的，這條拉桿對它沒有意義。
const COVER_TITLE_CREATIVITY = [
    ['規矩', '白／黃／紅逐行配色，版位固定（現行排版）'],
    ['微設計', '字體、描邊、材質放開；配色、大小、版位不動'],
    ['有設計', '整組節目美術字（大小落差、關鍵詞壓框、飽和平塗），版位仍固定'],
    ['奔放', '再加：版位自由、可掛小圖示'],
    ['最狂', '再加：更大落差、多層描邊立體、傾斜錯落、爆裂裝飾（字句永遠一字不改）'],
];

function updateCoverTitleStyleButton() {
    const bar = document.getElementById('coverTitleStyleBar');
    if (!bar) return;
    // 2026-09-14 使用者裁決：創意 0 標題預設程式壓字、1 級起由 AI 畫。拉桿是主開關，所以它
    // 永遠露出，不再被勾選框藏起來。同日晚放寬：0 級的勾選框**可以勾**（預設不勾），使用者
    // 明點就交 AI 畫（錯字／原圖漂移的風險自己承擔）；1 級以上仍鎖成必勾。
    // 注意這支每次切版型／重繪都會跑，所以勾選框只能從 state.coverAiTitle 畫回去——
    // 寫死 `= creativity >= 1` 會把使用者剛勾的選擇洗掉。後端同一條規則（title_mode_for_creativity）。
    const hidden = editorFormat().inputs !== 'cover';
    bar.className = (hidden ? 'hidden ' : '') + 'flex items-center gap-2';
    const aiBox = document.getElementById('coverAiTitle');
    if (aiBox) {
        aiBox.disabled = state.coverTitleCreativity >= 1;
        aiBox.checked = state.coverAiTitle;
    }
    const range = document.getElementById('coverTitleStyleRange');
    if (range) range.value = String(state.coverTitleCreativity);
    const label = document.getElementById('coverTitleStyleLabel');
    if (label) label.innerText = COVER_TITLE_CREATIVITY[state.coverTitleCreativity][0];
    // 側邊標籤與畫面小籤只有 3 級起才畫得出來（後端同一條線），所以前台也只有 3 級起才露。
    // 2026-09-10 先藏是因為功能還在測；2026-09-11 使用者裁決兩個一起打開。
    const chipsOn = !hidden && state.coverTitleCreativity >= 3;
    ['coverSideLabels', 'coverInfoChips'].forEach(function (id) {
        const el = document.getElementById(id);
        if (el) el.classList.toggle('hidden', !chipsOn);
    });
}

function setCoverTitleCreativity(value) {
    const level = Math.min(4, Math.max(0, parseInt(value, 10) || 0));
    state.coverTitleCreativity = level;
    state.coverAiTitle = level >= 1;   // 拉桿一動就回該級的預設（0＝關、1 以上＝開）
    updateCoverTitleStyleButton();
    showToast('標題創意 ' + level + '　' + COVER_TITLE_CREATIVITY[level][0]
        + '：' + COVER_TITLE_CREATIVITY[level][1]);
}

function setCoverAiTitle(on) {
    // 只有創意 0 叫得動（1 級以上勾選框是 disabled）。明點 AI＝使用者要 0 級的 AI 標題。
    state.coverAiTitle = !!on;
    updateCoverTitleStyleButton();
    showToast(state.coverAiTitle
        ? '標題交給 AI 畫（創意 0 的規矩排版，但可能出錯字、原圖那格會被重畫）'
        : '標題由程式壓字（零錯字、原圖零漂移）');
}

// YT 三版型（整點／國內外新聞直播／今日熱搜）「創意」拉桿（P5，2026-09-11）。
// 後端 YtCoverRequest.creativity 四級早就做好了（見 main.py／editor_formats.py
// 的 yt_design_brief／yt_layout_rules／yt_fixed_block／yt_title_top），前端
// 卻一直沒有拉桿可按——這裡補上，照搬十點那條拉桿的做法，數字取自
// editor_formats.YT_BRIEF_SPECS（塊高 26/31/36/41%）與 _YT_STYLE_CLAUSES，
// 不是憑感覺寫的說明。三個 layout 共用同一顆 state.ytCreativity 與同一支
// 拉桿——後端 yt_design_brief 本來就是三個版型共用同一份邏輯，只是 layout
// 參數不同，拉桿沒有理由分開。
const YT_CREATIVITY = [
    ['規矩', '現行成品：兩行同大小、白／黃固定配色、版位固定；整點日期牌由程式畫死'],
    ['微設計', '標題塊拉到約 26% 畫面高，兩行仍同大小；改用材質字面（漸層／斜角／光澤），兩塊板統一收邊；整點日期牌改交給 AI 畫（連數字都是它畫的）'],
    ['有設計', '再加：塊高約 31%，字級落差 1.8 倍、兩行錯位、換字體、配色開到三色，掛 1 件無字配件'],
    ['奔放', '再加：塊高約 36%，字級落差 2.5 倍，標題塊可疊進照片主體邊緣，掛 2 件無字配件'],
    ['最狂', '再加：塊高約 41%，字級落差 3 倍，整段傾斜 5–8 度、配色全開，掛 3 件配件並加一道爆裂裝飾（字句永遠一字不改）'],
];

function updateYtCreativityBar() {
    // 只有 YT 封面版型（hourly／news／hot）的 AI 整張模式看得到：
    // - 版型要先卡對：YT 直播直標（inputs === 'yt_vstrip'）沒有創意階梯這回事，
    //   不能靠「祖先容器剛好也藏起來」這種巧合擋掉——十點那支 updateCoverTitleStyleButton
    //   有明寫 `editorFormat().inputs !== 'cover'`，這支原本漏了同一條，2026-09-11
    //   驗收時被抓到（面板結構一動就會漏出來），補上跟十點對稱的檢查。
    // - composite 模式標題由程式壓字，creativity 這條線只影響 _yt_cover_full_image
    //   （AI 整張），對程式壓字沒有作用——跟十點的 coverTitleStyleBar 同一個理由
    //   （見 updateCoverTitleStyleButton）。
    // 2026-09-14 使用者裁決：創意 0 標題預設程式壓字、1 級起由 AI 畫；同日晚放寬成 0 級可勾、
    // 預設不勾（與十點的 updateCoverTitleStyleButton 同一套，勾選框一律從 state 畫回去）。
    const hidden = editorFormat().inputs !== 'yt_cover';
    const bar = document.getElementById('ytCreativityBar');
    if (bar) bar.classList.toggle('hidden', hidden);
    const aiBox = document.getElementById('ytCoverAiTitle');
    if (aiBox) {
        aiBox.disabled = state.ytCreativity >= 1;
        aiBox.checked = state.ytAiTitle;
    }
    const range = document.getElementById('ytCreativityRange');
    if (range) range.value = String(state.ytCreativity);
    const label = document.getElementById('ytCreativityLabel');
    if (label) label.innerText = YT_CREATIVITY[state.ytCreativity][0];
}

function setYtAiTitle(on) {
    // 只有創意 0 叫得動（1 級以上 disabled）；語意與十點的 setCoverAiTitle 相同。
    state.ytAiTitle = !!on;
    updateYtCreativityBar();
    showToast(state.ytAiTitle
        ? '標題交給 AI 畫（創意 0 的規矩排版，但可能出錯字、原圖那格會被重畫）'
        : '標題由程式壓字（零錯字、原圖零漂移）');
}

function setYtCreativity(value) {
    const level = Math.min(4, Math.max(0, parseInt(value, 10) || 0));
    state.ytCreativity = level;
    state.ytAiTitle = level >= 1;   // 同十點：拉桿一動就回該級的預設
    updateYtCreativityBar();
    showToast('YT 創意 ' + level + '　' + YT_CREATIVITY[level][0] + '：' + YT_CREATIVITY[level][1]);
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

// B110：版面挖空不等於白色壓框；播出鏡面永遠把方向送到生圖端。
function broadcastLayoutHoleForApi() {
    if (!editorFormat().hole) return '';
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

// D26（2026-09-26 使用者裁決）：記者＋安全框 ON 才有「延伸背景」勾選框。
// 三個條件缺一就當沒勾，勾選狀態本身保留（切回記者 ON 時還在）。
function modelExtensionActive() {
    return !!state.modelExtension && state.safeFrame && state.currentRole === '記者';
}

function frameStrategyForApi() {
    return modelExtensionActive() ? 'model_extension' : '';
}

function toggleModelExtension(checked) {
    state.modelExtension = !!checked;
    syncModelExtensionControl();
    updateAspectBadge();
    syncOutput();
    showToast(state.modelExtension
        ? '延伸背景：模型把背景畫到四邊、字縮在安全框內（2K）；字若超出安全框會跳警告，由你決定用或重生'
        : '延伸背景：關閉');
}

function syncModelExtensionControl() {
    const row = document.getElementById('p1-extensionRow');
    if (!row) return;
    const formatHidesSafeFrame = !!((editorFormat() || {}).hides || {}).safeFrame;
    const visible = state.currentRole === '記者' && state.safeFrame && !formatHidesSafeFrame;
    row.classList.toggle('hidden', !visible);
    const box = document.getElementById('p1-chkExtension');
    if (box) box.checked = !!state.modelExtension;
}

function currentAspectRatio() {
    // D26：延伸背景的圖就是交付物，要直接生 16:9（後端一律 2K）
    if (modelExtensionActive()) return DEFAULT_ASPECT_RATIO;
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
    } else if (modelExtensionActive()) {
        text = `${currentAspectRatio()} → 延伸背景 2560×1440（字出框會警告）`;
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
        aspectRatio: currentAspectRatio(),
        noText: state.digestDensity === 'no_text',
        modelExtension: modelExtensionActive(),
        holeSide: broadcastLayoutHoleForApi(),
    });
    updatePromptCounter();
}

// 無字檔（2026-09-14 D14／F20）的生圖端覆蓋。與 news_prompt.NO_TEXT_IMAGE_OVERRIDE
// 逐字相同（test_prompt_parity 守著）：網頁版在前端組 prompt、LINE／整合端在後端組，
// 只改一邊不會有任何執行期錯誤，只會讓兩條路徑悄悄出不一樣的圖。
const NO_TEXT_IMAGE_OVERRIDE =
`
==================================================
NO TEXT AT ALL (OVERRIDES EVERY EARLIER RULE ABOUT RENDERING WORDS)
==================================================
- The user asked for a picture with no writing on it. Render NO text of any kind: no headline, no label, no caption, no legend, no axis value, no date, no place name, no source line, no badge, no logo, no watermark, no signature — not a single letter or digit anywhere in the frame.
- VARIABLE FIELDS is empty on purpose. Every earlier instruction about rendering the words, figures or markers supplied there does not apply, and any placeholder standing in for those fields is not something to draw.
- Everything else still binds in full: the reserved margin, likeness and scene fidelity, the use of any attached references, and the ban on inventing content.
- The empty area where a headline would have gone is the correct result. Do not fill it with words.`;

// D26（2026-09-26）延伸背景模式的生圖端覆蓋。與 news_prompt.MODEL_EXTENSION_IMAGE_OVERRIDE
// 逐字相同（test_prompt_parity 守著）。接在 body 後面、不寫進樣板字串，理由同無字檔。
const MODEL_EXTENSION_IMAGE_OVERRIDE =
`
==================================================
EXTENDED BACKGROUND SAFE LAYOUT (OVERRIDES EVERY EARLIER RULE ABOUT MARGINS, CANVAS USE AND TITLE POSITION)
==================================================
- The background artwork is ONE continuous illustrated scene that extends naturally all the way to the four edges of the canvas.
- The outer border area is a background-only perimeter: it must be filled with continuing scenery, texture, lighting, atmosphere or visual motifs from the same scene. It must never become a blank, solid-colour, flat-gradient or letterboxed border.
- Treat every headline, word, number, card, chart, icon, subject cutout, badge and banner as ONE foreground group, and keep that entire foreground group inside the central content region, clear of the perimeter on every side, with the widest clearance along the bottom.
- Background scenery may run behind the foreground group and out into the perimeter; foreground information may not enter the perimeter.
- Place the main title at the top of the foreground group, not at the top edge of the canvas.
- Any closing banner or bottom line is the lowest element of the foreground group and stays well above the deeper background-only area at the bottom.
- Do NOT render any frame, rectangle, outline, border line, guide line, crop mark or dimmed band to mark where the central region ends.`;

const BROADCAST_HOLE_LAYOUT_RULES_TEMPLATE = `==================================================
BROADCAST VIDEO HOLE — {hole_side_upper} VIDEO ZONE IS BACKGROUND-ONLY (CRITICAL OVERRIDE)
==================================================
- The video zone is a 16:9 area on the {hole_side} side of the frame, filling roughly the {hole_side} half of the space between the headline at the top and the bottom band. Post-production will place live video there.
- Inside the video zone: background ONLY. The same full-frame scene continues naturally through it; do not leave it blank and do not draw a white box, frame, guide or placeholder there.
- No attached image, generated subject, text, number, card, chart, logo, badge or callout may enter or overlap the video zone.
- The headline at the top and the bottom band may still span the full width as the layout requires; they stay above and below the video zone, never inside it.
- Every other content element goes in the {content_side} half between the headline and the bottom band. Every attached PLACE AS-IS image MUST appear there, clearly visible and unaltered — as the main picture of that half or inside a card. Never omit it and never move it into the video zone.
- This applies whether the software white alignment frame is ON or OFF. It OVERRIDES any earlier instruction to make an attached image full-frame, extend or crop it across the canvas, or place content on the {hole_side} side.`;

function broadcastHoleLayoutRules(side) {
    if (side !== 'left' && side !== 'right') return '';
    return BROADCAST_HOLE_LAYOUT_RULES_TEMPLATE
        .replaceAll('{hole_side_upper}', side.toUpperCase())
        .replaceAll('{hole_side}', side)
        .replaceAll('{content_side}', side === 'left' ? 'right' : 'left');
}

function buildPrompt({ role, engine, typeLabel, style, structure, variable, safeFrame = false, aspectRatio = '16:9', noText = false, modelExtension = false, holeSide = '' }) {
    // 共用的正文區塊（style / structure / variable）
    const textRules = role === '編輯' ? EDITOR_TEXT_RULES : REPORTER_TEXT_RULES;
    // D26 延伸背景：模型的圖就是交付物，版面走「中央內容」那條（跟安全框 OFF 同組），
    // 再在最後接 MODEL_EXTENSION_IMAGE_OVERRIDE。只有記者會進來（modelExtensionActive）。
    if (modelExtension) safeFrame = false;
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

    // 無字檔的覆蓋接在 body 後面，**刻意不寫進上面那段樣板字串裡**：
    // tests/test_content_fidelity 的雙來源比對是用正規表示式從 app.js 原始碼抓
    // 「FINAL OUTPUT RULE 到樣板結尾」那一段，跟 news_prompt 逐字比對。在樣板裡
    // 插一個 ${...} 會讓抓到的字面多出那段程式碼、比對就永遠對不起來。
    let fullBody = noText ? `${body}\n${NO_TEXT_IMAGE_OVERRIDE}` : body;
    if (modelExtension) fullBody = `${fullBody}\n${MODEL_EXTENSION_IMAGE_OVERRIDE}`;
    const holeRules = broadcastHoleLayoutRules(holeSide);
    if (holeRules) fullBody = `${fullBody}\n\n${holeRules}`;

    // 依引擎切換開頭語法
    if (engine === 'gpt') {
        return `Generate an image: a professional international TV news infographic (${typeLabel}) for broadcast and digital editorial use. Follow the specification below exactly. Do not redesign or reinterpret the layout logic. Current Operating Context: ${role} Workflow.

${fullBody}`;
    }
    // gemini（預設）
    return `Create a professional international TV news infographic (${typeLabel}) designed for broadcast and digital editorial use.
The output must strictly follow the style, structure, and data logic defined below.
Do not redesign, reinterpret, or alter the layout logic.
Current Operating Context: ${role} Workflow.

${fullBody}`;
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

/* AI-edit reference rules are injected by the backend when aiedit references
   reach /api/images/generate. Keep these frontend mirrors in lockstep so the
   web prompt vocabulary and backend prompt vocabulary cannot drift. The
   final-image baseline remains backend-owned and is deliberately not mirrored. */
const USER_REFERENCE_AIEDIT_RULES = `==================================================
ATTACHED IMAGE — REDRAW THIS SAME PICTURE (CRITICAL)
==================================================
- One of the attached images is the picture this graphic's main visual is to BE. Re-draw that same picture in the graphic's own visual style: the same subject, the same framing, the same camera angle, the same arrangement of what is near and far.
- This is NOT a loose style reference. Someone who saw the attached image must recognise your output as the same moment redrawn, not as a different picture of a similar topic. Except where an editor's instruction below asks for a change, do not substitute another scene, another angle, another action or another setting for it.
- Do redraw it: repaint, restyle and colour-grade it into this graphic's illustration style, and extend or crop the edges as the layout needs. Apart from whatever an editor's instruction below asks you to change, the treatment changes and the content does not.
- PRESERVE-EXISTING: Text already present in the attached reference image is requested content — keep it as supplied. Preserve every readable word, number and existing brand mark already present in the image; do not erase it, rewrite it, replace it with fake text, garbled text or altered branding.
- DO-NOT-INVENT OR REUSE: Do not add any text or brand that is not already present in the attached reference image or explicitly requested elsewhere in this prompt. Do not move, copy or reuse text or brand marks from the attached reference image onto a different object.
- EXPLICIT-REMOVAL ONLY: Remove existing text or brand marks only when the editor's instruction explicitly asks for that specific text or mark to be removed; otherwise preserve them.
- People in the attached image stay who they are: reproduce every face in it as it appears, recognisable, in the redrawn style. The NAMED REAL PERSON rules below govern only people who are NOT in the attached image — they do not restrict, blur, hide or replace a face that the editor supplied here.
- If an attached image already contains on-air chrome (a date stamp, LIVE or 24H LIVE badge, channel logo, or a 示意圖 / AI示意圖 label), do not draw another copy of those marks.`;

const USER_REFERENCE_AIEDIT_FUSION_RULES_TEMPLATE = `==================================================
ATTACHED IMAGES — FUSE ALL {count} OF THEM INTO ONE PICTURE (CRITICAL)
==================================================
- {count} attached images together ARE the picture this graphic's main visual is to BE. Compose them into ONE coherent scene redrawn in the graphic's own visual style. Every one of the {count} images must be recognisably present in the output — its subject, its key objects and its people — none may be dropped, merged away or reduced to a vague background hint. Someone who saw all {count} images must be able to point to each of them inside your output.
- Give each image its own clear share of the frame — side by side, foreground and background, or a natural blend — keeping each image's subject, framing and camera angle recognisable. Do not pick one image and discard the rest; a picture that shows only some of the {count} images is wrong.
- Do redraw them: repaint, restyle and colour-grade them into this graphic's illustration style, and extend or crop the edges as the layout needs. Apart from whatever an editor's instruction below asks you to change, the treatment changes and the content does not.
- PRESERVE-EXISTING: Text already present in any attached reference image is requested content for that image — keep it as supplied. Preserve every readable word, number and existing brand mark already present in each image; do not erase it, rewrite it, replace it with fake text, garbled text or altered branding.
- DO-NOT-INVENT OR REUSE: Do not add any text or brand that is not already present in an attached reference image or explicitly requested elsewhere in this prompt. In a fusion, do not move, copy or reuse text or brand marks from one attached image onto an object from another attached image.
- EXPLICIT-REMOVAL ONLY: Remove existing text or brand marks only when the editor's instruction explicitly asks for that specific text or mark to be removed; otherwise preserve them.
- People in the attached images stay who they are: reproduce every face in every attached image as it appears, recognisable, in the redrawn style. The NAMED REAL PERSON rules below govern only people who are NOT in the attached images — they do not restrict, blur, hide or replace a face that the editor supplied here.
- If an attached image already contains on-air chrome (a date stamp, LIVE or 24H LIVE badge, channel logo, or a 示意圖 / AI示意圖 label), do not draw another copy of those marks.`;

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
// F47（2026-09-22）：事後把「示意圖」／「畫面來源」標籤改貼到另一個角落，不重生圖
const RESTAMP_BACKEND_URL = `${API_BASE}/api/images/restamp-disclaimer`;

// 後端有給 detail 時直接照用（那是後端刻意寫給人看的訊息）；
// 只有 fallback（例如 524 這種被 Cloudflare 邊緣層直接攔掉、後端來不及回應的情況）
// 才需要把狀態碼翻成使用者看得懂、且知道「下一步該做什麼」的中文。
// context: 這個函式被 12 個呼叫點共用（消化／生圖／封面／改圖…），「縮短新聞、降字數拉桿」
// 這個建議只對「消化新聞」那一步成立——生圖、改圖、封面都不吃新聞稿或字數拉桿，硬套同一句
// 會給錯的下一步（B38 驗收時發現）。只有 _digestFetch 傳 'digest'，其餘呼叫點走中性版本。
function _apiError(data, status, context) {
    const detail = data && data.detail;
    if (typeof detail === "string") return detail;
    if (status === 408 || status === 504 || status === 524) {
        return context === "digest"
            ? `新聞太長，消化超過時間上限。建議縮短新聞內容，或把字數拉桿降一階再試（HTTP ${status}）`
            : `處理超過時間上限，請稍後再試（HTTP ${status}）`;
    }
    if (status === 502 || status === 503) {
        return `AI 服務暫時忙碌或無回應，請稍後再試（HTTP ${status}）`;
    }
    if (status === 429) {
        return `請求太頻繁，請稍等一下再試（HTTP ${status}）`;
    }
    if (status === 401 || status === 403) {
        return `登入可能已過期，請重新整理頁面後再登入（HTTP ${status}）`;
    }
    return `生成失敗（HTTP ${status}），請稍後再試`;
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

/* 前端這一側的保險絲（2026-09-10 線上事故，2026-09-15 B39 改寫語意）：
   /api/generate 現在是串流＋心跳（後端每 5~10 秒送一行 ping），正常情況下連線
   會一直有位元組流動、不會被公司 Cloudflare 的 proxy timeout（約 100~120 秒）
   當成靜默連線掐斷。這條逾時不再是「等後端訊息」的保險——那件事交給心跳處理
   ——而是「整趟串流真的卡死超過這個時間」的最後一道防線（例如背景執行緒本身
   卡住、心跳都送不出來），所以維持一個遠大於正常耗時的寬鬆上限即可。 */
const DIGEST_FETCH_TIMEOUT_MS = 290_000;

async function digestNewsText(input) {
    // CG 線沒有獨立的「重新生成」鈕——再按一次一鍵生成就是重生，所以遞增放這裡。
    // 第一次是 null，遞增後仍是 null，由後端現抽並在回應裡回報（見 rememberSeed）。
    state.cgSeed = bumpSeed(state.cgSeed);
    const abort = new AbortController();
    const fuse = setTimeout(() => abort.abort(), DIGEST_FETCH_TIMEOUT_MS);
    let response;
    try {
        response = await _digestFetch(input, abort.signal);
    } catch (err) {
        if (err.name === 'AbortError') {
            throw new Error('消化超過 5 分鐘沒有回應，已中止。請縮短新聞內容或稍後再試');
        }
        throw err;
    } finally {
        clearTimeout(fuse);
    }
    return response;
}

// B39（2026-09-15）：/api/generate 改成 NDJSON 串流＋心跳，一行一個 JSON 物件——
// {"type":"ping"} 處理期間陸續送、{"type":"result",...} 或 {"type":"error",...}
// 是最後一行。⚠ 一旦開始串流，HTTP 狀態碼就定死是 200，成敗只能看這裡讀到的
// 內容判斷，不能看 response.ok（那只反映「有沒有開始串流」，例如驗證失敗會在
// 串流開始前就回真正的狀態碼，此時 response.ok 仍然有意義，見下面第一段判斷）。
async function _digestFetch(input, signal) {
    const response = await fetch(AI_BACKEND_URL, {
        method: "POST",
        signal,
        headers: _apiHeaders(),
        body: JSON.stringify({
            news_text: input,
            type_label: digestTypeLabelForApi(),
            role: state.currentRole,
            density: state.digestDensity,
            visual_creativity: state.cgCreativity,
            seed: state.cgSeed,
            stamp: state.stamp,
            tone: state.tone,
            editor_format: state.editorFormat,
            // 挖空側要在消化階段就講清楚（2026-09-08 WP1）：內容得趕到影片那半邊的
            // 對面，只在生圖端決定的話，重點會剛好被影片蓋掉。
            hole_side: state.holeSide,
            safe_frame: state.safeFrame,
            frame_strategy: frameStrategyForApi(),
            user_instruction: currentUserInstruction(),
            portrait_photo_count: uploadedPortraitCount(),
            asis_reference_count: uploadedAsisCount(),
        }),
    });
    // 驗證／請求格式錯誤等會在串流開始前就被擋下（X-API-Key、Pydantic 驗證），
    // 這時狀態碼還沒定死，照舊看 status 判斷。
    if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(_apiError(data, response.status, "digest"));
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
        let chunk;
        try {
            chunk = await reader.read();
        } catch (err) {
            if (err.name === "AbortError") throw err;
            throw new Error("消化連線中途中斷，請稍後再試");
        }
        if (chunk.done) break;
        buffer += decoder.decode(chunk.value, { stream: true });
        let newlineIdx;
        while ((newlineIdx = buffer.indexOf("\n")) >= 0) {
            const line = buffer.slice(0, newlineIdx).trim();
            buffer = buffer.slice(newlineIdx + 1);
            if (!line) continue;
            let msg;
            try {
                msg = JSON.parse(line);
            } catch (err) {
                throw new Error("消化回應格式異常，請稍後再試");
            }
            if (msg.type === "ping") continue;   // 只是活著訊號，忽略
            if (msg.type === "result") {
                delete msg.type;   // 只是這一層的信封，往上不該看到
                return msg;
            }
            if (msg.type === "error") {
                throw new Error(_apiError({ detail: msg.detail }, msg.status, "digest"));
            }
        }
    }
    throw new Error("消化連線中途中斷，尚未收到結果，請稍後再試");
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
    rememberSeed('cgSeed', data);
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
        // B53：後端消化用新聞原文，原樣送出，不摘要、不截斷、不抽人名。
        news_text: document.getElementById('coverNewsText')?.value || '',
        date_text: val('coverDate'),
        badge: document.getElementById('coverBadge')?.value || 'on_air',
        title_creativity: state.coverTitleCreativity,
        // 側邊標籤（2026-09-10）：使用者自己打的短詞，後端原樣畫成一排小籤
        side_labels: val('coverSideLabels'),
        info_chips: val('coverInfoChips'),
        source_left: val('coverSourceLeft'),
        source_right: fullLayout ? '' : val('coverSourceRight'),
        provider: effectiveImageProvider(),
        // 重貼固定元素／只改文字：原樣送回目前這顆，長相不准變（遞增只在重生那條路徑）
        seed: state.coverSeed,
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

// 只改文字（2026-09-08 滿版；2026-09-14 雙切也有）：底圖不重生，用目前欄位重壓一次標題，零 API。
// 底圖走 state.tenCoverBackground，不是 refineSource——見該欄位的註解。
// 記下它是哪個版面生的：滿版底圖是整圖、雙切底圖是拼好的兩格，混用會壓錯版，後端也會 400。
function setTenCoverBackground(data) {
    const usable = data.mode === 'composite' && !!data.background_image_base64;
    state.tenCoverBackground = usable ? {
        base64: data.background_image_base64,
        mimeType: data.background_mime_type || 'image/png',
        isAi: !!data.background_is_ai,
        rightIsAi: !!data.right_is_ai,
        layout: coverLayoutNow(),
    } : null;
    applyCoverLayoutFields();
}

async function recomposeTenCoverText() {
    const background = state.tenCoverBackground;
    if (!background) throw new Error('還沒有底圖，請先生成一次');
    if (background.layout !== coverLayoutNow()) throw new Error('版面變了（滿版↔雙切），請重新生成');
    const res = await fetch(COVER_BACKEND_URL, {
        method: 'POST',
        headers: _apiHeaders(),
        body: JSON.stringify({
            ...tenCoverFields(),
            mode: 'composite',
            background_image_base64: background.base64,
            background_mime_type: background.mimeType,
            background_is_ai: background.isAi,
            background_right_is_ai: background.rightIsAi,
            background_layout: background.layout,
        }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(_apiError(data, res.status));
    return data;
}

// 十點不一樣封面：使用者直接給兩個標題，中間沒有消化這一段，所以走自己的端點。
// 下拉、產出區、下載都還在同一頁同一個位置，編輯不用切分頁。
// recomposeOnly=true：合成版（滿版／雙切）的「只改文字」，底圖不重生（比照 handleYtCoverGenerate）。
async function handleTenCoverGenerate(recomposeOnly = false) {
    clearGenerateBannerForNewRequest();
    const val = id => (document.getElementById(id)?.value || '').trim();
    const titleLeft = val('coverTitleLeft');
    const titleRight = val('coverTitleRight');
    const fullLayout = coverLayoutNow() === 'full';
    if (!titleLeft) return showToast('第一標題要填');
    // 只改文字只有合成版有（AI 版的字是模型畫的）；底圖要跟現在的版面同一種
    if (recomposeOnly && !state.tenCoverBackground) return showToast('還沒有底圖，請先生成一次');
    if (recomposeOnly && state.tenCoverBackground.layout !== coverLayoutNow()) {
        return showToast('版面變了（滿版↔雙切），請重新生成');
    }

    const btn = document.getElementById('aiBtn');
    const loading = document.getElementById('aiLoading');
    btn.disabled = true;
    loading.classList.remove('hidden');
    let completed = false;
    let generationParameters = null;
    try {
        let data;
        if (recomposeOnly) {
            showToast('用現有底圖重壓文字…');
            data = await recomposeTenCoverText();
        } else {
            // 真正重生這一條路徑才遞增 seed（只改文字／重貼固定元素走上面那半邊，不動）
            state.coverSeed = bumpSeed(state.coverSeed);
            const slots = coverAsisSlots();
            if (fullLayout) slots.right = false;   // 滿版只有一個附圖位
            const slotCount = (slots.left ? 1 : 0) + (slots.right ? 1 : 0);
            const asisCount = slotCount || uploadedAsisCount();
            // 2026-09-14 使用者裁決：拉桿決定預設（0＝程式壓字，1 級起交 AI 畫標題，原圖放置那格
            // 跟著整張重畫、接受漂移）；同日晚放寬後 0 級的勾選框可以自己打開，所以讀的是
            // 勾選框的真值 state.coverAiTitle（拉桿一動它就回該級的預設，見 setCoverTitleCreativity）。
            const composite = !state.coverAiTitle;
            const anySlotImage = state.coverAsis.left.length > 0 || (!fullLayout && state.coverAsis.right.length > 0);
            const deriving = true;   // 畫面描述欄移除後一律由 AI 推導（2026-09-08 WP1）
            showToast(!composite && (asisCount > 0 || anySlotImage)
                    ? (fullLayout && slots.left ? '原圖鋪滿後交給 AI 畫標題，約 30–90 秒…'
                                                : '附圖先各自處理、拼好底圖後交給 AI 畫標題（兩段），約 60–150 秒…')
                : fullLayout ? (slots.left ? '附圖鋪滿，合成中…' : (composite ? '生成底圖中，約 30–90 秒…' : '設計封面中，約 30–120 秒…'))
                : slots.left && slots.right ? '兩格都用附圖，合成中…'
                : slots.left ? '左格用附圖，右格生底圖中，約 30–90 秒…'
                : slots.right ? '右格用附圖，左格生底圖中，約 30–90 秒…'
                : asisCount >= 2 ? '兩格都用附圖，合成中…'
                : asisCount === 1 ? '單張附圖整版鋪滿，合成中…'
                : composite
                    ? '生成左右底圖中，兩張平行跑，約 60–120 秒…'
                    : (deriving ? 'AI 補畫面描述後開始設計封面，約 40–140 秒…' : '設計封面中，約 30–120 秒…'));
            // 兩段生圖（附圖＋AI 標題）＝一輪平行的格底圖＋一張整張，預算約 180 秒（2026-09-13）
            const twoStage = !composite && (asisCount > 0 || anySlotImage);
            beginGenerationProgress('image', twoStage ? 2.4 : asisCount >= 2 ? 0.3 : slotCount === 1 ? 1.0 : asisCount === 1 ? 0.3 : (composite ? 1.6 : 1.3));
            // 請求送出前固定成品參數，避免等待期間的 UI 變更污染追加修改。
            generationParameters = refineParametersFromState();
            const res = await fetch(COVER_BACKEND_URL, {
                method: 'POST',
                headers: _apiHeaders(),
                body: JSON.stringify({
                    title_left: titleLeft,
                    title_right: fullLayout ? '' : titleRight,
                    layout: fullLayout ? 'full' : 'split',
                    instruction: coverInstructionForApi(),
                    // B53：原樣送新聞原文給封面補畫面描述，不摘要、不截斷、不抽人名。
                    news_text: document.getElementById('coverNewsText')?.value || '',
                    date_text: val('coverDate'),
                    badge: document.getElementById('coverBadge')?.value || 'on_air',
                    title_creativity: state.coverTitleCreativity,
                    seed: state.coverSeed,
                    mode: composite ? 'composite' : 'ai',
                    provider: effectiveImageProvider(),
                    // 十點把通用附圖區整個收起來（hides.refUpload），照片一律走上面那兩顆
                    // 附圖位。那一區殘留的圖不能偷偷跟著送出去，否則使用者看不到卻會影響成圖。
                    reference_images: (editorFormat().hides || {}).refUpload ? [] : userRefImagesPayload(),
                    slot_left: slotPayload(state.coverAsis.left),
                    slot_right: fullLayout ? [] : slotPayload(state.coverAsis.right),
                    source_left: val('coverSourceLeft'),
                    source_right: fullLayout ? '' : val('coverSourceRight'),
                }),
            });
            data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(_apiError(data, res.status));
        }

        rememberSeed('coverSeed', data);
        const imageUrl = `data:${data.mime_type};base64,${data.image_data_base64}`;
        document.getElementById('oneClickImage').src = imageUrl;
        setupFreeLabelEditor(data, 'oneClickImage');
        const download = document.getElementById('oneClickDownload');
        download.href = imageUrl;
        download.download = downloadFileName(state.editorFormat);
        download.innerText = '下載 PNG';
        // 追加修改只在 AI 版適用（2026-09-07）：AI 版的源圖是後貼 Logo 前的模型原圖，
        // 改完再走一次後貼就是新成品。合成版的成品是程式用 Pillow 拼的，沒有可以餵回
        // 生圖模型的原圖——把拼好的成品餵回去，模型會把 Logo 與標題一起重畫。
        state.tenCoverMode = data.mode || 'ai';
        const tenCoverSource = data.mode === 'ai' ? refineSourceFromResponse(data) : null;
        resetRefineState(tenCoverSource, tenCoverSource ? data : null, generationParameters);
        // 滿版合成版：把壓字前底圖記下來，「只改文字」才有東西可以帶回去（零 API 重壓）
        setTenCoverBackground(data);
        document.getElementById('oneClickLabel').innerText = editorFormat().label;
        document.getElementById('oneClickMeta').innerText = fullLayout ? titleLeft : `${titleLeft}｜${titleRight}`;
        document.getElementById('oneClickEmpty').classList.add('hidden');
        document.getElementById('oneClickResult').classList.remove('hidden');
        showGenerateNoticeBanner(data.notices);
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
            // 兩個籤也一起回填（2026-09-11）：消化讀的是編輯貼進來的內文，
            // 回填後編輯看得到、改得動、清得掉，按生成之前都在人手上。
            ['coverSideLabels', 'coverInfoChips'].forEach(function (id) {
                const el = document.getElementById(id);
                if (!el) return;
                el.value = (id === 'coverSideLabels' ? data.side_labels : data.info_chips) || '';
            });
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

// 直標的自動消化（2026-09-09 使用者）：貼一段文字 → 兩段標題＋判定來源。
// 與封面那條分開，因為回填的是三個欄位（含來源）、而且不動版面指示器；共用的是
// 同一個後端端點（target=yt_vstrip）。一樣不接生圖：編輯看過再自己按。
async function handleVstripTitleDigest() {
    const newsText = (document.getElementById('vstripNewsText')?.value || '').trim();
    if (newsText.length < 10) return showToast('先貼一段文字（至少 10 個字）');
    const btn = document.getElementById('vstripDigestBtn');
    if (btn) btn.disabled = true;
    try {
        showToast('AI 消化標題中，約 10–30 秒…');
        const res = await fetch(COVER_TITLES_BACKEND_URL, {
            method: 'POST',
            headers: _apiHeaders(),
            body: JSON.stringify({ news_text: newsText, target: 'yt_vstrip' }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) throw new Error(_apiError(data, res.status));
        document.getElementById('vstripTitle').value = data.title || '';
        document.getElementById('vstripTitleSecond').value = data.title_second || '';
        // 來源判不出來時後端回空字串——不要覆蓋掉編輯已經自己填好的那一欄
        const source = (data.source_text || '').trim();
        const sourceInput = document.getElementById('vstripSource');
        if (source) sourceInput.value = source;
        // 格數提示與來源角落那一列都吃這三個欄位，回填完要重算
        onVstripInput();
        showToast(source
            ? '標題與來源已回填，看過沒問題再按「生成」'
            : '標題已回填（判不出畫面來源，請自己填），看過沒問題再按「生成」');
    } catch (err) {
        showToast(`消化標題失敗：${err.message}`);
    } finally {
        if (btn) btn.disabled = false;
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
        // 2026-09-14：拉桿決定預設（0＝程式壓字），0 級的勾選框可以自己打開，所以讀真值
        title_mode: state.ytAiTitle ? 'ai' : 'composite',
        original_audio: layout === 'news' && !!document.getElementById('ytCoverOriginalAudio')?.checked,
        ai_translation: layout === 'news' && !!document.getElementById('ytCoverAiTranslation')?.checked,
        date_text: val('ytCoverDate'),
        time_text: layout === 'hourly' ? val('ytCoverTime') : '',
        bottom_band: layout !== 'hourly' && state.ytBottomBand,
        // live24 的底圖模式（2026-09-13）：其他版型帶了後端也忽略，照送不影響
        live24_bg: state.live24Bg,
        // 創意拉桿（P5，2026-09-11）：三個版型共用同一顆值，後端依 layout 各自套用。
        creativity: state.ytCreativity,
        // 一標一附圖（2026-09-10，對齊十點）：只有整點有；其餘版型送空字串，
        // 後端就會走原本的 reference_images 原圖放置清單（1 張整版／2 張雙切／3 張三切）
        slot_left: ytUsesAsisSlots() ? slotPayload(state.ytAsis.left) : [],
        slot_right: ytUsesAsisSlots() && ytLayoutNow() === 'dual' ? slotPayload(state.ytAsis.right) : [],
        // 指令欄（2026-09-08 WP1）：餵給底圖推導當畫面提示
        instruction: coverInstructionForApi(),
        // B53：後端消化用新聞原文，原樣送出，不摘要、不截斷、不抽人名。
        news_text: document.getElementById('ytCoverNewsText')?.value || '',
        // 只改文字／重貼固定元素也走這支，所以這裡一律送目前這顆；遞增只在重生那條路徑
        seed: state.ytSeed,
        source_text: val('ytCoverSource'),
    };
}

// 用既有底圖重疊文字（追加修改後、或只改標題／副標／日期）。
// background 從 refineSource 來——那格語意就是「給改圖用的原圖」，這條線上它是無文字底圖。
async function recomposeYtCover(refined, backgroundIsAi = state.ytCoverBackgroundIsAi) {
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
            // refine 是 AI 修改；handleRefine 會明送 true。單純「只改文字」仍沿用
            // 後端上一輪算出的 provenance（B107，2026-09-26）。
            background_is_ai: backgroundIsAi,
        }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(_apiError(data, res.status));
    return data;
}

function showYtCoverResult(data, fields, generationParameters) {
    const imageUrl = `data:${data.mime_type};base64,${data.image_data_base64}`;
    document.getElementById('oneClickImage').src = imageUrl;
    setupFreeLabelEditor(data, 'oneClickImage');
    const download = document.getElementById('oneClickDownload');
    download.href = imageUrl;
    download.download = downloadFileName(state.editorFormat, fields.title);
    download.innerText = '下載 PNG';
    state.ytCoverBackgroundIsAi = !!data.background_is_ai;
    state.ytCoverTitleMode = data.title_mode || 'ai';
    // 追加修改：以無文字底圖為源，改完由 handleRefine 再疊一次文字。
    // 雙則的底圖是左右兩張羽化拼好的那一張，這裡沒有分別。
    resetRefineState(refineSourceFromResponse(data), data, generationParameters);
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
    clearGenerateBannerForNewRequest();
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
    // 只改文字沿用原底圖參數；真正重生會在 fetch 前覆蓋成當次快照。
    let generationParameters = state.refineParameters ? {...state.refineParameters} : null;
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
            // 附圖（共用區的原圖放置、或附圖位裡任何圖）＋AI 標題＝兩段生圖（2026-09-13）
            const slotImages = (fields.slot_left || []).length + (fields.slot_right || []).length;
            const twoStage = aiTitle && (asis || slotImages > 0);
            showToast(twoStage ? '附圖先處理成底圖，再交給 AI 畫標題（兩段），約 60–180 秒…'
                : aiTitle ? 'AI 整張生成（含標題），約 30–120 秒…'
                : asis ? '用附圖當底圖，合成中…' : 'AI 生底圖後合成，約 30–120 秒…');
            beginGenerationProgress('image', twoStage ? 2.4 : (asis && !aiTitle) ? 0.3 : 1.3);
            generationParameters = refineParametersFromState();
            const res = await fetch(YT_COVER_BACKEND_URL, {
                method: 'POST',
                headers: _apiHeaders(),
                body: JSON.stringify({
                    ...fields,
                    // fields 帶的是目前這顆；真正重生要遞增，所以在這裡覆蓋掉
                    seed: (state.ytSeed = bumpSeed(state.ytSeed)),
                    provider: effectiveImageProvider(),
                    image_size: state.imageSize,
                    // 整點把共用附圖區收起來（hides.refUpload），那裡殘留的圖不能偷偷送出去
                    reference_images: (editorFormat().hides || {}).refUpload ? [] : userRefImagesPayload(),
                }),
            });
            data = await res.json().catch(() => ({}));
            if (!res.ok) throw new Error(_apiError(data, res.status));
        }
        rememberSeed('ytSeed', data);
        showYtCoverResult(data, fields, generationParameters);
        showGenerateNoticeBanner(data.notices);
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

// ---- B70／F43：示意圖／畫面來源標籤（2026-09-21）----
// 值是後端方位詞原文，四個角都在安全區內（compose._disclaimer_box 釘住）。
const DISCLAIMER_CORNER_LABELS = {
    upper_left: '左上', lower_left: '左下', upper_right: '右上', lower_right: '右下',
    lower_center: '正下方',  // F48（2026-09-26）：安全框下緣置中
};

function setDisclaimerCorner(corner) {
    if (!DISCLAIMER_CORNER_LABELS[corner]) return;
    state.disclaimerCorner = corner;
    updateDisclaimerControls();
    // F47（2026-09-22 使用者要求）：已經有成品的話立刻把標籤挪過去，不用重生一張。
    // 貼標籤全程是 Pillow，一次生圖 API 都不打（見後端 /api/images/restamp-disclaimer）。
    restampDisclaimer();
}

// F47：把標籤改貼到另一個角落。沒有成品、或那張成品根本沒貼標籤就什麼都不做
// ——後者不是錯誤，是「這次本來就沒有標籤可以挪」。
async function restampDisclaimer() {
    const applied = appliedDisclaimer();
    if (!applied.kind || !state.refineSource) return;
    // 封面版型的標籤是 compose 自己畫的（版位綁在角標上），不吃這組設定
    if ((editorFormat().hides || {}).disclaimer) return;
    const requestId = ++state.restampRequestId;
    const corner = state.disclaimerCorner;
    const params = state.refineParameters || refineParametersFromState(state.refineDisplay);
    try {
        const response = await fetch(RESTAMP_BACKEND_URL, {
            method: 'POST',
            headers: _apiHeaders(),
            body: JSON.stringify({
                source_image_base64: state.refineSource.base64,
                source_mime_type: state.refineSource.mimeType,
                model: params.model,
                provider: params.provider,
                aspect_ratio: params.aspect_ratio,
                image_size: params.image_size,
                // 少了這格會把一張 2K 成品悄悄重算成 1K（同 B84）
                density: params.density,
                safe_frame: params.safe_frame,
                frame_strategy: params.frame_strategy || '',
                safe_frame_profile: params.safe_frame_profile,
                broadcast_hole: broadcastHoleForApi(),
                disclaimer_kind: applied.kind,
                disclaimer_source_text: applied.sourceText,
                disclaimer_corner: corner,
            }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(_apiError(data, response.status));
        if (requestId !== state.restampRequestId) return;
        // 只換顯示中的成品；refineSource 是置框前原圖，標籤不在上面，不必動
        state.refineDisplay = data;
        showRefinedImage(data);
        showToast(`標籤已移到${DISCLAIMER_CORNER_LABELS[corner]}`);
    } catch (err) {
        if (requestId !== state.restampRequestId) return;
        showToast(`標籤移位失敗：${err.message}`);
    }
}

/* 成圖後自由放置（桌機滑鼠）：拖曳期間只動虛線框，pointerup 才送一筆 Pillow 重貼。
   種類／來源文字在手機仍可用；pointerType=touch 不啟動拖曳。 */
function currentFreeLabelTarget() {
    const inputs = editorFormat().inputs;
    if (inputs === 'cover') return 'ten_cover';
    if (inputs === 'yt_cover') return `yt_${editorFormat().ytLayout || 'news'}`;
    if (inputs === 'yt_vstrip') return 'yt_vstrip';
    return editorFormat().hole ? 'broadcast' : 'cg';
}

function currentFreeLabelContext() {
    const target = currentFreeLabelTarget();
    if (target === 'yt_vstrip') return vstripFields();
    if (target.startsWith('yt_')) {
        const fields = ytCoverFields();
        return {
            original_audio: fields.original_audio,
            ai_translation: fields.ai_translation,
            draw_date: !(fields.layout === 'hourly' && fields.creativity >= 1 && fields.title_mode === 'ai'),
        };
    }
    if (target === 'broadcast') return {hole_side: broadcastLayoutHoleForApi()};
    return {};
}

function _defaultFreeLabelItem(data) {
    const kind = data.disclaimer_kind || '';
    return {
        id: 'global', side: 'global', kind,
        source_text: data.disclaimer_source_text || '',
        provenance_kind: data.disclaimer_provenance_kind || kind,
        manual_override: !!data.disclaimer_manual_override,
        position: data.disclaimer_position || {x: 0.82, y: 0.82},
        bbox: data.disclaimer_bbox || [],
    };
}

function setupFreeLabelEditor(data, imageId) {
    if (!data?.disclaimer_base_image_base64) {
        if (state.labelEditor?.imageId === imageId) state.labelEditor = null;
        renderFreeLabelEditor();
        return;
    }
    const items = Array.isArray(data.disclaimer_items) && data.disclaimer_items.length
        ? data.disclaimer_items.map(item => ({...item, position: item.position || {x: 0.82, y: 0.18}}))
        : [_defaultFreeLabelItem(data)];
    state.labelEditor = {
        imageId,
        target: currentFreeLabelTarget(),
        context: currentFreeLabelContext(),
        base64: data.disclaimer_base_image_base64,
        model: data.model || '',
        items,
        safeRect: data.disclaimer_safe_rect || [],
        obstacles: data.disclaimer_obstacles || [],
        canvasWidth: 1920,
        canvasHeight: 1080,
    };
    const image = document.getElementById(imageId);
    const syncSize = () => {
        if (image.naturalWidth && image.naturalHeight && state.labelEditor?.imageId === imageId) {
            state.labelEditor.canvasWidth = image.naturalWidth;
            state.labelEditor.canvasHeight = image.naturalHeight;
            renderFreeLabelEditor();
        }
    };
    image.addEventListener('load', syncSize, {once: true});
    syncSize();
    renderFreeLabelEditor();
}

function _freeLabelBoxRatio(item, editor) {
    const bbox = item.bbox || [];
    if (bbox.length === 4 && editor.canvasWidth && editor.canvasHeight) {
        return {w: (bbox[2] - bbox[0]) / editor.canvasWidth,
                h: (bbox[3] - bbox[1]) / editor.canvasHeight};
    }
    const text = item.kind === 'source' ? (item.source_text || '畫面來源') : 'AI示意圖';
    // bbox 尚未由後端回來（剛切種類／改字）時採保守估寬，讓前端先夾位與擋碰撞；
    // 後端仍會用實際字型量一次，作最後一道 400 守門。
    const maxWidth = editor.target === 'ten_cover' ? 0.45
        : (editor.target.startsWith('yt_') ? 0.56 : 0.90);
    // Pillow 的 3% 是相對「畫布高度」，不是寬度；舊公式直接拿 0.03 當寬度比例，
    // 16:9 上會放大約 1.78 倍，正是拖曳框明顯比成品寬的原因。
    const heightToWidth = editor.canvasHeight / editor.canvasWidth;
    const sizeRatio = editor.target.startsWith('yt_') && editor.target !== 'yt_vstrip' ? 0.032 : 0.03;
    const padRatio = editor.target === 'yt_vstrip' ? 0
        : (editor.target.startsWith('yt_') ? 24 / editor.canvasWidth : 0.024 * heightToWidth);
    const width = Array.from(text).length * sizeRatio * heightToWidth + padRatio;
    const height = editor.target === 'yt_vstrip' ? 0.039 : 0.048;
    return {w: Math.min(maxWidth, Math.max(0.04, width)), h: height};
}

function _freeLabelBounds(item, editor) {
    const safe = editor.safeRect.length === 4
        ? editor.safeRect : [0, 0, editor.canvasWidth, editor.canvasHeight];
    let [x0, y0, x1, y1] = safe.map((v, i) => v / (i % 2 === 0 ? editor.canvasWidth : editor.canvasHeight));
    if (editor.target === 'ten_cover' && item.side === 'left') x1 = Math.min(x1, 0.5);
    if (editor.target === 'ten_cover' && item.side === 'right') x0 = Math.max(x0, 0.5);
    return {x0, y0, x1, y1};
}

function _clampFreeLabelPosition(item, editor, position) {
    const size = _freeLabelBoxRatio(item, editor);
    const bounds = _freeLabelBounds(item, editor);
    return {
        x: Math.max(bounds.x0 + size.w / 2, Math.min(bounds.x1 - size.w / 2, position.x)),
        y: Math.max(bounds.y0 + size.h / 2, Math.min(bounds.y1 - size.h / 2, position.y)),
    };
}

function _freeLabelCollision(item, editor, position) {
    const size = _freeLabelBoxRatio(item, editor);
    const candidate = [
        (position.x - size.w / 2) * editor.canvasWidth,
        (position.y - size.h / 2) * editor.canvasHeight,
        (position.x + size.w / 2) * editor.canvasWidth,
        (position.y + size.h / 2) * editor.canvasHeight,
    ];
    return (editor.obstacles || []).find(({bbox}) =>
        candidate[0] < bbox[2] && candidate[2] > bbox[0]
        && candidate[1] < bbox[3] && candidate[3] > bbox[1]
    );
}

function _labelKindOptions(editor) {
    return editor.target === 'yt_vstrip'
        ? [['source', '畫面來源'], ['', '無']]
        : [['ai', editor.target === 'cg' || editor.target === 'broadcast' ? '示意圖' : 'AI示意圖'],
           ['source', '畫面來源'], ['', '無']];
}

function renderFreeLabelEditor() {
    document.querySelectorAll('[data-label-controls]').forEach(el => el.classList.add('hidden'));
    document.querySelectorAll('[data-label-overlay]').forEach(el => { el.innerHTML = ''; });
    const editor = state.labelEditor;
    if (!editor) return;
    const controls = document.querySelector(`[data-label-controls="${editor.imageId}"]`);
    const stage = document.querySelector(`[data-label-stage="${editor.imageId}"]`);
    const overlay = stage?.querySelector('[data-label-overlay]');
    if (!controls || !overlay) return;
    controls.classList.remove('hidden');
    controls.innerHTML = editor.items.map((item, index) => {
        const side = editor.items.length > 1 ? (item.side === 'left' ? '左側' : '右側') : '標籤';
        const options = _labelKindOptions(editor).map(([value, label]) =>
            `<option value="${value}" ${item.kind === value ? 'selected' : ''}>${label}</option>`).join('');
        const warning = item.kind !== item.provenance_kind
            ? (item.provenance_kind === 'ai' && item.kind === 'source'
                ? '此圖含 AI 生成內容，改成「畫面來源」請自行確認'
                : '已手動覆寫系統判定，請自行確認') : '';
        return `<div class="${index ? 'mt-2 pt-2 border-t border-amber-900/60' : ''}">
            <div class="flex items-center gap-2 flex-wrap">
                <span class="text-[9px] font-black text-amber-300">${side}</span>
                <select data-free-label-kind="${index}" class="bg-slate-950 border border-slate-700 rounded px-2 py-1 text-[10px]">${options}</select>
                <input data-free-label-source="${index}" maxlength="40" value="${(item.source_text || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;')}"
                    placeholder="來源文字" class="${item.kind === 'source' ? '' : 'hidden'} flex-1 min-w-[150px] bg-slate-950 border border-slate-700 rounded px-2 py-1 text-[10px]" />
                <span class="text-[9px] text-slate-500">桌機可直接拖曳圖片上的虛線框</span>
            </div>
            <p data-free-label-warning="${index}" class="${warning ? '' : 'hidden'} mt-1 text-[10px] text-amber-300">${warning}</p>
        </div>`;
    }).join('');
    controls.querySelectorAll('[data-free-label-kind]').forEach(select => {
        select.addEventListener('change', () => changeFreeLabelKind(Number(select.dataset.freeLabelKind), select.value));
    });
    controls.querySelectorAll('[data-free-label-source]').forEach(input => {
        input.addEventListener('change', () => changeFreeLabelSource(Number(input.dataset.freeLabelSource), input.value));
    });
    editor.items.forEach((item, index) => {
        if (!item.position) return;
        const size = _freeLabelBoxRatio(item, editor);
        const handle = document.createElement('div');
        handle.dataset.freeLabelHandle = String(index);
        handle.className = 'absolute border-2 border-dashed border-amber-400 bg-amber-400/10 cursor-move pointer-events-auto';
        handle.style.left = `${(item.position.x - size.w / 2) * 100}%`;
        handle.style.top = `${(item.position.y - size.h / 2) * 100}%`;
        handle.style.width = `${size.w * 100}%`;
        handle.style.height = `${size.h * 100}%`;
        handle.title = '拖曳標籤；放開後才重貼';
        handle.addEventListener('pointerdown', event => beginFreeLabelDrag(event, index, handle, stage));
        overlay.appendChild(handle);
    });
}

function beginFreeLabelDrag(event, index, handle, stage) {
    if (event.pointerType === 'touch' || window.matchMedia('(max-width: 767px)').matches) return;
    event.preventDefault();
    const editor = state.labelEditor;
    const item = editor?.items[index];
    if (!item) return;
    const original = {...item.position};
    handle.setPointerCapture(event.pointerId);
    const move = ev => {
        const rect = stage.getBoundingClientRect();
        const next = _clampFreeLabelPosition(item, editor, {
            x: (ev.clientX - rect.left) / rect.width,
            y: (ev.clientY - rect.top) / rect.height,
        });
        const hit = _freeLabelCollision(item, editor, next);
        const size = _freeLabelBoxRatio(item, editor);
        handle.style.left = `${(next.x - size.w / 2) * 100}%`;
        handle.style.top = `${(next.y - size.h / 2) * 100}%`;
        handle.classList.toggle('border-red-500', !!hit);
        handle.classList.toggle('bg-red-500/20', !!hit);
        handle._candidate = next;
        handle._hit = hit;
    };
    const up = () => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', up);
        handle.removeEventListener('pointercancel', cancel);
        if (handle._hit) {
            item.position = original;
            showToast(`標籤碰到固定元素：${handle._hit.name}`);
            renderFreeLabelEditor();
            return;
        }
        item.position = handle._candidate || original;
        restampFreeLabels();
    };
    const cancel = () => { item.position = original; renderFreeLabelEditor(); };
    handle.addEventListener('pointermove', move);
    handle.addEventListener('pointerup', up);
    handle.addEventListener('pointercancel', cancel);
}

function changeFreeLabelKind(index, kind) {
    const editor = state.labelEditor;
    if (!editor?.items[index]) return;
    const item = editor.items[index];
    item.kind = kind;
    item.bbox = [];
    item.position = _clampFreeLabelPosition(item, editor, item.position);
    if (kind === 'source' && !item.source_text) {
        renderFreeLabelEditor();
        return showToast('請先填畫面來源文字');
    }
    renderFreeLabelEditor();
    const hit = _freeLabelCollision(item, editor, item.position);
    if (hit) return showToast(`標籤碰到固定元素：${hit.name}，請先拖到其他位置`);
    restampFreeLabels();
}

function changeFreeLabelSource(index, text) {
    const editor = state.labelEditor;
    if (!editor?.items[index]) return;
    const item = editor.items[index];
    item.source_text = String(text || '').trim().slice(0, 40);
    item.bbox = [];
    item.position = _clampFreeLabelPosition(item, editor, item.position);
    renderFreeLabelEditor();
    if (item.kind === 'source' && !item.source_text) {
        return showToast('畫面來源文字不可空白');
    }
    const hit = _freeLabelCollision(item, editor, item.position);
    if (hit) return showToast(`標籤碰到固定元素：${hit.name}，請先拖到其他位置`);
    restampFreeLabels();
}

async function restampFreeLabels() {
    const editor = state.labelEditor;
    if (!editor) return;
    const requestId = ++state.labelRestampRequestId;
    try {
        const response = await fetch(`${API_BASE}/api/images/restamp-disclaimer`, {
            method: 'POST', headers: _apiHeaders(),
            body: JSON.stringify(buildFreeLabelPayload(editor, state.currentRole)),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(_apiError(data, response.status));
        if (requestId !== state.labelRestampRequestId || state.labelEditor !== editor) return;
        const imageUrl = `data:${data.mime_type};base64,${data.image_data_base64}`;
        document.getElementById(editor.imageId).src = imageUrl;
        const download = document.getElementById(editor.imageId === 'generatedImage' ? 'downloadGeneratedImage' : 'oneClickDownload');
        if (download) download.href = imageUrl;
        editor.items = data.disclaimer_items?.length ? data.disclaimer_items : editor.items;
        editor.safeRect = data.disclaimer_safe_rect || editor.safeRect;
        editor.obstacles = data.disclaimer_obstacles || editor.obstacles;
        if (editor.imageId === 'oneClickImage') state.refineDisplay = {...(state.refineDisplay || {}), ...data};
        hideToast();
        hideGenerateErrorBanner(true);
        showGenerateNoticeBanner(data.notices);
        renderFreeLabelEditor();
    } catch (err) {
        if (requestId !== state.labelRestampRequestId) return;
        showToast(`標籤重貼失敗：${err.message}`);
        renderFreeLabelEditor();
    }
}

function buildFreeLabelPayload(editor, role) {
    return {
        disclaimer_base_image_base64: editor.base64,
        target: editor.target,
        context: editor.context,
        safe_frame_profile: editor.target === 'cg' || editor.target === 'broadcast' ? role : '編輯安全框',
        hole_side: editor.context.hole_side || '',
        model: editor.model,
        items: editor.items.map(item => ({
            id: item.id, target_side: item.side || 'global', kind: item.kind,
            source_text: item.source_text || '', position: item.position,
            provenance_kind: item.provenance_kind || '',
            manual_override: !!item.manual_override || item.kind !== (item.provenance_kind || ''),
        })),
    };
}

function onDisclaimerSourceInput(input) {
    // 後端 disclaimer_source_text 是 max_length=40，超過會被 422 擋在生圖之前，
    // 所以這裡先截斷而不是讓使用者打完才失敗（input 本身也有 maxlength）。
    state.disclaimerSourceText = (input?.value || '').slice(0, 40);
    updateDisclaimerControls();
}

function updateDisclaimerControls() {
    document.querySelectorAll('[data-disclaimer-corner]').forEach(btn => {
        const on = btn.dataset.disclaimerCorner === state.disclaimerCorner;
        btn.classList.toggle('bg-amber-600', on);
        btn.classList.toggle('text-white', on);
        btn.classList.toggle('text-slate-400', !on);
        btn.title = `「示意圖」／「畫面來源」標籤貼在${DISCLAIMER_CORNER_LABELS[btn.dataset.disclaimerCorner]}`;
    });
    // 兩頁各有一份控制項（p1- 前綴那份與第二／三頁那份），值要同步顯示
    document.querySelectorAll('[data-disclaimer-source]').forEach(input => {
        if (input.value !== state.disclaimerSourceText) input.value = state.disclaimerSourceText;
    });
    // 封面版型走 compose 自己的 _draw_ai_note，不吃這組設定，整列收起來
    const hide = !!(editorFormat().hides || {}).disclaimer;
    document.querySelectorAll('[data-disclaimer-row]').forEach(row => {
        row.classList.toggle('hidden', hide);
    });
}

// 兩個生圖送出點共用：一組控制、兩種標籤，該貼哪一種由後端判。
function disclaimerPayload() {
    return {
        disclaimer_source_text: state.disclaimerSourceText.trim(),
        disclaimer_corner: state.disclaimerCorner,
    };
}

// 按鈕外觀：選中的填色、沒選中的只有邊框；會壓到直標的角落直接 disabled
function _vstripPick(selector, value) {
    document.querySelectorAll(selector).forEach(btn => {
        const on = btn.dataset.vstripValue === value;
        btn.classList.toggle('bg-red-600', on);
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
    setupFreeLabelEditor(data, 'oneClickImage');
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
    clearGenerateBannerForNewRequest();
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
        hideGenerateErrorBanner();
        showToast("消化中…");
        beginGenerationProgress("digest");
        const digest = await digestNewsText(input);
        applyDigestToForm(digest);
        showGenerateNoticeBanner(digest.notices);
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
            noText: state.digestDensity === 'no_text',
            modelExtension: modelExtensionActive(),
            holeSide: broadcastLayoutHoleForApi(),
        });
        showToast("生圖中，約 30–120 秒…");
        // 2K 與 GPT 都明顯較慢，預估時間拉長免得進度早早貼上限乾等
        const slowCombo = (state.imageSize === "2K" ? 1.5 : 1)
            * (effectiveImageProvider() === "gpt" ? 1.3 : 1);
        beginGenerationProgress("image", slowCombo);
        // 消化完成後才是生圖送出點；此刻固定實際送出的成品參數。
        const generationParameters = refineParametersFromState();
        const imgRes = await fetch(IMAGE_BACKEND_URL, {
            method: "POST",
            headers: _apiHeaders(),
            body: JSON.stringify({
                prompt,
                provider: effectiveImageProvider(),
                aspect_ratio: currentAspectRatio(),
                image_size: state.imageSize,
                density: state.density,
                safe_frame: state.safeFrame,
                frame_strategy: frameStrategyForApi(),
                safe_frame_profile: state.currentRole,
                // 白框與 AI 版面挖空分開送：前者只在壓框 ON 時有值，後者不受壓框開關影響。
                broadcast_hole: broadcastHoleForApi(),
                hole_side: broadcastLayoutHoleForApi(),
                // 地圖類的真實座標（消化端列地名、後端實查 Nominatim）。後端據此
                // 拼一張真實底圖、把標點畫在正確位置再當參考圖附上——模型記憶裡的
                // 經緯度實測差到 2.3 公里，冷門地名尤其不準。
                map_points: state.mapPoints,
                portrait_subjects: state.portraitSubjects,
                portrait_subjects_en: state.portraitSubjectsEn,
                reference_images: userRefImagesPayload(),
                // AI改圖 專用（2026-09-13）：指令欄要直接送到生圖模型手上，當成
                // 「這張附圖要改哪裡」。沒附 AI改圖 的圖時後端會忽略這個欄位。
                editor_instruction: currentUserInstruction(),
                // B70／F43：示意圖／畫面來源標籤的來源名與角落。該貼哪一種（或都不貼）
                // 由後端 resolve_image_disclaimer 判，前端只負責把這兩個值送到。
                ...disclaimerPayload(),
            }),
        });
        const data = await imgRes.json().catch(() => ({}));
        if (!imgRes.ok) {
            throw new Error(_apiError(data, imgRes.status));
        }

        const imageUrl = `data:${data.mime_type};base64,${data.image_data_base64}`;
        const isPng = data.mime_type === "image/png";
        document.getElementById("oneClickImage").src = imageUrl;
        setupFreeLabelEditor(data, 'oneClickImage');
        const download = document.getElementById("oneClickDownload");
        download.href = imageUrl;
        download.download = downloadFileName(state.editorFormat, undefined, isPng ? "png" : "jpg");
        download.innerText = `下載 ${isPng ? "PNG" : "JPEG"}`;
        // ③ 記住「置框前」原圖供追加修改；未置框時成品本身就是原圖
        resetRefineState(refineSourceFromResponse(data), data, generationParameters);
        document.getElementById("oneClickLabel").innerText = data.model || "AI Generated";
        const titleMatch = variable.match(/\[標題\]\s*([^\n]+)/);
        document.getElementById("oneClickMeta").innerText = titleMatch ? titleMatch[1].trim() : "";
        document.getElementById("oneClickEmpty").classList.add("hidden");
        document.getElementById("oneClickResult").classList.remove("hidden");
        completed = true;
        hideGenerateErrorBanner();
        showGenerateNoticeBanner(data.notices);
        showToast(titleMatch ? `已生成：${titleMatch[1].trim()}` : "已完成圖片生成");
    } catch (err) {
        console.error(err);
        const msg = err.message || "生成失敗，請稍後再試";
        showGenerateErrorBanner(msg);
        showToast(msg);
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
    const generationParameters = refineParametersFromState();

    try {
        const response = await fetch(IMAGE_BACKEND_URL, {
            method: 'POST',
            headers: _apiHeaders(),
            body: JSON.stringify({
                prompt,
                provider,
                aspect_ratio: currentAspectRatio(),
                image_size: state.imageSize,
                // B84（2026-09-22）：這格以前漏掉，後端收到 density="" → F38 的高解析度
                // 閘門在第二／三頁這個送出點**永遠不成立**，字多／字超多從來沒拿到 2K。
                // 與第一頁那個送出點一致，兩邊少一邊就有一邊靜靜降級。
                density: state.density,
                safe_frame: state.safeFrame,
                frame_strategy: frameStrategyForApi(),
                safe_frame_profile: state.currentRole,
                // 白框與 AI 版面挖空分開送：前者只在壓框 ON 時有值，後者不受壓框開關影響。
                broadcast_hole: broadcastHoleForApi(),
                hole_side: broadcastLayoutHoleForApi(),
                // 地圖類的真實座標（消化端列地名、後端實查 Nominatim）。後端據此
                // 拼一張真實底圖、把標點畫在正確位置再當參考圖附上——模型記憶裡的
                // 經緯度實測差到 2.3 公里，冷門地名尤其不準。
                map_points: state.mapPoints,
                portrait_subjects: state.portraitSubjects,
                portrait_subjects_en: state.portraitSubjectsEn,
                // B70／F43：同上，兩個送出點要一致，不然第二／三頁按生成就沒有標籤。
                ...disclaimerPayload(),
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
        setupFreeLabelEditor(data, 'generatedImage');
        download.href = imageUrl;
        download.download = downloadFileName(state.editorFormat, undefined, isPng ? 'png' : 'jpg');
        download.innerText = `下載 ${isPng ? 'PNG' : 'JPEG'}`;
        resultLabel.innerText = `${providerName} Generated Preview`;
        image.alt = `${providerName} 生成的新聞 CG 預覽`;
        result.classList.remove('hidden');
        // 第二／三頁也保存同一組置框前原圖與送出快照，成圖後拖曳／切種類才有乾淨底圖可重貼。
        resetRefineState(refineSourceFromResponse(data), data, generationParameters);
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
const REF_MAX_FILES = 4;   // 2026-09-13 使用者：4 格放寬（原 3）
// 後端 data_url 上限約 2MB base64；1.5MB 原檔編碼後約 2MB，貼著上限
const REF_MAX_BYTES = 1.5 * 1024 * 1024;
// portrait＝肖像照：使用者親自上傳時，「兩位以上具名真人不畫臉」鐵律解除
// （2026-08-17 使用者裁決）；沒附照片的人後端規則仍要求不畫臉。
//
// 2026-09-13 使用者裁決：全站上傳統一成這一組，順序照使用者指定，預設改成「原圖放置」。
// aiedit（AI改圖）是這次新增的——這張圖就是成品那塊畫面，但交給生圖模型重畫一次。
// ⚠️ 這裡是 editor_formats.REF_PURPOSE_ORDER 的鏡像，順序與標籤都由
// tests/test_ref_upload_module_20260913.py 的 parity 測試釘住，改一邊要改兩邊。
// 刻意用陣列不用物件：順序是規格的一部分，靠物件鍵序保證太脆。
const REF_PURPOSES = [
    ['asis', '原圖放置'],
    ['aiedit', 'AI改圖'],
    ['scene', '實景參考'],
    ['portrait', '肖像照片'],
    ['map', '地圖底稿'],
];
const REF_PURPOSE_DEFAULT = 'asis';

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

/* ------------------------------------------------------------
   上傳圖片共用模組（2026-09-13，見 docs/plan-20260913-上傳圖片模組化.md）

   在此之前有三份幾乎逐字相同的實作：共用附圖區、十點的左右附圖位、整點的
   左右附圖位。讀檔與壓縮抄三次、render 各寫一份，而且只有共用附圖區有用途
   下拉——十點與整點固定當原圖放置。這裡收成三支函式：

     readImageFile(file)                 → {dataUrl, name}；超標自動壓縮，失敗丟例外
     addImageFilesTo(list, input, …)     → 讀進清單（就地 push），滿了 toast 並停
     renderRefList(listEl, items, cb)    → 一列一張圖：縮圖＋檔名＋用途下拉＋✕

   三處呼叫同一組，用途下拉因此自動長在十點與整點的附圖位上。
   ------------------------------------------------------------ */

// 讀成 data URL；超過 REF_MAX_BYTES 就壓縮（壓完仍超標視為失敗）。
// 「已自動壓縮」的 toast 在這裡發——呼叫端只需要處理成功值與例外。
async function readImageFile(file) {
    if (file.size <= REF_MAX_BYTES) {
        const dataUrl = await new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = () => reject(new Error('圖片讀取失敗'));
            reader.readAsDataURL(file);
        });
        return { dataUrl, name: file.name };
    }
    const dataUrl = await compressImageFile(file, REF_MAX_BYTES);
    if (dataUrlByteLength(dataUrl) > REF_MAX_BYTES) {
        throw new Error('壓縮後仍過大，請換一張較小的圖');
    }
    showToast(`「${file.name}」已自動壓縮上傳`);
    return { dataUrl, name: file.name };
}

// 把選到的檔案讀進 list（就地 push），滿了就 toast 並停。回傳有沒有真的加進東西。
async function addImageFilesTo(list, input, max, onDone) {
    const files = Array.from(input.files || []);
    input.value = '';
    const limit = max || REF_MAX_FILES;
    let added = false;
    for (const file of files) {
        if (list.length >= limit) {
            showToast(`這一區最多 ${limit} 張`);
            break;
        }
        try {
            const ref = await readImageFile(file);
            list.push({ dataUrl: ref.dataUrl, name: ref.name, purpose: REF_PURPOSE_DEFAULT });
            added = true;
        } catch (err) {
            showToast(`「${file.name}」讀取失敗：${err.message}`);
        }
        if (onDone) onDone();
    }
    if (onDone) onDone();
    return added;
}

// 一列一張圖。items 是就地改的陣列；改用途或刪掉都呼叫 onChange 重畫。
// opts.lockAsis（2026-09-13 使用者裁決）：半版附圖位放了 2 張以上時，原圖放置不能選——
// 一個半格只有一個版位，多張的用意是讓 AI 重新構圖融成一張，所以整格鎖成 AI改圖。
// 既有已選原圖放置的那幾張在這裡就地翻成 AI改圖，跟後端 main.lock_half_slot_asis 同一套。
function renderRefList(listEl, items, onChange, opts) {
    if (!listEl) return;
    const lockAsis = !!(opts && opts.lockAsis);
    if (lockAsis) items.forEach(ref => { if (ref.purpose === 'asis') ref.purpose = 'aiedit'; });
    listEl.innerHTML = '';
    items.forEach((ref, index) => {
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
        for (const [value, label] of REF_PURPOSES) {
            if (lockAsis && value === 'asis') continue;
            const option = document.createElement('option');
            option.value = value;
            option.textContent = label;
            option.selected = ref.purpose === value;
            select.appendChild(option);
        }
        select.onchange = () => { ref.purpose = select.value; if (onChange) onChange(); };
        const remove = document.createElement('button');
        remove.className = 'text-[10px] font-black text-slate-500 hover:text-red-400 px-1';
        remove.textContent = '✕';
        remove.onclick = () => { items.splice(index, 1); if (onChange) onChange(); };
        row.append(img, name, select, remove);
        listEl.appendChild(row);
    });
}

async function handleRefFilesSelected(input) {
    await addImageFilesTo(state.userRefImages, input, REF_MAX_FILES, renderRefUploads);
}

function renderRefUploads() {
    renderRefList(document.getElementById('refUploadList'), state.userRefImages, renderRefUploads);
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

/* 十點與整點的附圖位（2026-09-13 起走共用上傳模組）：一格可以放多張，每張各有
   自己的用途下拉。一格只有一個版位，所以那格的**第一張「原圖放置」**才是直接上版
   的圖，同格其他張（AI改圖／實景參考／肖像照片／地圖底稿）是那格生底圖時的參考。
   後端同一套讀法，見 main.slot_reference_list／slot_placement_url。 */
async function handleCoverAsisSelected(side, input) {
    await addImageFilesTo(state.coverAsis[side], input, REF_MAX_FILES, renderCoverAsis);
}

function clearCoverAsis(side) {
    state.coverAsis[side] = [];
    renderCoverAsis();
}

// 整點直播的附圖位（2026-09-10）：與十點同一組動作，只是存在 state.ytAsis。
async function handleYtAsisSelected(side, input) {
    await addImageFilesTo(state.ytAsis[side], input, REF_MAX_FILES, renderYtAsis);
}

function clearYtAsis(side) {
    state.ytAsis[side] = [];
    renderYtAsis();
}

// 一格裡直接上版的那張圖（第一張原圖放置）；沒有就是「這格由 AI 生底圖」。
function slotPlacement(list) {
    return (list || []).find(ref => ref.purpose === 'asis') || null;
}

// 這一格送給後端的清單（後端欄位 slot_left／slot_right）
function slotPayload(list) {
    return (list || []).map(ref => ({ data_url: ref.dataUrl, purpose: ref.purpose }));
}

function slotHintText(list, lockAsis, isHalf) {
    if (!(list || []).length) return '沒圖＝這格由 AI 生底圖';
    if (lockAsis) return isHalf ? '半版放多張＝AI 把它們融成一張（不能原圖放置）'
                                : '有 AI改圖＝整版交給 AI 合成一張（不能原圖放置）';
    if (slotPlacement(list)) return '這格直接用附圖';
    return '這格由 AI 生底圖（附圖當參考）';
}

// 原圖放置什麼時候不能選（2026-09-13 使用者裁決，後端 lock_half_slot_asis／merge_mixed_slot_to_aiedit 同一套）：
// 半版格子 ≥2 張就鎖；滿版（十點滿版的左格、YT 單則）只在混了 AI改圖 時鎖——
// 多張都是原圖走自動切格，任一張選了 AI改圖 就整版交給 AI 合成一張。
function slotAsisLocked(list, isHalf) {
    const items = list || [];
    if (isHalf) return items.length >= 2;
    return items.some(ref => ref.purpose === 'aiedit');
}

function renderYtAsis() {
    const dual = ytLayoutNow() === 'dual';
    for (const [side, cap] of [['left', 'Left'], ['right', 'Right']]) {
        const lock = slotAsisLocked(state.ytAsis[side], dual);
        renderRefList(document.getElementById(`ytAsis${cap}List`), state.ytAsis[side], renderYtAsis, { lockAsis: lock });
        const hint = document.getElementById(`ytAsis${cap}Hint`);
        if (hint) hint.textContent = slotHintText(state.ytAsis[side], lock, dual);
    }
}

/* 附圖位只有整點直播有：國內外新聞直播與今日熱搜仍走共用附圖區，因為那兩個支援
   1 張整版／2 張左右雙切／3 張三切——改成一標一圖會把雙切與三切砍掉。
   第二個附圖位再多一層條件：判定成雙則（第二標題有填）時才出現，比照十點的滿版／雙切。 */
function ytUsesAsisSlots() {
    // 哪些版型有一標一附圖位看版型表的 slots（後端 FORMAT_CAPABILITIES 同一份，parity 測試釘住），
    // 不再在這裡寫死版型名單——對齊新版型時只要在表上翻旗子
    const format = editorFormat();
    return format.inputs === 'yt_cover' && !!format.slots;
}

function updateYtAsisSlots() {
    const slots = ytUsesAsisSlots();
    const dual = slots && ytLayoutNow() === 'dual';
    const leftRow = document.getElementById('ytAsisLeftRow');
    const rightRow = document.getElementById('ytAsisRightRow');
    if (leftRow) {
        leftRow.classList.toggle('hidden', !slots);
        leftRow.classList.toggle('flex', slots);
    }
    if (rightRow) {
        rightRow.classList.toggle('hidden', !dual);
        rightRow.classList.toggle('flex', dual);
    }
    // 單則時左邊那顆就是整版的附圖位，字要跟著改（比照十點的滿版）
    const leftBtn = document.getElementById('ytAsisLeftBtn');
    const live24 = (editorFormat().ytLayout || '') === 'live24';
    if (leftBtn) {
        leftBtn.textContent = live24
            ? (dual ? '📁 ＋ 大底圖（選填）' : '📁 ＋ 附圖（選填）')
            : (dual ? '📁 ＋ 第一附圖（選填）' : '📁 ＋ 附圖（選填）');
    }
    // 底圖模式那一列只有 live24 有
    const bgRow = document.getElementById('live24BgRow');
    if (bgRow) bgRow.classList.toggle('hidden', !live24);
    // 從雙則退回單則時，右邊那格的圖不能留著偷偷送出去
    if (!dual && state.ytAsis.right.length) state.ytAsis.right = [];
    renderYtAsis();
}

function renderCoverAsis() {
    const split = coverLayoutNow() === 'split';
    for (const [side, cap] of [['left', 'Left'], ['right', 'Right']]) {
        const lock = slotAsisLocked(state.coverAsis[side], split);
        renderRefList(document.getElementById(`coverAsis${cap}List`), state.coverAsis[side], renderCoverAsis, { lockAsis: lock });
        const hint = document.getElementById(`coverAsis${cap}Hint`);
        if (hint) hint.textContent = slotHintText(state.coverAsis[side], lock, split);
    }
}

// 哪一格會「直接用附圖」。只放了 AI改圖／參考圖的格子不算——那格照樣要生底圖，
// 進度提示與強制壓字都看這個（2026-09-13，後端 slot_placements 同一判準）。
function coverAsisSlots() {
    return { left: !!slotPlacement(state.coverAsis.left), right: !!slotPlacement(state.coverAsis.right) };
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

// B83／F47（2026-09-22）：上一張成品**實際**貼的那一組標籤。
// 後端刻意不重判——refine 不送 portrait_subjects，重判會讓一張本來標「示意圖」的
// 具名肖像因為來源名還留在輸入框而被降級成「畫面來源」，那是對觀眾說謊。
// 所以這裡讀的是**回應**裡的值（後端貼了什麼就回什麼），不是前端那組輸入控制項。
// 沒有成品、或那張根本沒貼標籤時回 kind=''，後端就不貼。
function appliedDisclaimer() {
    const d = state.refineDisplay || {};
    const editor = state.labelEditor;
    if (editor?.items?.length) {
        const items = editor.items.map(item => ({
            id: item.id || 'global',
            target_side: item.side || item.target_side || 'global',
            kind: item.kind || '',
            source_text: item.source_text || '',
            position: item.position || null,
            provenance_kind: item.provenance_kind || '',
            manual_override: !!item.manual_override || item.kind !== (item.provenance_kind || ''),
        }));
        const first = items.length === 1 ? items[0] : null;
        return {
            kind: first?.kind || '',
            sourceText: first?.source_text || '',
            corner: state.disclaimerCorner || d.disclaimer_corner || 'lower_right',
            position: first?.position || null,
            provenanceKind: first?.provenance_kind || '',
            manualOverride: items.some(item => item.manual_override),
            target: editor.target || 'cg',
            context: editor.context || {},
            items,
        };
    }
    return {
        kind: d.disclaimer_kind || '',
        sourceText: d.disclaimer_source_text || '',
        // 角落是使用者現在選的那個（F47 事後改位置就是改這格）；
        // 沒選過就沿用上一張貼的位置。
        corner: state.disclaimerCorner || d.disclaimer_corner || 'lower_right',
        position: d.disclaimer_position || null,
        provenanceKind: d.disclaimer_provenance_kind || d.disclaimer_kind || '',
        manualOverride: !!d.disclaimer_manual_override,
        target: currentFreeLabelTarget(),
        context: currentFreeLabelContext(),
        items: Array.isArray(d.disclaimer_items) ? d.disclaimer_items.map(item => ({
            id: item.id || 'global',
            target_side: item.side || item.target_side || 'global',
            kind: item.kind || '',
            source_text: item.source_text || '',
            position: item.position || null,
            provenance_kind: item.provenance_kind || '',
            manual_override: !!item.manual_override || item.kind !== (item.provenance_kind || ''),
        })) : [],
    };
}

function refineDisclaimerPayload(applied) {
    return {
        disclaimer_kind: applied.kind,
        disclaimer_source_text: applied.sourceText,
        disclaimer_corner: applied.corner,
        disclaimer_position: applied.position,
        disclaimer_provenance_kind: applied.provenanceKind,
        disclaimer_manual_override: applied.manualOverride,
        disclaimer_target: applied.target,
        disclaimer_context: applied.context,
        disclaimer_items: applied.items,
    };
}

async function restampRefinedCoverLabels(display, applied) {
    if (!display?.disclaimer_base_image_base64) return display;
    const response = await fetch(`${API_BASE}/api/images/restamp-disclaimer`, {
        method: 'POST', headers: _apiHeaders(),
        body: JSON.stringify({
            disclaimer_base_image_base64: display.disclaimer_base_image_base64,
            source_image_base64: display.source_image_base64 || '',
            source_mime_type: display.source_mime_type || display.mime_type || 'image/png',
            model: display.model || '',
            target: applied.target,
            context: applied.context,
            safe_frame_profile: '編輯安全框',
            disclaimer_kind: applied.kind,
            disclaimer_source_text: applied.sourceText,
            position: applied.position,
            provenance_kind: applied.provenanceKind,
            manual_override: applied.manualOverride,
            items: applied.items,
            clamp_to_legal: true,
        }),
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(_apiError(data, response.status));
    return {
        ...data,
        notices: Array.from(new Set([
            ...(Array.isArray(display.notices) ? display.notices : []),
            ...(Array.isArray(data.notices) ? data.notices : []),
        ])),
    };
}

function refineParametersFromState(display = null) {
    return {
        density: state.density,
        safe_frame: state.safeFrame,
        frame_strategy: frameStrategyForApi(),
        safe_frame_profile: state.currentRole,
        aspect_ratio: currentAspectRatio(),
        image_size: state.imageSize,
        provider: effectiveImageProvider(),
        model: (display || {}).model || '',
    };
}

function resetRefineState(source, display, parameters = null) {
    // 新成品會讓先前尚未回來的 restamp 全部失效。
    state.restampRequestId += 1;
    state.refineSource = source || null;
    // 顯示中的成品也記在 state（退回上一版用），不從 DOM 反解
    state.refineDisplay = display || null;
    state.refineParameters = source ? {
        ...(parameters || refineParametersFromState(display)),
        // 模型名稱以後端實際回應為準，其他欄位則必須沿用送出快照。
        model: (display || {}).model || (parameters || {}).model || '',
    } : null;
    state.refineStack = [];
    const input = document.getElementById('refineInput');
    if (input) input.value = '';
    const replacement = document.getElementById('replacementPerson');
    if (replacement) replacement.value = '';
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
    setupFreeLabelEditor(data, 'oneClickImage');
    const download = document.getElementById('oneClickDownload');
    download.href = imageUrl;
    download.download = downloadFileName(state.editorFormat, undefined, isPng ? 'png' : 'jpg');
    document.getElementById('oneClickLabel').innerText = data.model || 'AI Generated';
}

// F32（2026-09-20）：輸入框改成多行 textarea，Enter 換行，Ctrl+Enter／⌘+Enter 才送出，
// 送出仍走既有的 handleRefine（按鈕沒有換掉）。
function handleRefineKeydown(event) {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
        event.preventDefault();
        handleRefine();
    }
}

async function handleRefine() {
    const input = document.getElementById('refineInput');
    const instruction = input.value.trim();
    if (!instruction) return showToast('請輸入要修改的內容');
    if (!state.refineSource) return showToast('沒有可修改的圖，請先生成一張');
    const replacementInput = document.getElementById('replacementPerson');
    const replacementPerson = (replacementInput?.value || '').trim();
    if (!replacementPerson && requestsNamedFaceReplacement(instruction)) {
        showGenerateErrorBanner('要換臉時請填寫「換臉對象（具名時必填）」欄位，系統不會從自由文字猜姓名。');
        replacementInput?.focus();
        return;
    }
    clearGenerateBannerForNewRequest();

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
    const savedRefineParameters = state.refineParameters
        || refineParametersFromState(state.refineDisplay);
    const refineParameters = {
        ...savedRefineParameters,
        aspect_ratio: isCover ? '16:9' : savedRefineParameters.aspect_ratio,
        safe_frame: isCover ? false : savedRefineParameters.safe_frame,
        safe_frame_profile: isCover ? '' : savedRefineParameters.safe_frame_profile,
    };
    // 送出前凍結「畫面上現在這一版」；await 期間即使 UI 狀態改變，也不能換成別張。
    const applied = appliedDisclaimer();
    try {
        const response = await fetch(REFINE_BACKEND_URL, {
            method: 'POST',
            headers: _apiHeaders(),
            body: JSON.stringify({
                source_image_base64: state.refineSource.base64,
                source_mime_type: state.refineSource.mimeType,
                instruction,
                provider: refineParameters.provider,
                aspect_ratio: refineParameters.aspect_ratio,
                image_size: refineParameters.image_size,
                // B84（2026-09-22）：這格以前不存在，後端 ImageRefineRequest 也沒有——
                // 於是追加修改一律掉回 1K 畫布，字多／字超多生的 2K 圖只要一改就降級。
                density: refineParameters.density,
                // B83（2026-09-22）：refine 以前完全不貼標籤，「畫面來源」與「示意圖」
                // 改完圖就整個消失。原樣帶回上一張實際貼的那一組（見 appliedDisclaimer）。
                // 封面版型走 compose 自己的 _draw_ai_note，不吃這組。
                disclaimer_kind: applied.kind,
                disclaimer_source_text: applied.sourceText,
                disclaimer_corner: applied.corner,
                disclaimer_position: applied.position || null,
                disclaimer_provenance_kind: applied.provenanceKind || '',
                disclaimer_manual_override: !!applied.manualOverride,
                disclaimer_target: applied.target || 'cg',
                disclaimer_context: applied.context || {},
                disclaimer_items: applied.items || [],
                safe_frame: refineParameters.safe_frame,
                frame_strategy: isCover ? '' : (refineParameters.frame_strategy || ''),
                // B51：封面不能只送 safe_frame=false 卻仍帶「編輯」——編輯身分在
                // resolve_frame_plan 一律會被置對位框（見 main.py 的說明），safe_frame
                // 的值因此完全無效。封面一律送空字串，並改用下面的 cover_kind 讓後端
                // 走結構化 bypass，不依角色字串猜。
                safe_frame_profile: refineParameters.safe_frame_profile,
                // 白名單值＝ EDITOR_FORMATS 的版型 key，正好對齊後端
                // editor_formats.COVER_REFINE_KINDS；非封面一律不送。
                cover_kind: isCover ? state.editorFormat : '',
                // 追加修改沿用同一個版面挖空側；白框仍由壓框開關獨立決定。
                broadcast_hole: isCover ? '' : broadcastHoleForApi(),
                hole_side: isCover || !editorFormat().hole ? '' : state.holeSide,
                text_free: ytTextFree,
                replacement_person: replacementPerson,
                reference_images: replacementPerson
                    ? userRefImagesPayload().filter(ref => ref.purpose === 'portrait')
                    : [],
            }),
        });
        const data = await response.json().catch(() => ({}));
        if (!response.ok) throw new Error(_apiError(data, response.status));

        // 封面兩條線：refine 只改了模型那張圖，要再走一次程式後貼才是成品。
        // 回來的 data 帶著 source_image_base64＝新的模型圖，refineSource 因此自動接上。
        const recomposed = isYtCover ? await recomposeYtCover(data, true)
            : isTenCover ? await recomposeTenCover(data)
            : data;
        const shown = isCover ? await restampRefinedCoverLabels(recomposed, applied) : recomposed;

        // 退回上一版用：存目前這一版的置框前原圖與顯示中成品（都在 state，不碰 DOM）
        state.refineStack.push({
            source: state.refineSource,
            display: state.refineDisplay,
            parameters: state.refineParameters,
        });
        // 下一輪修改要用**新的**置框前原圖，不是成品
        state.refineSource = refineSourceFromResponse(shown);
        state.refineDisplay = shown;
        state.refineParameters = {...refineParameters, model: shown.model || refineParameters.model};
        showRefinedImage(shown);
        showGenerateNoticeBanner(
            Array.isArray(shown.notices) && shown.notices.length ? shown.notices : data.notices
        );
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
    state.refineParameters = previous.parameters;
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

// F42：判斷 showToast 的文字要不要標成 error 色。只認「失敗」會漏掉 catch 區塊常見的
// 「逾時」「錯誤」「無法」（例如 3132 行 err.message 直接塞「TimeoutError」之類的英文
// 例外訊息時也未必含「失敗」），所以擴成關鍵字陣列，任一命中就標 error。
const TOAST_ERROR_KEYWORDS = ['失敗', '逾時', '錯誤', '無法', 'timeout', 'error', 'failed'];
let _toastTimer = null;

function hideToast() {
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = null;
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.style.opacity = '0';
    toast.classList.remove('toast-animate');
}

function showToast(msg) {
    const toast = document.getElementById('toast');
    if (_toastTimer) clearTimeout(_toastTimer);
    toast.innerText = msg;
    toast.style.opacity = '1'; toast.classList.add('toast-animate');
    _toastTimer = setTimeout(hideToast, 3000);
    // toast 3 秒就消失，看不到的人事後想查「剛才系統說了什麼」——一律再記一份到訊息歷史。
    const lower = String(msg || '').toLowerCase();
    const isError = TOAST_ERROR_KEYWORDS.some(k => lower.includes(k.toLowerCase()));
    logMessage(msg, isError ? 'error' : 'info');
}

// B38：一鍵生成失敗時的訊息要留在畫面上讓使用者自己關掉，不能像 toast 3 秒就消失。
function showGenerateErrorBanner(msg) {
    const banner = document.getElementById('oneClickErrorBanner');
    logMessage(msg, 'error');
    if (!banner) return;
    banner.dataset.notice = '0';
    document.getElementById('oneClickErrorMsg').innerText = msg;
    banner.classList.remove('hidden');
    const staleNotice = document.getElementById('oneClickStaleNotice');
    if (staleNotice && !document.getElementById('oneClickResult').classList.contains('hidden')) {
        staleNotice.classList.remove('hidden');
    }
}

function hideGenerateErrorBanner(force = false) {
    const banner = document.getElementById('oneClickErrorBanner');
    if (banner && banner.dataset.notice === '1' && !force) return;
    if (banner) banner.classList.add('hidden');
    if (banner) banner.dataset.notice = '';
    const staleNotice = document.getElementById('oneClickStaleNotice');
    if (staleNotice) staleNotice.classList.add('hidden');
}

function showGenerateNoticeBanner(notices) {
    const messages = Array.isArray(notices) ? notices.filter(Boolean) : [];
    if (!messages.length) return;
    messages.forEach(m => logMessage(m, 'notice'));
    const banner = document.getElementById('oneClickErrorBanner');
    if (!banner) return;
    banner.dataset.notice = '1';
    document.getElementById('oneClickErrorMsg').innerText = messages.join('\n');
    banner.classList.remove('hidden');
    const staleNotice = document.getElementById('oneClickStaleNotice');
    if (staleNotice) staleNotice.classList.add('hidden');
}

function clearGenerateBannerForNewRequest() {
    hideGenerateErrorBanner(true);
}

/* ============================================================
   F42（2026-09-20）：訊息歷史視窗——累積顯示訊息（時間＋內容＋類別），不會像 toast／
   紅色框一閃即逝；同一區塊兼做進度顯示（消化中／生圖中／完成／失敗都進這條時間軸）。
   刻意不另開一套平行的訊息系統：所有進入口都是既有的 showToast／
   showGenerateErrorBanner／showGenerateNoticeBanner／beginGenerationProgress 呼叫點，
   這裡只是多記一筆，不改變它們原本的畫面行為。
   ============================================================ */
const MESSAGE_HISTORY_LIMIT = 200;
const MESSAGE_TYPE_CLASS = {
    error: 'text-red-300',
    notice: 'text-amber-300',
    success: 'text-emerald-300',
    info: 'text-slate-300',
};
let _messageHistory = [];
let _messageHistoryUnread = 0;

function logMessage(text, type = 'info') {
    const msg = String(text || '').trim();
    if (!msg) return;
    const time = new Date().toLocaleTimeString('zh-TW', { hour12: false });
    _messageHistory.push({ time, text: msg, type });
    if (_messageHistory.length > MESSAGE_HISTORY_LIMIT) _messageHistory.shift();
    const list = document.getElementById('messageHistoryList');
    if (list && list.classList.contains('hidden')) _messageHistoryUnread += 1;
    renderMessageHistory();
}

function renderMessageHistory() {
    const list = document.getElementById('messageHistoryList');
    if (list) {
        // 只有使用者本來就貼著底部時才跟著捲——正往上翻看前一則錯誤的時候，
        // 新訊息一來就把人拽回底部，剛好毀掉這個視窗存在的理由（回看錯誤訊息）。
        // 8px 容差：瀏覽器在縮放比例非整數時 scrollTop 會有次像素誤差，抓太死會判成沒貼底。
        const wasAtBottom = list.scrollHeight - list.scrollTop - list.clientHeight < 8;
        list.innerHTML = '';
        _messageHistory.forEach(entry => {
            const row = document.createElement('div');
            row.className = `px-3 py-2 text-[10px] leading-relaxed ${MESSAGE_TYPE_CLASS[entry.type] || MESSAGE_TYPE_CLASS.info}`;
            const time = document.createElement('span');
            time.className = 'text-slate-500 font-mono mr-1';
            time.textContent = `[${entry.time}]`;
            const text = document.createElement('span');
            text.textContent = entry.text;
            row.appendChild(time);
            row.appendChild(text);
            list.appendChild(row);
        });
        if (wasAtBottom) list.scrollTop = list.scrollHeight;
    }
    const badge = document.getElementById('messageHistoryBadge');
    if (badge) {
        if (_messageHistoryUnread > 0) {
            badge.textContent = _messageHistoryUnread > 99 ? '99+' : String(_messageHistoryUnread);
            badge.classList.remove('hidden');
        } else {
            badge.classList.add('hidden');
        }
    }
}

function toggleMessageHistory() {
    const list = document.getElementById('messageHistoryList');
    if (!list) return;
    list.classList.toggle('hidden');
    if (!list.classList.contains('hidden')) {
        _messageHistoryUnread = 0;
        renderMessageHistory();
        // 剛展開一定要看到最新的那幾筆。收合時 display:none，scrollHeight 是 0，
        // renderMessageHistory() 的「貼底」判斷在這一刻不成立，所以這裡明確捲一次。
        list.scrollTop = list.scrollHeight;
    }
}

// 只判斷「這段話是否在要求換臉」，不從自由文字抽取或猜測姓名。
//
// ⚠「刪臉」不算換臉，一定要先排除掉。2026-09-16 監督驗收時抓到：曹雪卿 0915 下的
// 「左邊的鮑爾不要!!!!」是**刪掉那張臉**，而且那條路徑本來就會成功（見 MASTER B63
// 「刪得掉、換不掉」）。如果她改打「把左邊那張臉換掉」，在只看「臉＋換掉」的判斷下
// 會被擋住要她填換臉對象——但她根本沒有要換成誰，等於整條路被堵死。
// 所以句子裡出現移除語意時一律放行，交給既有的一般 refine 規則處理。
function requestsNamedFaceReplacement(text) {
    const value = String(text || '').toLowerCase();
    const removalTerms = ['不要', '刪除', '刪掉', '移除', '拿掉', '去掉', 'remove', 'delete'];
    if (removalTerms.some(term => value.includes(term))) return false;
    const directTerms = ['換臉', '換人', 'face swap', 'swap face', 'replace the face'];
    if (directTerms.some(term => value.includes(term))) return true;
    const faceTerms = ['臉', '人臉', '人頭', 'face'];
    const changeTerms = ['換成', '換為', '替換', '換掉', 'replace', 'swap'];
    return faceTerms.some(term => value.includes(term))
        && changeTerms.some(term => value.includes(term));
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
