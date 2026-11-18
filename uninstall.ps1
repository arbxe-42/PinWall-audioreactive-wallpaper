# Pin Wall uninstall: stops the listener, removes autostart and the Lively library link.
# Your images and this folder are left alone (delete the folder yourself if you want).
$ErrorActionPreference = 'SilentlyContinue'
Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*listener\server.py*' -and $_.Name -like 'python*' } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Remove-Item (Join-Path ([Environment]::GetFolderPath('Startup')) 'Pin Wall listener.lnk')
$pkg = Get-AppxPackage -Name '*LivelyWallpaper*' | Select-Object -First 1
$libs = @((Join-Path $env:LOCALAPPDATA 'Lively Wallpaper\Library\wallpapers\pinwall'))
if ($pkg) { $libs += (Join-Path $env:LOCALAPPDATA "Packages\$($pkg.PackageFamilyName)\LocalCache\Local\Lively Wallpaper\Library\wallpapers\pinwall") }
foreach ($l in $libs) { $i = Get-Item $l; if ($i -and $i.LinkType -eq 'Junction') { $i.Delete() } }
Write-Host 'Pin Wall removed. Pick another wallpaper in Lively.' -ForegroundColor Green
