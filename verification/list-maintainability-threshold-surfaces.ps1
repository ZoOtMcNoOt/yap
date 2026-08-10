[CmdletBinding()]
param(
    [string]$RepositoryRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [ValidateRange(1, 1000000)]
    [int]$MinimumLines = 250,
    [switch]$Json
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$root = (Resolve-Path -LiteralPath $RepositoryRoot).Path
$extensions = @(
    ".rs", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".py",
    ".ps1", ".psm1", ".sh", ".md", ".yml", ".yaml", ".sql", ".toml",
    ".css", ".html", ".txt", ".cs", ".json"
)
$excludedArtifacts = @(
    "desktop/pnpm-lock.yaml",
    "server/openapi/live-events.schema.json",
    "server/openapi/openapi.json",
    "SHIPPED_DEPENDENCY_INVENTORY.json",
    "SHIPPED_DEPENDENCY_NOTICES.json"
)

function Get-Disposition([string]$Path) {
    switch -Regex ($Path) {
        "^\.github/workflows/" { return "CI" }
        "^desktop/src-tauri/migrations/" { return "NATIVE-MIGRATION" }
        "^desktop/src-tauri/src/" { return "NATIVE-SOURCE" }
        "^desktop/src-tauri/tests/" { return "NATIVE-TEST" }
        "^desktop/src/" { return "UI-SOURCE" }
        "^desktop/tests/" { return "DESKTOP-TEST" }
        "^demo/" { return "DEMO" }
        "^docs/plans/(archived|completed)/|^docs/research/" {
            return "HISTORICAL-DOC"
        }
        "^docs/" { return "CURRENT-DOC" }
        "^infra/" { return "INFRA" }
        "^server/README\.md$" { return "SERVER-RUNBOOK" }
        "^THIRD_PARTY_NOTICES\.md$" { return "DEPENDENCY-NOTICE" }
        "^server/src/yap_server/auth/" { return "AUTH" }
        "^server/src/yap_server/evaluation/" { return "EVALUATION" }
        "^server/src/yap_server/jobs/" { return "JOBS" }
        "^server/src/yap_server/knowledge/" { return "KNOWLEDGE" }
        "^server/src/yap_server/lid/" { return "LID" }
        "^server/src/yap_server/live/" { return "LIVE" }
        "^server/src/yap_server/meeting_transcription/" { return "MEETING" }
        "^server/src/yap_server/pools/" { return "POOLS" }
        "^server/tests/(auth|capabilities|contract)/" {
            return "TEST-AUTH-CONTRACT"
        }
        "^server/tests/evaluation/" { return "TEST-EVALUATION" }
        "^server/tests/infra/" { return "TEST-INFRA" }
        "^server/tests/jobs/" { return "TEST-JOBS" }
        "^server/tests/knowledge/" { return "TEST-KNOWLEDGE" }
        "^server/tests/(lid|live|model_pools|pools)/" { return "TEST-RUNTIME" }
        "^server/" { return "SERVER-CONTRACT" }
        "^verification/" { return "VERIFICATION" }
        default { throw "Tracked threshold surface has no disposition: $Path" }
    }
}

$tracked = & git -C $root ls-files
if ($LASTEXITCODE -ne 0) {
    throw "Unable to enumerate tracked repository files"
}

$surfaces = foreach ($path in $tracked) {
    if ($path -in $excludedArtifacts) {
        continue
    }
    if ([IO.Path]::GetExtension($path) -notin $extensions) {
        continue
    }
    $fullPath = Join-Path $root $path
    $item = Get-Item -LiteralPath $fullPath
    if ($item.PSIsContainer -or ($item.Attributes -band [IO.FileAttributes]::ReparsePoint)) {
        continue
    }
    $lineCount = @(Get-Content -LiteralPath $fullPath).Count
    if ($lineCount -lt $MinimumLines) {
        continue
    }
    [pscustomobject]@{
        path = $path.Replace("\", "/")
        lines = $lineCount
        disposition = Get-Disposition $path.Replace("\", "/")
    }
}

$ordered = @($surfaces | Sort-Object path)
if ($Json) {
    $ordered | ConvertTo-Json -Depth 3 -Compress
} else {
    $ordered
}
