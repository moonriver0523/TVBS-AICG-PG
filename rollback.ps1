# 一鍵回滾 Cloud Run 到上一個 revision。
#
# 為什麼需要這支：Cloud Run 每次部署都會留下舊 revision，回滾只是把流量切回去，
# 不用重新建置（幾秒鐘的事）。但那串指令沒人記得住，出事時最需要的就是不用想。
#
# 用法：
#   .\rollback.ps1              → 切回「上一個」revision（目前服務中的前一個）
#   .\rollback.ps1 -Revision tvbs-aicg-linebot-00022-95m  → 切回指定 revision
#   .\rollback.ps1 -List        → 只列出可選的 revision，不動流量
#
# 已知良好版本（2026-08-18 肖像放寬熱修「之前」的線上版）：
#   tvbs-aicg-linebot-00022-95m
#
# 注意：回滾只換程式碼，不會動環境變數（那些設在服務上，跨 revision 共用）。

param(
    [string]$Revision = "",
    [switch]$List
)

$ErrorActionPreference = "Stop"

$Service = "tvbs-aicg-linebot"
$Region = "asia-east1"
$Gcloud = "$env:LOCALAPPDATA\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd"
if (-not (Test-Path $Gcloud)) {
    $found = Get-Command gcloud -ErrorAction SilentlyContinue
    if (-not $found) { throw "找不到 gcloud，請確認 Google Cloud SDK 已安裝" }
    $Gcloud = $found.Source
}

$current = & $Gcloud run services describe $Service --region $Region `
    --format="value(status.traffic[0].revisionName)"
Write-Host "目前服務中：$current"

$all = & $Gcloud run revisions list --service $Service --region $Region `
    --format="value(metadata.name)" --sort-by="~metadata.creationTimestamp"

if ($List) {
    Write-Host "`n可回滾的 revision（新到舊）："
    $all | ForEach-Object { if ($_ -eq $current) { "  $_  ← 目前服務中" } else { "  $_" } }
    exit 0
}

if (-not $Revision) {
    # 「上一個」＝ 目前服務中的那個之後、時間最近的一個
    $Revision = $all | Where-Object { $_ -ne $current } | Select-Object -First 1
    if (-not $Revision) { throw "只有一個 revision，沒有可以回滾的目標" }
}

Write-Host "準備把 100% 流量切到：$Revision"
& $Gcloud run services update-traffic $Service --region $Region `
    --to-revisions="$Revision=100" --quiet

$now = & $Gcloud run services describe $Service --region $Region `
    --format="value(status.traffic[0].revisionName)"
Write-Host "`n完成。目前服務中：$now"
Write-Host "要再切回去：.\rollback.ps1 -Revision $current"
