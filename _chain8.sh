#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
PY=/c/Users/humac/anaconda3/python.exe
echo "=== 1/5 extract 8 states ==="
env -u PYTHONPATH -u PYTHONHOME $PY extract_frames.py sleep roll dance stretch happy beg play_dead eat
echo "=== 2/5 make_clean_eat ==="
env -u PYTHONPATH -u PYTHONHOME $PY make_clean_eat.py
echo "=== 3/5 deploy --copy ==="
env -u PYTHONPATH -u PYTHONHOME $PY deploy_frames.py --copy
echo "=== 4/5 final_fix ==="
env -u PYTHONPATH -u PYTHONHOME $PY final_fix.py
echo "=== 5/5 bake_prop ==="
env -u PYTHONPATH -u PYTHONHOME $PY bake_prop.py
echo "CHAIN_DONE"
