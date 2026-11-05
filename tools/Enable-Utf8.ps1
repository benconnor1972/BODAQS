# Dot-source in the same PowerShell process before native text pipelines.
# ASCII source keeps this bootstrap readable by Windows PowerShell 5.1 too.
$global:OutputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::InputEncoding = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
