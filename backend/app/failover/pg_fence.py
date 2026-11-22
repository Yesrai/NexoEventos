"""Vallado de escritura EN LA PROPIA BASE (PostgreSQL), ligado al lease: la base decide, al COMMIT y con SU reloj, si una escritura vale. Complementa a la compuerta de la aplicación (gate.py)
y cierra el hueco que ella declara: una pausa del proceso entre la comprobación y la escritura efectiva, o un proceso viejo que sobrevive, ya no pueden confirmar nada sin autoridad vigente.

Mecanismo (instalable y comprobable; se prueba contra PostgreSQL real desechable):
  · `nexo_fence.writer_fence` guarda la ÉPOCA vigente, el titular y `valid_until` (instante del reloj de la BASE). Sin autorización vigente: `valid_until = -infinity` (estado de un standby y de un
    primario vallado).
  · Cada tabla del esquema `public` lleva un TRIGGER DE RESTRICCIÓN `DEFERRABLE INITIALLY DEFERRED` (AFTER INSERT/UPDATE/DELETE, por fila) que se ejecuta AL COMMIT: rechaza la transacción si
    `valid_until <= clock_timestamp()` o si la época que declara la sesión (`nexo.writer_epoch`, fijada por la aplicación con el epoch de SU lease) no es la de la base. Un TRUNCATE se rechaza al
    instante con la misma regla. Una transacción larga que empezó con autoridad y la perdió ANTES del commit se rechaza: el servidor, no el proceso, decide.
  · Un EVENT TRIGGER engancha automáticamente las tablas nuevas (migraciones futuras).
  · Solo el rol «guardián» (`keeper_role`) puede conceder o revocar autoridad (`grant_authority`/`revoke_authority`); el rol de la aplicación solo puede LEER el estado. Una renovación solo se
    envía tras renovar el lease con éxito; si el guardián (o el almacén del lease) falla, la autorización de la base CADUCA SOLA y la base rechaza los commits.
  · La época solo puede subir: una época menor se rechaza (un standby viejo no puede reclamar).
LÍMITES (declarados, no ocultos): lo evita el propietario de las tablas o un superusuario (pueden desactivar triggers o fijar `session_replication_role = replica`): son accesos de ADMINISTRACIÓN,
no del rol de la aplicación; las secuencias avanzan sin autoridad (no es un cambio de datos); no verificado en RDS (event triggers y propietarios restringidos). La garantía entre nubes depende de
que ESTE vallado esté instalado y comprobado (`attest`) también en la base del primario: sin esa atestación no se acepta evidencia INFERIDA de vallado.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass

_IDENT = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")
SQLSTATE_FENCED = "NX001"


class PgFenceError(Exception):
    pass


def _q(ident: str) -> str:
    if not _IDENT.match(ident or ""):
        raise PgFenceError("identificador inválido")
    return '"' + ident + '"'


def install_sql(*, app_role: str, keeper_role: str, schema: str = "public", event_trigger: bool = True, fence_owner: str | None = None) -> str:
    """`event_trigger=False` para administradores que NO pueden crear event triggers (el guardián cubre las tablas nuevas con attach_all periódico y, mientras haya tablas sin cubrir, NO se concede autoridad)."""
    a, k, s = _q(app_role), _q(keeper_role), _q(schema)
    ev_sql = ("DROP EVENT TRIGGER IF EXISTS nexo_fence_ddl;\nCREATE EVENT TRIGGER nexo_fence_ddl ON ddl_command_end WHEN TAG IN ('CREATE TABLE', 'CREATE TABLE AS', 'SELECT INTO') EXECUTE FUNCTION nexo_fence.on_ddl();" if event_trigger else "-- sin event trigger (administrador sin ese privilegio): attach_all lo ejecuta el guardián")
    pre, post = ((f"SET ROLE {_q(fence_owner)};\n", "\nRESET ROLE;\n") if fence_owner else ("", ""))
    if fence_owner and event_trigger:
        raise PgFenceError("con fence_owner (rol sin privilegios de administrador) los event triggers no están disponibles: use event_trigger=False (el guardián engancha las tablas nuevas)")
    return pre + f"""
CREATE SCHEMA IF NOT EXISTS nexo_fence;
CREATE TABLE IF NOT EXISTS nexo_fence.writer_fence (id smallint PRIMARY KEY CHECK (id = 1), epoch bigint NOT NULL DEFAULT 0, holder text, valid_until timestamptz NOT NULL DEFAULT '-infinity');
INSERT INTO nexo_fence.writer_fence (id) VALUES (1) ON CONFLICT DO NOTHING;
CREATE TABLE IF NOT EXISTS nexo_fence.config (id smallint PRIMARY KEY CHECK (id = 1), app_role text NOT NULL, schema_name text NOT NULL, event_trigger_expected boolean NOT NULL, app_had_create boolean NOT NULL DEFAULT false);
INSERT INTO nexo_fence.config VALUES (1, {_lit(app_role)}, {_lit(schema)}, {'true' if event_trigger else 'false'}, coalesce(has_schema_privilege({_lit(app_role)}, {_lit(schema)}, 'CREATE'), false))
  ON CONFLICT (id) DO UPDATE SET app_role = EXCLUDED.app_role, schema_name = EXCLUDED.schema_name, event_trigger_expected = EXCLUDED.event_trigger_expected;   -- app_had_create se conserva de la PRIMERA instalación
CREATE TABLE IF NOT EXISTS nexo_fence.write_probe (id bigserial PRIMARY KEY, epoch bigint NOT NULL, payload text, at timestamptz NOT NULL DEFAULT clock_timestamp());
-- Registro de las transacciones que PASARON la comprobación (una fila por transacción): permite detectar a posteriori los commits que terminaron DESPUÉS de vencer la autoridad (pausa del servidor entre la
-- comprobación y el fin del commit). Requiere track_commit_timestamp=on para dar la hora de commit; sin él, late_commits() lo dice y la barrera de reconocimiento de la API sigue protegiendo al cliente.
CREATE TABLE IF NOT EXISTS nexo_fence.commit_log (x8 bigint PRIMARY KEY, epoch bigint NOT NULL, valid_until timestamptz NOT NULL, checked_at timestamptz NOT NULL DEFAULT clock_timestamp());
-- CERROJO del vallado fuerte: tras una promoción, esta base NO concede autoridad a nadie hasta un levantamiento MANUAL (failback humano). Persiste en la base: sobrevive a reinicios y a la vuelta de la API.
CREATE TABLE IF NOT EXISTS nexo_fence.latch (id smallint PRIMARY KEY CHECK (id = 1), latched boolean NOT NULL DEFAULT false, since timestamptz, reason text);
INSERT INTO nexo_fence.latch (id) VALUES (1) ON CONFLICT DO NOTHING;
-- Trinquete del sello de promoción (seal_log.py): mayor secuencia del registro de sello vista JAMÁS por este consumidor; solo sube.
CREATE TABLE IF NOT EXISTS nexo_fence.seal_ratchet (id smallint PRIMARY KEY CHECK (id = 1), seq bigint NOT NULL DEFAULT 0);
INSERT INTO nexo_fence.seal_ratchet (id) VALUES (1) ON CONFLICT DO NOTHING;
REVOKE ALL ON SCHEMA nexo_fence FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA nexo_fence FROM PUBLIC;
REVOKE CREATE ON SCHEMA {s} FROM {a};   -- la aplicación no crea objetos (migraciones las hace el propietario)
GRANT USAGE ON SCHEMA nexo_fence TO {a}, {k};
GRANT SELECT, INSERT ON nexo_fence.write_probe TO {a}, {k};
GRANT USAGE, SELECT ON SEQUENCE nexo_fence.write_probe_id_seq TO {a}, {k};

