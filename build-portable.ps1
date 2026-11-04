param(
  [string]$OutputName = "KickTrack-0.8.33-portable.zip"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repoRoot = $PSScriptRoot

function Invoke-Checked {
  param(
    [Parameter(Mandatory = $true)]
    [scriptblock]$Command,
    [Parameter(Mandatory = $true)]
    [string]$FailureMessage
  )

  & $Command
  if ($LASTEXITCODE -ne 0) {
    throw $FailureMessage
  }
}

Push-Location $repoRoot
try {
  Invoke-Checked { & ".\node_modules\.bin\tsc.cmd" --noEmit } "TypeScript-Prüfung fehlgeschlagen."
  Invoke-Checked { & ".\node_modules\.bin\vite.cmd" build } "Frontend-Build fehlgeschlagen."
  Invoke-Checked {
    & ".\node_modules\.bin\tauri.cmd" build --no-bundle --config ".\src-tauri\tauri.portable.conf.json"
  } "Tauri-Release-Build fehlgeschlagen."

  $executable = Join-Path $repoRoot "src-tauri\target\release\kicktrack.exe"
  if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw "Die Release-EXE wurde nicht erzeugt: $executable"
  }

  $archive = Join-Path $repoRoot $OutputName
  Compress-Archive -LiteralPath $executable -DestinationPath $archive -Force
  Write-Host "Portable ZIP erstellt: $archive"
}
finally {
  Pop-Location
}
