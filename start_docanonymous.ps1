$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $root ".venv\Scripts\python.exe"

function Test-ApplicationUpdate {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Host "Git nicht gefunden, Update-Pruefung uebersprungen."
        return
    }

    Push-Location $root
    try {
        $insideWorkTree = git rev-parse --is-inside-work-tree 2>$null
        if ($LASTEXITCODE -ne 0 -or $insideWorkTree -ne "true") {
            Write-Host "Kein Git-Repository, Update-Pruefung uebersprungen."
            return
        }

        git fetch --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-Host "GitHub-Update-Pruefung fehlgeschlagen."
            return
        }

        $upstream = git rev-parse --abbrev-ref --symbolic-full-name "@{u}" 2>$null
        if ($LASTEXITCODE -ne 0 -or -not $upstream) {
            Write-Host "Kein Git-Upstream konfiguriert, Update-Pruefung uebersprungen."
            return
        }

        $local = git rev-parse HEAD
        $remote = git rev-parse "@{u}"
        $base = git merge-base HEAD "@{u}"

        if ($local -eq $remote) {
            Write-Host "DocAnonymous ist auf dem neuesten Stand."
        } elseif ($local -eq $base) {
            Write-Host "Update verfuegbar: $upstream enthaelt neue Versionen. Zum Aktualisieren: git pull --ff-only"
        } elseif ($remote -eq $base) {
            Write-Host "Lokale Version ist neuer als GitHub."
        } else {
            Write-Host "Lokale und GitHub-Version sind auseinander gelaufen. Bitte manuell pruefen."
        }
    } finally {
        Pop-Location
    }
}

if (-not (Test-Path $python)) {
    python -m venv (Join-Path $root ".venv")
    & $python -m pip install -r (Join-Path $root "requirements.txt")
}

Test-ApplicationUpdate
& $python -m doc_anonymizer.app.main
