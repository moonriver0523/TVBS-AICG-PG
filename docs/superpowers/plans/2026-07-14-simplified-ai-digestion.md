# Simplified AI Digestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an extensible Standard/Simplified AI digestion density control, synchronized Reporter/Editor controls, focused simplified prompt rules, and complete the approved 1K/documentation/lint consistency work.

**Architecture:** Keep role and density as independent state dimensions. The backend composes the existing role template with an optional simplified-density override through a pure helper, while the frontend sends `density` only with `/api/generate` requests; manual template and final-prompt workflows remain unchanged. BrowserSync on `localhost:3000` stays running during frontend work so the user can review every UI change immediately.

**Tech Stack:** Vanilla HTML/CSS, vanilla JavaScript, FastAPI, Pydantic, OpenAI Python SDK, Python `unittest`, uv, Ruff, BrowserSync, Playwright browser tools.

## Global Constraints

- All user-visible Chinese must use Traditional Chinese and Taiwan terminology.
- Default AI digestion combination is `記者 + 標準`.
- Density values are exactly `standard` and `simplified`.
- Density affects only `/api/generate`; it must not truncate or rewrite manual field input or the final assembled prompt.
- Simplified mode dynamically emits 1–3 points and never pads the output to three points.
- Simplified mode chooses one of three visual-focus strategies: one hero visual with short callouts, one dominant number/conclusion, or one large thematic image with minimal copy.
- In Editor + Simplified, `<蓋章>` is optional and counts toward the three-point maximum.
- Gemini image requests use `1K`; GPT Image 2 remains `1280x720` PNG.
- Do not call paid AI digestion or image-generation APIs during verification.
- Preserve the seven pre-existing uncommitted file changes and the approved full-width Final Prompt Output layout.
- Do not add the Person/Profile fifth chart type in this plan.
- Keep `localhost:3000` running during UI implementation and pause for user visual feedback before finalizing frontend work.

---

## File Structure and Responsibilities

- `main.py` — request validation, role/density prompt composition, AI digestion endpoint, image-size defaults.
- `tests/test_digest_prompts.py` — standard-library unit tests for request defaults, density validation, prompt composition, and 1K backend defaults.
- `index.html` — density controls, second synchronized role control, responsive layout, existing full-width output layout.
- `app.js` — shared role state, digestion-density state, synchronized controls, button label, `/api/generate` payload, 1K image payload.
- `.gitignore` — excludes `.superpowers/` visual brainstorming artifacts.
- `notion-templates/tools/build_rep_images.py` — remove one unused import.
- `notion-templates/tools/parse_notion_export.py` — rename ambiguous local variables without changing behavior.
- `editor-templates/PROMPTS.md` — retain approved 1K wording in editor reference prompts.
- `notion-templates/templates.json` — retain the existing 205-template 1K normalization.
- `pyproject.toml`, `uv.lock` — retain the existing OpenAI/certifi dependency alignment and verify lock consistency.
- `README.md` — document the current OpenAI digestion backend, density modes, image providers, and 1K behavior.
- `docs/HANDOFF.md` — replace stale Claude/Artifact and placeholder-template status with the actual architecture and current backlog.
- `docs/superpowers/specs/2026-07-14-simplified-ai-digestion-design.md` — approved source of truth; do not alter unless implementation reveals a contradiction.

---

### Task 1: Add Tested Backend Density Composition

**Files:**
- Create: `tests/test_digest_prompts.py`
- Modify: `main.py:29-46`
- Modify: `main.py:88-131`
- Modify: `main.py:126-180`
- Preserve: `pyproject.toml`
- Preserve: `uv.lock`

**Interfaces:**
- Consumes: existing `SYSTEM_PROMPT_TEMPLATE`, `EDITOR_SYSTEM_PROMPT_TEMPLATE`, and `GenerateRequest`.
- Produces: `DigestDensity`, `GenerateRequest.density`, `SIMPLIFIED_DENSITY_RULES`, and `build_digest_instructions(role: str, density: DigestDensity, type_label: str) -> str`.

