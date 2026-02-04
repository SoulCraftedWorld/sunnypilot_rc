#!/usr/bin/env python3
import glob
import json
import os
import time
from typing import Optional, TextIO

DIR = "/data/log"
GLOB_MASK = os.path.join(DIR, "swaglog.*")

# Фильтры (можешь менять как хочешь)
FILTER_DAEMON = ["controlsd" , "card", "manager", "webrtcd", "stream_encoderd"]  #"selfdrived"
FILTER_SUBSTR = ""  #"Log remote control:"  # "" чтобы не фильтровать по тексту

# Сколько строк показать при старте (0 = только новые)
SHOW_LAST_LINES_ON_START = 1500


def newest_swaglog() -> Optional[str]:
  files = glob.glob(GLOB_MASK)
  if not files:
    return None

  def key(p: str) -> int:
    base = os.path.basename(p)
    _, _, num = base.partition(".")
    try:
      return int(num)
    except ValueError:
      return -1

  return max(files, key=key)


def open_and_position(path: str) -> TextIO:
  f = open(path, "r", encoding="utf-8", errors="replace")

  if SHOW_LAST_LINES_ON_START > 0:
    # Быстро показать последние N строк без чтения всего файла
    try:
      f.seek(0, os.SEEK_END)
      size = f.tell()
      # грубо: 4KB * N/20, но минимум 8KB
      back = max(8192, SHOW_LAST_LINES_ON_START * 256)
      f.seek(max(0, size - back), os.SEEK_SET)
      data = f.read()
      lines = data.splitlines()[-SHOW_LAST_LINES_ON_START:]
      for line in lines:
        yield_line(line)
    except Exception:
      pass

  # Далее — только новые строки
  f.seek(0, os.SEEK_END)
  return f


def yield_line(line: str) -> None:
  line = line.strip()
  if not line:
    return

  try:
    rec = json.loads(line)
  except json.JSONDecodeError:
    # не JSON — печатаем как есть (если проходит фильтры по подстроке)
    if not FILTER_SUBSTR or FILTER_SUBSTR in line:
      print(line, flush=True)
    return

  msg = rec.get("msg$s") or rec.get("msg") or ""
  ctx = rec.get("ctx", {})
  daemon = ctx.get("daemon", "?")
  level = rec.get("level", "?")
  created = rec.get("created", 0)

  # daemon может быть только в ctx (как у тебя), но иногда его нет
  if FILTER_DAEMON and daemon not in FILTER_DAEMON:
    return
  if FILTER_SUBSTR and FILTER_SUBSTR not in str(msg):
    return

  ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(created)) if created else "?"
  print(f"[{ts}] {daemon} {level}: {msg}", flush=True)


def main():
  current_path = None
  f = None

  print("Starting swaglog watcher...", flush=True)
  print(f"DIR={DIR}", flush=True)
  print(f"FILTER_DAEMON={FILTER_DAEMON!r} FILTER_SUBSTR={FILTER_SUBSTR!r}", flush=True)
  print(f"SHOW_LAST_LINES_ON_START={SHOW_LAST_LINES_ON_START}", flush=True)

  while True:
    newest = newest_swaglog()
    if newest is None:
      time.sleep(0.2)
      continue

    if newest != current_path:
      if f:
        try:
          f.close()
        except Exception:
          pass
      current_path = newest
      print(f"=== watching: {current_path} ===", flush=True)
      f = open_and_position(current_path)

    line = f.readline()
    if not line:
      time.sleep(0.05)
      continue

    yield_line(line)


if __name__ == "__main__":
  main()
