"""Key taps for the emulator on a nested display: focus the DuckStation top-level window first
(Qt moves the focus to an inner widget that ignores key events), then send the keys like xkey.py.
usage: key.py :7 z 1 Down 0.5 ..."""
import sys
import time

from Xlib import X, XK, display
from Xlib.ext import xtest

disp = sys.argv[1]
assert disp not in (":0", ":1"), "refusing to touch the user desktop"
d = display.Display(disp)
root = d.screen().root


def focus():
    wins = [c for c in root.query_tree().children if (c.get_wm_name() or "").startswith("Rock-Climbing")]
    if wins:
        wins[-1].set_input_focus(X.RevertToParent, X.CurrentTime)
        d.sync()


for tok in sys.argv[2:]:
    try:
        time.sleep(float(tok))
        continue
    except ValueError:
        pass
    focus()
    kc = d.keysym_to_keycode(XK.string_to_keysym(tok))
    xtest.fake_input(d, X.KeyPress, kc)
    d.sync()
    time.sleep(0.08)
    xtest.fake_input(d, X.KeyRelease, kc)
    d.sync()
    time.sleep(0.05)
