// Supabase Edge Function "digest": builds each subscriber's morning email from the published briefs and market closes.
// Called on a schedule with the header x-digest-secret = DIGEST_SECRET. Sends through Resend only when RESEND_API_KEY
// and DIGEST_FROM are set; otherwise it returns what it would send (dry run), so it can be checked first.
import { createClient } from "npm:@supabase/supabase-js@2.45.4";
const RAW = "https://raw.githubusercontent.com/martinfgaleano-crypto/signalpoint";
const SITE = "https://martinfgaleano-crypto.github.io/signalpoint/";
const esc = (s: unknown) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]!));
type Brief = { id: string; title: string; summary: string; eventDate: string; source?: { name?: string }; tags?: string[]; es?: { title?: string; summary?: string } };
type Market = { id?: string; name?: string; name_es?: string; series?: [string, number][]; decimals?: number; prefix?: string };
const NAMES: Record<string, [string, string]> = { usdcop: ["Dollar in pesos (TRM)", "Dólar en pesos (TRM)"], colcap: ["Colombian stocks", "Acciones colombianas"], sp500: ["S&P 500", "S&P 500"], nasdaq: ["Nasdaq", "Nasdaq"], dow: ["Dow Jones", "Dow Jones"], us10y: ["10-year Treasury yield", "Bono del Tesoro a 10 años"], brent: ["Brent oil", "Petróleo Brent"], btc: ["Bitcoin", "Bitcoin"], eurusd: ["Euro in dollars", "Euro en dólares"] };

function line(id: string, m: Market, lang: string) {
  const s = m.series ?? []; if (s.length < 2) return "";
  const a = s[s.length - 2][1], b = s[s.length - 1][1], ch = (b / a - 1) * 100;
  const n = (NAMES[id] ?? [m.name ?? id, m.name_es ?? m.name ?? id])[lang === "en" ? 0 : 1];
  const v = b.toLocaleString(lang === "en" ? "en-US" : "es-CO", { maximumFractionDigits: m.decimals ?? 2 });
  const c = (ch >= 0 ? "▲ +" : "▼ ") + ch.toFixed(2).replace(".", lang === "en" ? "." : ",") + "%";
  return `<tr><td style="padding:6px 0">${esc(n)}</td><td style="padding:6px 0;text-align:right">${esc((m.prefix ?? "") + v)}</td><td style="padding:6px 0 6px 12px;text-align:right;color:${ch >= 0 ? "#0E7A37" : "#B42318"}">${c}</td></tr>`;
}
function email(lang: string, watch: string[], briefs: Brief[], markets: Record<string, Market>) {
  const en = lang === "en", ids = (watch.length ? watch : ["usdcop", "colcap", "sp500", "brent"]).filter((i) => markets[i]).slice(0, 6);
  const top = briefs.slice(0, 4).map((b) => {
    const t = en ? b.title : (b.es?.title ?? b.title), s = en ? b.summary : (b.es?.summary ?? b.summary);
    return `<div style="margin:0 0 18px"><a href="${SITE}#briefing" style="color:#111;font-weight:700;font-size:16px;text-decoration:none">${esc(t)}</a><p style="margin:4px 0 0;color:#444;font-size:14px;line-height:1.5">${esc(s.split(". ")[0])}.</p><p style="margin:4px 0 0;color:#777;font-size:12px">${esc(b.source?.name ?? "")}</p></div>`;
  }).join("");
  const subject = en ? `Your markets this morning: ${briefs[0]?.title ?? "SignalPoint"}` : `Tus mercados esta mañana: ${briefs[0]?.es?.title ?? briefs[0]?.title ?? "SignalPoint"}`;
  const html = `<div style="font-family:-apple-system,Segoe UI,Inter,sans-serif;max-width:560px;margin:0 auto;padding:24px;color:#111">
<p style="margin:0 0 4px;font-weight:700">SignalPoint</p><h1 style="font-size:22px;margin:0 0 16px">${en ? "Your morning, in one minute" : "Tu mañana, en un minuto"}</h1>
<table style="width:100%;border-collapse:collapse;font-size:14px;margin:0 0 20px">${ids.map((i) => line(i, markets[i], lang)).join("")}</table>
<h2 style="font-size:15px;margin:0 0 10px">${en ? "The news behind the numbers" : "Las noticias detrás de los números"}</h2>${top}
<p style="margin:20px 0"><a href="${SITE}" style="background:#2F5BFF;color:#fff;padding:12px 18px;border-radius:999px;text-decoration:none;font-weight:600">${en ? "Open SignalPoint" : "Abrir SignalPoint"}</a></p>
<p style="color:#777;font-size:12px;line-height:1.5">${en ? "Last market closes, not real time. Not investment advice. You get this because you turned on the morning summary; turn it off in your account." : "Últimos cierres, no tiempo real. No es asesoría de inversión. Lo recibes porque activaste el resumen de la mañana; puedes apagarlo en tu cuenta."}</p></div>`;
  return { subject, html };
}
Deno.serve(async (req) => {
  if (req.headers.get("x-digest-secret") !== Deno.env.get("DIGEST_SECRET") || !Deno.env.get("DIGEST_SECRET")) return new Response("forbidden", { status: 403 });
  const admin = createClient(Deno.env.get("SUPABASE_URL")!, Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!, { auth: { persistSession: false } });
  const [lb, lm] = await Promise.all([fetch(`${RAW}/drafts/live/briefs-live.json`).then((r) => r.json()).catch(() => ({ briefs: [] })), fetch(`${RAW}/data/markets-live.json`).then((r) => r.json()).catch(() => ({}))]);
  const briefs: Brief[] = (lb.briefs ?? []).filter((b: Brief) => !(lb.retracted ?? []).includes(b.id));
  const markets: Record<string, Market> = lm.markets ?? lm;
  const today = new Date().toISOString().slice(0, 10);
  const { data: subs } = await admin.from("digest_subs").select("*").eq("enabled", true).or(`last_sent.is.null,last_sent.lt.${today}`).limit(500);
  const key = Deno.env.get("RESEND_API_KEY"), from = Deno.env.get("DIGEST_FROM");
  const out: unknown[] = [];
  for (const s of subs ?? []) {
    const m = email(s.lang, s.watch ?? [], briefs, markets);
    if (!key || !from) { out.push({ to: s.email, subject: m.subject, dry_run: true }); continue; }
    const r = await fetch("https://api.resend.com/emails", { method: "POST", headers: { Authorization: `Bearer ${key}`, "Content-Type": "application/json" }, body: JSON.stringify({ from, to: s.email, subject: m.subject, html: m.html }) });
    if (r.ok) await admin.from("digest_subs").update({ last_sent: today }).eq("user_id", s.user_id);
    out.push({ to: s.email, status: r.status });
  }
  return new Response(JSON.stringify({ sent: out.length, results: out.slice(0, 50) }), { headers: { "Content-Type": "application/json" } });
});
