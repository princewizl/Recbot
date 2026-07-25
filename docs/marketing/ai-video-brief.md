# Collxct — HeyGen Ad Playbook

Everything to make a new "Coming August" ad in **HeyGen** — the cheapest tool that does
a **talking owner + voice + captions** from a pasted script. Copy the blocks marked **PASTE**.

- **Tool:** [HeyGen](https://www.heygen.com) — **Free** (3 videos/mo, no card to start) → **$24/mo** (annual) if you need more
- **Format:** 9:16 vertical (1080×1920), ~20s
- **Product:** *Collxct* — turns a business's WhatsApp into a 24/7 ordering machine
  (menu → cart → delivery fee → Paystack payment → **loud order alerts**)
- **Launch line:** *"Going live this August 2026."*
- **Brand look:** near-black `#040a07`, emerald `#34d399 / #10b981 / #059669`, gold `#f5b21c / #fcd34d`

> ⚠️ **The rule that keeps it looking pro:** HeyGen (like all AI video) **can't spell "collxct",
> draw your logo, or show real ₦ prices**. So don't make the AI render the chat or the "AUGUST"
> card. Let the **avatar do the talking**, drop in the **chat demo (`coming-soon.webm`)** as the
> "here's how it works" cutaway, and end on the **poster** — both are pixel-perfect from the HTML
> I already built.

---

## 1. The script (paste into HeyGen's script box)

~20s at a natural pace. Keep the `(cue)` notes as short pauses.

```
(tired) It's 9PM. My kitchen is closing…
but the orders? They never stop coming.
Every missed WhatsApp chat was money — gone.
(hopeful) So I got Collxct.
Now it chats, takes the order, and collects the payment for me — 24 seven.
Then it alerts me, loud, the second an order lands.
Collxct. Your WhatsApp, open twenty-four seven.
Going live this August.
```

**Caption lines** (if you burn in subtitles, keep them short):
`It's 9PM. My kitchen is closing.` · `But the orders never stop.` ·
`Every missed chat was money gone.` · `So I got Collxct.` ·
`It chats, takes the order, collects payment.` · `Then alerts me — the second it lands.` ·
`Collxct — live this August.`

---

## 2. HeyGen — step by step

1. **New video → Portrait 9:16.**
2. **Avatar:** pick a friendly Nigerian / African **male** avatar in an apron (reads as a
   "restaurant owner"). Name him **Chidi**.
3. **Voice:** choose an **African-English / Nigerian-accent** voice; tone *warm, conversational*.
   Set speed to ~0.95x so it doesn't rush.
4. **Script:** paste Section 1. The `(tired)` / `(hopeful)` cues become small natural pauses.
5. **Background:** solid dark `#040a07` (or a dim kitchen scene if available).
6. **Captions:** turn on **auto-captions** → style **bold white**, active-word highlight in
   **emerald `#10b981`**, placed lower-third.
7. **Chat demo cutaway (the important bit):** upload **`coming-soon.webm`** and lay it over the line
   *"it chats, takes the order, collects the payment"* — this is where viewers actually SEE the bot work.
8. **End card:** add **`coming-soon-poster.png`** (or `launch-ad-poster.png`) as the final ~3s so the
   logo + **"AUGUST '26"** is exact. Do **not** let HeyGen draw it.
9. **Export** 1080×1920 MP4.

**15-second cut?** Drop lines 2 and 5 from the script and shorten the cutaway to ~2s.

---

## 3. Brand guardrails & assets

- Spelling is **collxct** (lowercase, gold "x") — overlay the real logo/poster, never AI-typed.
- Currency is **Naira ₦**; don't invent prices — they come from the HTML demo.
- Colours: bg `#040a07`; emerald `#34d399 / #10b981 / #059669`; gold `#f5b21c / #fcd34d`.
- Keep it **calm and premium** — the only "loud" thing is the *alert*, not the edit.
- **Reuse from this folder:** `coming-soon.webm`, `coming-soon-poster.png`,
  `launch-ad.webm`, `launch-ad-poster.png`; wordmark lives in `collxct-flier.html`.

**Naira note:** HeyGen's free tier needs no card to start. If you later upgrade and a Naira card is
declined on the USD plan, try a virtual USD card (e.g. from a Nigerian fintech) or PayPal.
