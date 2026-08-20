$ErrorActionPreference = "Stop"

Write-Host "[0/3] Alte Build-Artefakte entfernen ..."
Remove-Item .\build -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\dist -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .\KickTrack.zip -Force -ErrorAction SilentlyContinue

Write-Host "[1/3] Spielerportraits fuer Release vorbereiten ..."
python .\tools\prepare_build_portraits.py

Write-Host "[2/3] KickTrack mit PyInstaller bauen ..."
python -m PyInstaller `
  --noconfirm `
  --clean `
  --windowed `
  --noupx `
  --name "KickTrack" `
  --icon "assets\kickbase_icon.ico" `
  --add-data "assets;assets" `
  main.py

Write-Host "[3/3] ZIP erstellen ..."
Compress-Archive `
  -Path .\dist\KickTrack\* `
  -DestinationPath .\KickTrack.zip `
  -Force

Write-Host "Fertig: .\KickTrack.zip"