- [ ] **Step 1: Save a rollback patch for all pre-existing uncommitted work**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
git diff --binary > "$CLAUDE_JOB_DIR/tmp/tvbs-aicg-pg-pre-implementation.patch"
git status --short --branch
```

Expected: the patch file is created outside the repository; the seven existing modified files remain in place.

- [ ] **Step 2: Write failing backend unit tests**

Create `tests/test_digest_prompts.py`:

```python
import os
import unittest

from pydantic import ValidationError

os.environ.setdefault("OPENAI_API_KEY", "test-key")

from main import (  # noqa: E402
    GenerateRequest,
    ImageGenerateRequest,
    build_digest_instructions,
)


class DigestPromptTests(unittest.TestCase):
    def test_density_defaults_to_standard(self):
        request = GenerateRequest(news_text="素材", type_label="資料圖表")
        self.assertEqual(request.density, "standard")

    def test_invalid_density_is_rejected(self):
        with self.assertRaises(ValidationError):
            GenerateRequest(
                news_text="素材",
                type_label="資料圖表",
                density="verbose",
            )

    def test_reporter_standard_does_not_include_simplified_override(self):
        prompt = build_digest_instructions("記者", "standard", "資料圖表")
        self.assertNotIn("SIMPLIFIED MODE OVERRIDE", prompt)
        self.assertIn("The current chart type is", prompt)

    def test_reporter_simplified_includes_focus_rules(self):
        prompt = build_digest_instructions("記者", "simplified", "資料圖表")
        self.assertIn("SIMPLIFIED MODE OVERRIDE", prompt)
        self.assertIn("dynamically select only 1 to 3 key points", prompt)
        self.assertIn("ONE dominant visual focus", prompt)
        self.assertIn("do not force three points", prompt)

    def test_editor_simplified_makes_stamp_optional(self):
        prompt = build_digest_instructions("編輯", "simplified", "資料圖表")
        self.assertIn("ignore the earlier 150-180 character target", prompt)
        self.assertIn("<蓋章> is optional", prompt)
        self.assertIn("counts as one of the maximum three points", prompt)

    def test_image_request_defaults_to_1k(self):
        request = ImageGenerateRequest(prompt="test")
        self.assertEqual(request.image_size, "1K")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: Run the tests to verify they fail for the missing density API and current 2K default**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
uv run python -m unittest tests/test_digest_prompts.py -v
```

Expected: FAIL because `build_digest_instructions` does not exist, `GenerateRequest` has no `density`, and the image default is still `2K`.

- [ ] **Step 4: Add the request type and simplified override rules**

In `main.py`, add the type alias and request field:

```python
DigestDensity = Literal["standard", "simplified"]


class GenerateRequest(BaseModel):
    news_text: str
    type_label: str
    role: str = "記者"
    density: DigestDensity = "standard"
```

Change the image default in the same request-model section:

```python
class ImageGenerateRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    provider: Literal["gemini", "gpt"] = "gemini"
    aspect_ratio: str = "16:9"
    image_size: str = "1K"
```

Add this density block after `EDITOR_SYSTEM_PROMPT_TEMPLATE`:

```python
SIMPLIFIED_DENSITY_RULES = """

SIMPLIFIED MODE OVERRIDE — THESE RULES OVERRIDE ANY EARLIER STANDARD-MODE LENGTH OR FORMAT REQUIREMENT:
1. From the source material, dynamically select only 1 to 3 key points. Do not force three points when one or two are enough.
2. Each point must communicate one fact in a short, scan-friendly line. Do not repeat the same fact in the title, points, or conclusion.
3. Remove secondary background, side facts, repeated numbers, and details that do not improve immediate understanding.
4. Use ONE dominant visual focus and choose the best presentation for the material:
   A. one hero map/chart/person/scene/process with up to three short callouts;
   B. one dominant number or conclusion with one or two supporting labels;
   C. one large thematic image/map/scene with text confined to one compact area.
5. Do not add multiple secondary card groups, unnecessary decorative icons, competing focal points, or invented filler text.
6. For editor role, ignore the earlier 150-180 character target. <蓋章> is optional, must appear only when the source supports a clear conclusion or quote, and counts as one of the maximum three points.
"""
```

Add the pure composition helper:

```python
def build_digest_instructions(
    role: str,
    density: DigestDensity,
    type_label: str,
) -> str:
    template = (
        EDITOR_SYSTEM_PROMPT_TEMPLATE if role == "編輯" else SYSTEM_PROMPT_TEMPLATE
    )
    instructions = template.format(type_label=type_label)
    if density == "simplified":
        instructions += SIMPLIFIED_DENSITY_RULES
    return instructions
