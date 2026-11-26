#requires -Version 7.4
#requires -PSEdition Core
param(
  [Parameter(Mandatory)][string]$AppExecutable,
  [Parameter(Mandatory)][string[]]$BrowserExecutables,
  [Parameter(Mandatory)][scriptblock]$CheckWorkspace
)
$ErrorActionPreference = "Stop"
$tag = "Yap-package-" + [guid]::NewGuid().ToString("N")
$probe = Join-Path ([IO.Path]::GetTempPath()) "$tag.exe"
$rules = @()
$endpoint = "https://api.github.com/"
$probeArgs = @("--ipv4", "--noproxy", "*", "--silent", "--output", "NUL", "--write-out", "%{remote_ip}", "--connect-timeout", "5", "--max-time", "10")
try {
  Copy-Item -LiteralPath (Join-Path $env:SystemRoot "System32/curl.exe") -Destination $probe
  $remoteAddress = & $probe @probeArgs $endpoint
  $parsed = [ipaddress]::None
  if ($LASTEXITCODE -ne 0 -or -not [ipaddress]::TryParse($remoteAddress, [ref]$parsed)) {
    throw "The disposable HTTP probe could not establish its online baseline."
  }
  $probeArgs += @("--resolve", "api.github.com:443:$remoteAddress")
  foreach ($program in @($AppExecutable) + $BrowserExecutables + @($probe)) {
    $rule = New-NetFirewallRule -DisplayName $tag -Program $program -Enabled True -Profile Any -Direction Outbound -Action Block
    $rules += $rule.Name
    $active = Get-NetFirewallRule -Name $rule.Name -PolicyStore ActiveStore
    $filter = $active | Get-NetFirewallApplicationFilter
    if ($active.Enabled -ne "True" -or $active.Action -ne "Block" -or $active.Direction -ne "Outbound" -or $filter.Program -ine $program) {
      throw "The installed workflow could not verify its outbound block for $program."
    }
  }
  $null = & $probe @probeArgs $endpoint
  if ($LASTEXITCODE -notin @(7, 28)) { throw "The active firewall rule did not deny the control connection." }
  Write-Host "Confirmed outbound denial for the control and active rules for Yap and its WebView2 runtime."
  & $CheckWorkspace
} finally {
  foreach ($id in $rules) { Remove-NetFirewallRule -Name $id }
  if (Test-Path -LiteralPath $probe) { [IO.File]::Delete($probe) }
}
