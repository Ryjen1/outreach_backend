# Backend Deployment Guide (Render)

## 1. Create the Web Service

1. Go to https://dashboard.render.com
2. Click **New** → **Web Service**
3. Connect your GitHub account (if not already connected)
4. Select the repository: **`Ryjen1/outreach_backend`**
5. Branch: **`master`**
6. Name: anything you like (e.g. `outreach-backend`)
7. Runtime: **Python 3** (do NOT choose Docker)
8. Region: closest to you
9. Instance Type: **Free**

## 2. Build & Start Commands

**Build Command:**
```
pip install -r requirements.txt
```

**Start Command:**
```
python manage.py migrate --noinput && gunicorn wsgi:application --bind 0.0.0.0:$PORT --workers 1
```

## 3. Environment Variables

Add these under **Environment** on the left sidebar:

| Key | Value |
|---|---|
| `SECRET_KEY` | any random string (e.g. `django-insecure-xY9k2abc123def456`) |
| `DEBUG` | `False` |
| `ALLOWED_HOSTS` | `your-backend-name.onrender.com` |
| `DB_ENGINE` | `sqlite` |
| `CORS_ALLOWED_ORIGINS` | `https://your-frontend.vercel.app` |

> Replace `your-backend-name.onrender.com` with the actual URL Render gives you (shown at the top of the service page after first deploy).
> Replace `your-frontend.vercel.app` with your actual Vercel URL (from Step 2).

## 4. Deploy

Click **Create Web Service** / **Deploy**.

Wait for the build to finish (first build takes ~2–3 minutes).

## 5. Verify

Open these URLs in your browser:

- `https://your-backend-name.onrender.com/`
  → should return: `{"status":"ok"}`

- `https://your-backend-name.onrender.com/api/auth/register/`
  → should show a DRF HTML page (HTTP 405 Method Not Allowed is fine — it means the route exists)

## 6. After you get your Vercel frontend URL

Come back to Render → **Environment** → update:

```
CORS_ALLOWED_ORIGINS=https://your-actual-vercel-url.vercel.app
```

Save → Render auto-redeploys.

## 7. Notes

- Render free tier uses an **ephemeral disk**: the SQLite DB resets on every redeploy. This is fine for a demo — registered users persist between register and login within the same deploy.
- Free tier sleeps after ~15 min of inactivity. First request after sleep takes ~30 seconds to wake up.
- If you see a `DisallowedHost` error, your `ALLOWED_HOSTS` is missing the Render URL.
- If you see a CORS error in the browser console, your `CORS_ALLOWED_ORIGINS` is missing the Vercel URL (or has a typo).
