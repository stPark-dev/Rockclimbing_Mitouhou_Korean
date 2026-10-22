"""Start a game task (coroutine) by hand through DuckStation's GDB server, for state intervention.

usage: spawn_task.py <handler hex> [port]   e.g. spawn_task.py 800b3d2c 2345 (KABE rockfall)

Stops at the entry of the yield function 0x800118D8 (task context), fakes a call to the task
creator 0x80014D50(handler, 8) that returns to the same entry, then restores the registers it
changed. DuckStation refuses `G`, so registers are written one by one with `P` (docs/survey.md §9).
"""
import struct
import sys

from gdb import GDB, REG

YIELD, SPAWN = 0x800118D8, 0x80014D50
# every writable register except zero, k0/k1 and the read-only sr, bad, cause
RESTORE = [n for n in REG if n not in ("zero", "k0", "k1", "sr", "bad", "cause")]


def setregs(g, r, names):
    for n in names:
        g.ask(f"P{REG[n]:x}={struct.pack('<I', r[REG[n]]).hex()}")


def main():
    handler = int(sys.argv[1], 16)
    g = GDB(port=int(sys.argv[2]) if len(sys.argv) > 2 else 2346)
    g.stop()
    g.brk(YIELD)
    saved = None
    try:
        g.cont()
        g.wait(10)
        saved = g.regs()
        if saved[REG["pc"]] != YIELD:
            raise RuntimeError(f"stopped at {saved[REG['pc']]:#x}, not the yield entry")
        r = list(saved)
        r[REG["a0"]], r[REG["a1"]], r[REG["ra"]], r[REG["pc"]] = handler, 8, YIELD, SPAWN
        setregs(g, r, ("a0", "a1", "ra", "pc"))
        g.cont()
        g.wait(10)
        after = g.regs()
        if after[REG["pc"]] != YIELD or after[REG["sp"]] != saved[REG["sp"]]:
            raise RuntimeError(f"call did not return to the yield entry (pc {after[REG['pc']]:#x})")
        print("task", hex(after[REG["v0"]]))
    except Exception:
        g.stop()  # a timed-out wait leaves the game running
        raise
    finally:
        if saved is not None:
            setregs(g, saved, RESTORE)
        g.brk(YIELD, False)
        g.cont()


if __name__ == "__main__":
    main()