```

- [ ] **Step 5: Route the endpoint through the composition helper**

Replace the role-template selection at the start of `generate()` with:

```python
@app.post("/api/generate", response_model=GenerateResponse)
def generate(req: GenerateRequest):
    system_prompt = build_digest_instructions(
        role=req.role,
        density=req.density,
        type_label=req.type_label,
    )
```

Leave the OpenAI request, JSON schema, response parsing, and error handling unchanged.

- [ ] **Step 6: Run the backend tests and static checks**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
uv run python -m unittest tests/test_digest_prompts.py -v
python3 -m compileall -q main.py tests
uv lock --check
```

Expected: all six unit tests PASS, compile exits 0, and uv reports the lock is resolved.

- [ ] **Step 7: Commit the backend contract and tests**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
git add main.py tests/test_digest_prompts.py pyproject.toml uv.lock
git commit -m "Add simplified AI digestion prompt mode

Co-Authored-By: Claude <noreply@anthropic.com>"
```

Expected: commit includes only the backend, tests, and already-pending dependency alignment.

---

### Task 2: Add Live, Synchronized Frontend Controls

**Files:**
- Modify: `index.html:124-149`
- Modify: `app.js:294-302`
- Modify: `app.js:332-397`
- Modify: `app.js:675-704`

**Interfaces:**
- Consumes: `GenerateRequest.density` from Task 1.
- Produces: `state.digestDensity`, `switchDigestDensity(density)`, synchronized `switchRole(role)`, and a `/api/generate` body containing `density`.

- [ ] **Step 1: Start the live development servers and keep them running**

Run `./dev.sh` as a background task from the repository root.

Expected endpoints:

- Frontend: `http://localhost:3000`
- Backend OpenAPI: `http://127.0.0.1:8787/openapi.json`

Wait until both URLs respond before editing. Keep this process running through Tasks 2–5 so BrowserSync refreshes `index.html` and `app.js` immediately.

- [ ] **Step 2: Capture the current UI baseline**

Open `http://localhost:3000` and verify before editing:

- The AI card has no density control.
- The existing role selector appears only above the template library.
- Final Prompt Output is already full-width because that pending layout change is preserved.

Expected: this baseline demonstrates the new controls are not yet implemented.

- [ ] **Step 3: Add reusable active styling and the two control groups**

In `index.html`, keep `.role-active` and add:

```css
.density-active {
    background: #2563eb !important;
    color: white !important;
    box-shadow: 0 4px 12px rgba(37, 99, 235, 0.25);
}
```

Between `#aiInput` and `#aiBtn`, add:

```html
<div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
    <div>
        <span class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">文字密度 / Text Density</span>
        <div class="flex bg-black/40 p-1 rounded-lg">
            <button data-density="standard" onclick="switchDigestDensity('standard')"
                    class="density-active flex-1 px-3 py-2 rounded-md text-[10px] font-black transition-all">標準</button>
            <button data-density="simplified" onclick="switchDigestDensity('simplified')"
                    class="flex-1 px-3 py-2 rounded-md text-[10px] font-black text-slate-500 hover:text-white transition-all">簡化</button>
        </div>
    </div>
    <div>
        <span class="block text-[9px] font-black text-slate-500 uppercase tracking-widest mb-2">工作角色 / Role Mode</span>
        <div class="flex bg-black/40 p-1 rounded-lg">
            <button data-role="記者" onclick="switchRole('記者')"
                    class="role-active flex-1 px-3 py-2 rounded-md text-[10px] font-black transition-all">記者</button>
            <button data-role="編輯" onclick="switchRole('編輯')"
                    class="flex-1 px-3 py-2 rounded-md text-[10px] font-black text-slate-500 hover:text-white transition-all">編輯</button>
        </div>
    </div>
</div>
```

Update the existing lower role buttons so both have `data-role` and call `switchRole` without passing `this`:

