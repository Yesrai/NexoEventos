"""B-T6-1: anclaje anti-retroceso del testigo. Cubre restauración de prefijos antiguos, reutilización de épocas, concurrencia, reinicios, duplicados, corrupción, errores de red, pérdida del anclaje y recuperación tras fallos parciales."""
import json, shutil, sys, threading
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "backend")); sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_witness_service import Env  # noqa: E402
from app.failover.anchor import (AnchorLost, AnchoredAppendStore, FileAnchorBucket, RollbackDetected, SimAnchorBucket)  # noqa: E402
from app.failover.store import PreconditionFailed, StoreError, StoreUnavailable  # noqa: E402
from app.failover.witness import FileAppendStore, ObjectAppendStore, ImmutableBucketSim  # noqa: E402


def make(e, tmp, anchor=None, primary=None, **kw):
    primary = primary or FileAppendStore(tmp / "p.jsonl"); anchor = anchor if anchor is not None else SimAnchorBucket()
    st = AnchoredAppendStore(primary, anchor, e.signer, e.verifier, **kw)
    return st, anchor, primary


def setup(tmp_path, n_epochs=5):
    e = Env(tmp_path); st, an, pr = make(e, tmp_path); w = e.witness(store=st); e.genesis(w)
    for ep in range(1, n_epochs + 1): assert w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=ep))[0]
    return e, w, st, an, pr


