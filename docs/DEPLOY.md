# Deploy Navaid (GitHub Pages + Cloud Run)

The GitHub Action [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml) deploys:

1. **Backend** → Cloud Run service `navaid` in `us-central1`
2. **Frontend** → GitHub Pages (static export pointed at that Cloud Run URL)

## Already live (GCP)

Project **`navaid-airport-agent`** under `maorarnon@gmail.com`, billing linked, Vertex on the Cloud Run service account.

| What | Where |
| --- | --- |
| API + site | [https://navaid-931662514254.us-central1.run.app](https://navaid-931662514254.us-central1.run.app) |
| Health | [https://navaid-931662514254.us-central1.run.app/health](https://navaid-931662514254.us-central1.run.app/health) |
| Workbench | [https://navaid-931662514254.us-central1.run.app/workbench](https://navaid-931662514254.us-central1.run.app/workbench) |

`GET /health` reports `gemini_auth: vertex_adc`. The same origin also serves the analyst UI until GitHub Pages is connected.

## Remaining: GitHub (needs a browser login)

`gh` is installed but not logged in. From the repo root:

```powershell
gh auth login --web
.\scripts\go_live.ps1
```

That creates **`navaid-airport-agent`**, sets `GCP_PROJECT_ID` / `GCP_SA_KEY` from the existing `gcp-sa-navaid.json`, and pushes `main`. After Actions is green, Pages is `https://<you>.github.io/navaid-airport-agent/`.

The Pages job sets `enablement: true` on `actions/configure-pages` so CI can create the site and set **Source: GitHub Actions**. If that still fails with “Get Pages site failed” (private repo, org policy, or `GITHUB_TOKEN` without administration), open **Settings → Pages** and set **Source** to **GitHub Actions**, then re-run the workflow.

Private repo: `.\scripts\go_live.ps1 -Private` (Pages then needs GitHub Pro).

## Manual equivalent

```powershell
gh auth login --web
gh repo create navaid-airport-agent --public --source=. --remote=origin
gh secret set GCP_PROJECT_ID -b "navaid-airport-agent"
Get-Content -Raw .\gcp-sa-navaid.json | gh secret set GCP_SA_KEY
git push -u origin main
```

Optional Gemini Developer API key instead of Vertex on the Cloud Run service account:

```powershell
gh secret set GEMINI_API_KEY
```

## Local check of the static export

```powershell
python scripts/export_site.py --out site-dist --api-url https://navaid-931662514254.us-central1.run.app --root ""
```

## What you do not need

- Docker Desktop (Cloud Build and GitHub’s Ubuntu runner both build the image)
- A separate frontend host or nginx
- To copy the DuckDB file; the image builds a fixture snapshot at image-build time (`NAVAID_OFFLINE=1`)
