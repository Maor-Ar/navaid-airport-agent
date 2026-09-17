<#
.SYNOPSIS
Create the GitHub repo, wire Cloud Run IAM, set Actions secrets, and push main.

This is the only command you should need after a GitHub browser login.

.EXAMPLE
.\scripts\go_live.ps1
.\scripts\go_live.ps1 -GcpProject navaid-airport-agent
#>
param(
    [string]$GcpProject = "navaid-airport-agent",
    [string]$RepoName = "navaid-airport-agent",
    [switch]$Private
)

$ErrorActionPreference = "Stop"

$gh = Join-Path ${env:ProgramFiles} "GitHub CLI\gh.exe"
if (-not (Test-Path $gh)) {
    $gh = "gh"
}

function Assert-GhAuth {
    & $gh auth status 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) {
        return
    }
    Write-Host "Finish GitHub login in the browser (code is on your clipboard)."
    & $gh auth login --hostname github.com --git-protocol https --web --clipboard
    if ($LASTEXITCODE -ne 0) {
        throw "GitHub login did not complete. Re-run this script after: gh auth login --web"
    }
}

Assert-GhAuth

$origin = git remote get-url origin 2>$null
if (-not $origin) {
    $visibility = if ($Private) { "--private" } else { "--public" }
    Write-Host "Creating GitHub repo $RepoName ($visibility) without pushing yet..."
    & $gh repo create $RepoName $visibility --source=. --remote=origin --description "Navaid — airport investment intelligence agent"
    if ($LASTEXITCODE -ne 0) {
        throw "gh repo create failed"
    }
}

if (-not $GcpProject) {
    throw "GCP project is required. Re-run with -GcpProject YOUR_PROJECT"
}

Write-Host "Bootstrapping GCP project $GcpProject ..."
& (Join-Path $PSScriptRoot "bootstrap_gcp.ps1") -Project $GcpProject
if ($LASTEXITCODE -ne 0) {
    throw "bootstrap_gcp.ps1 failed — check that you have Owner/Editor on $GcpProject"
}

Write-Host "Writing GitHub Actions secrets..."
& $gh secret set GCP_PROJECT_ID -b $GcpProject
Get-Content -Raw .\gcp-sa-navaid.json | & $gh secret set GCP_SA_KEY

Write-Host "Pushing main (this starts the deploy workflow)..."
git push -u origin main

$repoUrl = (& $gh repo view --json url --jq .url).Trim()
$login = (& $gh api user --jq .login).Trim()
Write-Host ""
Write-Host "Repo:    $repoUrl"
Write-Host "Actions: $repoUrl/actions"
Write-Host "Pages:   https://$login.github.io/$RepoName/  (live after the workflow is green)"
Write-Host "If Pages 404s on a private repo, GitHub Settings → Change repository visibility → Public."
