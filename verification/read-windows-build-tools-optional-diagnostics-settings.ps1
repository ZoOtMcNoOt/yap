#requires -Version 5.1
#requires -PSEdition Desktop

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Read-OptInSetting {
    param(
        [Parameter(Mandatory)]
        [Microsoft.Win32.RegistryKey]$BaseKey,

        [Parameter(Mandatory)]
        [string]$SubKey
    )

    $key = $null
    try {
        $key = $BaseKey.OpenSubKey($SubKey, $false)
        if ($null -eq $key) {
            return [ordered]@{ state = 'absent' }
        }

        $valueName = $null
        foreach ($candidate in $key.GetValueNames()) {
            if ([StringComparer]::OrdinalIgnoreCase.Equals($candidate, 'OptIn')) {
                $valueName = $candidate
                break
            }
        }
        if ($null -eq $valueName) {
            return [ordered]@{ state = 'absent' }
        }

        $kind = $key.GetValueKind($valueName)
        if ($kind -ne [Microsoft.Win32.RegistryValueKind]::DWord) {
            throw "Registry value $SubKey\OptIn must be a DWORD."
        }
        $rawValue = $key.GetValue(
            $valueName,
            $null,
            [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames
        )
        if ($rawValue -isnot [int]) {
            throw "Registry value $SubKey\OptIn did not return a 32-bit integer."
        }
        return [ordered]@{
            state = 'present'
            kind  = 'DWord'
            value = [uint32]$rawValue
        }
    }
    finally {
        if ($null -ne $key) {
            $key.Dispose()
        }
    }
}

$baseKey = $null
try {
    $baseKey = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine,
        [Microsoft.Win32.RegistryView]::Registry64
    )
    [ordered]@{
        schemaVersion = 1
        registryView  = 'Registry64'
        policy        = Read-OptInSetting `
            -BaseKey $baseKey `
            -SubKey 'Software\Policies\Microsoft\VisualStudio\SQM'
        installation  = Read-OptInSetting `
            -BaseKey $baseKey `
            -SubKey 'SOFTWARE\Wow6432Node\Microsoft\VSCommon\17.0\SQM'
    } | ConvertTo-Json -Compress -Depth 4
}
finally {
    if ($null -ne $baseKey) {
        $baseKey.Dispose()
    }
}
