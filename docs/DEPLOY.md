# Deploy Navaid (GitHub Pages + Cloud Run)

The GitHub Action [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) does both:

1. **Backend** → Cloud Run service `navaid` in `us-central1`
2. **Frontend** → GitHub Pages (static export pointed at that Cloud Run URL)

## Fast path (recommended)

The repo is already a git repository on `main`. In PowerShell from the repo root:

```powershell
.\scripts\go_live.ps1 -GcpProject YOUR_VERTEX_PROJECT
```

That one script:

1. Opens GitHub login in the browser if needed
2. Creates `navaid-airport-agent` on GitHub (public, so Pages works on a free account)
3. Enables Cloud Run / Artifact Registry / Vertex on that GCP project
4. Sets `GCP_PROJECT_ID` and `GCP_SA_KEY` Actions secrets
5. Pushes `main`, which starts the deploy workflow

Watch **Actions**. When it is green:

| What | Where |
| --- | --- |
| API | `https://navaid-…..run.app` (`GET /health`, `POST /ask`) |
| Site | `https://<you>.github.io/navaid-airport-agent/` |

Use the GCP project that already has Vertex / Gemini, not an unrelated Studio Buda project.

Private repo: `.\scripts\go_live.ps1 -GcpProject YOUR_PROJECT -Private` (Pages then needs GitHub Pro).

## Manual equivalent

```powershell
gh auth login --web
gh repo create navaid-airport-agent --public --source=. --remote=origin
.\scripts\bootstrap_gcp.ps1 -Project YOUR_VERTEX_PROJECT
gh secret set GCP_PROJECT_ID -b "YOUR_VERTEX_PROJECT"
Get-Content -Raw .\gcp-sa-navaid.json | gh secret set GCP_SA_KEY
git push -u origin main
```

Optional Gemini Developer API key instead of Vertex on the Cloud Run service account:

```powershell
gh secret set GEMINI_API_KEY
```

## Local check of the static export

```powershell
python scripts/export_site.py --out site-dist --api-url http://127.0.0.1:8000 --root ""
```

## What you do not need

- Docker Desktop (GitHub’s Ubuntu runner builds the image)
- A separate frontend host or nginx
- To copy the DuckDB file; the image builds a fixture snapshot at image-build time (`NAVAID_OFFLINE=1`)
