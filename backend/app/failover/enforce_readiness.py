"""Dry-run de preparación para activar WRITE_GATE_MODE=enforce. SOLO LECTURA: no cambia el modo (el valor por defecto sigue siendo `off`), no escribe en la base de datos, no modifica el
lease y no escribe en el almacén salvo que se pida expresamente la autoprueba de escrituras (`selftest_writes=True`, que crea objetos `selftest-*` y solo está pensada para un almacén de
ensayo). Todo lo que no se pueda comprobar se informa como NO_VERIFICADO y **nunca** cuenta como seguro: el veredicto falla cerrado.

Comprueba: configuración del entorno, conectividad y semántica del almacén del lease, estado del lease, compatibilidad con las rutas actuales, escritores externos (si se da un detector),
comportamiento ante la pérdida del lease (autoprueba con el MISMO código de la compuerta sobre una base SQLite en memoria), procedimiento de reversión y qué pasa si la activación falla.
Veredictos: SEGURO_PARA_ACTIVAR (sin bloqueos ni nada sin verificar) · NO_SEGURO (algún BLOQUEA) · NO_VERIFICADO (sin bloqueos pero con comprobaciones sin evidencia).
Un veredicto SEGURO no sustituye una ventana autorizada ni la validación contra el servicio real: no demuestra nada sobre AWS/OCI.
"""
from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path

from app.failover import write_paths as wp
from app.failover.gate import WriteGate, build_gate_from_env, install_db_guard, WriteFenceError
from app.failover.lease import LeaseClient, LeaseConfig, LeaseConfigError, Record, init_lease
from app.failover.store import FileStore, InMemoryStore, OciCliStore, ParHttpStore, StoreError, StoreUnavailable, verify_store_semantics

OK, WARN, BLOCK, UNKNOWN = "OK", "ADVERTENCIA", "BLOQUEA", "NO_VERIFICADO"
CRITICAL_UNKNOWN = ("almacen_semantica", "escritores_externos", "estado_lease")     # sin evidencia de esto, no se declara seguro


def _item(estado, detalle, **extra):
    return {"estado": estado, "detalle": detalle, **extra}


def _build_store(env, selftest_writes: bool):
    kind = env.get("WRITE_GATE_STORE", "").strip().lower()
    app_env = env.get("APP_ENV", "development").strip().lower()
    obj = env.get("WRITE_GATE_OCI_OBJECT", "writer-lease.json")
    if kind == "file":
        if app_env == "production":
            raise RuntimeError("WRITE_GATE_STORE=file no se permite con APP_ENV=production")
        path = env.get("WRITE_GATE_FILE_PATH")
        if not path:
            raise RuntimeError("falta WRITE_GATE_FILE_PATH")
        return kind, FileStore(path), (lambda: FileStore(f"{path}.dryrun-{uuid.uuid4().hex[:6]}"))   # la autoprueba de archivos solo usa archivos temporales: es segura
    if kind == "par-http":
        par = env.get("WRITE_GATE_PAR_URL_FILE")
        if not par:
            raise RuntimeError("falta WRITE_GATE_PAR_URL_FILE")
        local = env.get("WRITE_GATE_ALLOW_HTTP_LOCALHOST") == "1" and app_env != "production"
        return kind, ParHttpStore(par, object_name=obj, allow_http_localhost=local), (lambda: ParHttpStore(par, object_name=f"{obj}.selftest-{uuid.uuid4().hex[:8]}", allow_http_localhost=local))
    if kind == "oci-cli":
        ns, bucket = env.get("WRITE_GATE_OCI_NAMESPACE"), env.get("WRITE_GATE_OCI_BUCKET")
        if not (ns and bucket):
            raise RuntimeError("faltan WRITE_GATE_OCI_NAMESPACE / WRITE_GATE_OCI_BUCKET")
        profile = env.get("WRITE_GATE_OCI_PROFILE", "NEXOEVENTOS_LEASE")
        return kind, OciCliStore(ns, bucket, obj, profile), (lambda: OciCliStore(ns, bucket, f"{obj}.selftest-{uuid.uuid4().hex[:8]}", profile))
    raise RuntimeError("WRITE_GATE_STORE debe ser file, oci-cli o par-http")


