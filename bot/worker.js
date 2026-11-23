// Телеграм-бот на Cloudflare Workers. Считает пользователей на /start.
// Секреты (Settings -> Variables): BOT_TOKEN, OWNER_ID, APP_URL. KV-привязка: STATS.
async function tg(env, method, body) {
  return fetch(`https://api.telegram.org/bot${env.BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
}

export default {
  async fetch(req, env) {
    if (req.method !== "POST") return new Response("ok");
    if (env.SECRET && req.headers.get("x-telegram-bot-api-secret-token") !== env.SECRET) return new Response("no", { status: 403 });
    const upd = await req.json();
    const m = upd.message;
    if (!m || !m.text) return new Response("ok");
    const id = String(m.from.id), text = m.text.trim();

    if (text.startsWith("/start")) {
      const key = "u:" + id;
      if (!(await env.STATS.get(key))) {
        await env.STATS.put(key, new Date().toISOString());
        const n = Number((await env.STATS.get("total")) || 0) + 1;
        await env.STATS.put("total", String(n));
      }
      await tg(env, "sendMessage", {
        chat_id: m.chat.id,
        text: "Сборщик SBC в FC 27: кристаллы и самая дешёвая сборка за монеты.",
        reply_markup: { inline_keyboard: [[{ text: "Открыть", web_app: { url: env.APP_URL } }]] },
      });
    } else if (text === "/id") {
      await tg(env, "sendMessage", { chat_id: m.chat.id, text: "Ваш ID: " + id });
    } else if (text === "/stats" && id === String(env.OWNER_ID)) {
      const total = (await env.STATS.get("total")) || "0";
      await tg(env, "sendMessage", { chat_id: m.chat.id, text: "Пользователей бота: " + total });
    }
    // /stats от остальных молча игнорируется
    return new Response("ok");
  },
};
