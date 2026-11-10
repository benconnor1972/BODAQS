# Preserve the existing Windows PowerShell UTF-8 bridge in native text pipelines.
param([string]$Python = 'python', [Parameter(ValueFromRemainingArguments=$true)][string[]]$BenchArgs)
. (Join-Path $PSScriptRoot 'Enable-Utf8.ps1')
& $Python -B (Join-Path $PSScriptRoot '../firmware/tools/bench.py') @BenchArgs
exit $LASTEXITCODE
