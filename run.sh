#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"

echo "========================================"
echo "  路线啵啵机 · Travel Atlas"
echo "========================================"
echo

# 选择可用的 python
PY=""
for c in python3.12 python3.11 python3.10 python3 python; do
  if command -v "$c" >/dev/null 2>&1; then PY="$c"; break; fi
done
if [ -z "$PY" ]; then
  echo "[错误] 未找到 Python，请先安装 Python 3.10+"
  exit 1
fi
echo "[环境] 使用 $PY"

# 创建 venv
if [ ! -d ".venv" ]; then
  echo "[初次启动] 创建虚拟环境 .venv ..."
  "$PY" -m venv .venv
fi

# 激活
# shellcheck disable=SC1091
source .venv/bin/activate

# 装依赖
if ! python -c "import flask" 2>/dev/null; then
  echo "[初次启动] 安装依赖（约 200MB，需要几分钟）..."
  python -m pip install --upgrade pip
  python -m pip install -r requirements.txt
fi

echo "[启动] http://127.0.0.1:5000 （Ctrl+C 停止）"
echo

# 后台 3 秒后打开浏览器
( sleep 3 && (xdg-open http://127.0.0.1:5000 >/dev/null 2>&1 || open http://127.0.0.1:5000 >/dev/null 2>&1 || true) ) &

exec python server.py
