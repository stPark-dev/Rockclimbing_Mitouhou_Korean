#!/bin/sh
# drive dev build from title to the mountain screen (route from tools/re/redux_route.lua)
P=${PYTHON:-python3}; K=${XKEY:-../kenshin/tools/re/xkey.py}
shot(){ import -display :7 -window root -crop 800x610+0+23 work/shots/route/$1.png; echo "shot $1"; }
PYTHON=$P sh tools/re/emu_restart.sh build/mitouhou_ko_dev.cue
$P $K :7 z 3 z 3 Down 0.4 Down 0.4 Down 0.4 Down 0.4 Down 0.4 Down 0.4 Down 1 z 4; shot 01_menu
$P $K :7 Down 0.5 Down 0.5 z 4 z 40; shot 02_after_summer
$P $K :7 z 40; shot 03_after_partner
$P $K :7 z 4 Down 0.4 Down 0.4 z 4; shot 04_plan
i=0; while [ $i -lt 30 ]; do $P $K :7 z 2.5; i=$((i+1)); [ $((i%6)) -eq 0 ] && shot 04_plan_$i; done
$P $K :7 x 2; shot 05_menu_with_plan
$P $K :7 Down 0.4 Down 0.4 Down 0.5 z 1
i=1; while [ $i -le 12 ]; do sleep 10; shot 06_mountain_$i; i=$((i+1)); done
echo done
