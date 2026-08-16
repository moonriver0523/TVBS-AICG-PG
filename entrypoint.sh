#!/bin/sh
set -e

# app.js / hybrid.js 裡的 _INTERNAL_API_KEY 進 git 時只是占位符，
# 這裡在容器啟動時換成 Secret Manager 注入的真實值，真實 Key 不進公開 repo。
if [ -n "$NEWS_IMAGE_API_KEY" ]; then
    sed -i "s#__NEWS_IMAGE_API_KEY__#${NEWS_IMAGE_API_KEY}#g" app.js hybrid.js
fi

exec uvicorn main:app --host 0.0.0.0 --port "${PORT:-8080}"