CREATE OR REPLACE FUNCTION nexo_fence.check_write() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
DECLARE f record; claimed bigint;
BEGIN
  SELECT epoch, valid_until INTO f FROM nexo_fence.writer_fence WHERE id = 1;
  BEGIN claimed := nullif(current_setting('nexo.writer_epoch', true), '')::bigint; EXCEPTION WHEN others THEN claimed := NULL; END;
  IF f.valid_until <= clock_timestamp() OR claimed IS DISTINCT FROM f.epoch THEN
    RAISE EXCEPTION 'NEXO_FENCE: escritura rechazada (sin autoridad vigente en la base: época declarada %, época de la base %)', claimed, f.epoch USING ERRCODE = '{SQLSTATE_FENCED}';
  END IF;
  INSERT INTO nexo_fence.commit_log (x8, epoch, valid_until) VALUES (pg_current_xact_id()::text::bigint, f.epoch, f.valid_until) ON CONFLICT DO NOTHING;
  RETURN NULL;
END $f$;

CREATE OR REPLACE FUNCTION nexo_fence.attach_all() RETURNS integer LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
DECLARE r record; n integer := 0;
BEGIN
  FOR r IN SELECT c.oid, c.relname FROM pg_class c WHERE c.relnamespace = {_lit(schema)}::regnamespace AND c.relkind IN ('r','p') LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgrelid = r.oid AND t.tgname = 'nexo_fence_commit') THEN
      EXECUTE format('CREATE CONSTRAINT TRIGGER nexo_fence_commit AFTER INSERT OR UPDATE OR DELETE ON %I.%I DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nexo_fence.check_write()', {_lit(schema)}, r.relname);
      n := n + 1;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgrelid = r.oid AND t.tgname = 'nexo_fence_truncate') THEN
      EXECUTE format('CREATE TRIGGER nexo_fence_truncate BEFORE TRUNCATE ON %I.%I FOR EACH STATEMENT EXECUTE FUNCTION nexo_fence.check_write()', {_lit(schema)}, r.relname);
    END IF;
  END LOOP;
  RETURN n;
END $f$;

CREATE OR REPLACE FUNCTION nexo_fence.on_ddl() RETURNS event_trigger LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
BEGIN PERFORM nexo_fence.attach_all(); END $f$;
{ev_sql}

CREATE OR REPLACE FUNCTION nexo_fence.grant_authority(p_epoch bigint, p_holder text, p_seconds double precision) RETURNS timestamptz LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
DECLARE cur bigint; v timestamptz;
BEGIN
  IF p_seconds IS NOT NULL AND p_seconds > 0 AND NOT coalesce((nexo_fence.attest((SELECT app_role FROM nexo_fence.config WHERE id = 1))->>'ok')::boolean, false) THEN
    RAISE EXCEPTION 'NEXO_FENCE: cobertura del vallado incompleta o con vías de escape: no se concede autoridad' USING ERRCODE = '{SQLSTATE_FENCED}';   -- cada RENOVACIÓN la comprueba
  END IF;
  IF p_seconds IS NOT NULL AND p_seconds > 0 AND (SELECT latched FROM nexo_fence.latch WHERE id = 1) THEN
    RAISE EXCEPTION 'NEXO_FENCE: base CERROJADA (vallado fuerte tras una promoción): no se concede autoridad; levantar el cerrojo es una decisión humana (failback)' USING ERRCODE = '{SQLSTATE_FENCED}';
  END IF;
  SELECT epoch INTO cur FROM nexo_fence.writer_fence WHERE id = 1 FOR UPDATE;
  IF p_epoch < cur THEN RAISE EXCEPTION 'NEXO_FENCE: época % menor que la de la base %: se rechaza', p_epoch, cur USING ERRCODE = '{SQLSTATE_FENCED}'; END IF;
  IF p_seconds IS NULL OR p_seconds <= 0 THEN v := '-infinity'; ELSE v := clock_timestamp() + make_interval(secs => p_seconds); END IF;
  UPDATE nexo_fence.writer_fence SET epoch = p_epoch, holder = p_holder, valid_until = v WHERE id = 1;
  RETURN v;
END $f$;

CREATE OR REPLACE FUNCTION nexo_fence.revoke_authority(p_epoch bigint) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
  UPDATE nexo_fence.writer_fence SET valid_until = '-infinity' WHERE id = 1 AND epoch <= p_epoch;
$f$;

CREATE OR REPLACE FUNCTION nexo_fence.reset_after_restore() RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
  UPDATE nexo_fence.writer_fence SET valid_until = '-infinity', holder = NULL WHERE id = 1;     -- tras restaurar un volcado ajeno: SIN autoridad; la época se conserva (nunca baja)
$f$;

CREATE OR REPLACE FUNCTION nexo_fence.fence_status() RETURNS TABLE (epoch bigint, holder text, remaining_s double precision, db_now timestamptz) LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
  SELECT epoch, holder, GREATEST(0, EXTRACT(EPOCH FROM (valid_until - clock_timestamp())))::double precision, clock_timestamp() FROM nexo_fence.writer_fence WHERE id = 1;
$f$;

