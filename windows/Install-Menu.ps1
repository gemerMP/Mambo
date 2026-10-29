$ErrorActionPreference = 'Stop'
$menu = Join-Path ([Environment]::GetFolderPath('Programs')) 'Mambo'
New-Item -ItemType Directory -Force -Path $menu | Out-Null
$shell = New-Object -ComObject WScript.Shell
foreach ($name in @('Mambo', 'MamboLite')) {
    $exe = Join-Path $PSScriptRoot ($name + '.exe')
    if (Test-Path $exe) {
        $link = $shell.CreateShortcut((Join-Path $menu ($name + '.lnk')))
        $link.TargetPath = $exe
        $link.WorkingDirectory = $PSScriptRoot
        $link.Save()
    }
}
Write-Host 'Mambo shortcuts added to Start menu. Keep this application folder in place.'
