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
    $button = Find-Control $Label ([Windows.Automation.ControlType]::Button)
    if ($button -and $button.Current.IsEnabled) {
      $button.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
      return
    }
    $skip = Find-Control "Skip for now" ([Windows.Automation.ControlType]::Button)
    if ($skip -and $skip.Current.IsEnabled) {
      $skip.GetCurrentPattern([Windows.Automation.InvokePattern]::Pattern).Invoke()
    }
    Start-Sleep -Milliseconds 150
  }
  throw "The installed workspace did not expose the enabled button '$Label'."
}
$recording = "live-s-package-dictation"
$reference = [IO.File]::ReadAllText($ReferenceFile).Trim()
Press-Button "Review recording $recording"
$deadline = [Diagnostics.Stopwatch]::StartNew()
while ($deadline.Elapsed.TotalSeconds -lt 30) {
  if ((Find-Control "Open transcript for $recording" ([Windows.Automation.ControlType]::Button)) -and
      (Find-Control $reference ([Windows.Automation.ControlType]::Text))) {
    Write-Host "Installed Windows History displayed the full reference and the open-transcript action."
    exit 0
  }
  Start-Sleep -Milliseconds 150
}
throw "The installed workspace did not display the complete saved transcript."
