# Deploying Recbot to the Collxct Server (same domain, port 8443)

## Important correction from earlier

Collxct, as documented in your existing deploy guide, is **a different, already-running application** — Flask + Postgres + Redis + Celery, Monnify for payments, Meta's native WhatsApp Cloud API for messaging, deployed from `github.com/princewizl/collxct` to `/opt/collxct` on a Contabo VPS at `collxct.com.ng`, with its own `nginx` container owning host ports 80/443 as part of that stack. This Recbot app is FastAPI + SQLite + Paystack + Twilio — a separate codebase. They are **not** the same running app, despite the `COLLXCT-` string that shows up in this app's Paystack payment references (that was a naming coincidence, not evidence of shared deployment).

This guide deploys Recbot **alongside** Collxct on the same physical server, under the same domain, on a new port (**8443**), without touching Collxct's live nginx container or config at all.

## How this works

Recbot runs as its own, fully independent docker-compose stack in `/opt/recbot` (a sibling directory to `/opt/collxct`). It has its own tiny `nginx:alpine` sidecar container that:
- Terminates TLS on port **8443**, using the **same Let's Encrypt certificate** already issued for `collxct.com.ng` (mounted read-only from `/etc/letsencrypt` — certs aren't port-bound, so reusing them for a second, independent process is completely normal)
- Reverse-proxies to the Recbot app container over Recbot's own internal docker network

Zero edits to Collxct's `docker-compose.yml` or `nginx.conf`. The only shared-infrastructure touch is one extra line added to certbot's renewal hook (step 6) so this sidecar also reloads when the cert renews.

**Verified locally before writing this guide:** built the image, ran the full two-container stack with a self-signed cert standing in for the real one, confirmed `/health` and `/webhook` respond correctly through the TLS-terminated sidecar, and confirmed Twilio signature verification works correctly against the non-standard port (this required a fix — see the note in step 4).

## 0. Before you start

⚠️ Unrelated but worth knowing: your local `C:\Users\Olufemi` has a `git init` at the **home directory** level (not scoped to any project), with `origin` already pointed at `github.com/princewizl/kiosk_app.git` and zero commits. A stray `git push` from there would try to push your entire home folder. I haven't touched it — fix it when convenient (delete that `.git`, `git init` fresh inside a real project folder). This guide uses `rsync`, not git, for the same reason — Recbot doesn't have its own scoped repo yet either. Once you set one up, you can switch to the same deploy-key + `git pull` pattern Collxct already uses.

## 1. Copy the code to the server

```bash
rsync -avz --exclude='.venv' --exclude='.venv-1' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='bot.db' --exclude='.env' \
  "C:/Users/Olufemi/Documents/PROJECTS/Recbot/" root@<server-ip>:/opt/recbot/
```

## 2. Configure environment

```bash
ssh root@<server-ip>
cd /opt/recbot
cp .env.example .env
nano .env
```

Fill in:
- `SECRET_KEY` — `openssl rand -hex 32`
- `ADMIN_EMAIL` / `ADMIN_PASSWORD` — real admin login
- `PAYSTACK_SECRET_KEY`, `PAYSTACK_CALLBACK_URL` → `https://collxct.com.ng:8443/paystack/webhook`
- `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER`
- `PUBLIC_PORT` — leave as `8443` unless that's taken (check with `ss -ltnp`)

If `collxct.com.ng` isn't actually the right domain, edit `nginx/recbot.conf` — the `server_name` and both `ssl_certificate*` paths are hardcoded there (deliberately not templated, to avoid a real gotcha with nginx's auto-templating envsubst feature mangling nginx's own `$host`/`$remote_addr` variables).

## 3. Build and start

```bash
docker compose up -d --build
docker compose ps          # both "recbot" and "nginx" should show healthy
curl -s http://127.0.0.1:8443/health   # will fail — this port is HTTPS only
curl -sk https://127.0.0.1:8443/health # -k because no real hostname match yet locally
```

Expect `{"status":"ok"}` on the `https` + `-k` curl.

