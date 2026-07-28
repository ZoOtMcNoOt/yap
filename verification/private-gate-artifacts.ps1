#requires -Version 5.1

param(
    [Parameter(Mandatory)]
    [ValidateSet(
        'protect-directory',
        'protect-file',
        'protect-ssh-file',
        'verify-directory',
        'verify-file',
        'verify-ssh-file'
    )]
    [string]$Operation,

    [Parameter(Mandatory)]
    [string]$LiteralPath
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-ExpectedPrivateAcl {
    param(
        [Parameter(Mandatory)]
        [Security.Principal.SecurityIdentifier]$Owner,

        [Parameter(Mandatory)]
        [bool]$Directory,

        [Parameter(Mandatory)]
        [bool]$SshCompatible
    )

    $security = if ($Directory) {
        [Security.AccessControl.DirectorySecurity]::new()
    }
    else {
        [Security.AccessControl.FileSecurity]::new()
    }
    $security.SetAccessRuleProtection($true, $false)
    $inheritance = if ($Directory) {
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    else {
        [Security.AccessControl.InheritanceFlags]::None
    }
    $trusted = @(
        if ($SshCompatible) {
            $Owner
        }
        else {
            [Security.Principal.SecurityIdentifier]::new('S-1-3-4')
        }
        [Security.Principal.SecurityIdentifier]::new('S-1-5-18')
        [Security.Principal.SecurityIdentifier]::new('S-1-5-32-544')
    )
    foreach ($identity in $trusted) {
        $rule = [Security.AccessControl.FileSystemAccessRule]::new(
            $identity,
            [Security.AccessControl.FileSystemRights]::FullControl,
            $inheritance,
            [Security.AccessControl.PropagationFlags]::None,
            [Security.AccessControl.AccessControlType]::Allow
        )
        [void]$security.AddAccessRule($rule)
    }
    return $security
}

function Assert-ExpectedPrivateAcl {
    param(
        [Parameter(Mandatory)]
        [Security.AccessControl.FileSystemSecurity]$Security,

        [Parameter(Mandatory)]
        [Security.Principal.SecurityIdentifier]$Owner,

        [Parameter(Mandatory)]
        [bool]$Directory,

        [Parameter(Mandatory)]
        [bool]$SshCompatible
    )

    $observedOwner = $Security.GetOwner(
        [Security.Principal.SecurityIdentifier]
    )
    if ($observedOwner.Value -cne $Owner.Value) {
        throw 'Private artifact owner differs from the current Windows identity.'
    }
    if (-not $Security.AreAccessRulesProtected) {
        throw 'Private artifact DACL still inherits access rules.'
    }

    $expectedSids = @(
        if ($SshCompatible) {
            $Owner.Value
        }
        else {
            'S-1-3-4'
        }
        'S-1-5-18'
        'S-1-5-32-544'
    )
    $expectedInheritance = if ($Directory) {
        [Security.AccessControl.InheritanceFlags]::ContainerInherit -bor
            [Security.AccessControl.InheritanceFlags]::ObjectInherit
    }
    else {
        [Security.AccessControl.InheritanceFlags]::None
    }
    $rules = @(
        $Security.GetAccessRules(
            $true,
            $true,
            [Security.Principal.SecurityIdentifier]
        )
    )
    if ($rules.Count -ne $expectedSids.Count) {
        throw 'Private artifact DACL contains an unexpected rule count.'
    }
    $observedSids = [Collections.Generic.HashSet[string]]::new(
        [StringComparer]::Ordinal
    )
    foreach ($rule in $rules) {
        if (
            $rule.IsInherited -or
            $rule.AccessControlType -ne
                [Security.AccessControl.AccessControlType]::Allow -or
            $rule.FileSystemRights -ne
                [Security.AccessControl.FileSystemRights]::FullControl -or
            $rule.InheritanceFlags -ne $expectedInheritance -or
            $rule.PropagationFlags -ne
                [Security.AccessControl.PropagationFlags]::None -or
            $expectedSids -cnotcontains $rule.IdentityReference.Value -or
            -not $observedSids.Add($rule.IdentityReference.Value)
        ) {
            throw 'Private artifact DACL contains an unexpected access rule.'
        }
    }
    foreach ($expectedSid in $expectedSids) {
        if (-not $observedSids.Contains($expectedSid)) {
            throw 'Private artifact DACL omitted a trusted recovery identity.'
        }
    }
}

$fullPath = [IO.Path]::GetFullPath($LiteralPath)
$item = Get-Item -LiteralPath $fullPath -Force
$directory = $Operation.EndsWith(
    'directory',
    [StringComparison]::Ordinal
)
$sshCompatible = $Operation.IndexOf(
    '-ssh-file',
    [StringComparison]::Ordinal
) -ge 0
if (
    ($directory -and -not $item.PSIsContainer) -or
    (-not $directory -and $item.PSIsContainer) -or
    ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
) {
    throw 'Private artifact must be one real item of the requested kind.'
}

$owner = [Security.Principal.WindowsIdentity]::GetCurrent().User
function Get-ObservedPrivateAcl {
    $sections = [Security.AccessControl.AccessControlSections]::Access -bor
        [Security.AccessControl.AccessControlSections]::Owner
    if ($PSVersionTable.PSEdition -ceq 'Desktop') {
        return $item.GetAccessControl($sections)
    }
    if ($directory) {
        return [IO.FileSystemAclExtensions]::GetAccessControl(
            [IO.DirectoryInfo]::new($fullPath),
            $sections
        )
    }
    return [IO.FileSystemAclExtensions]::GetAccessControl(
        [IO.FileInfo]::new($fullPath),
        $sections
    )
}

function Set-ExpectedPrivateAcl {
    param(
        [Parameter(Mandatory)]
        [Security.AccessControl.FileSystemSecurity]$Security
    )

    if ($PSVersionTable.PSEdition -ceq 'Desktop') {
        $item.SetAccessControl($Security)
        return
    }
    if ($directory) {
        [IO.FileSystemAclExtensions]::SetAccessControl(
            [IO.DirectoryInfo]::new($fullPath),
            $Security
        )
        return
    }
    [IO.FileSystemAclExtensions]::SetAccessControl(
        [IO.FileInfo]::new($fullPath),
        $Security
    )
}

$observed = Get-ObservedPrivateAcl
if ($Operation.StartsWith('protect-', [StringComparison]::Ordinal)) {
    $requiresProtection = $false
    try {
        Assert-ExpectedPrivateAcl `
            -Security $observed `
            -Owner $owner `
            -Directory $directory `
            -SshCompatible $sshCompatible
    }
    catch {
        $requiresProtection = $true
    }
    if ($requiresProtection) {
        $security = Get-ExpectedPrivateAcl `
            -Owner $owner `
            -Directory $directory `
            -SshCompatible $sshCompatible
        Set-ExpectedPrivateAcl -Security $security
        $observed = Get-ObservedPrivateAcl
    }
}
Assert-ExpectedPrivateAcl `
    -Security $observed `
    -Owner $owner `
    -Directory $directory `
    -SshCompatible $sshCompatible

[pscustomobject]@{
    schemaVersion = 1
    path = $fullPath
    kind = if ($directory) { 'directory' } else { 'file' }
    policy = if ($sshCompatible) { 'openssh' } else { 'gate' }
    ownerSid = $owner.Value
    protectedDacl = $observed.AreAccessRulesProtected
    explicitRuleCount = @(
        $observed.GetAccessRules(
            $true,
            $true,
            [Security.Principal.SecurityIdentifier]
        )
    ).Count
} | ConvertTo-Json -Compress
