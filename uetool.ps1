# uetool launcher (PowerShell). Add this folder to your PATH, or call directly.
# Set $env:UETOOL_PYTHON to a Python 3.11+ interpreter if `python` is older.
$ToolDir = Split-Path -Parent $PSCommandPath
$Py = if ($env:UETOOL_PYTHON) { $env:UETOOL_PYTHON } else { "python" }
& $Py (Join-Path $ToolDir "uetool.py") @args
exit $LASTEXITCODE
