$ErrorActionPreference = "Stop"
$repo = Split-Path $PSScriptRoot -Parent
Push-Location $repo
try {
    dotnet restore server --locked-mode
    if ($LASTEXITCODE -ne 0) { throw "Restore failed" }
    dotnet publish server -c Release -r win-x64 --self-contained true -p:PublishSingleFile=true -p:IncludeNativeLibrariesForSelfExtract=true -p:NuGetLockFilePath=obj/packages.publish.lock.json -o artifacts/windows-x64
    if ($LASTEXITCODE -ne 0) { throw "Publish failed" }
    Copy-Item README.md artifacts/windows-x64/README.md
    Compress-Archive -Path artifacts/windows-x64/* -DestinationPath artifacts/Bww-Windows-x64.zip -Force
} finally { Pop-Location }