CREATE OR REPLACE FUNCTION nexo_fence.attest(p_app_role text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
DECLARE total int; covered int; trunc int; uncovered jsonb; ev boolean; ev_expected boolean; can_fence boolean; owns boolean; paths jsonb := '[]'::jsonb; mpt int; prepared int; srr text; is_super boolean; adm boolean; admins jsonb; k text := session_user;
BEGIN
  SELECT count(*) INTO total FROM pg_class c WHERE c.relnamespace = {_lit(schema)}::regnamespace AND c.relkind IN ('r','p');
  SELECT count(*) INTO covered FROM pg_class c WHERE c.relnamespace = {_lit(schema)}::regnamespace AND c.relkind IN ('r','p') AND EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgrelid = c.oid AND t.tgname = 'nexo_fence_commit' AND t.tgenabled = 'O' AND t.tgdeferrable AND t.tginitdeferred);
  SELECT count(*) INTO trunc FROM pg_class c WHERE c.relnamespace = {_lit(schema)}::regnamespace AND c.relkind IN ('r','p') AND EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgrelid = c.oid AND t.tgname = 'nexo_fence_truncate' AND t.tgenabled = 'O');
  SELECT coalesce(jsonb_agg(c.relname ORDER BY c.relname), '[]'::jsonb) INTO uncovered FROM pg_class c WHERE c.relnamespace = {_lit(schema)}::regnamespace AND c.relkind IN ('r','p')
     AND NOT EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgrelid = c.oid AND t.tgname = 'nexo_fence_commit' AND t.tgenabled = 'O');
  SELECT EXISTS (SELECT 1 FROM pg_event_trigger e WHERE e.evtname = 'nexo_fence_ddl' AND e.evtenabled = 'O') INTO ev;
  SELECT coalesce((SELECT event_trigger_expected FROM nexo_fence.config WHERE id = 1), true) INTO ev_expected;
  can_fence := has_function_privilege(p_app_role, 'nexo_fence.grant_authority(bigint,text,double precision)', 'EXECUTE') OR has_function_privilege(p_app_role, 'nexo_fence.revoke_authority(bigint)', 'EXECUTE')
               OR has_function_privilege(p_app_role, 'nexo_fence.attach_all()', 'EXECUTE') OR has_table_privilege(p_app_role, 'nexo_fence.writer_fence', 'INSERT, UPDATE, DELETE, TRUNCATE');
  SELECT coalesce(bool_or(pg_has_role(p_app_role, c.relowner, 'MEMBER')), false) INTO owns FROM pg_class c WHERE c.relnamespace = {_lit(schema)}::regnamespace AND c.relkind IN ('r','p');
  SELECT coalesce((SELECT rolsuper FROM pg_roles WHERE rolname = p_app_role), false) INTO is_super;
  SELECT coalesce((SELECT pg_has_role(p_app_role, 'rds_superuser', 'MEMBER') FROM pg_roles WHERE rolname = 'rds_superuser'), false) INTO adm;
  mpt := current_setting('max_prepared_transactions')::int; SELECT count(*) INTO prepared FROM pg_prepared_xacts;
  IF mpt > 0 THEN paths := paths || to_jsonb('max_prepared_transactions>0: un COMMIT PREPARED posterior evita el trigger (la comprobación ocurre al PREPARE)'::text); END IF;
  IF prepared > 0 THEN paths := paths || to_jsonb('hay transacciones preparadas pendientes'::text); END IF;
  IF is_super OR adm THEN paths := paths || to_jsonb('el rol de la aplicación es superusuario o rds_superuser'::text); END IF;
  IF owns THEN paths := paths || to_jsonb('el rol de la aplicación posee tablas (puede desactivar triggers)'::text); END IF;
  SELECT coalesce(jsonb_agg(r.rolname ORDER BY r.rolname), '[]'::jsonb) INTO admins FROM pg_roles r WHERE r.rolname NOT LIKE 'pg\\_%' AND (r.rolsuper OR (EXISTS (SELECT 1 FROM pg_roles x WHERE x.rolname = 'rds_superuser') AND pg_has_role(r.rolname, 'rds_superuser', 'MEMBER')));
  -- el GUARDIÁN (quien llama) tampoco puede poder saltarse los triggers: ni superusuario/rds_superuser, ni propietario de tablas, ni fijar session_replication_role
  IF k <> current_user AND ((SELECT rolsuper FROM pg_roles WHERE rolname = k) OR (EXISTS (SELECT 1 FROM pg_roles x WHERE x.rolname = 'rds_superuser') AND pg_has_role(k, 'rds_superuser', 'MEMBER'))
       OR coalesce((SELECT bool_or(pg_has_role(k, c.relowner, 'MEMBER')) FROM pg_class c WHERE c.relnamespace = {_lit(schema)}::regnamespace AND c.relkind IN ('r','p')), false) OR has_parameter_privilege(k, 'session_replication_role', 'SET')) THEN
    paths := paths || to_jsonb('el rol guardián puede saltarse los triggers (administrador, propietario de tablas o puede fijar session_replication_role)'::text); END IF;
  IF has_parameter_privilege(p_app_role, 'session_replication_role', 'SET') THEN paths := paths || to_jsonb('el rol de la aplicación puede fijar session_replication_role'::text); END IF;
  IF EXISTS (SELECT 1 FROM pg_db_role_setting s WHERE EXISTS (SELECT 1 FROM unnest(s.setconfig) x WHERE x LIKE 'session_replication_role=%' AND x NOT LIKE 'session_replication_role=origin')) THEN
    paths := paths || to_jsonb('session_replication_role distinto de origin fijado por base o rol'::text); END IF;
  SELECT current_setting('session_replication_role') INTO srr; IF srr <> 'origin' THEN paths := paths || to_jsonb('session_replication_role de esta sesión distinto de origin'::text); END IF;
  IF has_schema_privilege(p_app_role, {_lit(schema)}, 'CREATE') THEN paths := paths || to_jsonb('el rol de la aplicación puede crear objetos en el esquema de datos'::text); END IF;
  IF ev_expected AND NOT ev THEN paths := paths || to_jsonb('falta el event trigger que cubre las tablas nuevas (y se esperaba)'::text); END IF;
  RETURN jsonb_build_object('tables_total', total, 'tables_covered', covered, 'truncate_covered', trunc, 'uncovered', uncovered, 'event_trigger', ev, 'event_trigger_expected', ev_expected,
     'admin_roles', admins, 'app_role_can_change_fence', can_fence, 'app_role_owns_tables', owns, 'max_prepared_transactions', mpt, 'bypass_paths', paths, 'db_now', to_jsonb(clock_timestamp()),
     'ok', (total = covered AND total = trunc AND NOT can_fence AND NOT owns AND jsonb_array_length(paths) = 0));
END $f$;

CREATE OR REPLACE FUNCTION nexo_fence.late_commits() RETURNS TABLE (x8 bigint, epoch bigint, valid_until timestamptz, committed_at timestamptz, late_by_s double precision) LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
BEGIN
  IF current_setting('track_commit_timestamp') <> 'on' THEN RAISE EXCEPTION 'track_commit_timestamp=off: no se puede conocer la hora de commit (activarlo en el grupo de parámetros)'; END IF;
  RETURN QUERY SELECT q.x8, q.epoch, q.valid_until, q.ts, EXTRACT(EPOCH FROM (q.ts - q.valid_until))::double precision
    FROM (SELECT l.x8, l.epoch, l.valid_until, pg_xact_commit_timestamp((l.x8::text)::xid8::xid) AS ts FROM nexo_fence.commit_log l) q WHERE q.ts > q.valid_until ORDER BY q.ts;
END $f$;

CREATE OR REPLACE FUNCTION nexo_fence.prune_commit_log(p_keep interval DEFAULT interval '1 day') RETURNS bigint LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
  WITH d AS (DELETE FROM nexo_fence.commit_log WHERE checked_at < clock_timestamp() - p_keep RETURNING 1) SELECT count(*) FROM d;
$f$;