def check_loss_behavior() -> dict:
    """Autoprueba del comportamiento ante la pérdida del lease con el código REAL de la compuerta (HTTP + guardia de BD) sobre SQLite en memoria. No toca ninguna base real."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from sqlalchemy.pool import StaticPool
    from app.failover.gate import WriteGateMiddleware

    class Clk:
        t = 1000.0
        def __call__(self): return self.t
    clk, store = Clk(), InMemoryStore(); store.verified = True; init_lease(store)
    lease = LeaseClient(store, LeaseConfig(ttl_s=15, margin_s=5), holder_id="dryrun", mono=clk)
    gate = WriteGate(lease, "primary")
    eng = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}); SF = sessionmaker(bind=eng)
    with eng.begin() as c: c.execute(text("CREATE TABLE t (id int)"))
    install_db_guard(eng, SF, gate)
    app = FastAPI(); app.add_middleware(WriteGateMiddleware, gate=gate)
    @app.post("/w")
    def w(): return {}
    @app.get("/r")
    def r(): return {}
    res = {}
    def rejected(fn):
        try: fn(); return False
        except WriteFenceError: return True
    assert lease.acquire().ok
    with eng.begin() as c: c.execute(text("INSERT INTO t VALUES (1)"))
    res["escribe_con_lease"] = True
    def mid_session():
        with SF() as s:
            s.execute(text("INSERT INTO t VALUES (2)")); clk.t += 100; s.commit()
    clk.t += 0.0; res["commit_de_sesion_abortado_si_caduca_a_mitad"] = rejected(mid_session)
    lease2 = lease; lease2._deadline = clk.t + 10                                   # restablece un plazo válido para la siguiente comprobación
    def mid_engine():
        with eng.begin() as c:
            c.execute(text("INSERT INTO t VALUES (3)")); clk.t += 100
    res["commit_de_engine_abortado_si_caduca_a_mitad"] = rejected(mid_engine)
    res["sentencia_rechazada_sin_lease"] = rejected(lambda: eng.connect().exec_driver_sql("INSERT INTO t VALUES (4)"))
    cl = TestClient(app)
    res["http_post_503_sin_lease"] = cl.post("/w").status_code == 503
    res["http_get_sigue_sirviendo"] = cl.get("/r").status_code == 200
    with eng.connect() as c: n = c.execute(text("SELECT count(*) FROM t")).scalar()
    res["filas_persistidas_solo_las_validas"] = n == 1
    return res


def check_enforce_readiness(env: dict | None = None, *, app=None, external_check=None, selftest_writes: bool = False) -> dict:
    env = dict(os.environ if env is None else env)
    rep: dict[str, dict] = {}
    mode = env.get("WRITE_GATE_MODE", "off").strip().lower()
    rep["modo_actual"] = _item(OK, f"WRITE_GATE_MODE={mode or 'off'} (este dry-run no cambia ningún modo; el valor por defecto sigue siendo off)")

    # 1) configuración
    store = factory = None
    try:
        cfg = LeaseConfig(ttl_s=float(env.get("WRITE_GATE_TTL_S", "15")), margin_s=float(env.get("WRITE_GATE_MARGIN_S", "5"))); cfg.validate()
        role = env.get("WRITE_GATE_ROLE", "primary")
        if role not in ("primary", "standby"):
            raise RuntimeError("WRITE_GATE_ROLE debe ser primary o standby")
        kind, store, factory = _build_store(env, selftest_writes)
        rep["configuracion"] = _item(OK, f"almacén {kind}, rol {role}, ttl {cfg.ttl_s:g} s, margen {cfg.margin_s:g} s")
    except (RuntimeError, LeaseConfigError, ValueError, StoreError) as e:
        rep["configuracion"] = _item(BLOCK, f"configuración inválida o incompleta ({type(e).__name__}): con enforce la API NO arrancaría (falla cerrado)")
        role = None

    # 2) conectividad, semántica y estado del lease (solo lecturas; las escrituras de la autoprueba son opt-in)
    if store is not None:
        try:
            rv = store.read()
            rep["almacen_conectividad"] = _item(OK, "el almacén responde a la lectura")
        except Exception as e:  # noqa: BLE001 — cualquier error de lectura (red, archivo corrupto, CLI) es «no responde / ilegible»: falla cerrado
            rv = None
            rep["almacen_conectividad"] = _item(BLOCK, f"el almacén no responde ({type(e).__name__}): con enforce no habría lease y las escrituras se rechazarían")
            rep["estado_lease"] = _item(UNKNOWN, "no se pudo leer el lease")
        else:
            if rv is None:
                rep["estado_lease"] = _item(BLOCK, "el lease no está inicializado (init_lease pendiente): con enforce nadie podría escribir")
            else:
                try:
                    rec = Record.load(rv.data)
                    if rec.released or rec.holder is None:
                        rep["estado_lease"] = _item(OK, f"lease libre (época {rec.epoch})")
                    else:
                        rep["estado_lease"] = _item(WARN, f"hay un titular activo (época {rec.epoch}): este nodo solo escribirá cuando lo obtenga (TTL+margen tras la última renovación del titular)")
                except StoreError:
                    rep["estado_lease"] = _item(BLOCK, "el registro del lease es ilegible (falla cerrado)")
        if rep["almacen_conectividad"]["estado"] == OK:
            if kind == "file" or selftest_writes:
                try:
                    sem = verify_store_semantics(factory); ok = all(sem.values())
                    rep["almacen_semantica"] = _item(OK if ok else BLOCK, "autoprueba de If-Match / If-None-Match " + ("superada" if ok else f"FALLIDA: {sem}") + (" (con escrituras a objetos de prueba)" if kind != "file" else " (archivos temporales)"))
                except (StoreError, OSError) as e:
                    rep["almacen_semantica"] = _item(BLOCK, f"autoprueba imposible ({type(e).__name__})")
            else:
                rep["almacen_semantica"] = _item(UNKNOWN, "la autoprueba de condiciones requiere escribir objetos de prueba (selftest_writes=True contra un almacén de ensayo); con enforce se ejecuta al arrancar y falla cerrado")
        else:
            rep["almacen_semantica"] = _item(UNKNOWN, "sin conectividad no se puede verificar")
    else:
        for k in ("almacen_conectividad", "almacen_semantica", "estado_lease"):
            rep[k] = _item(UNKNOWN, "configuración inválida")

    # 3) rutas actuales
    if app is not None:
        inv = wp.route_inventory(app); src = wp.scan_app_sources(Path(__file__).resolve().parents[1])
        problems = [k for k, bad in (("otro motor de BD", src["engine"] - wp.EXPECTED_ENGINE_FILES), ("conexión cruda", src["raw"]), ("tareas de fondo nuevas", src["background"] - wp.EXPECTED_BACKGROUND_FILES)) if bad]
        unsafe = [r for r in inv if any(m not in wp.SAFE_METHODS for m in r["metodos"])]
        rep["rutas"] = _item(BLOCK if problems else OK, ("productores fuera de la compuerta: " + ", ".join(problems)) if problems else
                             f"{len(unsafe)} rutas de escritura (503 sin lease) y {len(inv) - len(unsafe)} de lectura; un solo motor de BD, sin conexiones crudas ni tareas de fondo que escriban",
                             login_y_registro_requieren_lease=any("/api/auth/login" in r["ruta"] for r in unsafe))
    else:
        rep["rutas"] = _item(UNKNOWN, "no se entregó la aplicación para inventariar las rutas")

    # 4) escritores externos
    if external_check is None:
        rep["escritores_externos"] = _item(UNKNOWN, "no se entregó un detector (hace falta un rol de monitoreo de la base); migraciones, scripts y psql NO están descartados")
    else:
        try:
            r = external_check()
            blocks, vis = bool(r.get("bloquea")), r.get("visibilidad")
            rep["escritores_externos"] = _item(BLOCK if blocks else (WARN if vis != "completa" else OK),
                                               "hay escritores fuera de la compuerta" if blocks else ("visibilidad parcial: no se pueden descartar" if vis != "completa" else "sin escritores externos en este instante"),
                                               hallazgos=[{k: f.get(k) for k in ("severity", "kind", "role")} for f in r.get("hallazgos", [])])
            if vis != "completa" and not blocks:
                rep["escritores_externos"]["estado"] = UNKNOWN
        except Exception as e:  # noqa: BLE001
            rep["escritores_externos"] = _item(UNKNOWN, f"el detector falló ({type(e).__name__})")

    # 5) pérdida del lease (autoprueba del código real)
    try:
        sim = check_loss_behavior()
        rep["perdida_de_lease"] = _item(OK if all(sim.values()) else BLOCK, "comportamiento ante la pérdida del lease " + ("correcto" if all(sim.values()) else f"INCORRECTO: {sim}"), pruebas=sim, entorno="simulado (SQLite en memoria, código real de la compuerta)")
    except Exception as e:  # noqa: BLE001
        rep["perdida_de_lease"] = _item(UNKNOWN, f"no se pudo ejecutar la autoprueba ({type(e).__name__})")

    # 6) reversión y activación fallida
    try:
        revert_ok = build_gate_from_env({**env, "WRITE_GATE_MODE": "off"}) is None
        try:
            build_gate_from_env({"WRITE_GATE_MODE": "enforce", "WRITE_GATE_STORE": "inexistente"}); invalid_fails = False
        except RuntimeError:
            invalid_fails = True
        rep["reversion"] = _item(OK if revert_ok else BLOCK, "volver a WRITE_GATE_MODE=off (y reiniciar la API) elimina la compuerta" if revert_ok else "con off todavía se construye una compuerta",
                                 pasos=["WRITE_GATE_MODE=off en el entorno del servicio", "reiniciar la API", "comprobar GET /write-gate → 404 y escrituras 201/200"],
                                 condiciones=["el lease nunca debe quedar retenido por un nodo sin API (liberar o esperar TTL+margen)", "con off no hay protección: el failover automático no es seguro"])
        rep["activacion_fallida"] = _item(OK if invalid_fails else BLOCK, "una configuración inválida impide el arranque (no degrada en silencio a off); si el lease no se obtiene, la API sirve LECTURAS y rechaza escrituras con 503 (solo lectura)" if invalid_fails
                                          else "una configuración inválida arrancaría sin compuerta")
    except Exception as e:  # noqa: BLE001
        rep["reversion"] = _item(UNKNOWN, f"no se pudo comprobar ({type(e).__name__})")
        rep["activacion_fallida"] = _item(UNKNOWN, "no se pudo comprobar")

    estados = {k: v["estado"] for k, v in rep.items()}
    if BLOCK in estados.values():
        verdict = "NO_SEGURO"
    elif UNKNOWN in estados.values() or any(estados.get(k) != OK and estados.get(k) != WARN for k in CRITICAL_UNKNOWN):
        verdict = "NO_VERIFICADO"
    else:
        verdict = "SEGURO_PARA_ACTIVAR"
    return {"veredicto": verdict, "comprobaciones": rep, "modo_cambiado": False, "nota": "Un veredicto SEGURO no valida AWS/OCI ni sustituye una ventana autorizada."}
