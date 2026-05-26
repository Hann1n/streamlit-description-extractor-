$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Write-Step($message) {
    Write-Host ""
    Write-Host "==> $message" -ForegroundColor Cyan
}

function Refresh-Path {
    $machinePath = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $userPath = [Environment]::GetEnvironmentVariable("Path", "User")
    $extraPaths = @(
        "$env:LOCALAPPDATA\Programs\Python\Python311",
        "$env:LOCALAPPDATA\Programs\Python\Python311\Scripts",
        "$env:ProgramFiles\Tesseract-OCR"
    )

    $searchRoots = @(
        "$env:LOCALAPPDATA\Microsoft\WinGet\Packages",
        "$env:ProgramFiles",
        "${env:ProgramFiles(x86)}"
    ) | Where-Object { $_ -and (Test-Path $_) }

    foreach ($root in $searchRoots) {
        Get-ChildItem -Path $root -Filter "pdftoppm.exe" -Recurse -ErrorAction SilentlyContinue |
            Select-Object -First 5 |
            ForEach-Object { $extraPaths += $_.DirectoryName }
    }

    $env:Path = (@($machinePath, $userPath) + $extraPaths | Where-Object { $_ }) -join ";"
}

function Ensure-WingetPackage($commandName, $packageId, $displayName) {
    Refresh-Path
    if (Get-Command $commandName -ErrorAction SilentlyContinue) {
        Write-Host "$displayName already installed."
        return
    }

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "winget is not available. Install 'App Installer' from Microsoft Store first."
    }

    Write-Step "Installing $displayName"
    winget install --id $packageId --exact --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path

    if (-not (Get-Command $commandName -ErrorAction SilentlyContinue)) {
        throw "$displayName was installed, but '$commandName' is still not on PATH. Restart PowerShell and run this installer again."
    }
}

function Get-PythonCommand {
    Refresh-Path
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.11 --version *> $null
        if ($LASTEXITCODE -eq 0) {
            return @("py", "-3.11")
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        return @("python")
    }
    return $null
}

function Invoke-Python {
    param(
        [Parameter(ValueFromRemainingArguments = $true)]
        [string[]] $Arguments
    )
    if ($pythonCommand.Length -gt 1) {
        & $pythonCommand[0] @($pythonCommand[1..($pythonCommand.Length - 1)]) @Arguments
    }
    else {
        & $pythonCommand[0] @Arguments
    }
}

Write-Step "Checking system dependencies"

$pythonCommand = Get-PythonCommand
if (-not $pythonCommand) {
    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "Python is not installed and winget is not available. Install Python 3.11 first."
    }
    Write-Step "Installing Python 3.11"
    winget install --id Python.Python.3.11 --exact --silent --accept-package-agreements --accept-source-agreements
    Refresh-Path
    $pythonCommand = Get-PythonCommand
    if (-not $pythonCommand) {
        throw "Python installed, but command was not found. Restart PowerShell and run this installer again."
    }
}

Ensure-WingetPackage "tesseract.exe" "UB-Mannheim.TesseractOCR" "Tesseract OCR"
Ensure-WingetPackage "pdftoppm.exe" "oschwartz10612.Poppler" "Poppler PDF tools"

Write-Step "Creating Python virtual environment"
if (-not (Test-Path ".venv")) {
    Invoke-Python @("-m", "venv", ".venv")
}

Write-Step "Installing Python packages"
& ".\.venv\Scripts\python.exe" -m pip install --upgrade pip
& ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt

Write-Step "Creating desktop shortcut"
$desktop = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktop "PDF DESCRIPTION Extractor.lnk"
$targetPath = Join-Path $PSScriptRoot "Start-Windows.bat"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $PSScriptRoot
$shortcut.Save()

Write-Step "Installation complete"
Write-Host "Run Start-Windows.bat or use the desktop shortcut: PDF DESCRIPTION Extractor"
Write-Host "The app opens at http://127.0.0.1:8501"