-- VALLADO FUERTE, en DOS llamadas (cada una es su propia transacción: la revocación debe estar CONFIRMADA antes de empezar a terminar sesiones, o una sesión nueva podría pasar la comprobación durante el bucle).
CREATE OR REPLACE FUNCTION nexo_fence.fence_revoke(p_reason text) RETURNS void LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
  UPDATE nexo_fence.latch SET latched = true, since = coalesce(since, clock_timestamp()), reason = left(p_reason, 120) WHERE id = 1;
  UPDATE nexo_fence.writer_fence SET valid_until = '-infinity', holder = NULL WHERE id = 1;
$f$;

CREATE OR REPLACE FUNCTION nexo_fence.fence_drain(p_wait double precision) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
DECLARE app text; t0 timestamptz := clock_timestamp(); n int; prep int; lat boolean; vu timestamptz;
BEGIN
  SELECT app_role INTO app FROM nexo_fence.config WHERE id = 1;
  LOOP
    PERFORM pg_stat_clear_snapshot();      -- pg_stat_activity se «congela» dentro de la transacción: sin esto el bucle vería siempre las mismas sesiones aunque ya hayan muerto
    PERFORM pg_terminate_backend(pid) FROM pg_stat_activity WHERE usename = app AND datname = current_database() AND pid <> pg_backend_pid();      -- SOLO esta base y SOLO el rol de la aplicación configurado
    SELECT count(*) INTO n FROM pg_stat_activity WHERE usename = app AND datname = current_database() AND pid <> pg_backend_pid();
    EXIT WHEN n = 0 OR clock_timestamp() - t0 > make_interval(secs => p_wait);
    PERFORM pg_sleep(0.05);
  END LOOP;
  SELECT count(*) INTO prep FROM pg_prepared_xacts;
  SELECT latched INTO lat FROM nexo_fence.latch WHERE id = 1; SELECT valid_until INTO vu FROM nexo_fence.writer_fence WHERE id = 1;
  RETURN jsonb_build_object('latched', lat, 'authority_revoked', vu <= clock_timestamp(), 'app_sessions_left', n, 'prepared_xacts', prep, 'db_now', to_jsonb(clock_timestamp()), 'waited_s', EXTRACT(EPOCH FROM (clock_timestamp() - t0)));
END $f$;

CREATE OR REPLACE FUNCTION nexo_fence.release_latch(p_confirm text) RETURNS void LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
BEGIN
  IF p_confirm IS DISTINCT FROM 'LIBERAR CERROJO DEL VALLADO' THEN RAISE EXCEPTION 'NEXO_FENCE: falta la frase de confirmación del failback manual'; END IF;
  UPDATE nexo_fence.latch SET latched = false, since = NULL, reason = NULL WHERE id = 1;
END $f$;

