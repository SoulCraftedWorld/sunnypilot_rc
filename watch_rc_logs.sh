#!/usr/bin/env bash
set -euo pipefail

PATTERN='Log remote control:'
DIR='/data/log'

current=""

while true; do
  newest="$(ls -1 "$DIR"/swaglog.* 2>/dev/null | sort | tail -n 1 || true)"

  if [[ -z "$newest" ]]; then
    sleep 0.2
    continue
  fi

  if [[ "$newest" != "$current" ]]; then
    current="$newest"
    echo "=== watching: $current ===" >&2
    # tail: only new lines; grep: realtime
    tail -n 0 -F "$current" 2>/dev/null | grep --line-buffered "$PATTERN" &
    tail_pid=$!
  fi

  # Если tail умер (например файл удалили) — перезапустим цикл
  if ! kill -0 "$tail_pid" 2>/dev/null; then
    current=""
  fi

  # Проверяем периодически, появился ли новый файл
  sleep 0.5

  # Если появился новый файл, убьём старый tail и переподключимся
  newest2="$(ls -1 "$DIR"/swaglog.* 2>/dev/null | sort | tail -n 1 || true)"
  if [[ -n "$newest2" && "$newest2" != "$current" ]]; then
    kill "$tail_pid" 2>/dev/null || true
    wait "$tail_pid" 2>/dev/null || true
    current=""
  fi
done
