# Production Deployment Guide

This guide walks you through setting up the full production stack:
**Render (backend + Celery worker)** + **Upstash (Redis)** + **Vercel (frontend)**.

---

## Architecture

```
Vercel (frontend) → Render (Django API) → Celery worker → Upstash (Redis)
                         ↘ Apify (Google Maps Scraper)
```

The Celery worker is required — Apify discovery takes 1-3 minutes and
cannot run synchronously in a web request (Render times out at 30s).

---

## Step 1: Create Upstash Redis (free)

1. Go to https://upstash.com → sign up (free, no credit card)
2. Click **Create Database**
3. Name: `outreach-redis`
4. Region: same as your Render backend
5. Click **Create**
6. Copy the **Endpoint** (e.g. `us1-xxxxx-xxxxx.upstash.io`)
7. Copy the **Port** (e.g. `6379`)
8. Copy the **Password**
9. Your Redis URL is: `redis://default:PASSWORD@ENDPOINT:PORT/0`
   - Example: `redis://default:abc123@us1-outreach-xxxx.upstash.io:6379/0`

> Save this URL — you'll need it in Steps 2 and 3.

---

## Step 2: Deploy Backend on Render (web service)

### 2.1 Create the Web Service

1. Go to https://dashboard.render.com
2. Click **New** → **Web Service**
3. Connect GitHub → select **`Ryjen1/outreach_backend`**
4. Branch: **`master`**
5. Name: `outreach-backend`
6. Runtime: **Python 3**
7. Region: closest to you
8. Instance Type: **Free**
9. Build Command:
   ```
   pip install -r requirements.txt
   ```
10. Start Command:
    ```
    python manage.py migrate --noinput && gunicorn wsgi:application --bind 0.0.0.0:$PORT --workers 1
    ```

### 2.2 Environment Variables (Web Service)

Scroll down to **Environment** and add ALL of these:

| Key | Value |
|---|---|
| `SECRET_KEY` | `django-insecure-CHANGE-ME-to-random-string` |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `outreach-backend-xxxx.onrender.com` |
| `DB_ENGINE` | `sqlite` |
| `CELERY_EAGER` | `False` |
| `CELERY_BROKER_URL` | `redis://default:PASSWORD@ENDPOINT:PORT/0` |
| `CELERY_RESULT_BACKEND` | `redis://default:PASSWORD@ENDPOINT:PORT/0` |
| `APIFY_API_TOKEN` | `your-apify-api-token` |
| `CORS_ALLOWED_ORIGINS` | `https://your-frontend.vercel.app` |

> Replace `outreach-backend-xxxx.onrender.com` with the actual URL Render gives you (shown at top after first deploy).
> Replace `https://your-frontend.vercel.app` with your actual Vercel URL (from Step 4).
> Leave `CORS_ALLOWED_ORIGINS` blank for now if you don't have the Vercel URL yet — come back and update it after Step 4.

Click **Create Web Service** → wait for first deploy (~2-3 min).

### 2.3 Verify

- Open `https://outreach-backend-xxxx.onrender.com/` → should return `{"status":"ok"}`
- Open `https://outreach-backend-xxxx.onrender.com/api/auth/register/` → should show DRF HTML (405 is fine)

---

## Step 3: Deploy Celery Worker on Render (background worker)

### 3.1 Create the Background Worker

1. On Render dashboard → **New** → **Background Worker**
2. Connect GitHub → select **`Ryjen1/outreach_backend`** (same repo!)
3. Branch: **`master`**
4. Name: `outreach-celery-worker`
5. Runtime: **Python 3**
6. Region: same as web service
7. Instance Type: **Free**
8. Build Command:
   ```
   pip install -r requirements.txt
   ```
9. Start Command:
   ```
   celery -A outreach_celery worker --loglevel=info --concurrency=2
   ```

### 3.2 Environment Variables (Background Worker)

Add the SAME env vars as the web service (copy-paste from Step 2.2):

| Key | Value |
|---|---|
| `SECRET_KEY` | `django-insecure-CHANGE-ME-to-random-string` |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `outreach-backend-xxxx.onrender.com` |
| `DB_ENGINE` | `sqlite` |
| `CELERY_EAGER` | `False` |
| `CELERY_BROKER_URL` | `redis://default:PASSWORD@ENDPOINT:PORT/0` |
| `CELERY_RESULT_BACKEND` | `redis://default:PASSWORD@ENDPOINT:PORT/0` |
| `APIFY_API_TOKEN` | `your-apify-api-token` |