REVOKE ALL ON FUNCTION nexo_fence.fence_revoke(text), nexo_fence.fence_drain(double precision), nexo_fence.release_latch(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION nexo_fence.fence_revoke(text), nexo_fence.fence_drain(double precision), nexo_fence.release_latch(text) TO {k};
CREATE OR REPLACE FUNCTION nexo_fence.ratchet_seal(p_seq bigint) RETURNS bigint LANGUAGE sql SECURITY DEFINER SET search_path = pg_catalog, pg_temp AS $f$
  UPDATE nexo_fence.seal_ratchet SET seq = greatest(seq, p_seq) WHERE id = 1 RETURNING seq;
$f$;
REVOKE ALL ON FUNCTION nexo_fence.ratchet_seal(bigint) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION nexo_fence.ratchet_seal(bigint) TO {k};
REVOKE ALL ON FUNCTION nexo_fence.late_commits(), nexo_fence.prune_commit_log(interval) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION nexo_fence.late_commits(), nexo_fence.prune_commit_log(interval) TO {k};
REVOKE ALL ON FUNCTION nexo_fence.grant_authority(bigint,text,double precision), nexo_fence.revoke_authority(bigint), nexo_fence.reset_after_restore(), nexo_fence.attest(text), nexo_fence.fence_status(), nexo_fence.attach_all() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION nexo_fence.grant_authority(bigint,text,double precision), nexo_fence.revoke_authority(bigint), nexo_fence.reset_after_restore(), nexo_fence.attest(text), nexo_fence.fence_status(), nexo_fence.attach_all() TO {k};
GRANT EXECUTE ON FUNCTION nexo_fence.fence_status() TO {a};
SELECT nexo_fence.attach_all();
DO $d$ BEGIN   -- la tabla de sondeo del propio vallado también exige autoridad (una escritura sintética REAL debe pasar por la misma regla)
  IF NOT EXISTS (SELECT 1 FROM pg_trigger t WHERE t.tgrelid = 'nexo_fence.write_probe'::regclass AND t.tgname = 'nexo_fence_commit') THEN
    CREATE CONSTRAINT TRIGGER nexo_fence_commit AFTER INSERT OR UPDATE OR DELETE ON nexo_fence.write_probe DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nexo_fence.check_write();
    CREATE TRIGGER nexo_fence_truncate BEFORE TRUNCATE ON nexo_fence.write_probe FOR EACH STATEMENT EXECUTE FUNCTION nexo_fence.check_write();
  END IF;
END $d$;
""" + post


def _lit(v: str) -> str:
    if not _IDENT.match(v or ""):
        raise PgFenceError("identificador inválido")
    return "'" + v + "'"


@dataclass
class PgFence:
    """Cliente del vallado en la base. `execute(sql, params=None) -> list[tuple]` con las credenciales del GUARDIÁN (no las de la aplicación). Cualquier fallo se propaga: quien llama NO debe asumir autoridad."""
    execute: object
    app_role: str = "nexoeventos_app"

    def grant(self, epoch: int, holder: str, seconds: float) -> dict:
        """Concede/renueva autoridad `seconds` (reloj de la BASE) para la época. La base RECHAZA la renovación si su cobertura está incompleta o tiene vías de escape. Devuelve {valid_until, db_now}
        (db_now estimado = valid_until − seconds) para que el guardián detecte saltos del reloj de la base."""
        rows = self.execute("SELECT nexo_fence.grant_authority(%(e)s, %(h)s, %(s)s)", {"e": int(epoch), "h": str(holder)[:60], "s": float(seconds)})
        v = rows[0][0] if rows else None
        db_now = None
        try:
            from datetime import timedelta
            db_now = v - timedelta(seconds=float(seconds)) if hasattr(v, "year") else None
        except Exception:  # noqa: BLE001
            db_now = None
        return {"valid_until": v, "db_now": db_now, "seconds": float(seconds)}

    def attach_all(self) -> int:
        """Engancha las tablas nuevas (sin event trigger): lo ejecuta el guardián; la función es SECURITY DEFINER del instalador, que debe poseer las tablas."""
        rows = self.execute("SELECT nexo_fence.attach_all()")
        return int(rows[0][0]) if rows else 0

    def revoke(self, epoch: int) -> None:
        self.execute("SELECT nexo_fence.revoke_authority(%(e)s)", {"e": int(epoch)})

    def reset_after_restore(self) -> None:
        self.execute("SELECT nexo_fence.reset_after_restore()")

    def hard_fence(self, reason: str = "promocion", wait_s: float = 5.0) -> dict:
        """VALLADO FUERTE (la base del primario ALCANZABLE): 1) cerrojo + revocación CONFIRMADA; 2) terminar todas las sesiones de la aplicación y esperar a que desaparezcan. Devuelve la PRUEBA: solo es válida si
        `proof_ok(...)`: cerrojo puesto, autoridad revocada, 0 sesiones de la aplicación y 0 transacciones preparadas. Una sesión congelada que no muere deja `app_sessions_left > 0` → NO hay prueba."""
        self.execute("SELECT nexo_fence.fence_revoke(%(r)s)", {"r": reason})
        rows = self.execute("SELECT nexo_fence.fence_drain(%(w)s)", {"w": float(wait_s)})
        import json as _j
        p = rows[0][0] if rows else None
        return _j.loads(p) if isinstance(p, str) else dict(p or {})

    def release_latch(self, confirm: str) -> None:
        self.execute("SELECT nexo_fence.release_latch(%(c)s)", {"c": confirm})

    @staticmethod
    def proof_ok(p: dict | None) -> bool:
        return bool(p) and p.get("latched") is True and p.get("authority_revoked") is True and p.get("app_sessions_left") == 0 and p.get("prepared_xacts") == 0

    def late_commits(self) -> list[dict]:
        """Transacciones aceptadas cuyo COMMIT terminó DESPUÉS de vencer la autoridad con la que pasaron la comprobación (huérfanas: no se reconocieron al cliente; se descartan en el failback)."""
        rows = self.execute("SELECT x8, epoch, valid_until, committed_at, late_by_s FROM nexo_fence.late_commits()")
        return [dict(x8=r[0], epoch=r[1], valid_until=r[2], committed_at=r[3], late_by_s=float(r[4])) for r in rows]

    def prune_commit_log(self, keep_hours: float = 24.0) -> int:
        rows = self.execute("SELECT nexo_fence.prune_commit_log(make_interval(hours => %(h)s::int))", {"h": int(keep_hours)})
        return int(rows[0][0]) if rows else 0

    def status(self) -> dict | None:
        rows = self.execute("SELECT epoch, holder, remaining_s, db_now FROM nexo_fence.fence_status()")
        if not rows:
            return None
        e, h, rem, now = rows[0]
        return {"epoch": int(e), "holder": h, "remaining_s": float(rem), "valid": float(rem) > 0, "db_now": now}

    def attest(self) -> dict:
        rows = self.execute("SELECT nexo_fence.attest(%(r)s)", {"r": self.app_role})
        v = rows[0][0] if rows else None
        return v if isinstance(v, dict) else json.loads(v)


class FenceAttestation:
    """Atestación PUBLICADA por el guardián del primario en un almacén condicional (el mismo tipo que el lease) para que el sitio de recuperación la lea aunque el primario esté aislado.
    Es una AFIRMACIÓN con hora: solo vale si es reciente (`max_age_s`, 30 s por defecto: unos 3 ciclos del guardián; una atestación caducada NUNCA es prueba suficiente), `ok` es verdadero y la época coincide o es posterior a la última conocida. Falla cerrado ante cualquier duda."""
    def __init__(self, store, wall=time.time):
        self.store, self.wall = store, wall

    def publish(self, att: dict, epoch: int | None) -> None:
        data = json.dumps({"v": 1, "ok": bool(att.get("ok")), "epoch": epoch, "at": self.wall(), "tables_total": att.get("tables_total"), "tables_covered": att.get("tables_covered")}).encode()
        rv = None
        try:
            rv = self.store.read()
        except Exception:  # noqa: BLE001
            rv = None
        if rv is None:
            self.store.create(data)
        else:
            self.store.replace(rv.etag, data)

    def read(self, max_age_s: float = 30.0, min_epoch: int | None = None) -> dict:
        """{"ok": bool, "age_s": float|None, "reason": str}; ok=False ante ausencia, ilegibilidad, vejez, atestación negativa o época vieja."""
        try:
            rv = self.store.read()
            if rv is None:
                return {"ok": False, "age_s": None, "reason": "sin atestación publicada"}
            d = json.loads(rv.data)
            age = self.wall() - float(d["at"])
        except Exception:  # noqa: BLE001
            return {"ok": False, "age_s": None, "reason": "atestación ilegible o almacén inaccesible"}
        if age < -60 or age > max_age_s:
            return {"ok": False, "age_s": round(age, 1), "reason": "atestación vencida"}
        if d.get("ok") is not True:
            return {"ok": False, "age_s": round(age, 1), "reason": "la atestación indica cobertura incompleta"}
        if min_epoch is not None and (d.get("epoch") is None or int(d["epoch"]) < int(min_epoch)):
            return {"ok": False, "age_s": round(age, 1), "reason": "atestación de una época anterior"}
        return {"ok": True, "age_s": round(age, 1), "reason": "vigente"}


def uninstall_sql(*, schema: str = "public", keeper_role: str | None = None, drop_role: bool = False, fence_owner: str | None = None, drop_triggers: bool = True) -> str:
    """Reversión COMPLETA, verificable y SEGURA ante dependencias: quita triggers de todas las tablas, el event trigger, las funciones y las tablas de nexo_fence (RESTRICT: si un objeto AJENO depende
    de ellas —p. ej. una vista del cliente— falla sin tocarlo y todo se deshace) y devuelve al rol de la aplicación el CREATE que tuviera antes de instalar. Idempotente.
    Con drop_role también elimina el rol guardián (solo si ya no tiene dependencias)."""
    s = _lit(schema)
    nspnames = f"{s}, 'nexo_fence'" if drop_triggers else "'nexo_fence'"          # sin drop_triggers: los de las tablas de NEGOCIO los quita su propietario (uninstall_triggers_sql); si quedara alguno, DROP FUNCTION ... RESTRICT falla y todo se deshace
    trig = """  FOR r IN SELECT c.oid, c.relname, n.nspname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE c.relkind IN ('r','p') AND n.nspname IN (%s) LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS nexo_fence_commit ON %%I.%%I', r.nspname, r.relname);
    EXECUTE format('DROP TRIGGER IF EXISTS nexo_fence_truncate ON %%I.%%I', r.nspname, r.relname);
  END LOOP;
""" % nspnames
    out = (f"SET ROLE {_q(fence_owner)};\n" if fence_owner else "") + f"""
DO $d$ DECLARE r record; had boolean := false; app text; BEGIN
  IF to_regclass('nexo_fence.config') IS NOT NULL THEN
    SELECT app_role, app_had_create INTO app, had FROM nexo_fence.config WHERE id = 1;
  END IF;
  EXECUTE 'DROP EVENT TRIGGER IF EXISTS nexo_fence_ddl';
{trig}  IF to_regnamespace('nexo_fence') IS NOT NULL THEN
    FOR r IN SELECT p.oid::regprocedure AS sig FROM pg_proc p WHERE p.pronamespace = 'nexo_fence'::regnamespace LOOP EXECUTE format('DROP FUNCTION %s RESTRICT', r.sig); END LOOP;
    FOR r IN SELECT c.relname FROM pg_class c WHERE c.relnamespace = 'nexo_fence'::regnamespace AND c.relkind = 'r' LOOP EXECUTE format('DROP TABLE nexo_fence.%I RESTRICT', r.relname); END LOOP;
    EXECUTE 'DROP SCHEMA nexo_fence RESTRICT';
  END IF;
  IF had AND app IS NOT NULL THEN EXECUTE format('GRANT CREATE ON SCHEMA %I TO %I', {s}, app); END IF;