def test_camino_feliz_ancla_cada_entrada_y_sobrevive_a_reinicio(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    assert len(an.o) == w.entries == 6
    st2, _, _ = make(e, tmp_path, anchor=an); w2 = e.witness(store=st2)                       # reinicio: nuevo proceso, mismo primario y anclaje
    assert w2.wm["lease_epoch"] == 5 and w2.entries == 6 and w2.last_hash == w.last_hash


def test_restaurar_prefijo_antiguo_del_primario_se_detecta_y_bloquea(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    old = pr.path.read_text().splitlines()[:3]; pr.path.write_text("\n".join(old) + "\n")       # ROLLBACK: el atacante restaura una copia antigua válida
    with pytest.raises(RollbackDetected): e.witness(store=make(e, tmp_path, anchor=an)[0])        # no arranca
    st2 = make(e, tmp_path, anchor=an)[0]
    with pytest.raises(RollbackDetected): st2.lines()
    with pytest.raises(RollbackDetected): st2.append("{}", 4)                                      # tampoco acepta informes


def test_servicio_en_marcha_bloquea_atestacion_tras_el_rollback_y_no_autoriza_con_estado_viejo(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    assert w.attest("a" * 16)["watermark"]["lease_epoch"] == 5
    pr.path.write_text("\n".join(pr.path.read_text().splitlines()[:2]) + "\n")                     # época 1 «restaurada»
    with pytest.raises(RollbackDetected): w.attest("b" * 16)                                       # nunca atesta con el estado viejo
    ok = False
    try: ok = w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=2))[0]                          # reutilizar una época antigua para volver a autorizar
    except RollbackDetected: pass
    assert not ok


def test_reutilizacion_de_epocas_tras_el_rollback_no_se_reanuda(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    pr.path.write_text("\n".join(pr.path.read_text().splitlines()[:4]) + "\n")
    st2 = make(e, tmp_path, anchor=an)[0]
    with pytest.raises(StoreError): e.witness(store=st2)
    assert len(an.o) == 6                                                                          # el anclaje conserva la historia completa


def test_recuperacion_explicita_desde_el_anclaje_restablece_el_estado(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    pr.path.write_text("\n".join(pr.path.read_text().splitlines()[:2]) + "\n")
    st2 = make(e, tmp_path, anchor=an)[0]
    with pytest.raises(StoreError): st2.recover_primary("sí")                                      # exige confirmación literal
    assert st2.recover_primary("RECUPERAR-PRIMARIO-DESDE-ANCLAJE") == 4
    w2 = e.witness(store=make(e, tmp_path, anchor=an)[0]); assert w2.wm["lease_epoch"] == 5 and w2.entries == 6


def test_rollback_con_primario_vacio_tambien_se_detecta(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    pr.path.write_text("")
    with pytest.raises(RollbackDetected): make(e, tmp_path, anchor=an)[0].lines()


def test_bifurcacion_primario_distinto_del_anclado(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    ls = pr.path.read_text().splitlines(); d = json.loads(ls[2]); d["reporter"] = "oci"; ls[2] = json.dumps(d); pr.path.write_text("\n".join(ls) + "\n")
    with pytest.raises(StoreError): make(e, tmp_path, anchor=an)[0].lines()


def test_anclaje_corrupto_firma_invalida_o_fuera_de_secuencia(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    name = "anchor/000000000003"; good = an.o[name]
    for mala in (b"no es json", json.dumps({**json.loads(good), "sig": "00" * 32}).encode(), json.dumps({**json.loads(good), "seq": 9}).encode(), json.dumps({**json.loads(good), "hash": "f" * 64}).encode()):
        an.o[name] = mala
        with pytest.raises(StoreError): make(e, tmp_path, anchor=an)[0].lines()
    an.o[name] = good; make(e, tmp_path, anchor=an)[0].lines()


def test_anclaje_con_entrada_intermedia_borrada(tmp_path):
    e, w, st, an, pr = setup(tmp_path, 6)
    an.worm = False; an.delete("anchor/000000000003")
    with pytest.raises(StoreError): make(e, tmp_path, anchor=an)[0].lines()


def test_atacante_sin_retencion_puede_sustituir_pero_la_firma_lo_delata(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    worm = SimAnchorBucket(worm=True)
    with pytest.raises(PreconditionFailed): an.put_blind("anchor/000000000002", b"x")               # con retención: no se sobrescribe
    with pytest.raises(PreconditionFailed): an.delete("anchor/000000000002")
    an.worm = False; an.put_blind("anchor/000000000002", b"forjado")                               # CONTROL negativo: sin retención el atacante escribe, pero no puede firmar como el testigo
    with pytest.raises(StoreError): make(e, tmp_path, anchor=an)[0].lines(); _ = worm


def test_perdida_del_anclaje_con_historial_bloquea_salvo_bootstrap_explicito(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    with pytest.raises(AnchorLost): make(e, tmp_path, anchor=SimAnchorBucket())[0].lines()          # bucket vacío/nuevo: no se re-ancla en silencio
    st2, an2, _ = make(e, tmp_path, anchor=SimAnchorBucket(), bootstrap=True); st2.lines(); assert len(an2.o) == 6    # migración controlada y explícita


def test_genesis_en_vuelo_con_anclaje_vacio_se_completa(tmp_path):
    e = Env(tmp_path); st, an, pr = make(e, tmp_path)
    an.before = lambda op, name: (_ for _ in ()).throw(StoreUnavailable("red")) if op == "create" else None
    w = e.witness(store=st)
    with pytest.raises(StoreUnavailable): e.genesis(w)                                              # el primario quedó con 1 entrada y el anclaje sin ella
    an.before = None; w2 = e.witness(store=make(e, tmp_path, anchor=an)[0]); assert len(an.o) == 1 and w2.entries == 1


def test_fallo_parcial_primario_escrito_anclaje_no(tmp_path):
    e, w, st, an, pr = setup(tmp_path, 2)
    an.before = lambda op, name: (_ for _ in ()).throw(StoreUnavailable("red caída")) if op == "create" else None
    with pytest.raises(StoreUnavailable): w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=3))
    with pytest.raises(StoreUnavailable): w.attest("c" * 16)                                       # sin anclaje NO se atesta (falla cerrado)
    an.before = None
    r = w.attest("d" * 16); assert r["watermark"]["lease_epoch"] == 3 and len(an.o) == 4            # recuperado: el anclaje se completó antes de servir
    assert w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=4))[0] and len(an.o) == 5


def test_respuesta_perdida_tras_aplicar_el_anclaje_es_idempotente(tmp_path):
    e, w, st, an, pr = setup(tmp_path, 1)
    c = {"n": 0}
    def after(op, name):
        if op == "create" and c["n"] == 0: c["n"] = 1; raise StoreUnavailable("respuesta perdida")
    an.after = after
    with pytest.raises(StoreUnavailable): w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=2))
    assert w.attest("e" * 16)["watermark"]["lease_epoch"] == 2 and len(an.o) == 3                   # ya estaba anclado: el reintento no lo duplica ni bifurca


def test_lectura_del_anclaje_caida_falla_cerrado(tmp_path):
    e, w, st, an, pr = setup(tmp_path)
    an.before = lambda op, name: (_ for _ in ()).throw(StoreUnavailable("red")) if op == "read" else None
    with pytest.raises(StoreUnavailable): w.attest("f" * 16)


def test_duplicado_con_distinto_contenido_es_bifurcacion(tmp_path):
    e, w, st, an, pr = setup(tmp_path, 2)
    other = Env(tmp_path / "otro"); _ = other
    line = pr.lines()[1]; d = json.loads(line); d["payload"] = {**d["payload"], "lease_epoch": 99}
    with pytest.raises(StoreError): st._anchor_put(json.dumps(d))                                    # misma secuencia, otro contenido
    st._anchor_put(line)                                                                            # mismo contenido: idempotente


def test_concurrencia_varias_instancias_comparten_primario_y_anclaje(tmp_path):
    e = Env(tmp_path); an = SimAnchorBucket(); primary = FileAppendStore(tmp_path / "c.jsonl")
    inst = [e.witness(store=make(e, tmp_path, anchor=an, primary=primary)[0], max_epoch_jump=1000) for _ in range(4)]; e.genesis(inst[0])
    def worker(i, eps):
        for ep in eps: inst[i % 4].report(*e.rep("aws", kind="lease_epoch", lease_epoch=ep))
    ths = [threading.Thread(target=worker, args=(i, list(range(i + 1, 41, 8)))) for i in range(8)]; [t.start() for t in ths]; [t.join() for t in ths]
    final = e.witness(store=make(e, tmp_path, anchor=an, primary=primary)[0], max_epoch_jump=1000)
    assert final.wm["lease_epoch"] == 40 and len(an.o) == final.entries == len(primary.lines())
    prev = "0" * 64
    for ln in primary.lines(): d = json.loads(ln); assert d["prev"] == prev; prev = d["hash"]


def test_anclaje_en_directorio_real_es_solo_creacion_y_detecta_rollback(tmp_path):
    e = Env(tmp_path); an = FileAnchorBucket(tmp_path / "anchor"); st, _, pr = make(e, tmp_path, anchor=an); w = e.witness(store=st); e.genesis(w)
    for ep in (1, 2, 3): w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=ep))
    with pytest.raises(PreconditionFailed): an.create("anchor/000000000001", b"otro")
    shutil.copy(pr.path, tmp_path / "old.jsonl"); old = (tmp_path / "old.jsonl").read_text().splitlines()[:2]
    pr.path.write_text("\n".join(old) + "\n")
    with pytest.raises(RollbackDetected): make(e, tmp_path, anchor=FileAnchorBucket(tmp_path / "anchor"))[0].lines()


def test_ObjectAppendStore_como_primario_tambien_se_ancla(tmp_path):
    e = Env(tmp_path); an = SimAnchorBucket(); pr = ObjectAppendStore(ImmutableBucketSim(worm=True)); st = AnchoredAppendStore(pr, an, e.signer, e.verifier)
    w = e.witness(store=st); e.genesis(w); w.report(*e.rep("aws", kind="lease_epoch", lease_epoch=1))
    pr.b.o.pop("log/000000000002", None) if not pr.b.worm else pr.b.o.pop("log/000000000002")      # restauración del primario (el atacante controla ese almacén)
    with pytest.raises(RollbackDetected): st.lines()
