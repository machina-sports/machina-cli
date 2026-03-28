# Machina Sports CLI — Windows installer
# Usage: irm https://raw.githubusercontent.com/machina-sports/machina-cli/main/install.ps1 | iex
$ErrorActionPreference = "Stop"

$Repo = "machina-sports/machina-cli"
$InstallDir = if ($env:MACHINA_INSTALL_DIR) { $env:MACHINA_INSTALL_DIR } else { "$env:LOCALAPPDATA\machina\bin" }

function Get-LatestVersion {
    $release = Invoke-RestMethod "https://api.github.com/repos/$Repo/releases/latest"
    return $release.tag_name
}

function Main {
    $version = Get-LatestVersion
    $asset = "machina-windows-amd64.exe"
    $url = "https://github.com/$Repo/releases/download/$version/$asset"

    Write-Host "Installing machina $version for Windows..."

    if (-not (Test-Path $InstallDir)) {
        New-Item -ItemType Directory -Path $InstallDir -Force | Out-Null
    }

    $dest = Join-Path $InstallDir "machina.exe"
    Invoke-WebRequest -Uri $url -OutFile $dest

    # Add to PATH if not already there
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    if ($userPath -notlike "*$InstallDir*") {
        [Environment]::SetEnvironmentVariable("Path", "$userPath;$InstallDir", "User")
        Write-Host "Added $InstallDir to your PATH (restart your terminal to use it)."
    }

    Write-Host "Installed machina to $dest"
    & $dest version
}

Main
