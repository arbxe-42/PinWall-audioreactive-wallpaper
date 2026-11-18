# Pin Wall setup: installs the music listener, imports your images, adds the wallpaper to Lively.
# Run it through Setup.bat (double-click). Safe to run again: it updates an existing install.
param([string]$Images, [switch]$NoLively, [switch]$NoStartup, [switch]$NoListener, [switch]$NoPrompt)
# (the switches are for unattended installs and tests; a normal double-click needs none)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
function Say($t, $c = 'Gray') { Write-Host $t -ForegroundColor $c }
function Ask($q, $default = 'y') {
  if ($NoPrompt) { return $default -eq 'y' }
  $a = Read-Host "$q [$(if ($default -eq 'y') {'Y/n'} else {'y/N'})]"
  if ([string]::IsNullOrWhiteSpace($a)) { $a = $default }
  return $a.Trim().ToLower().StartsWith('y')
}

Say ''
Say '  PIN WALL  -  setup' 'Green'
Say '  a living collage of your images that moves with your music' 'DarkGray'
Say ''

# ---------------------------------------------------------------- 1. Python
Say '[1/6] Looking for Python 3.10 or newer...'
$pyExe = $null; $pyArgs = @()
foreach ($cand in @('py -3.12', 'py -3', 'python')) {
  $parts = $cand.Split(' ')
  $exe = $parts[0]
  $pre = @(); if ($parts.Length -gt 1) { $pre = $parts[1..($parts.Length - 1)] }
  if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
  try {
    $ok = & $exe @pre -c "import sys; print(sys.version_info >= (3, 10))" 2>$null
    if ($ok -eq 'True') { $pyExe = $exe; $pyArgs = $pre; break }
  } catch {}
}
if (-not $pyExe) {
  Say 'Python was not found. Install Python 3.12 from https://www.python.org/downloads/' 'Yellow'
  Say '(tick "Add python.exe to PATH" in the installer), then run Setup.bat again.' 'Yellow'
  exit 1
}
Say "      using: $pyExe $($pyArgs -join ' ')" 'DarkGray'

# ---------------------------------------------------------------- 2. listener environment
Say '[2/6] Installing the music listener (a minute or two the first time)...'
$venv = Join-Path $root 'listener\.venv'
$vpy = Join-Path $venv 'Scripts\python.exe'
$vpyw = Join-Path $venv 'Scripts\pythonw.exe'
if (-not (Test-Path $vpy)) { & $pyExe @pyArgs -m venv $venv }
& $vpy -m pip install --upgrade pip --quiet
& $vpy -m pip install -r (Join-Path $root 'listener\requirements.txt') --quiet
if ($LASTEXITCODE -ne 0) { Say 'Installing the Python packages failed (see above).' 'Red'; exit 1 }

# ---------------------------------------------------------------- 3. images
Say '[3/6] Pick the folder with your images (jpg, png, webp, gif)...'
$manifest = Join-Path $root 'wallpaper\pins\manifest.json'
$have = (Test-Path $manifest) -and ((Get-Content $manifest -Raw).Trim().Length -gt 2)
if ($Images) {
  & $vpy (Join-Path $root 'tools\prep_pins.py') --src $Images
} elseif (-not $NoPrompt -and (-not $have -or (Ask '      Import a new image folder?' 'n'))) {
  Add-Type -AssemblyName System.Windows.Forms
  $d = New-Object System.Windows.Forms.FolderBrowserDialog
  $d.Description = 'Pick the folder with your images for Pin Wall'
  if ($d.ShowDialog() -eq 'OK') {
    & $vpy (Join-Path $root 'tools\prep_pins.py') --src $d.SelectedPath
  } else {
    Say '      skipped: you can add images later from the tray icon (Change images...)' 'Yellow'
  }
}

# ---------------------------------------------------------------- 4. Lively
Say '[4/6] Adding the wallpaper to Lively...'
$pkg = Get-AppxPackage -Name '*LivelyWallpaper*' -ErrorAction SilentlyContinue | Select-Object -First 1
$lively = $null; $lib = $null
if ($pkg) {
  $lively = Join-Path $pkg.InstallLocation 'Build\Lively.exe'
  $lib = Join-Path $env:LOCALAPPDATA "Packages\$($pkg.PackageFamilyName)\LocalCache\Local\Lively Wallpaper\Library\wallpapers"
} else {
  $lib = Join-Path $env:LOCALAPPDATA 'Lively Wallpaper\Library\wallpapers'
  foreach ($p in @("$env:ProgramFiles\Lively Wallpaper\Lively.exe", "$env:LOCALAPPDATA\Programs\Lively Wallpaper\Lively.exe")) {
    if (Test-Path $p) { $lively = $p }
  }
}
if ($NoLively) {
  Say '      skipped (-NoLively)' 'DarkGray'
} elseif (-not $lively -or -not (Test-Path (Split-Path $lib -Parent))) {
  Say '      Lively Wallpaper was not found. Install it (free) from the Microsoft Store, open it once,' 'Yellow'
  Say '      then run Setup.bat again.' 'Yellow'
} else {
  New-Item -ItemType Directory -Force $lib | Out-Null
  $link = Join-Path $lib 'pinwall'
  if (Test-Path $link) { (Get-Item $link).Delete() }
  New-Item -ItemType Junction -Path $link -Target (Join-Path $root 'wallpaper') | Out-Null
  # Lively sees its library at this path (the Store version redirects it)
  $seen = Join-Path $env:LOCALAPPDATA 'Lively Wallpaper\Library\wallpapers\pinwall'
  Add-Type -AssemblyName System.Windows.Forms
  $n = [System.Windows.Forms.Screen]::AllScreens.Count
  for ($i = 1; $i -le $n; $i++) { & $lively setwp --file $seen --monitor $i; Start-Sleep -Milliseconds 800 }
  Say "      set on $n screen(s)" 'DarkGray'
}

# ---------------------------------------------------------------- 5. start with Windows
Say '[5/6] Starting the listener...'
if (-not $NoListener) {
  Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*listener\server.py*' -and $_.Name -like 'python*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
$server = Join-Path $root 'listener\server.py'
if (-not $NoStartup -and (Ask '      Start Pin Wall with Windows?' 'y')) {
  $ws = New-Object -ComObject WScript.Shell
  $lnk = $ws.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Startup')) 'Pin Wall listener.lnk'))
  $lnk.TargetPath = $vpyw; $lnk.Arguments = "`"$server`""; $lnk.WorkingDirectory = (Join-Path $root 'listener')
  $lnk.Description = 'Pin Wall: hears your music for the wallpaper (Ctrl+Alt+W toggles reactive/ambient)'
  $lnk.Save()
}
if (-not $NoListener) { Start-Process -FilePath $vpyw -ArgumentList "`"$server`"" -WorkingDirectory (Join-Path $root 'listener') }

# ---------------------------------------------------------------- 6. speaker delay
Say '[6/6] Speaker delay'
if (-not $NoPrompt -and (Ask '      Do you listen on Bluetooth speakers or headphones?' 'n')) {
  Say '      Opening the calibration page: press start and tap along to the clicks.' 'DarkGray'
  Start-Process (Join-Path $root 'listener\calibrate.html')
}

Say ''
Say 'Done. Play some music and look at your desktop.' 'Green'
Say 'Tray icon (starburst): left-click = reactive/ambient, right-click = change images, calibrate.' 'DarkGray'
Say 'Ctrl+Alt+W also switches reactive / ambient. Full guide: README.md' 'DarkGray'