END $d$;
"""
    if fence_owner:
        out += "RESET ROLE;\n"
    if drop_role and keeper_role:
        out += f"REVOKE ALL ON SCHEMA {_q(schema)} FROM {_q(keeper_role)};\nDROP ROLE IF EXISTS {_q(keeper_role)};\n"
    return out


# --- Instalación sobre tablas de NEGOCIO sin cambiar sus propietarios: tres roles y tres fases -------------------------------------------------------------------------------------------------
#  propietario de las tablas (p. ej. nexoeventos_owner)  → solo concede/retira TRIGGER y dos permisos menores (owner_grants_sql / owner_revoke_sql) y quita los triggers al revertir (uninstall_triggers_sql)
#  fence_owner (NOLOGIN, dueño del esquema nexo_fence y de sus funciones)  → instala/desinstala el vallado (install_sql/uninstall_sql con fence_owner); NO posee las tablas de negocio
#  guardián (LOGIN, solo EXECUTE de las funciones)  y  aplicación (solo DML)  → sin privilegios sobre triggers, parámetros ni propiedad
def db_grants_sql(*, fence_owner: str, keeper_role: str, database: str) -> str:
    """Permisos de BASE DE DATOS (CREATE del esquema nexo_fence, CONNECT del guardián): los concede quien sea PROPIETARIO de la base (en la RDS real, el administrador si la creó él; si no, el propietario de las tablas)."""
    return f"GRANT CREATE, TEMPORARY ON DATABASE {_q(database)} TO {_q(fence_owner)};\nGRANT CONNECT ON DATABASE {_q(database)} TO {_q(keeper_role)};\n"


def db_revoke_sql(*, fence_owner: str, keeper_role: str, database: str) -> str:
    return f"REVOKE CREATE, TEMPORARY ON DATABASE {_q(database)} FROM {_q(fence_owner)};\nREVOKE CONNECT ON DATABASE {_q(database)} FROM {_q(keeper_role)};\n"


def owner_grants_sql(*, owner_role: str, fence_owner: str, app_role: str, database: str, keeper_role: str, schema: str = "public", include_db_grants: bool = True) -> str:
    o, f, a, s = _q(owner_role), _q(fence_owner), _q(app_role), _q(schema)
    return f"""SET ROLE {o};
GRANT USAGE ON SCHEMA {s} TO {f};
GRANT TRIGGER ON ALL TABLES IN SCHEMA {s} TO {f};
ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA {s} GRANT TRIGGER ON TABLES TO {f};
{db_grants_sql(fence_owner=fence_owner, keeper_role=keeper_role, database=database) if include_db_grants else ""}REVOKE CREATE ON SCHEMA {s} FROM {a};
RESET ROLE;
"""


def uninstall_triggers_sql(*, owner_role: str, schema: str = "public") -> str:
    """Fase de reversión del PROPIETARIO: quitar los triggers del vallado de las tablas de negocio (DROP TRIGGER exige ser el propietario de la tabla)."""
    return f"""SET ROLE {_q(owner_role)};
DO $d$ DECLARE r record; BEGIN
  FOR r IN SELECT c.relname FROM pg_class c WHERE c.relnamespace = {_lit(schema)}::regnamespace AND c.relkind IN ('r','p') LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS nexo_fence_commit ON %I.%I', {_lit(schema)}, r.relname);
    EXECUTE format('DROP TRIGGER IF EXISTS nexo_fence_truncate ON %I.%I', {_lit(schema)}, r.relname);
  END LOOP;
END $d$;
RESET ROLE;
"""


def owner_revoke_sql(*, owner_role: str, fence_owner: str, app_role: str, database: str, keeper_role: str, schema: str = "public", restore_app_create: bool = False, include_db_grants: bool = True) -> str:
    o, f, a, s = _q(owner_role), _q(fence_owner), _q(app_role), _q(schema)
    return f"""SET ROLE {o};
