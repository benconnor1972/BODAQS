param([string] $Python = 'python')

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Enable-Utf8.ps1')
$testDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ('bodaqs-utf8-' + [guid]::NewGuid().ToString('N'))
[System.IO.Directory]::CreateDirectory($testDirectory) | Out-Null
$scriptFile = Join-Path $testDirectory 'roundtrip.py'
$resultFile = Join-Path $testDirectory 'result.txt'
try {
    # Build codepoints explicitly: a damaged script encoding cannot make this
    # oracle agree with damaged input by replacing both sides with question marks.
    $expectedText = 'scenario 1' + [char]0x2013 + '13; ' + [char]0x00b5 + 's; ' + [char]0x8a08
    $pythonSource = @'
from pathlib import Path
import sys
text = sys.stdin.read().rstrip("\r\n")
Path(sys.argv[1]).write_text(text, encoding="utf-8")
sys.stdout.write(text)
'@
    [System.IO.File]::WriteAllText($scriptFile, $pythonSource, (New-Object System.Text.UTF8Encoding($false)))
    $roundtrip = $expectedText | & $Python -X utf8 $scriptFile $resultFile
    if ($LASTEXITCODE -ne 0) { throw 'Python roundtrip failed' }
    $saved = [System.IO.File]::ReadAllText($resultFile, [System.Text.Encoding]::UTF8)
    if ($roundtrip -cne $expectedText -or $saved -cne $expectedText) {
        throw 'Native stdin/stdout or saved UTF-8 text was corrupted'
    }
    Write-Output 'PowerShell/native stdin/stdout/file UTF-8 roundtrip passed.'
} finally {
    foreach ($generatedFile in @($scriptFile, $resultFile)) {
        if (Test-Path -LiteralPath $generatedFile) { Remove-Item -LiteralPath $generatedFile }
    }
    # Remove only this owned, empty directory; never recursively traverse temp.
    if (Test-Path -LiteralPath $testDirectory) { Remove-Item -LiteralPath $testDirectory }
}
