#!/usr/bin/env sh
export PYTHONUTF8=1
export PYTHONIOENCODING=utf-8
exec python3 "$(dirname "$0")/../bin/agent_memory.py" hook
