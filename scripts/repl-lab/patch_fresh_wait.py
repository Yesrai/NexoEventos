#!/usr/bin/env python3
"""fresh_lab: tras arrancar el monitor espera a que HAProxy-BD enrute al escritor (el lease del setup caduca en 6 s y hace falta un ciclo de renovación + 'rise' del health check)."""
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
s = p.read_text()
old = "    return start_monitor(tag, env=env) if monitor else None\n"
new = '''    if not monitor:
        return None
    log = start_monitor(tag, env=env)
    assert wait_until(lambda: any(v.startswith("UP") for v in L.hap_state().values()), 30) is not None, "HAProxy-BD no enruta a ningún escritor tras arrancar el monitor"
    return log
'''
assert old in s
p.write_text(s.replace(old, new))
print("ok")
