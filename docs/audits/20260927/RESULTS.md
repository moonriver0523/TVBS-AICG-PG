# 2026-09-27 網頁架構體檢：驗證紀錄

對應 [完整計畫書](../../plan-20260927-web-architecture-refactor-audit.md)。基準 commit：`0d38ecdc0ddeb1cc09c62b6a7724b1b325f30f1e`，產品 `260927-01`。僅新增評估文件與重現腳本，產品程式未修改。

## 環境與安全隔離

| 項目 | 本輪使用 | 專案宣告／限制 |
|---|---|---|
| OS | Windows，PowerShell | 不是 Linux 正式容器 |
| Python | 3.11.15 | `pyproject.toml` 及 `.python-version` 要求 3.14；repo `.venv` 無法啟動 |
| Node | 24.18.0 | 用於語法檢查與 VM 行為重現 |
| FastAPI | 0.133.1 | 專案要求 >=0.139.0 |
| OpenAI SDK | 2.24.0 | 專案要求 >=2.26.0 |
| Pillow | 12.2.0 | 專案要求 >=12.3.0 |
| httpx | 0.28.1 | 同宣告下限 |
| Pydantic / Starlette | 2.13.4 / 1.3.1 | 非依本專案 lockfile 建立的環境 |

`offline_checks.py` 在匯入應用之前停用 dotenv 讀取、清除憑證類環境值、注入假 API key、停用真實稽核／GCS 設定、以暫存目錄接住 request log。audit hook 阻止外部 socket connect；Windows asyncio 內部喚醒使用的 loopback 連線保留。前端重現全部使用假的 fetch 與假 token，沒有外部請求。

此腳本是本機評估工具，不是全面安全沙箱；未來新增會自行啟動外部子程序的測試，仍需在 CI 層封鎖對外網路。

## 已執行的缺陷重現

指令：

```powershell
node docs/audits/20260927/frontend_repro.cjs
python docs/audits/20260927/offline_checks.py
```

實際輸出的關鍵部分：

```text
AUD-02 {"clearedBeforeReply":true,"actual":"old-result","defect_reproduced":true}
AUD-03 {"request_count":2,"defect_reproduced":true}
AUD-03-order {"actual":"older-result","defect_reproduced":true}
AUD-05 {"source":"undo-source","display":"restamped-old-version","defect_reproduced":true}
AUD-06 {"external_requests_with_dummy_token":2,"defect_reproduced":true}
AUD-04 {'expected_news': 'article-A', 'actual_news': 'article-B', 'defect_reproduced': True}
AUD-01 {'backup_count': 1, 'not_excluded_count': 1, 'defect_reproduced': True}
AUD-07 {'ticker_expected_ms': 10, 'ticker_actual_ms': 109, 'defect_reproduced': True}
```

AUD-07 的毫秒數隨排程略變；腳本以 >90ms 判定 100ms 同步替身是否阻塞 ticker。AUD-01 只比對當前簡單 `.dockerignore` 規則與檔名，不讀備份內容，也不代替最終映像檢查。其餘案例在實際函式層重現，尚須在真瀏覽器及正式 runtime 補驗。

`defect_reproduced=true` 代表確認當前不正確行為，並非「已修復」。重現腳本故意不掛入 `tests/test_*.py`；後續修正應建立斷言正確行為的回歸測試。

## 全套測試基線

執行：`python docs/audits/20260927/offline_checks.py suite`。

最終結果：**2,448 項，2,447 通過、1 預期失敗；0 failures、0 errors、0 skipped、0 unexpected successes。** runner 總時間 170.9 秒，unittest 本身 169.068 秒，程序 exit code 0。

```text
AUDIT_SUMMARY {'run': 2448, 'failures': 0, 'errors': 0, 'skipped': 0,
 'expected_failures': 1, 'unexpected_successes': 0, 'seconds': 170.9}
Ran 2448 tests in 169.068s
OK (expected failures=1)
```

這表示現有回歸套件在替代環境沒有非預期失敗，不表示本輪發現的七項問題已經解決，更不等同正式環境全綠。

過程更正：

1. 最早的隔離嘗試禁止所有 socket，連 Windows asyncio 的本機喚醒也受影響，該次已中止，結果不採用。
2. 第一輪完整執行 2,448 項、164.9 秒，出現 1 failure／7 errors。原因是 runner 把 `REQUEST_LOG=0`，導致預期有紀錄的測試找不到檔案；這是本輪測試設定造成，不能登記成八個產品缺陷。
3. 修正為啟用 request log 並寫入暫存目錄，重新完整執行；最終結果以上方紀錄為準。

既有 expected failure：`test_b71_simplified_char_gap_20260916.B71ObservedLeakTests.test_the_observed_leak_pian_is_not_yet_rejected`。它記錄簡體「骗」未被品質守門攔截，屬已列管 B71，不納入本輪 AUD-01～07 計數，也不能把它描述成通過。

本地完整輸出保存在被 git 忽略的 `scripts/output/architecture-audit-20260927/unittest-corrected.txt`，本文件保留可供版控的結果摘要；沒有將完整執行 log 或任何真實金鑰內容加入文件。

## 其他檢查

- `node --check app.js`：通過。
- `node --check hybrid.js`：通過。
- `node --check static/auth-bootstrap.js`：通過。
- Python 根目錄應用程式與 `tests/test_*.py` 共 163 個檔案：在 Python 3.11 執行 compile-only 檢查通過，不代表 Python 3.14／依賴整合測試已通過。
- 文件中的本輪引用行號與規模統計取自當前工作目錄；codebase graph 的 snippet 行號存在偏移，未直接採信。

## 未執行項目

正式站／現役映像檢查、實際瀏覽器 E2E、付費模型生成、Linux／Python 3.14 lockfile 回歸、跨執行個體壓測、第三方 CVE 掃描、真實儲存故障及備份還原。這些已納入計畫波次及驗收矩陣，不以本次離線結果宣稱通過。
