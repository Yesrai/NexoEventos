#!/usr/bin/env python3
"""Tras la corrida 3 de F (31/33):
- F8: el monitor RESTABLECIÓ la protección por sí solo en 2 s (unknown -> unprotected -> reprotecting -> protected con barrera de LSN) antes de la caída, de modo que al caer la primaria el estado era
  legítimamente 'protected' y la promoción fue correcta. La prueba no mantenía la incertidumbre: ahora se pausa el monitor, se pone el estado en 'unknown', se tira la primaria y solo entonces se reanuda.
- F4: se contaban como 'confirmaciones sin copia' también las respuestas 200 de REPETICIONES de una clave cuya reserva original ya estaba confirmada y replicada (no hay COMMIT nuevo). Ahora se
  separan: los 201 (COMMIT nuevo) durante la caída del seguidor deben ser 0, y los 200 solo valen si la reserva ya existía en el seguidor; se conservan las listas como evidencia."""
import textwrap
from pathlib import Path

p = Path(__file__).with_name("repl_test.py")
T = p.read_text()


def rep(old: str, new: str):
    global T
    for extra in (0, 4, 8):
        o = textwrap.indent(textwrap.dedent(old), " " * extra)
        n = textwrap.indent(textwrap.dedent(new), " " * extra)
        if o in T:
            T = T.replace(o, n, 1)
            return
    raise AssertionError("no se encontró: " + old[:90])


rep('''
assert L.prot_cas("unknown", expect=("protected",), primario="pg-aws", motivo="F8: el estado de protección se vuelve incierto"), "no se pudo provocar la incertidumbre"
w = Writers("f8"); w.start(); msleep(3)
t_kill = kill_node("pg-aws")
msleep(10)''', '''
w = Writers("f8"); w.start(); msleep(3)
L.PAUSE.parent.mkdir(parents=True, exist_ok=True); L.PAUSE.write_text("F8"); time.sleep(1.0)     # el monitor no actúa: así la incertidumbre se mantiene hasta la caída
assert L.prot_cas("unknown", expect=("protected",), primario="pg-aws", motivo="F8: el estado de protección se vuelve incierto"), "no se pudo provocar la incertidumbre"
t_kill = kill_node("pg-aws")
time.sleep(0.5); L.PAUSE.unlink(missing_ok=True)          # se reanuda el monitor con la primaria ya caída y el estado en 'unknown'
msleep(10)''')

rep('''
acks_blocked = sum(1 for a in w.acked if a[0] > t_dis + 0.7)''', '''
win_acks = [a for a in w.acked if a[0] > t_dis + 0.7]
new_commit_acks = [a for a in win_acks if a[3] == 201]            # COMMIT nuevo confirmado con el seguidor caído: debe ser 0
replay_acks = [a for a in win_acks if a[3] == 200]                # repeticiones de una clave cuya reserva ya estaba confirmada: válidas solo si ya existía en el seguidor
ids_seguidor = set(q1("pg-oci", f"SELECT id::text FROM reservations WHERE event_id={EV_GENERAL}").split())
replays_con_copia = all(a[2] in ids_seguidor for a in replay_acks)
acks_blocked = len(new_commit_acks)''')
rep('''"confirmaciones_al_cliente_con_el_seguidor_caido": acks_blocked,''', '''"confirmaciones_201_(COMMIT_nuevo)_con_el_seguidor_caido": acks_blocked, "respuestas_200_repeticion_de_claves_ya_replicadas": len(replay_acks), "todas_las_repeticiones_ya_estaban_en_el_seguidor": replays_con_copia,''')
rep('''int(waiters) > 0 and acks_blocked == 0 and mode_blocked == "protected"''', '''int(waiters) > 0 and acks_blocked == 0 and replays_con_copia and mode_blocked == "protected"''')
p.write_text(T)
print("ok")
