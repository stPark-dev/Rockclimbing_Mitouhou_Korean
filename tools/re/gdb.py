"""Small GDB remote client for DuckStation's GDB server (127.0.0.1:2346; 2345 clashes with RPCS3).

Every request reads exactly one reply; a stop reply that arrives late is kept apart,
so register and memory reads never pick up an `S05` by mistake.
"""
import socket
import struct
import time


class GDB:
    def __init__(self, host="127.0.0.1", port=2346, timeout=10):
        self.s = socket.create_connection((host, port), timeout=timeout)
        self.buf = b""
        self.stops = []

    def _packet(self):
        while True:
            while self.buf[:1] in (b"+", b"-"):
                self.buf = self.buf[1:]
            start = self.buf.find(b"$")
            end = self.buf.find(b"#", start + 1) if start >= 0 else -1
            if start >= 0 and end >= 0 and len(self.buf) >= end + 3:
                body = self.buf[start + 1:end].decode("latin-1")
                self.buf = self.buf[end + 3:]
                self.s.sendall(b"+")
                return body
            chunk = self.s.recv(65536)
            if not chunk:
                raise ConnectionError("gdb server closed")
            self.buf += chunk

    def _send(self, cmd):
        data = cmd.encode("latin-1")
        self.s.sendall(b"$" + data + b"#" + b"%02x" % (sum(data) & 0xFF))

    def ask(self, cmd, ok=lambda r: True):
        self._send(cmd)
        while True:
            r = self._packet()
            if r[:1] in ("S", "T") and len(r) <= 4 and not cmd.startswith(("?", "c")):
                self.stops.append(r)
                continue
            if ok(r):
                return r

    def stop(self):
        # DuckStation pauses on ^C but answers only the next request
        self.s.sendall(b"\x03")
        time.sleep(0.2)
        return self.ask("?")

    def cont(self):
        self._send("c")

    def wait(self, timeout=None):
        old = self.s.gettimeout()
        self.s.settimeout(timeout)
        try:
            r = self._packet()
        finally:
            self.s.settimeout(old)
        self.stops.append(r)
        return r

    def regs(self):
        g = self.ask("g", ok=lambda r: len(r) >= 38 * 8).replace("x", "0")
        return [struct.unpack("<I", bytes.fromhex(g[i * 8:i * 8 + 8]))[0] for i in range(38)]

    def mem(self, addr, n):
        out = b""
        while n:
            k = min(n, 0x400)
            m = self.ask(f"m{addr:x},{k:x}", ok=lambda r: len(r) == 2 * k)
            out += bytes.fromhex(m)
            addr += k
            n -= k
        return out

    def u32(self, addr):
        return struct.unpack("<I", self.mem(addr, 4))[0]

    def brk(self, addr, on=True):
        return self.ask(f"{'Z' if on else 'z'}0,{addr:x},4")


REG = {n: i for i, n in enumerate(
    "zero at v0 v1 a0 a1 a2 a3 t0 t1 t2 t3 t4 t5 t6 t7 s0 s1 s2 s3 s4 s5 s6 s7 t8 t9 k0 k1 gp sp fp ra sr lo hi bad cause pc".split())}
