"""One-time GCP setup for Cloud Run + GitHub Actions.

Run from the repo root in PowerShell (you already have gcloud):

    .\scripts\bootstrap_gcp.ps1

It enables APIs, creates Artifact Registry, a GitHub deploy service account,
and writes gcp-sa-navaid.json (gitignored). Then:

    gh secret set GCP_PROJECT_ID -b "<project>"
    gh secret set GCP_SA_KEY < gcp-sa-navaid.json
"""

$ErrorActionPreference = "Stop"

$Project = gcloud config get-value project 2>$null
if (-not $Project -or $Project -eq "(unset)") {
    Write-Error "No GCP project. Run: gcloud config set project YOUR_PROJECT"
}

$Region = "us-central1"
$Repo = "navaid"
$SaName = "navaid-github"
$SaEmail = "$SaName@${Project}.iam.gserviceaccount.com"
$KeyPath = Join-Path (Get-Location) "gcp-sa-navaid.json"

Write-Host "Project: $Project"
Write-Host "Region:  $Region"

gcloud services enable `
    run.googleapis.com `
    cloudbuild.googleapis.com `
    artifactregistry.googleapis.com `
    aiplatform.googleapis.com `
    iam.googleapis.com `
    --project $Project

$existingRepo = gcloud artifacts repositories describe $Repo --location $Region --project $Project 2>$null
if (-not $existingRepo) {
    gcloud artifacts repositories create $Repo `
        --repository-format=docker `
        --location $Region `
        --description "Navaid Cloud Run images" `
        --project $Project
}

$existingSa = gcloud iam service-accounts describe $SaEmail --project $Project 2>$null
if (-not $existingSa) {
    gcloud iam service-accounts create $SaName `
        --display-name "Navaid GitHub Actions" `
        --project $Project
}

$roles = @(
    "roles/run.admin",
    "roles/iam.serviceAccountUser",
    "roles/artifactregistry.writer",
    "roles/storage.admin"
)
foreach ($role in $roles) {
    gcloud projects add-iam-policy-binding $Project `
        --member "serviceAccount:$SaEmail" `
        --role $role `
        --condition None `
        --quiet | Out-Null
}

$ProjectNumber = gcloud projects describe $Project --format "value(projectNumber)"
$ComputeSa = "$ProjectNumber-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding $Project `
    --member "serviceAccount:$ComputeSa" `
    --role "roles/aiplatform.user" `
    --condition None `
    --quiet | Out-Null

if (Test-Path $KeyPath) {
    Write-Host "Keeping existing $KeyPath"
} else {
    gcloud iam service-accounts keys create $KeyPath --iam-account $SaEmail --project $Project
}

Write-Host ""
Write-Host "Done. Add these GitHub Actions secrets (Settings → Secrets and variables → Actions):"
Write-Host "  GCP_PROJECT_ID = $Project"
Write-Host "  GCP_SA_KEY     = contents of $KeyPath"
Write-Host ""
Write-Host "If gh is logged in, this script can set them:"
Write-Host "  gh secret set GCP_PROJECT_ID -b `"$Project`""
Write-Host "  gh secret set GCP_SA_KEY < gcp-sa-navaid.json"
Write-Host ""
Write-Host "Optional: gh secret set GEMINI_API_KEY  (only if you are not using Vertex on Cloud Run)"
Write-Host "Push to main after that. Actions deploys Cloud Run then GitHub Pages."
