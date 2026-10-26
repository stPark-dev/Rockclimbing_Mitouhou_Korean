#!/bin/sh
# restart DuckStation on the nested display :7 with $1 (cue) and give it input focus
for p in $(ps -eo pid,comm | awk '$2=="duckstation" || $2=="AppRun"{print $1}'); do kill $p; done
sleep 2
(DISPLAY=:7 duckstation -batch -fastboot "$1" >/dev/null 2>&1 &)
sleep 40
"${PYTHON:-python3}" - <<'PY'
from Xlib import display, X
d=display.Display(':7'); root=d.screen().root
wins=[c for c in root.query_tree().children if (c.get_wm_name() or '').startswith('Rock-Climbing')]
for w in wins[:-1]:
    try: w.unmap()
    except Exception: pass
w=wins[-1]; w.configure(stack_mode=X.Above); w.set_input_focus(X.RevertToParent, X.CurrentTime); d.sync()
print('focused', hex(w.id), 'of', len(wins))
PY
