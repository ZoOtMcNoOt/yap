#requires -Version 5.1
param([Parameter(Mandatory)][long]$WindowHandle, [Parameter(Mandatory)][string]$ReferenceFile)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$workspace = [Windows.Automation.AutomationElement]::FromHandle([IntPtr]$WindowHandle)
function Find-Control([string]$Name, [Windows.Automation.ControlType]$Type) {
  $byName = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty, $Name)
  $byType = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty, $Type)
  return $workspace.FindFirst([Windows.Automation.TreeScope]::Descendants, [Windows.Automation.AndCondition]::new($byName, $byType))
}
function Press-Button([string]$Label) {
  $deadline = [Diagnostics.Stopwatch]::StartNew()
  while ($deadline.Elapsed.TotalSeconds -lt 30) {
    $skip = Find-Control "Skip for now" ([Windows.Automation.ControlType]::Button)
    if ($skip -and $skip.Current.IsEnabled -and -not $skip.Current.IsOffscreen) {
      $skip.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
    } else {
      $button = Find-Control $Label ([Windows.Automation.ControlType]::Button)
      if ($button -and $button.Current.IsEnabled -and -not $button.Current.IsOffscreen) {
        $button.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
        return
      }
    }
    Start-Sleep -Milliseconds 150
  }
  throw "The installed workspace did not expose the enabled button '$Label'."
}
function Read-TranscriptRegion($Region) {
  $ancestor = $Region
  while ($ancestor) {
    $pattern = $null
    if ($ancestor.TryGetCurrentPattern([Windows.Automation.TextPattern]::Pattern, [ref]$pattern)) {
      if ($ancestor.Equals($Region)) {
        $pattern.DocumentRange.GetText(-1)
      } else {
        try {
          $range = $pattern.RangeFromChild($Region)
          if ($range) { $range.GetText(-1) }
        } catch [System.ArgumentException] {
          # The provider can still expose text through the region's children.
        }
      }
    }
    if ($ancestor.Current.ControlType -eq [Windows.Automation.ControlType]::Document) { break }
    $ancestor = [Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($ancestor)
  }
  $textType = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty, [Windows.Automation.ControlType]::Text)
  $leaves = $Region.FindAll([Windows.Automation.TreeScope]::Descendants, $textType)
  return ($leaves | ForEach-Object { $_.Current.Name }) -join " "
}

$recording = "live-s-package-dictation"
$reference = [IO.File]::ReadAllText($ReferenceFile).Trim()
Press-Button "Review recording $recording"
$regionName = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty, "Transcript text")
$dialogName = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty, $recording)
$actionName = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::NameProperty, "Open transcript for $recording")
$buttonType = [Windows.Automation.PropertyCondition]::new([Windows.Automation.AutomationElement]::ControlTypeProperty, [Windows.Automation.ControlType]::Button)
$openAction = [Windows.Automation.AndCondition]::new($actionName, $buttonType)
$expected = ($reference -replace '\s+', ' ').Trim()
$deadline = [Diagnostics.Stopwatch]::StartNew()
$foundAction = $false
$foundRegion = $false
$observedLength = 0
while ($deadline.Elapsed.TotalSeconds -lt 30) {
  try {
    $containers = $workspace.FindAll([Windows.Automation.TreeScope]::Descendants, $dialogName)
    foreach ($container in $containers) {
      if ($container.Current.IsOffscreen) { continue }
      $action = $container.FindFirst([Windows.Automation.TreeScope]::Descendants, $openAction)
      if (-not $action -or -not $action.Current.IsEnabled -or $action.Current.IsOffscreen) { continue }
      $foundAction = $true
      $region = $container.FindFirst([Windows.Automation.TreeScope]::Descendants, $regionName)
      if (-not $region -or $region.Current.IsOffscreen) { continue }
      $foundRegion = $true
      foreach ($candidate in @(Read-TranscriptRegion $region)) {
        $actual = (([string]$candidate) -replace '\s+', ' ').Trim()
        $observedLength = [Math]::Max($observedLength, $actual.Length)
        if ($actual -ceq $expected) {
          Write-Host "Installed Windows History displayed the full reference and the open-transcript action."
          exit 0
        }
      }
    }
  } catch [Windows.Automation.ElementNotAvailableException] {
    # WebView2 replaced the accessible subtree during navigation.
  }
  Start-Sleep -Milliseconds 150
}
throw "History verification timed out. Open action=$foundAction, visible transcript region=$foundRegion, text length=$observedLength, expected length=$($expected.Length)."
