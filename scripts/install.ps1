$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
$target = if ($args.Count -ge 1) { $args[0] } else { (Get-Location).Path }
$rest = @()
if ($args.Count -gt 1) { $rest = $args[1..($args.Count - 1)] }
$mapped = @()
foreach ($item in $rest) {
    if ($item -match '^-[A-Za-z]') { $mapped += "-$item" } else { $mapped += $item }
}
python "$PSScriptRoot\install.py" --target $target @mapped
exit $LASTEXITCODE
