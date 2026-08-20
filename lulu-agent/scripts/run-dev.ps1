# 启动 LuLu Agent（开发）
Set-Location $PSScriptRoot\..
$req = Join-Path (Resolve-Path ..) "requirements.txt"
if (-not (Test-Path .\.venv\Scripts\python.exe)) {
  python -m venv .venv
  .\.venv\Scripts\pip install -r $req
}
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
