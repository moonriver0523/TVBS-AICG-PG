/*
  Clerk 登入引導（2026-08-25）。index.html 與 hybrid.html 共用。

  稽核需求要每一筆生成都對得到人，後端 middleware 會擋掉沒有 session 的 API 請求，
  這支負責兩件事：(1) 讓使用者登得進去，(2) 把登入權杖自動附到每一個 API 呼叫上。

  刻意不改 app.js／hybrid.js：兩支合計一萬多行、共 9 個 fetch 呼叫點，逐一改成
  async 取權杖的風險遠高於在這裡包一層 fetch。包 fetch 的作法對它們完全透明。

  必須在 app.js／hybrid.js 之前載入，否則它們發出的請求會來不及被包到。

  沒設 CLERK_PUBLISHABLE_KEY 的部署（本機開發、舊環境）會拿到 enabled:false，
  整支等於不存在，維持原本行為。

  放在 /static/ 而不是新增一條路由：該路徑已經掛載且免登入可取，
  少一個要維護的端點，也不會被登入門擋住（擋住就變成雞生蛋的死結）。
*/
(function () {
  var config = fetch("/auth-config.json")
    .then(function (r) { return r.json(); })
    .catch(function () { return { enabled: false }; });

  function token() {
    var clerk = window.Clerk;
    if (!clerk || !clerk.session) return Promise.resolve("");
    return clerk.session.getToken().catch(function () { return ""; });
  }

  // 立刻換掉 fetch，確保稍後載入的前端主檔發出的請求都已經帶得到權杖。
  var original = window.fetch.bind(window);
  window.fetch = function (input, init) {
    return config.then(function (cfg) {
      if (!cfg.enabled) return original(input, init);
      var url = typeof input === "string" ? input : (input && input.url) || "";
      var mine = url.indexOf("/") === 0 || url.indexOf(location.origin) === 0;
      if (!mine) return original(input, init);
      return token().then(function (value) {
        if (!value) return original(input, init);
        var next = {};
        for (var k in init || {}) next[k] = init[k];
        var headers = new Headers((init && init.headers) || undefined);
        headers.set("Authorization", "Bearer " + value);
        next.headers = headers;
        return original(input, next);
      });
    });
  };

  function overlay(message, mountSignIn) {
    // 兩條觸發路徑（DOMContentLoaded 與已載入完成）只能有一個生效。
    if (document.getElementById("aicg-login-gate")) return;
    var box = document.createElement("div");
    box.id = "aicg-login-gate";
    box.style.cssText =
      "position:fixed;inset:0;z-index:9999;background:#0b0f19;color:#fff;" +
      "display:flex;flex-direction:column;align-items:center;justify-content:center;" +
      "gap:20px;font-family:'Noto Sans TC',sans-serif;text-align:center;padding:24px";
    var title = document.createElement("div");
    title.style.cssText = "font-size:18px;font-weight:700";
    title.textContent = message;
    var slot = document.createElement("div");
    box.appendChild(title);
    box.appendChild(slot);
    document.body.appendChild(box);
    if (mountSignIn) window.Clerk.mountSignIn(slot);
  }

  function gate() {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", function () {
        overlay("請以公司帳號登入後使用", true);
      });
    } else {
      overlay("請以公司帳號登入後使用", true);
    }
  }

  config.then(function (cfg) {
    if (!cfg.enabled) return;
    var script = document.createElement("script");
    script.async = true;
    script.crossOrigin = "anonymous";
    script.setAttribute("data-clerk-publishable-key", cfg.publishableKey);
    script.src =
      "https://" + cfg.frontendApi + "/npm/@clerk/clerk-js@5/dist/clerk.browser.js";
    script.onerror = function () {
      overlay("登入服務載入失敗，請重新整理或聯絡管理者", false);
    };
    script.onload = function () {
      window.Clerk.load().then(function () {
        if (window.Clerk.user) return;
        gate();
      });
    };
    document.head.appendChild(script);
  });
})();
