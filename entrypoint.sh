#!/bin/sh
set -e

# app.js / hybrid.js 裡的 _INTERNAL_API_KEY 進 git 時只是占位符，
# 這裡在容器啟動時換成 Secret Manager 注入的真實值，真實 Key 不進公開 repo。
# 2026-08-25：啟用 Clerk 時**絕對不能**做這個代換。
# 這個 sed 是就地改磁碟上的檔案，改完就回不去了；而啟用 Clerk 後 app.js／hybrid.js
# 是公開可取的（不公開就載不進來，見 main.py 的 CLERK_PUBLIC_PATHS），
# 代換等於把金鑰送給任何訪客——實測確實外洩過。
# 啟用 Clerk 時前端不需要這把金鑰，改用登入權杖（verify_internal_api_key 兩種都收）。
if [ -n "$NEWS_IMAGE_API_KEY" ] && [ -z "$CLERK_PUBLISHABLE_KEY" ]; then
    sed -i "s#__NEWS_IMAGE_API_KEY__#${NEWS_IMAGE_API_KEY}#g" app.js hybrid.js
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8080}"
