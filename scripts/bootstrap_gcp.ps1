<#
.SYNOPSIS
One-time GCP setup for Cloud Run + GitHub Actions.

.EXAMPLE
.\scripts\bootstrap_gcp.ps1 -Project dgt-gcp-moe-gemini-test
#>
param(
    [string]$Project = ""
)

$ErrorActionPreference = "Continue"

if (-not $Project) {
    $Project = (gcloud config get-value project 2>$null).Trim()
}
if (-not $Project -or $Project -eq "(unset)") {
    Write-Error "Pass -Project YOUR_GCP_PROJECT (the project with Vertex AI / Gemini)."
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
Write-Host "GCP is ready. GitHub secrets:"
Write-Host "  GCP_PROJECT_ID = $Project"
Write-Host "  GCP_SA_KEY     = $KeyPath"
