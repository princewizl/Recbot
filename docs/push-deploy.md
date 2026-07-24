# Deploying the push-enabled backend to the server

The mobile app needs the production backend (`collxct.com.ng:8443`) to run this
branch's `/api/*` code **and** have Firebase Cloud Messaging configured. Steps:

## 1. Get the code on the server
Pull this branch on the server as usual (git). `mobile/` and `secrets/` are not
needed by the backend — only `app/`, `requirements.txt`, `Dockerfile`,
`docker-compose.yml`, `nginx/`.

`requirements.txt` already includes `firebase-admin`, so the image build installs
it. The new `device_tokens` table is created automatically on boot (no migration).

## 2. Put the FCM key on the server (never via git)
Copy the service-account key to `./secrets/` on the server, e.g. from your PC:

```bash
scp secrets/firebase-service-account.json user@server:/path/to/Recbot/secrets/
```

`docker-compose.yml` mounts it read-only into the container at
`/secrets/firebase-service-account.json`.

## 3. Set the env var
In the server's `.env`:

```
FCM_CREDENTIALS_FILE=/secrets/firebase-service-account.json
```

(Path is the in-container mount path, not the host path.)

## 4. Rebuild and restart
```bash
docker compose build recbot
docker compose up -d
```

## 5. Verify
```bash
docker compose logs recbot | grep -i push
# expect: "Push enabled: firebase-admin initialised from /secrets/firebase-service-account.json"
docker compose exec recbot curl -fs http://127.0.0.1:8000/health
```

Then the app's default Server address (`https://collxct.com.ng:8443`) works from
any network — no LAN IP or ngrok needed. If push is misconfigured the app still
works; alerts just fall back to WhatsApp + the web dashboard.

## Security notes
- The key is mounted read-only and is **not** in the image or git (`.dockerignore`
  copies only `app/`; `.gitignore` covers `secrets/` and `*firebase-adminsdk*.json`).
- If the key ever leaks, revoke it in Firebase console → Project settings →
  Service accounts, and generate a new one.