```html
<button data-role="記者" onclick="switchRole('記者')" class="role-active px-4 py-1.5 rounded-md text-[10px] font-black transition-all">記者</button>
<button data-role="編輯" onclick="switchRole('編輯')" class="px-4 py-1.5 rounded-md text-[10px] font-black text-slate-500 hover:text-white transition-all">編輯</button>
```

- [ ] **Step 4: Add density state and synchronize every control instance**

Extend `state` in `app.js`:

```javascript
let state = {
    chartType: 'data',
    currentRole: '記者',
    digestDensity: 'standard',
    currentTab: 'style',
    engine: 'gemini',
    activeParent: null,
    selectedByType: {}
};
```

Replace `switchRole` and expand the button-label helper:

```javascript
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

function updateAIBtnRoleHint() {
    const buttonText = document.getElementById('aiBtnText');
    const densityLabel = state.digestDensity === 'simplified' ? '簡化' : '標準';
    if (buttonText) {
        buttonText.innerText = `開始 AI 自動消化整理（${state.currentRole}・${densityLabel}）`;
    }
}
```

At the end of `window.onload`, call `updateAIBtnRoleHint()` after `resetToType('data')`.

- [ ] **Step 5: Send density only with AI digestion**

Update the `/api/generate` request body in `handleAIDigestion()`:

```javascript
body: JSON.stringify({
    news_text: input,
    type_label: typeLabel,
    role: state.currentRole,
    density: state.digestDensity
})
```

Do not read `state.digestDensity` in `syncOutput()`, `buildPrompt()`, manual template rendering, or image generation.

- [ ] **Step 6: Run frontend syntax verification**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
node --check app.js
```

Expected: exit 0 with no output.

- [ ] **Step 7: Review the live UI with the user on localhost:3000**

In the live browser, verify:

- Desktop: density and role controls are side-by-side above the full-width red action button.
- Narrow viewport: the two groups stack without clipping.
- Top role switch updates the lower role switch.
- Lower role switch updates the top role switch.
- Button text shows all four combinations.
- Changing density does not alter current manual matrix fields or Final Prompt Output.

Pause here and let the user identify visual changes. Apply requested spacing, wording, button sizing, or responsive adjustments immediately and let BrowserSync refresh the page after each edit.

- [ ] **Step 8: Intercept the API call without using paid services**

Use a Playwright route for `http://127.0.0.1:8787/api/generate`, capture `request.postDataJSON()`, and return:

```json
{
  "style": "Test style",
  "structure": "Test structure",
  "variable": "[標題] 測試"
}
```

Submit once in Standard and once in Simplified. Expected captured bodies:

```json
{"role":"記者","density":"standard"}
```

and:

```json
{"role":"編輯","density":"simplified"}
```

The intercepted response should populate the three frontend fields without contacting OpenAI.

- [ ] **Step 9: Commit the approved frontend interaction**

Run only after the user approves the live layout:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
git add index.html app.js
git commit -m "Add synchronized digestion controls

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Finish 1K Consistency, Ignore Local Mockups, and Fix Ruff

**Files:**
- Modify: `app.js:774-782`
- Modify: `main.py:41-46`
- Modify: `.gitignore:1-9`
- Modify: `notion-templates/tools/build_rep_images.py:3-6`
- Modify: `notion-templates/tools/parse_notion_export.py:72-80`
- Preserve: `editor-templates/PROMPTS.md`
- Preserve: `notion-templates/templates.json`
- Test: `tests/test_digest_prompts.py`

**Interfaces:**
- Consumes: `ImageGenerateRequest` test from Task 1.
- Produces: consistent `1K` Gemini requests and a Ruff-clean Python tree.

- [ ] **Step 1: Change the frontend Gemini request to 1K**

In `handleImageGeneration()`, use:

```javascript
body: JSON.stringify({
    prompt,
    provider,
    aspect_ratio: '16:9',
    image_size: '1K'
})
```

The Task 1 backend test already requires `ImageGenerateRequest(prompt="test").image_size == "1K"`.

- [ ] **Step 2: Ignore visual-companion artifacts**

Append to `.gitignore`:

```gitignore
.superpowers/
```

Run `git status --short` and confirm `.superpowers/` no longer appears.

- [ ] **Step 3: Remove the unused import**

In `notion-templates/tools/build_rep_images.py`, change:

```python
import json
import subprocess
from pathlib import Path
```

- [ ] **Step 4: Rename ambiguous variables without changing parsing behavior**

In `notion-templates/tools/parse_notion_export.py`, replace the three `l` uses with `line`:

```python
indents = [
    len(line) - len(line.lstrip())
    for line in code_lines
    if line.strip()
]
pad = min(indents) if indents else 0
code = "\n".join(
    line[pad:] if len(line) >= pad else line
    for line in code_lines
).strip()
```

and:

```python
plain = "\n".join(
    line.strip()
    for line in body_lines
    if line.strip() and not IMG_REF_RE.search(line)
)
```

- [ ] **Step 5: Verify 1K-normalized reference data**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
python3 - <<'PY'
import json
import re
from pathlib import Path

data = json.loads(Path('notion-templates/templates.json').read_text())
assert data['template_count'] == 205
assert len(data['templates']) == 205
pattern = re.compile(r'(?<![A-Za-z0-9])[24][kK](?![A-Za-z0-9])')

def walk(value):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)
    elif isinstance(value, str):
        yield value

hits = [value for value in walk(data) if pattern.search(value)]
assert not hits, hits[:5]
print('205 templates; no standalone 2K/4K prompt requirements')
PY
```

Expected: `205 templates; no standalone 2K/4K prompt requirements`.

- [ ] **Step 6: Run all consistency checks**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
uv run ruff check main.py tests notion-templates/tools
uv run python -m unittest tests/test_digest_prompts.py -v
node --check app.js
python3 -m compileall -q main.py tests notion-templates/tools
uv lock --check
git diff --check
```

Expected: every command exits 0; Ruff reports no errors.

- [ ] **Step 7: Commit the consistency work**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
git add .gitignore app.js main.py editor-templates/PROMPTS.md notion-templates/templates.json notion-templates/tools/build_rep_images.py notion-templates/tools/parse_notion_export.py
git commit -m "Standardize image output and template references to 1K

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: Refresh README and Handoff Documentation

**Files:**
- Modify: `README.md:11-58`
- Modify: `docs/HANDOFF.md:15-175`

**Interfaces:**
- Consumes: final names and behavior from Tasks 1–3.
- Produces: documentation matching the implemented API, UI, template status, and remaining backlog.

- [ ] **Step 1: Update README with the density request contract**

Keep the existing OpenAI and image-provider setup, and add this section after AI 自動消化:

```markdown
### 文字密度與工作角色

AI 自動消化有兩個獨立設定：

- 工作角色：`記者`／`編輯`
- 文字密度：`標準`／`簡化`

`標準`維持既有整理規則；`簡化`會依素材只保留 1～3 個重點，並在單一主視覺、大數字／結論、主題大圖三種聚焦方式中選擇最適合的呈現。文字密度只影響 AI 自動消化，不會刪減手動輸入內容。
```

Ensure the image section says Gemini uses native `1K` and GPT uses `1280×720`.

- [ ] **Step 2: Replace stale HANDOFF architecture statements**

Update the file-structure section to list `main.py`, `dev.sh`, `notion-templates/`, `editor-templates/`, and both docs files.

Replace the stale AI section with:

```markdown
## 五、AI 消化功能

前端 `handleAIDigestion()` 呼叫本機 FastAPI 的 `/api/generate`；API key 只存在 `.env`，不會送到瀏覽器。後端目前使用 OpenAI Responses API，預設模型由 `OPENAI_DIGEST_MODEL` 控制。

AI 消化有兩個獨立維度：

- 角色：記者／編輯
- 文字密度：標準／簡化

標準模式維持既有規則。簡化模式依素材選擇 1～3 個重點與單一視覺焦點；編輯簡化模式的 `<蓋章>` 改為可選，且計入三點上限。文字密度只影響 AI 消化，不限制手動欄位或最終 Prompt。
```

- [ ] **Step 3: Replace stale template status**

Document these verified facts:

```markdown
- `notion-templates/templates.json`：205 個記者資料庫模板。
- `editor-templates/`：編輯版 Prompt、提案及 130 張參考圖。
- data／scene／map／process 均已加入 Notion 實戰內容；scene／map／process 不再是通用佔位模板。
- 新版 scene／map／process 仍需持續用實際生成圖驗收。
```