ALTER DEFAULT PRIVILEGES FOR ROLE {o} IN SCHEMA {s} REVOKE TRIGGER ON TABLES FROM {f};
REVOKE TRIGGER ON ALL TABLES IN SCHEMA {s} FROM {f};
REVOKE USAGE ON SCHEMA {s} FROM {f};
{db_revoke_sql(fence_owner=fence_owner, keeper_role=keeper_role, database=database) if include_db_grants else ""}{f"GRANT CREATE ON SCHEMA {s} TO {a};" if restore_app_create else ""}
RESET ROLE;
"""


SNAPSHOT_SQL = """
SELECT md5(string_agg(x, E'\n' ORDER BY x)) , count(*) FROM (
  SELECT 'rel:' || c.relname || ':' || c.relkind::text || ':' || pg_get_userbyid(c.relowner) || ':' || coalesce(c.relacl, acldefault(CASE c.relkind WHEN 'S' THEN 's'::"char" ELSE 'r'::"char" END, c.relowner))::text AS x FROM pg_class c WHERE c.relnamespace = to_regnamespace(%(s)s) AND c.relkind IN ('r','p','S','v')
  UNION ALL SELECT 'trg:' || c.relname || ':' || t.tgname || ':' || t.tgenabled::text FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid WHERE c.relnamespace = to_regnamespace(%(s)s) AND NOT t.tgisinternal
  UNION ALL SELECT 'ns:' || n.nspname || ':' || coalesce(n.nspacl, acldefault('n', n.nspowner))::text FROM pg_namespace n WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname <> 'information_schema'
  UNION ALL SELECT 'ev:' || e.evtname FROM pg_event_trigger e
  UNION ALL SELECT 'fn:' || n.nspname || '.' || p.proname FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname NOT LIKE 'pg_%%' AND n.nspname <> 'information_schema'
  UNION ALL SELECT 'role:' || rolname FROM pg_roles WHERE rolname = ANY(%(roles)s)
  UNION ALL SELECT 'dbset:' || array_to_string(setconfig, ',') FROM pg_db_role_setting
) q
"""


def catalog_snapshot(execute, *, schema: str = "public", roles: tuple = ()) -> dict:
    """Huella del estado del catálogo que el vallado toca (relaciones y sus ACL, triggers, esquemas y sus ACL, event triggers, funciones, roles indicados, ajustes por base/rol). Antes de instalar y después de
    revertir debe ser IDÉNTICA: es la prueba de que la reversión devuelve la base a su estado previo (no basta con un snapshot del RDS)."""
    rows = execute(SNAPSHOT_SQL, {"s": schema, "roles": list(roles)})
    return {"huella": rows[0][0], "elementos": int(rows[0][1])}


PRECHECK_SQL = """
BEGIN;
CREATE FUNCTION pg_temp.nx_precheck(p_schema text, p_app text) RETURNS jsonb LANGUAGE plpgsql AS $f$
DECLARE r jsonb := '{}'::jsonb; ok boolean; n int; stuck jsonb;
BEGIN
  r := r || jsonb_build_object('server_version', current_setting('server_version'), 'current_user', current_user,
        'is_superuser', (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),
        'member_rds_superuser', coalesce((SELECT pg_has_role(current_user, 'rds_superuser', 'MEMBER') FROM pg_roles WHERE rolname = 'rds_superuser'), false),
        'max_prepared_transactions', current_setting('max_prepared_transactions')::int, 'db_now', to_jsonb(clock_timestamp()),
        'rds_superuser_can_signal', coalesce((SELECT pg_has_role('rds_superuser', 'pg_signal_backend', 'MEMBER') FROM pg_roles WHERE rolname = 'rds_superuser'), false),
        'can_signal_backends', coalesce((SELECT pg_has_role(current_user, 'pg_signal_backend', 'MEMBER') OR rolsuper FROM pg_roles WHERE rolname = current_user), false),
        'track_commit_timestamp', current_setting('track_commit_timestamp'), 'fence_installed', to_regclass('nexo_fence.writer_fence') IS NOT NULL);
  -- ¿puede este administrador crear el esquema, funciones SECURITY DEFINER, triggers de restricción diferidos y (opcional) event triggers? Cada intento se deshace.
  ok := false; BEGIN CREATE SCHEMA nx_probe; CREATE TABLE nx_probe.t (i int); CREATE FUNCTION nx_probe.f() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER AS 'BEGIN RETURN NULL; END';
        CREATE CONSTRAINT TRIGGER nx_probe_trg AFTER INSERT ON nx_probe.t DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION nx_probe.f(); ok := true;
        EXCEPTION WHEN others THEN ok := false; END;
  r := r || jsonb_build_object('can_create_secdef_and_constraint_triggers', ok);
  BEGIN DROP SCHEMA IF EXISTS nx_probe CASCADE; EXCEPTION WHEN others THEN NULL; END;
  ok := false; BEGIN CREATE FUNCTION pg_temp.nx_ev() RETURNS event_trigger LANGUAGE plpgsql AS 'BEGIN NULL; END'; CREATE EVENT TRIGGER nx_probe_ev ON ddl_command_end EXECUTE FUNCTION pg_temp.nx_ev(); ok := true; DROP EVENT TRIGGER nx_probe_ev;
        EXCEPTION WHEN others THEN ok := false; END;
  r := r || jsonb_build_object('can_create_event_trigger', ok);
  ok := false; BEGIN SET LOCAL session_replication_role = replica; ok := true; RESET session_replication_role; EXCEPTION WHEN others THEN ok := false; END;
  r := r || jsonb_build_object('admin_can_set_session_replication_role', ok);
  SELECT coalesce(jsonb_agg(c.relname ORDER BY c.relname), '[]'::jsonb) INTO stuck FROM pg_class c WHERE c.relnamespace = to_regnamespace(p_schema) AND c.relkind IN ('r','p') AND NOT (pg_has_role(current_user, c.relowner, 'USAGE') OR has_table_privilege(current_user, c.oid, 'TRIGGER'));
  r := r || jsonb_build_object('tables_not_owned_or_member', stuck,
        'app_role_exists', EXISTS (SELECT 1 FROM pg_roles WHERE rolname = p_app),
        'app_role_is_superuser', coalesce((SELECT rolsuper FROM pg_roles WHERE rolname = p_app), false),
        'app_role_can_set_srr', coalesce(has_parameter_privilege(p_app, 'session_replication_role', 'SET'), false),
        'app_role_owns_tables', coalesce((SELECT bool_or(pg_has_role(p_app, c.relowner, 'MEMBER')) FROM pg_class c WHERE c.relnamespace = to_regnamespace(p_schema) AND c.relkind IN ('r','p')), false),
        'tables', (SELECT count(*) FROM pg_class c WHERE c.relnamespace = to_regnamespace(p_schema) AND c.relkind IN ('r','p')));
  RETURN r;
END $f$;
"""


READONLY_SQL = """
SELECT jsonb_build_object(
  'read_only', true, 'server_version', current_setting('server_version'), 'current_user', current_user, 'db_now', to_jsonb(clock_timestamp()),
  'is_superuser', (SELECT rolsuper FROM pg_roles WHERE rolname = current_user),
  'member_rds_superuser', coalesce((SELECT pg_has_role(current_user, 'rds_superuser', 'MEMBER') FROM pg_roles WHERE rolname = 'rds_superuser'), false),
  'rds_superuser_can_signal', coalesce((SELECT pg_has_role('rds_superuser', 'pg_signal_backend', 'MEMBER') FROM pg_roles WHERE rolname = 'rds_superuser'), false),
  'can_signal_backends', coalesce((SELECT pg_has_role(current_user, 'pg_signal_backend', 'MEMBER') OR rolsuper FROM pg_roles WHERE rolname = current_user), false),
  'can_create_in_database', has_database_privilege(current_user, current_database(), 'CREATE'),
  'can_create_in_schema', has_schema_privilege(current_user, %(s)s, 'CREATE'),
  'can_create_role', (SELECT rolcreaterole FROM pg_roles WHERE rolname = current_user),
  'admin_can_set_session_replication_role', coalesce(has_parameter_privilege(current_user, 'session_replication_role', 'SET'), false),
  'max_prepared_transactions', current_setting('max_prepared_transactions')::int, 'track_commit_timestamp', current_setting('track_commit_timestamp'),
  'synchronous_commit', current_setting('synchronous_commit'), 'prepared_xacts', (SELECT count(*) FROM pg_prepared_xacts),
  'fence_installed', to_regclass('nexo_fence.writer_fence') IS NOT NULL,
  'tables', (SELECT count(*) FROM pg_class c WHERE c.relnamespace = to_regnamespace(%(s)s) AND c.relkind IN ('r','p')),
  'tables_not_owned_or_member', (SELECT coalesce(jsonb_agg(c.relname ORDER BY c.relname), '[]'::jsonb) FROM pg_class c WHERE c.relnamespace = to_regnamespace(%(s)s) AND c.relkind IN ('r','p') AND NOT (pg_has_role(current_user, c.relowner, 'USAGE') OR has_table_privilege(current_user, c.oid, 'TRIGGER'))),
  'app_role_exists', EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %(a)s),
  'app_role_is_superuser', coalesce((SELECT rolsuper FROM pg_roles WHERE rolname = %(a)s), false),
  'app_role_can_set_srr', coalesce(has_parameter_privilege(%(a)s, 'session_replication_role', 'SET'), false),
  'app_role_owns_tables', coalesce((SELECT bool_or(pg_has_role(%(a)s, c.relowner, 'USAGE')) FROM pg_class c WHERE c.relnamespace = to_regnamespace(%(s)s) AND c.relkind IN ('r','p')), false),
  'srr_override', (SELECT coalesce(jsonb_agg(array_to_string(setconfig, ',')), '[]'::jsonb) FROM pg_db_role_setting WHERE setconfig::text LIKE '%%session_replication_role%%'),
  'business_triggers_named_nexo', (SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'nexo_fence_%%'))