> Note: The worker does NOT need `CORS_ALLOWED_ORIGINS` (it doesn't serve HTTP).
> The worker shares the same SQLite DB as the web service on Render's free tier
> (ephemeral disk — DB resets on redeploy, fine for demo).

Click **Create Background Worker** → wait for first deploy.

### 3.3 Verify

- Check the worker logs on Render → should show:
  ```
  -------------- celery@... v5.x.x (recovery)
  - ** ---------- .> transport:   redis://...
  - ** ---------- .> app:         outreach_celery:0x...
  -------------- [queues]
                .> celery           exchange=celery(direct) key=celery
  [tasks]
    . api.tasks.bulk_scraping_task
    . api.tasks.domain_discovery_task
    . api.tasks.email_sending_task
  celery@... ready.
  ```
- The `transport:` line should show `redis://...` (NOT `amqp://`)
- Should show **all 3 tasks registered**
- Should say **`ready.`** at the end

---

## Step 4: Deploy Frontend on Vercel

### 4.1 Create the Project

1. Go to https://vercel.com → sign in with GitHub
2. Click **Add New** → **Project**
3. Import **`Ryjen1/outreach-frontend`**
4. Framework Preset: **Vite** (auto-detected)
5. Build Command: `pnpm build` (or `npm run build`)
6. Output Directory: `dist`
7. Install Command: `pnpm install` (or `npm install`)

### 4.2 Environment Variables

Scroll to **Environment Variables** and add:

| Key | Value |
|---|---|
| `VITE_API_BASE_URL` | `https://outreach-backend-xxxx.onrender.com/api` |

> Replace with your actual Render backend URL from Step 2.

Click **Deploy** → wait (~1-2 min).

### 4.3 Get Your Vercel URL

After deploy, Vercel shows your URL (e.g. `https://outreach-frontend-xxxx.vercel.app`).

### 4.4 Update Render CORS

Go back to Render → web service → Environment → update:

```
CORS_ALLOWED_ORIGINS=https://outreach-frontend-xxxx.vercel.app
```

Save → Render auto-redeploys.

---

## Step 5: Test End-to-End

1. Open your Vercel URL: `https://outreach-frontend-xxxx.vercel.app`
2. Register a new account
3. Go to **Bulk Outreach** → **Discover & Scrape** tab
4. Enter:
   - Keyword: `restaurant`
   - Location: `New York`
   - Max Results: `5`
5. Click **Discover Businesses**
6. Wait 1-3 minutes (watch the progress indicator)
7. Discovery completes → scraping auto-starts
8. Check **Contacts** page → should show businesses with emails

### Troubleshooting

| Symptom | Fix |
|---|---|
| Discovery stuck on "pending" | Celery worker not running. Check Render → Background Worker logs. |
| `kombu.exceptions.OperationalError` in worker logs | `CELERY_BROKER_URL` is wrong or Upstash Redis is down. |
| `ApifyError: APIFY_API_TOKEN is not configured` | `APIFY_API_TOKEN` env var missing on Render. |
| CORS error in browser console | `CORS_ALLOWED_ORIGINS` on Render doesn't match your Vercel URL. |
| 500 on `/api/domain-discovery/initiate/` | Check Render web service logs. Likely missing env var or worker not connected. |
| Discovery completes but 0 contacts | Businesses found have no websites/emails. Try a different keyword/location. |
| Worker shows `transport: amqp://` | `CELERY_EAGER` is `True` or `CELERY_BROKER_URL` is missing. Set both. |

---

## Quick Reference: All Environment Variables

### Render Web Service
```
SECRET_KEY=django-insecure-CHANGE-ME
DEBUG=False
ALLOWED_HOSTS=outreach-backend-xxxx.onrender.com
DB_ENGINE=sqlite
CELERY_EAGER=False
CELERY_BROKER_URL=redis://default:PASSWORD@ENDPOINT:PORT/0
CELERY_RESULT_BACKEND=redis://default:PASSWORD@ENDPOINT:PORT/0
APIFY_API_TOKEN=apify_api_xxxxxxxxxxxxxxxxxx
CORS_ALLOWED_ORIGINS=https://outreach-frontend-xxxx.vercel.app
```

### Render Background Worker (Celery)
```
SECRET_KEY=django-insecure-CHANGE-ME
DEBUG=False
ALLOWED_HOSTS=outreach-backend-xxxx.onrender.com
DB_ENGINE=sqlite
CELERY_EAGER=False
CELERY_BROKER_URL=redis://default:PASSWORD@ENDPOINT:PORT/0
CELERY_RESULT_BACKEND=redis://default:PASSWORD@ENDPOINT:PORT/0
APIFY_API_TOKEN=apify_api_xxxxxxxxxxxxxxxxxx
```

### Vercel Frontend
```
VITE_API_BASE_URL=https://outreach-backend-xxxx.onrender.com/api
```

---

## Notes

- **Render free tier**: Web service sleeps after 15 min inactivity (first request takes ~30s to wake). Background worker also sleeps.
- **Upstash free tier**: 10,000 Redis commands/day (plenty for low volume).
- **Apify free tier**: $5/mo credit (~3,300 places scraped).
- **SQLite on Render**: Ephemeral disk — DB resets on every redeploy. For production, switch to Render PostgreSQL (free tier: 90 days, then $7/mo).
- **Render + Celery limitation**: On the free tier, the worker and web service don't share a filesystem. SQLite DB is per-service. For production, use PostgreSQL so both services share the same DB.
