#!/bin/bash
# collect.py가 죽어있으면 재시작하는 워치독 (cron이 매분 실행)
if ! ps -eo cmd | grep -q "[c]ollect.py"; then
  cd /home/padmd/videoprocessing
  setsid ./venv/bin/python -u collect.py >> collect.log 2>&1 < /dev/null &
  echo "$(date '+%Y-%m-%d %H:%M:%S') 워치독: collect.py 재시작" >> collect_watchdog.log
fi
