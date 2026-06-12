#!/bin/zsh
cd /Users/panavmhatre/Desktop/Coding/News
source venv/bin/activate
python3 run_daily.py --count 3 >> data/cron.log 2>&1