- [ ] **Step 4: Replace the backlog with only current work**

Use this order:

```markdown
1. 持續用實際生成圖驗收新版 scene／map／process 模板與四邊安全區。
2. 決定是否新增第五類「人物／小檔案」（目前明確不納入本次功能）。
3. 持續從 Notion 批次匯入或整理精選模板。
4. 模板更新頻率提高後，再評估 Notion 直連階段 B。
```

Add a dated work record for the Standard/Simplified mode, synchronized role controls, and 1K consistency.

- [ ] **Step 5: Check docs for stale contradictions**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
rg -n 'claude-sonnet-4-6|只能在 claude.ai|尚未 App 化|僅有初版模板|AI 消化功能後端化|2K|4K' README.md docs/HANDOFF.md editor-templates/PROMPTS.md
```

Expected: no stale runtime/provider/backlog statements and no active 2K/4K requirements. Historical rollback notes may remain only if clearly marked as history rather than current behavior.

- [ ] **Step 6: Commit documentation**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
git add README.md docs/HANDOFF.md
git commit -m "Refresh AI digestion and template handoff docs

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: End-to-End Verification and Live User Refinement

**Files:**
- Verify: all files changed in Tasks 1–4
- Modify only if required by observed behavior or user feedback

**Interfaces:**
- Consumes: complete backend/UI/documentation implementation.
- Produces: user-approved live behavior and a clean, verified branch.

- [ ] **Step 1: Run the complete automated verification suite fresh**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
uv run python -m unittest tests/test_digest_prompts.py -v
uv run ruff check main.py tests notion-templates/tools
python3 -m compileall -q main.py tests notion-templates/tools
node --check app.js
uv lock --check
git diff --check
```

Expected: zero test failures, zero Ruff errors, and every command exits 0.

- [ ] **Step 2: Verify backend schema without calling AI**

Fetch `http://127.0.0.1:8787/openapi.json` and confirm `/api/generate` exposes:

```json
"density": {
  "enum": ["standard", "simplified"],
  "default": "standard"
}
```

- [ ] **Step 3: Drive every frontend combination on localhost:3000**

Verify in the real browser:

1. 記者＋標準
2. 記者＋簡化
3. 編輯＋標準
4. 編輯＋簡化

For each combination, confirm the action-button label and intercepted request body match. Verify both top and lower role controls can initiate the role change.

- [ ] **Step 4: Verify manual workflows are unaffected**

Enter a deliberately long manual `variable` value, switch between Standard and Simplified, and confirm:

- the manual value remains byte-for-byte unchanged;
- the Final Prompt Output remains unchanged except for unrelated role switching;
- density does not appear in `buildPrompt()` output.

- [ ] **Step 5: Verify desktop and mobile layouts visually with the user**

Keep `localhost:3000` visible to the user. Check at least:

- desktop width around 1440px;
- mobile width around 390px.

Apply user-requested visual refinements immediately, let BrowserSync reload, and repeat until the user approves both layouts. Do not generate paid AI images during this loop.

- [ ] **Step 6: Review the final diff and ensure no local artifacts are staged**

Run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
git status --short
git diff --stat origin/main...HEAD
git diff --check
```

Expected:

- `.env`, `.superpowers/`, caches, and generated bytecode are absent from staged/tracked changes.
- All intended product, test, template, and documentation changes are present.

- [ ] **Step 7: Commit any final user-approved refinements**

If Task 5 produced changes, run:

```bash
cd "/Users/dandanhanbao/Claude Code/Github/TVBS-AICG-PG"
git add index.html app.js main.py tests README.md docs/HANDOFF.md .gitignore notion-templates/tools editor-templates/PROMPTS.md notion-templates/templates.json pyproject.toml uv.lock
git commit -m "Polish simplified digestion workflow

Co-Authored-By: Claude <noreply@anthropic.com>"
```

If there are no Task 5 changes, do not create an empty commit.

- [ ] **Step 8: Present the complete branch diff before pushing**

Show the user:

- commit list;
- changed-file summary;
- automated verification results;
- any verification deliberately skipped;
- confirmation that no paid API was called.

Push only after the user has seen and approved the complete final behavior and diff.
