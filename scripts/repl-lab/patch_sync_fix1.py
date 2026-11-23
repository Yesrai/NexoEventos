#!/usr/bin/env python3
"""Corrige el registro del primer ciclo con el seguidor no disponible en _supervise_standby."""
from pathlib import Path

p = Path(__file__).with_name("labctl.py")
s = p.read_text()
old = '''            S.setdefault("sb_bad", time.time())
            if S["sb_bad"] and time.time() - S["sb_bad"] == 0:
                log("seguidor_no_disponible", estado=st)
'''
new = '''            if "sb_bad" not in S:
                S["sb_bad"] = time.time()
                log("seguidor_no_disponible", estado=st, politica=("degradar tras %ss" % DEGRADE_AFTER_S) if DEGRADE_AFTER_S > 0 else "bloquear: los COMMIT esperan, sin pérdida")
'''
assert old in s
p.write_text(s.replace(old, new))
print("ok")