## 4. Verify Twilio signature checking works on this port

This matters: Twilio signs the *exact* URL it calls, including the port when it's non-default (like 8443). The nginx sidecar sends `X-Forwarded-Port` and the app reconstructs the URL from it — already fixed and tested, but if you ever change the port or the nginx config, re-verify:

```bash
docker compose exec recbot python3 -c "
from twilio.request_validator import RequestValidator
v = RequestValidator('<your TWILIO_AUTH_TOKEN>')
print(v.compute_signature('https://collxct.com.ng:8443/webhook', {'From':'whatsapp:+2348012345678','To':'whatsapp:+14155238886','Body':'hi'}))
"
# then curl -sk -X POST https://127.0.0.1:8443/webhook -H "Host: collxct.com.ng" \
#   -H "X-Twilio-Signature: <signature from above>" \
#   -d "From=whatsapp:%2B2348012345678&To=whatsapp:%2B14155238886&Body=hi"
# should NOT return "Invalid Twilio signature"
```

## 5. DNS check (should already be true — same domain as Collxct)

`collxct.com.ng` already resolves to this server for Collxct to work, so no new DNS record is needed — you're just adding a new port on the same host.

## 6. Extend the certbot renewal hook

Collxct's renewal config already reloads its own nginx on cert renewal. Add a second reload so Recbot's sidecar also picks up the renewed cert:

```bash
cat /etc/letsencrypt/renewal/collxct.com.ng.conf | grep deploy_hook
```

You should see the existing line:
```
deploy_hook = docker exec collxct-nginx-1 nginx -s reload
```

**Only if the line matches exactly what's above**, this changes it to reload both containers:

```bash
sed -i 's|deploy_hook = docker exec collxct-nginx-1 nginx -s reload|deploy_hook = sh -c "docker exec collxct-nginx-1 nginx -s reload \&\& docker exec collxct-recbot-nginx nginx -s reload"|' /etc/letsencrypt/renewal/collxct.com.ng.conf
```

If the `grep` output looked different (different container name, different format), don't run the `sed` — open it in `nano` instead and add the second `docker exec ... nginx -s reload` by hand, since this file also governs how Collxct's own cert renewal reloads and a bad blind edit there is exactly the kind of live-production-config mistake worth being careful about.

```bash
certbot renew --dry-run   # confirm it still works either way
```

## 7. Verify publicly

```bash
curl -s https://collxct.com.ng:8443/health
```

Should return `{"status":"ok"}` with a valid cert this time (no `-k` needed). Also open `https://collxct.com.ng:8443/login` in a browser to confirm the CRM UI loads.

## 8. Register the webhook with Twilio (manual, in the Console)

1. [Twilio Console](https://console.twilio.com) → Messaging → Try it out → Send a WhatsApp message (sandbox) or Messaging → Senders (production).
2. Set **"WHEN A MESSAGE COMES IN"** to `https://collxct.com.ng:8443/webhook`, method `POST`. Save.
3. Text the sandbox/production number from a phone that's joined the sandbox — you should get the category menu back.

## Redeploying after code changes

```bash
# from your machine
rsync -avz --exclude='.venv' --exclude='.venv-1' --exclude='__pycache__' \
  --exclude='.pytest_cache' --exclude='bot.db' --exclude='.env' \
  "C:/Users/Olufemi/Documents/PROJECTS/Recbot/" root@<server-ip>:/opt/recbot/

# on the server
cd /opt/recbot
docker compose up -d --build
```

If only `nginx/recbot.conf` changed (not the app code), the app container doesn't need rebuilding — just `docker compose restart nginx` to pick up the new config (bind-mounted files don't auto-reload).

The SQLite database lives in the `recbot_data` named volume, not in the container, so rebuilds and restarts never lose order/conversation data.

## Files this deployment added

- `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `.env.example`, `.gitignore` — the app container
- `nginx/recbot.conf` — the TLS-terminating sidecar, hardcoded to `collxct.com.ng:8443`, reusing Collxct's existing Let's Encrypt cert