"""


def precheck_readonly(execute, *, app_role: str, schema: str = "public", acting_role: str | None = None) -> dict:
    """B2 PURO DE LECTURA: una transacción READ ONLY con SELECTs de catálogo. NO crea esquemas, funciones, tablas ni triggers de prueba (ni siquiera dentro de una transacción que se deshace): la PostgreSQL lo rechazaría.
    No puede MEDIR si el administrador puede crear esquema, funciones SECURITY DEFINER, triggers diferidos o event triggers (eso exige DDL): se mide en B3, SOLO en nexo_fence_lab. Devuelve hechos + bloqueos provisionales."""
    q = (f"SET ROLE {_q(acting_role)};\n" if acting_role else "") + "BEGIN TRANSACTION READ ONLY;\n" + READONLY_SQL.replace("%(s)s", _lit(schema)).replace("%(a)s", _lit(app_role)).replace("%%", "%") + ";\nROLLBACK;"
    rows = execute(q)
    d = rows[0][0] if rows else None
    d = d if isinstance(d, dict) else json.loads(d)
    return readonly_verdict(d)


def readonly_verdict(d: dict) -> dict:
    """Veredicto del precheck de SOLO LECTURA a partir de los hechos `d` (se puede calcular fuera de la base: la EC2 solo devuelve los hechos)."""
    blockers, warns = [], []
    if d.get("max_prepared_transactions", 0) > 0:
        blockers.append("max_prepared_transactions > 0: un COMMIT PREPARED posterior evita el trigger; ponerlo a 0 (parámetro de RDS: requiere reinicio)")
    if d.get("prepared_xacts"):
        blockers.append("hay transacciones preparadas abiertas")
    if not d.get("app_role_exists"):
        blockers.append("el rol de la aplicación no existe")
    if d.get("app_role_is_superuser") or d.get("app_role_can_set_srr") or d.get("app_role_owns_tables"):
        blockers.append("el rol de la aplicación puede saltarse triggers (superusuario, puede fijar session_replication_role o posee tablas)")
    if d.get("tables_not_owned_or_member"):
        blockers.append("el administrador no posee (ni es miembro del propietario de) estas tablas: " + ", ".join(d["tables_not_owned_or_member"][:8]))
    if d.get("srr_override"):
        blockers.append("hay session_replication_role fijado por base/rol (ALTER DATABASE/ROLE ... SET): salta los triggers")
    if not d.get("can_signal_backends"):
        warns.append("el administrador NO puede terminar sesiones de otros roles (pg_signal_backend): el vallado FUERTE por la base no sería posible")
    if d.get("track_commit_timestamp") != "on":
        warns.append("track_commit_timestamp=off: late_commits() no podrá enumerar commits tardíos")
    if d.get("admin_can_set_session_replication_role"):
        warns.append("el administrador PUEDE fijar session_replication_role=replica (vía de administración)")
    if d.get("fence_installed"):
        warns.append("el esquema nexo_fence YA existe en esta base")
    warns.append("la capacidad de crear esquema/funciones SECURITY DEFINER/triggers diferidos/event triggers NO se mide aquí (exige DDL): se mide en B3 dentro de nexo_fence_lab")
    return {**d, "blockers": blockers, "warnings": warns, "ok_to_install": None}


def precheck(execute, *, app_role: str, schema: str = "public", local_now=None, acting_role: str | None = None) -> dict:
    """Comprueba, SIN dejar cambios, si este administrador puede instalar el vallado y si hay vías de escape evidentes. NO supone que el administrador de RDS sea un superusuario: lo MIDE.
    `execute` debe ejecutar la cadena en UNA sesión (varias sentencias: se define una función temporal y se llama). Devuelve {"ok_to_install", "install_mode", "blockers", "warnings", ...}."""
    q = (f"SET ROLE {_q(acting_role)};\n" if acting_role else "") + PRECHECK_SQL + f"\nSELECT pg_temp.nx_precheck({_lit(schema)}, {_lit(app_role)});\nROLLBACK;"          # todo dentro de UNA transacción que se DESHACE: no deja nada
    rows = execute(q)
    d = rows[0][0] if rows else None
    d = d if isinstance(d, dict) else json.loads(d)
    blockers, warns = [], []
    if not d.get("can_create_secdef_and_constraint_triggers"):
        blockers.append("el administrador no puede crear esquema, funciones SECURITY DEFINER y triggers de restricción diferidos: no se puede instalar")
    if d.get("tables_not_owned_or_member"):
        blockers.append("el administrador no posee (ni es miembro del propietario de) estas tablas, así que no puede enganchar triggers: " + ", ".join(d["tables_not_owned_or_member"][:8]))
    if d.get("max_prepared_transactions", 0) > 0:
        blockers.append("max_prepared_transactions > 0: un COMMIT PREPARED posterior evita el trigger; ponerlo a 0 (parámetro de RDS: requiere reinicio)")
    if not d.get("app_role_exists"):
        blockers.append("el rol de la aplicación no existe")
    if d.get("app_role_is_superuser") or d.get("app_role_can_set_srr") or d.get("app_role_owns_tables"):
        blockers.append("el rol de la aplicación puede saltarse triggers (superusuario, puede fijar session_replication_role o posee tablas)")
    if not d.get("can_signal_backends"):
        warns.append("el administrador NO puede terminar sesiones de otros roles (pg_signal_backend): el vallado FUERTE por la base no sería posible; solo valdría la detención confirmada de la RDS por el plano de control")
    if d.get("track_commit_timestamp") != "on":
        warns.append("track_commit_timestamp=off: late_commits() no podrá enumerar commits tardíos (parámetro de RDS)")
    mode = "event_trigger" if d.get("can_create_event_trigger") else "keeper_attach"
    if mode == "keeper_attach":
        warns.append("no se pueden crear event triggers: las tablas nuevas las engancha el guardián (attach_all) y, mientras haya tablas sin cubrir, no se concede autoridad")
    if d.get("admin_can_set_session_replication_role"):
        warns.append("el administrador PUEDE fijar session_replication_role=replica (saltarse los triggers): es una vía de administración, no de la aplicación; hay que restringir y auditar su uso")
    skew = None
    if local_now is not None and d.get("db_now"):
        from datetime import datetime
        try:
            dn = datetime.fromisoformat(str(d["db_now"]).replace("Z", "+00:00"))
            skew = abs((dn - local_now).total_seconds())
            if skew > 2.0:
                warns.append(f"desfase de reloj base↔local de {skew:.1f} s")
        except ValueError:
            pass
    return {**d, "install_mode": mode, "blockers": blockers, "warnings": warns, "clock_skew_s": skew, "ok_to_install": not blockers}
