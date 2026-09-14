"""0-2 標題／內文字數量測：直接呼叫 build_digest_instructions／digest_completion。

不走 /api/generate（避免 DIGEST_TWO_STAGE 分類、肖像重消化、生圖）。
預設乾跑：只組 prompt、印 system_prompt 長度與預算，零模型呼叫。
真呼叫必須明確加 --go（消化 $，不是每張 $0.04 的圖）。

矩陣（2026-09-14 裁決）：3 則 × 4 density（無 verbatim）× 2 角色＝24。
長稿＋編輯走播出鏡面。type_label 固定自動判斷。

用法：
    python scripts/measure_title_length.py
    python scripts/measure_title_length.py --backend native --calibrate --go
    python scripts/measure_title_length.py --backend native --go
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_FIXTURE = SCRIPT_DIR / "fixtures" / "title-length-news.json"
DEFAULT_OUT = Path(r"D:\Downloads\AICG\後台紀錄\20260914\title_length_measure.json")

DENSITIES = ("minimal", "simplified", "standard", "maximum")
ROLES = ("記者", "編輯")
CALIBRATE_KEYS = ("short/minimal/記者", "long/maximum/編輯")

HIST_CONTENT_LO = 872
HIST_CONTENT_HI = 1259

TITLE_BLOCK_RE = re.compile(
    r"\[標題\](.*?)(?=\[內文小標\]|<蓋章>|<底帶>|\Z)", re.S
)
BODY_BLOCK_RE = re.compile(
    r"\[內文小標\](.*?)(?=\[內文小標\]|<蓋章>|<底帶>|\Z)", re.S
)
CJK_RE = re.compile(r"[\u3400-\u9fff\uf900-\ufaff]")

# 延後 import：DIGEST_BACKEND 在 import main 當下就定死。
main = None
editor_formats = None
TYPE_LABEL = "自動判斷"


def load_app(backend: str | None) -> None:
    global main, editor_formats, TYPE_LABEL
    if backend:
        os.environ["DIGEST_BACKEND"] = backend
    if backend == "native":
        # 原生不吃 OpenRouter slug；沒有 OPENAI_API_KEY 時 main.OpenAI() 仍能建 client，
        # 但 --go 會 401。test-key 只給乾跑用。
        os.environ.setdefault("OPENAI_API_KEY", "test-key")
    else:
        os.environ.setdefault("OPENAI_API_KEY", "test-key")
    import editor_formats as ef  # noqa: PLC0415
    import main as m  # noqa: PLC0415

    editor_formats = ef
    main = m
    TYPE_LABEL = m.AUTO_TYPE_LABEL


def estimate_tokens(text: str) -> int:
    """中文約 1 token／字（o200k 註解）；其餘按 4 字元 1 token。"""
    cjk = other = 0
    for ch in text:
        o = ord(ch)
        if 0x3400 <= o <= 0x9FFF or 0xF900 <= o <= 0xFAFF or 0xFF00 <= o <= 0xFFEF:
            cjk += 1
        else:
            other += 1
    return cjk + (other + 3) // 4


def cjk_count(text: str) -> int:
    return len(CJK_RE.findall(text))


def chars_no_ws(text: str) -> int:
    return len(re.sub(r"\s+", "", text))


def load_samples(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    samples = data["samples"]
    if len(samples) != 3:
        raise SystemExit(f"fixture 需要剛好 3 則，實際 {len(samples)}")
    return samples


def editor_format_for(role: str, sample_id: str) -> str:
    if role == "編輯" and sample_id == "long":
        return "broadcast"
    return editor_formats.DEFAULT_FORMAT


def cell_key(row: dict) -> str:
    return f"{row['sample']}/{row['density']}/{row['role']}"


def assemble(sample: dict, density: str, role: str) -> dict:
    news_text = sample["news_text"]
    sample_id = sample["id"]
    fmt = editor_format_for(role, sample_id)
    full_bleed, _, _ = main.resolve_frame_plan(role, safe_frame=False)
    system_prompt = main.build_digest_instructions(
        role=role,
        density=density,
        type_label=TYPE_LABEL,
        full_bleed=full_bleed,
        user_instruction="",
        exclude_people=[],
        asis_reference_count=0,
        stamp=True,
        editor_format=fmt,
        hole_side="left",
        visual_creativity=0,
    )
    budget = main.digest_token_budget(TYPE_LABEL, density, news_text)
    schema = main.digest_schema(TYPE_LABEL)
    user_msg = f'News Source Material:\n"{news_text}"'
    schema_json = json.dumps(schema, ensure_ascii=False)
    reasoning = main.digest_reasoning_body(budget)
    reasoning_max = (reasoning.get("reasoning") or {}).get("max_tokens") or 0
    est_in = (
        estimate_tokens(system_prompt)
        + estimate_tokens(user_msg)
        + estimate_tokens(schema_json)
    )
    if density == "verbatim":
        quoted_out_hi = min(budget, estimate_tokens(news_text) + 800 + reasoning_max)
        quoted_out_lo = estimate_tokens(news_text) + 400
    else:
        quoted_out_lo = HIST_CONTENT_LO + min(reasoning_max or 0, 560)
        quoted_out_hi = HIST_CONTENT_HI + (reasoning_max or 0)
    return {
        "sample": sample_id,
        "density": density,
        "role": role,
        "type_label": TYPE_LABEL,
        "editor_format": fmt,
        "full_bleed": full_bleed,
        "news_chars": chars_no_ws(news_text),
        "system_prompt_chars": len(system_prompt),
        "system_prompt_est_tokens": estimate_tokens(system_prompt),
        "user_est_tokens": estimate_tokens(user_msg),
        "schema_est_tokens": estimate_tokens(schema_json),
        "budget": budget,
        "reasoning_max": reasoning_max,
        "est_input_tokens": est_in,
        "quoted_out_lo": quoted_out_lo,
        "quoted_out_hi": quoted_out_hi,
        "_system_prompt": system_prompt,
        "_news_text": news_text,
        "_schema": schema,
    }


def parse_variable(variable: str) -> dict:
    title_m = TITLE_BLOCK_RE.search(variable or "")
    title_raw = title_m.group(1) if title_m else ""
    title_stripped = title_raw.strip()
    title_lines = [ln for ln in title_raw.splitlines() if ln.strip()]
    bodies = []
    for m in BODY_BLOCK_RE.finditer(variable or ""):
        block = m.group(1)
        bodies.append(
            {
                "chars": chars_no_ws(block),
                "cjk": cjk_count(block),
                "raw": block.strip(),
            }
        )
    return {
        "title_chars": chars_no_ws(title_stripped),
        "title_cjk": cjk_count(title_stripped),
        "title_lines": len(title_lines),
        "title_raw": title_stripped,
        "body_count": len(bodies),
        "body_chars": [b["chars"] for b in bodies],
        "body_cjk": [b["cjk"] for b in bodies],
        "body_chars_total": sum(b["chars"] for b in bodies),
    }


def usage_fields(response, budget: int, requested_model: str) -> dict:
    usage = getattr(response, "usage", None)
    prompt = getattr(usage, "prompt_tokens", None) or 0
    completion = getattr(usage, "completion_tokens", None) or 0
    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None) if details else None
    finish = response.choices[0].finish_reason if response.choices else "?"
    provider = (getattr(response, "model_extra", None) or {}).get("provider") or "-"
    ratio = completion / budget if budget else 0.0
    returned_model = getattr(response, "model", None) or requested_model
    return {
        "site": "measure_title_length",
        "model": returned_model,
        "model_requested": requested_model,
        "provider": provider,
        "budget": budget,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "reasoning_tokens": reasoning,
        "ratio": round(ratio, 2),
        "finish_reason": finish,
    }


def run_live(row: dict) -> dict:
    model = main.resolve_digest_model()
    response = main.digest_completion(
        model=model,
        system_prompt=row["_system_prompt"],
        news_text=row["_news_text"],
        max_output_tokens=row["budget"],
        schema_name="news_cg_digest",
        schema=row["_schema"],
        site="measure_title_length",
    )
    # digest_completion 內部已 log_digest_usage
    usage = usage_fields(response, row["budget"], model)
    raw = response.choices[0].message.content or ""
    finish = usage["finish_reason"]
    public = {k: v for k, v in row.items() if not k.startswith("_")}
    if finish == "length":
        return {**public, **usage, "usable": False, "skip_reason": "finish_reason=length"}
    try:
        data = main.parse_digest_json(raw)
    except (json.JSONDecodeError, IndexError, TypeError) as exc:
        return {**public, **usage, "usable": False, "skip_reason": f"parse_failed:{exc}"}
    variable = main.strip_wrapping_quotes(data.get("variable") or "")
    parsed = parse_variable(variable)
    return {
        **public,
        **usage,
        **parsed,
        "usable": True,
        "chart_type": data.get("chart_type") or "",
    }


def print_dry_run(rows: list[dict]) -> None:
    densities = sorted({r["density"] for r in rows})
    print("=== 乾跑，未呼叫任何模型 ===")
    print(
        f"矩陣 {len(rows)} 格＝{len({r['sample'] for r in rows})} 則 × "
        f"{len(densities)} density × {len({r['role'] for r in rows})} 角色"
    )
    print(f"type_label={TYPE_LABEL}  stamp=True  asis=0  creativity=0")
    print(f"digest model（若 --go）={main.resolve_digest_model()}")
    print(
        f"DIGEST_BACKEND={main.DIGEST_BACKEND}  "
        f"TWO_STAGE={main.DIGEST_TWO_STAGE}（本腳本不走分類器）  "
        f"reasoning_body={main.digest_reasoning_body(10000) or '（不送，思考不封頂）'}"
    )
    print()
    hdr = (
        f"{'sample':<6} {'dens':<12} {'role':<4} {'fmt':<10} "
        f"{'news':>5} {'sys字':>6} {'sys≈tok':>8} {'in≈':>6} "
        f"{'budget':>7} {'reas':>5}"
    )
    print(hdr)
    tot_in = 0
    for r in rows:
        print(
            f"{r['sample']:<6} {r['density']:<12} {r['role']:<4} {r['editor_format']:<10} "
            f"{r['news_chars']:>5} {r['system_prompt_chars']:>6} "
            f"{r['system_prompt_est_tokens']:>8} {r['est_input_tokens']:>6} "
            f"{r['budget']:>7} {r['reasoning_max']:>5}"
        )
        tot_in += r["est_input_tokens"]
    print()
    print(f"合計 est_input ≈ {tot_in} token")
    print("長稿＋編輯的 editor_format=broadcast；其餘 default。verbatim 已移出。")
    print("確認範圍後再加 --go。")


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="標題／內文字數量測（消化，不生圖）")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--go", action="store_true", help="真的呼叫消化 API（預設只乾跑）")
    parser.add_argument(
        "--backend",
        choices=("openrouter", "native"),
        help="覆寫 DIGEST_BACKEND（須在 import main 之前生效）",
    )
    parser.add_argument(
        "--calibrate",
        action="store_true",
        help="只跑最便宜＋最貴兩格：short/minimal/記者 與 long/maximum/編輯",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        metavar="sample/density/role",
        help="只跑指定格，可重複",
    )
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    load_app(args.backend)

    samples = load_samples(args.fixture)
    rows = [
        assemble(sample, density, role)
        for sample in samples
        for density in DENSITIES
        for role in ROLES
    ]
    wanted = list(args.only)
    if args.calibrate:
        wanted.extend(CALIBRATE_KEYS)
    if wanted:
        wanted_set = set(wanted)
        rows = [r for r in rows if cell_key(r) in wanted_set]
        missing = wanted_set - {cell_key(r) for r in rows}
        if missing:
            raise SystemExit(f"找不到格子：{sorted(missing)}")

    if not args.go:
        print_dry_run(rows)
        return

    if args.backend == "native" and os.getenv("OPENAI_API_KEY") in ("", "test-key", None):
        raise SystemExit("DIGEST_BACKEND=native 但 OPENAI_API_KEY 不是真鑰，中止")

    print(
        f"--go：digest_completion × {len(rows)}  "
        f"backend={main.DIGEST_BACKEND} model={main.resolve_digest_model()}  不生圖",
        flush=True,
    )
    results = []
    for i, row in enumerate(rows, 1):
        label = cell_key(row)
        print(f"\n▶ {i}/{len(rows)} {label} …", flush=True)
        try:
            results.append(run_live(row))
        except Exception as exc:  # 單格失敗不中斷矩陣
            results.append(
                {
                    **{k: v for k, v in row.items() if not k.startswith("_")},
                    "usable": False,
                    "skip_reason": f"call_failed:{exc}",
                    "model": main.resolve_digest_model(),
                }
            )
            print(f"  失敗：{exc}", flush=True)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    usable = [r for r in results if r.get("usable")]
    payload = {
        "note": "非正式站模型；數字帶此前提。正式站是 OpenRouter anthropic/claude-sonnet-5。",
        "backend": main.DIGEST_BACKEND,
        "model_requested": main.resolve_digest_model(),
        "reasoning_capped": bool(main.digest_reasoning_body(10000)),
        "n": len(results),
        "usable": len(usable),
        "unusable": len(results) - len(usable),
        "rows": results,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n寫入 {args.out}  usable={len(usable)}/{len(results)}")


if __name__ == "__main__":
    main_cli()
