<#
.SYNOPSIS
    Copy every non-gitignored file (the source needed to run the app) into a
    fresh timestamped folder.

.DESCRIPTION
    Enumerates files with `git ls-files -c -o --exclude-standard`, i.e. tracked
    files PLUS untracked files that are not ignored, MINUS everything .gitignore
    excludes. Because this project's .gitignore is an allowlist, that set is
    exactly the runtime source: backend/app, migrations, requirements.txt,
    frontend src+config, scripts, and the allowlisted root docs. It deliberately
    excludes data/, backend/.venv, frontend/dist, node_modules build output, and
    __pycache__.

    A few repo-relative paths are always excluded regardless of git state via
    the $ExcludePaths list near the top (currently progress.md and the
    improvementsv*.md notes). Edit that list to add/remove names.

    The copy is "source only": to actually run the export you still need to
    `pip install -r backend/requirements.txt` and `npm install; npm run build`
    in the new location (see CLAUDE.md).

    Each run creates a NEW timestamped subfolder, so previous exports are kept.

.PARAMETER Destination
    Base folder to export into. A timestamped subfolder is created under it.
    Defaults to a sibling of the repo: <repo-parent>\<repo-name>-export.
    Keep this OUTSIDE the repo working tree: an export placed inside the tree
    that isn't gitignored would be enumerated and re-copied on the next run.

.EXAMPLE
    .\scripts\export-source.ps1
    .\scripts\export-source.ps1 -Destination D:\backups\emailchrono
#>
[CmdletBinding()]
param(
    [string]$Destination
)

$ErrorActionPreference = 'Stop'

# Resolve the repo root from this script's location (scripts/ -> repo root).
try {
    $RepoRoot = (git -C $PSScriptRoot rev-parse --show-toplevel).Trim()
} catch {
    throw "Not a git repository (or git is not on PATH). This script needs git to know which files are not gitignored."
}
if (-not $RepoRoot) { throw "Could not determine the repository root." }
$RepoRoot = (Resolve-Path -LiteralPath $RepoRoot).Path

# Default destination: a sibling of the repo, never inside it.
if (-not $Destination) {
    $repoName = Split-Path -Leaf $RepoRoot
    $Destination = Join-Path (Split-Path -Parent $RepoRoot) "$repoName-export"
}

$timestamp = Get-Date -Format 'yyyy-MM-dd_HHmmss'
$TargetDir = Join-Path $Destination $timestamp
New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
$TargetResolved = (Resolve-Path -LiteralPath $TargetDir).Path

# Guard: refuse to export into the repo tree (would self-include next run).
# Compare on a path boundary so a sibling like "<repo>-export" is not mistaken
# for being inside "<repo>".
$repoBoundary = $RepoRoot.TrimEnd('\') + '\'
if (($TargetResolved.TrimEnd('\') + '\').ToLower().StartsWith($repoBoundary.ToLower())) {
    Remove-Item -LiteralPath $TargetDir -Force -Recurse -ErrorAction SilentlyContinue
    throw "Destination '$TargetResolved' is inside the repo. Choose a path outside '$RepoRoot'."
}

# Always exclude these repo-relative paths, even if git still tracks them
# (e.g. files committed before being gitignored). Matched case-insensitively
# against the git-relative path. This is a belt-and-suspenders guard: once a
# file is untracked AND gitignored, `git ls-files` already drops it, but this
# keeps the export clean if one is ever re-added to git by mistake.
$ExcludePaths = @(
    'progress.md',
    'improvementsv2.md',
    'improvementsv4.2.md'
)
$ExcludeSet = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($e in $ExcludePaths) { [void]$ExcludeSet.Add(($e -replace '\\', '/')) }

# The authoritative list of "not gitignored" files. core.quotepath=off keeps
# non-ASCII names readable/usable instead of octal-escaped.
$files = git -C $RepoRoot -c core.quotepath=off ls-files -c -o --exclude-standard

$copied = 0
$skipped = 0
$excluded = 0
foreach ($rel in $files) {
    if ([string]::IsNullOrWhiteSpace($rel)) { continue }
    if ($ExcludeSet.Contains(($rel -replace '\\', '/'))) { $excluded++; continue }
    $relWin = $rel -replace '/', '\'
    $src = Join-Path $RepoRoot $relWin

    # ls-files can list gitlink/submodule entries or paths that aren't plain
    # files on disk; copy only real files.
    if (-not (Test-Path -LiteralPath $src -PathType Leaf)) { $skipped++; continue }

    $dest = Join-Path $TargetResolved $relWin
    $destDir = Split-Path -Parent $dest
    if (-not (Test-Path -LiteralPath $destDir)) {
        New-Item -ItemType Directory -Force -Path $destDir | Out-Null
    }
    Copy-Item -LiteralPath $src -Destination $dest -Force
    $copied++
}

Write-Host ""
Write-Host "Exported $copied file(s) to:" -ForegroundColor Green
Write-Host "  $TargetResolved"
if ($skipped -gt 0) {
    Write-Host "Skipped $skipped non-file entr(ies) (submodules / missing paths)." -ForegroundColor DarkGray
}
if ($excluded -gt 0) {
    Write-Host "Excluded $excluded explicitly-listed file(s) (see `$ExcludePaths)." -ForegroundColor DarkGray
}
