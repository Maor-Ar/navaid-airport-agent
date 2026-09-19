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

# Pick up a freshly installed GitHub CLI without requiring a new terminal.
$machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

$gh = Join-Path ${env:ProgramFiles} "GitHub CLI\gh.exe"
if (-not (Test-Path $gh)) {
    $gh = "gh"
}

function Invoke-Gh {
    param([Parameter(Mandatory = $true)][string[]]$GhArgs)
    Write-Host ("+ gh " + ($GhArgs -join " "))
    & $gh @GhArgs
    if ($LASTEXITCODE -ne 0) {
        throw ("gh " + ($GhArgs[0..1] -join " ") + " failed with exit " + $LASTEXITCODE)
    }
}

function Assert-GhAuth {
    cmd /c "`"$gh`" auth status >nul 2>&1" | Out-Null
    if ($LASTEXITCODE -eq 0) {
        return
    }
    Write-Host "Finish GitHub login in the browser (code is on your clipboard)."
    Invoke-Gh -GhArgs @("auth", "login", "--hostname", "github.com", "--git-protocol", "https", "--web", "--clipboard")
}

Assert-GhAuth

if ((@(git remote) -notcontains "origin")) {
    $visibility = if ($Private) { "--private" } else { "--public" }
    Write-Host "Creating GitHub repo $RepoName ($visibility) without pushing yet..."
    Invoke-Gh -GhArgs @(
        "repo", "create", $RepoName,
        $visibility,
        "--source", ".",
        "--remote", "origin",
        "--description", "Navaid - airport investment intelligence agent"
    )
}

if ((@(git remote) -notcontains "origin")) {
    throw "Git remote 'origin' was not created. Repo create did not complete."
}

if (-not $GcpProject) {
    throw "GCP project is required. Re-run with -GcpProject YOUR_PROJECT"
}

Write-Host "Bootstrapping GCP project $GcpProject ..."
& (Join-Path $PSScriptRoot "bootstrap_gcp.ps1") -Project $GcpProject
if ($LASTEXITCODE -ne 0) {
    throw "bootstrap_gcp.ps1 failed - check that you have Owner/Editor on $GcpProject"
}

Write-Host "Writing GitHub Actions secrets..."
Invoke-Gh -GhArgs @("secret", "set", "GCP_PROJECT_ID", "-b", $GcpProject)
Get-Content -Raw .\gcp-sa-navaid.json | & $gh secret set GCP_SA_KEY
if ($LASTEXITCODE -ne 0) {
    throw "gh secret set GCP_SA_KEY failed with exit $LASTEXITCODE"
}

Write-Host "Pushing main (this starts the deploy workflow)..."
cmd /c "git push -u origin main"
if ($LASTEXITCODE -ne 0) {
    throw "git push failed with exit $LASTEXITCODE"
}

$repoUrl = (Invoke-Gh -GhArgs @("repo", "view", "--json", "url", "--jq", ".url")).Trim()
$login = (Invoke-Gh -GhArgs @("api", "user", "--jq", ".login")).Trim()
Write-Host ""
Write-Host "Repo:    $repoUrl"
Write-Host "Actions: $repoUrl/actions"
Write-Host "Pages:   https://$login.github.io/$RepoName/  (live after the workflow is green)"
Write-Host "If Pages 404s on a private repo, GitHub Settings -> Change repository visibility -> Public."
