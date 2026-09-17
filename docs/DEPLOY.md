# Deploy Navaid (GitHub Pages + Cloud Run)

The GitHub Action [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) does both:

1. **Backend** → [Cloud Run](https://cloud.google.com/run) (`navaid` in `us-central1`)
2. **Frontend** → GitHub Pages (static export pointed at that Cloud Run URL)

You only need to do the one-time account wiring below. After that, every push to `main` deploys.

## 1. GitHub repo

Already created if you used `gh repo create`. Otherwise:

```powershell
gh auth login
gh repo create navaid-airport-agent --private --source=. --remote=origin --push
```

GitHub Pages on a **private** repo needs GitHub Pro (or make the repo **public**). The published site is always public.

## 2. Google Cloud (once)

You already have `gcloud`. In the repo root:

```powershell
gcloud config set project YOUR_GCP_PROJECT
.\scripts\bootstrap_gcp.ps1
```

That enables Cloud Run / Artifact Registry / Vertex AI, creates the `navaid` Docker repo, a `navaid-github` service account, and writes `gcp-sa-navaid.json` (gitignored).

## 3. GitHub secrets (once)

```powershell
gh secret set GCP_PROJECT_ID -b "YOUR_GCP_PROJECT"
gh secret set GCP_SA_KEY < gcp-sa-navaid.json
```

Optional, only if Cloud Run should use a Gemini Developer API key instead of Vertex ADC on the default compute service account:

```powershell
gh secret set GEMINI_API_KEY
```

## 4. Push (or re-run the workflow)

```powershell
git push origin main
```

Open the **Actions** tab. When it is green:

| What | Where |
| --- | --- |
| API | `https://navaid-…..run.app` (`GET /health`, `POST /ask`) |
| Site | `https://<you>.github.io/<repo>/` |

The workbench on Pages calls Cloud Run. CORS already allows `*.github.io`.

## Local check of the static export

```powershell
python scripts/export_site.py --out site-dist --api-url http://127.0.0.1:8000 --root ""
```

## What you do not need

- Docker Desktop (GitHub’s Ubuntu runner builds the image)
- A separate frontend host or nginx
- To copy the DuckDB file; the image builds a fixture snapshot at image-build time (`NAVAID_OFFLINE=1`)
