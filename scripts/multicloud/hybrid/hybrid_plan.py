#!/usr/bin/env python3
"""Plan EJECUTABLE POR PASOS de la PRUEBA HÍBRIDA de vallado y lease (EC2 + RDS de AWS como primario, almacén de lease en un bucket de OCI, standby = PostgreSQL 18 local en el Mac). No es el
failover AWS → OCI: no hay detector, ni DNS, ni restauración de respaldo; solo se demuestra que el vallado y el lease impiden DOS escritores. Este módulo NO ejecuta nada: describe cada paso con su
efecto, su reversión, su verificación y la autorización que requiere; las pruebas comprueban que ningún paso toca DNS, IAM, claves ni S14 y que todo cambio tiene reversión.
Uso: hybrid_plan.py [--authorizations]   (imprime el plan o solo las autorizaciones que habría que dar)"""
from __future__ import annotations

import json
import sys

# cada paso: id, fase, titulo, accion (comandos descriptivos, sin secretos), cambia (qué estado cambia), revierte (cómo se deshace), verifica (qué demuestra), autoriza (permiso concreto) o None
PLAN: list[dict] = [
    {"id": "P0", "fase": "previa (local)", "titulo": "pruebas locales y precheck contra PostgreSQL 18 desechable", "accion": ["backend/.venv/bin/python -m pytest -q scripts/multicloud/tests/test_pg_fence_hardening.py scripts/multicloud/tests/test_pg_standby.py"],
     "cambia": None, "revierte": None, "verifica": "vallado, vías de escape y reversión funcionan en local", "autoriza": None},
    {"id": "A0", "fase": "AWS+OCI (solo lectura)", "titulo": "estado actual y créditos (solo lectura)", "accion": ["aws sts get-caller-identity; aws rds describe-db-instances; aws ec2 describe-instances (sin start/stop)", "créditos: panel de Academy (la CLI no los expone)", "oci os bucket get (versionado, NoPublicAccess) y oci os preauth-request list (debe haber 0 PAR)"],
     "cambia": None, "revierte": None, "verifica": "sesión Academy activa, RDS/EC2 detenidas, crédito suficiente (techo de gasto de la prueba ≈ 0,5 USD), 0 PAR activos", "autoriza": None},
    {"id": "K1", "fase": "local", "titulo": "claves de firma del lease (Ed25519, una por nodo) con lease_keys.py",
     "accion": ["NEXO_ALLOW_KEY_GENERATION=YES lease_keys.py generate --out-dir <fuera del repo> --scheme ed25519 --confirm \"GENERAR CLAVES DEL LEASE\"", "lease_keys.py verify-pair …", "copiar a cada nodo SOLO su carpeta (privada propia + públicas ajenas) con permisos 0600"],
     "cambia": "carpeta local 0700 con material nuevo; NO se tocan secretos existentes ni la clave C-04", "revierte": "borrar la carpeta y las copias en los nodos (las claves solo valen para el lease de la prueba)", "verifica": "verify-pair ok; ningún nodo contiene la privada del otro", "autoriza": "generar las claves de firma del lease (nuevas, sin tocar C-04) y copiar cada una a su nodo"},
    {"id": "A1", "fase": "OCI", "titulo": "dos PAR de lectura/escritura sobre objetos EXCLUSIVOS de la prueba (prefijo hybrid-test/)",
     "accion": ["oci os preauth-request create … --access-type ObjectReadWrite --object-name hybrid-test/writer-lease.json --time-expires <≤4 h>", "oci os preauth-request create … --object-name hybrid-test/fence-attestation.json (idem)"],
     "cambia": "2 PAR activos en el bucket nexoeventos-recovery (los crea la propietaria; la URL va a archivos 0600, nunca al chat)", "revierte": "oci os preauth-request delete (los 2) y verificar 0 PAR; los objetos hybrid-test/* se borran desde la consola (el perfil de carga no puede borrar)",
     "verifica": "la autoprueba If-Match / If-None-Match de lease_admin.py pasa contra OCI real", "autoriza": "crear 2 PAR (la propietaria) · escribir 2 objetos nuevos bajo hybrid-test/"},
    {"id": "A2", "fase": "OCI", "titulo": "inicializar el lease de PRUEBA (una vez)", "accion": ["lease_admin.py init --par-url-file <archivo 0600> --object writer-lease.json"], "cambia": "objeto hybrid-test/writer-lease.json (época 0, sin titular)",
     "revierte": "borrar el objeto desde la consola", "verifica": "lease_admin.py status → inicializado, verificado", "autoriza": None},
    {"id": "B1", "fase": "AWS", "titulo": "encender RDS y EC2 de V1", "accion": ["hybrid_b1.py preflight --credit-remaining <USD del panel> --max-minutes 90 (solo lectura: identidad, recursos correctos y detenidos, Auto Scaling a 0, gasto)", "NEXO_ALLOW_CLOUD_CHANGES=YES hybrid_b1.py start --credit-remaining <USD> --max-minutes 90 --confirm \"ENCENDER EC2 Y RDS DE V1 PARA B1\" (lanza un watchdog APARTE antes de encender; enciende RDS y luego EC2; cualquier error apaga todo)", "en cualquier momento: hybrid_b1.py stop (idempotente; verifica stopped)"],
     "cambia": "RDS available y EC2 running (consumen créditos; el RDS se reinicia solo a los 7 días si queda parado)", "revierte": "hybrid_b1.py stop (EC2 y RDS; comprueba stopped); el watchdog lo hace solo a la hora límite", "verifica": "describe-instances / describe-db-instances", "autoriza": "encender EC2 y RDS de V1 (≈ 1–2 h)"},
    {"id": "B2", "fase": "AWS", "titulo": "precheck de privilegios y compatibilidad en el RDS REAL (solo lectura: todo dentro de una transacción que se deshace)",
     "accion": ["rds_readiness.py plan --db-id nexoeventos-academy-postgres (solo lectura: describe-db-instances, describe-db-parameters)", "SSM en la EC2: fence_admin.py precheck --read-only --admin-dsn-file <archivo 0600 efímero en la EC2> --app-role nexoeventos_app > pg.json (transacción READ ONLY: la base rechaza cualquier escritura)", "rds_readiness.py evaluate --aws-file aws.json --params-file params.json --pg-file pg.json"], "cambia": None, "revierte": None,
     "verifica": "veredicto de rds_readiness (ready_for_b3, hard_fence_possible: pg_signal_backend, track_commit_timestamp, réplicas de lectura/Multi-AZ, AutomaticRestartTime); ok_to_install=true; max_prepared_transactions=0; el administrador posee las tablas; modo de instalación (event_trigger o keeper_attach); si puede fijar session_replication_role; can_signal_backends (vallado fuerte) y track_commit_timestamp=on", "autoriza": "SSM de solo lectura en la EC2 y lectura de las credenciales del RDS dentro de la EC2 (el DSN se genera allí y nunca se imprime)"},
    {"id": "B3", "fase": "AWS", "titulo": "snapshot manual del RDS (red de seguridad), base de LABORATORIO aislada dentro del mismo RDS e instalación del vallado SOLO en ella", "accion": ["aws rds create-db-snapshot …", "fence_admin.py lab-create --lab-db nexo_fence_lab --confirm \"CREAR BASE DE LABORATORIO\" (las tablas de negocio NO se tocan: la prueba usa tablas de laboratorio con el mismo esquema)", "fence_admin.py snapshot (huella previa) y --state-file en install", "crear el rol guardián con contraseña aleatoria guardada solo en la EC2 (0600)", "fence_admin.py install --confirm \"INSTALAR VALLADO EN LA BASE\"", "fence_admin.py attest"],
     "cambia": "base de LABORATORIO nexo_fence_lab dentro del RDS: esquema nexo_fence, triggers SOLO en sus tablas de prueba y rol nexo_fence_keeper; las tablas de negocio NO se tocan; 1 snapshot (fence_admin.py rechaza instalar fuera de nexo_fence_lab*)", "revierte": "fence_admin.py uninstall --state-file … (compara la huella del catálogo: debe ser IDÉNTICA) y lab-drop; drop-role del guardián; borrar el snapshot si ya no hace falta",
     "verifica": "attest ok=true (todas las tablas cubiertas, sin vías de escape) SOLO en la base de laboratorio; hard_fence de PRUEBA sobre nexo_fence_lab (sesión de prueba terminada, prueba completa, cerrojo y release_latch con la frase); track_commit_timestamp comprobado (late_commits disponible)", "autoriza": "DDL en el RDS (instalar y revertir el vallado) · crear 1 snapshot · crear 1 rol"},
    {"id": "B4", "fase": "AWS", "titulo": "activar la compuerta en el backend de la EC2 (WRITE_GATE_MODE=enforce, WRITE_GATE_DB_FENCE=require) con el lease de OCI",
     "accion": ["proceso de PRUEBA aparte (usuario y puerto propios; el servicio nexoeventos-api de producción NO se toca) con WRITE_GATE_* (archivos 0600: PAR, guardián, WRITE_GATE_LEASE_SIGNING_KEY_FILE / PEER_PUBKEYS_FILE / STATE_FILE) y WRITE_GATE_DB_FENCE=require apuntando SOLO a nexo_fence_lab", "systemctl restart nexoeventos-api", "curl /write-gate"],
     "cambia": "configuración del servicio en la EC2: sin lease de OCI la API pasa a SOLO LECTURA (disponibilidad reducida a propósito)", "revierte": "eliminar el drop-in y reiniciar; comprobar /write-gate 404 y que la API escribe",
     "verifica": "/write-gate: holds_lease=true, época ≥ 1, db_fence.last_sync_ok=true; la atestación aparece publicada en OCI", "autoriza": "cambiar la configuración del servicio en la EC2 (SSM) y reiniciarlo"},
    {"id": "C0", "fase": "prueba", "titulo": "línea base: solo AWS escribe", "accion": ["Mac: writer_probe --once <época> contra la base local (debe rechazar)", "EC2: writer_probe --once <época> (debe aceptar)"], "cambia": "filas en nexo_fence.write_probe (tabla de sondeo)",
     "revierte": "DELETE de las filas de sondeo (con autoridad o con el trigger desactivado por el administrador) o dejarlas (no son datos de negocio)", "verifica": "AWS acepta, el standby local rechaza", "autoriza": None},
    {"id": "C1", "fase": "prueba", "titulo": "fallo de EC2: se detiene la instancia", "accion": ["aws ec2 stop-instances", "Mac: PgStandby toma el lease tras TTL+margen y habilita; writer_probe --loop en el Mac"],
     "cambia": "EC2 stopped (el primario deja de renovar)", "revierte": "aws ec2 start-instances en C4", "verifica": "el standby tomó el lease SOLO tras caducar el del primario (época+1) y el hueco de escritura es ≥ TTL+margen; ninguna confirmación solapada", "autoriza": None},
    {"id": "C2", "fase": "prueba", "titulo": "pérdida de conexión con el primario VIVO: se corta su salida hacia OCI (iptables en la EC2)", "accion": ["SSM: iptables -I OUTPUT -d <IP del endpoint de Object Storage> -p tcp --dport 443 -j DROP"],
     "cambia": "una regla local de iptables en la EC2 (no toca SG, NSG ni redes cloud)", "revierte": "iptables -D OUTPUT … y comprobar que la regla ya no está", "verifica": "la autoridad de la base del primario caduca sola en ≤ TTL−margen aunque la API siga viva; /write-gate: holds_lease=false", "autoriza": "una regla de iptables temporal en la EC2 (SSM)"},
    {"id": "C3", "fase": "prueba", "titulo": "escritor anterior que intenta confirmar después de perder autoridad", "accion": ["EC2: writer_probe --hold <época> --hold-seconds 8 (abre la transacción con autoridad y confirma tras vencer)"],
     "cambia": "ninguna fila (el commit debe ser rechazado)", "revierte": None, "verifica": "accepted=false, reason=NEXO_FENCE; con una transacción lenta de la API: HTTP 503 write_outcome_unknown (barrera de reconocimiento) y late_commits() enumera los huérfanos", "autoriza": None},
    {"id": "C4", "fase": "prueba", "titulo": "regreso de AWS: se restablece la conexión / se vuelve a encender la EC2", "accion": ["iptables -D … o aws ec2 start-instances", "esperar ≥ 3 ciclos del guardián", "EC2: writer_probe --once <época vieja> y <época actual>"],
     "cambia": "la EC2 vuelve a intentar el lease", "revierte": None, "verifica": "AWS NO recupera autoridad mientras el standby sea el titular: /write-gate holds_lease=false, probes rechazadas, POST de la API → 503; analyze.py: seguro=true", "autoriza": None},
    {"id": "R1", "fase": "reversión", "titulo": "devolver todo al estado inicial", "accion": ["Mac: PgStandby.disable y liberar el lease", "quitar el drop-in WRITE_GATE_* y reiniciar la API", "fence_admin.py uninstall (+ drop del rol guardián)", "borrar la regla iptables si queda", "oci os preauth-request delete (2) y verificar 0 PAR",
                                                                  "aws ec2 stop-instances; aws rds stop-db-instance"], "cambia": "deshace los cambios de B3, B4, C2, A1", "revierte": None,
     "verifica": "uninstall con --state-file: huella del catálogo IDÉNTICA; lab-drop; /write-gate 404; 0 PAR; EC2 y RDS stopped; objetos hybrid-test/* retirados; carpeta de claves borrada de los nodos; late_commits registrados antes de borrar", "autoriza": None},
]


# Etapas A–E: cada una exige que la anterior haya PASADO (hybrid_gate.py); si falla, las siguientes quedan bloqueadas y solo se permite la reversión.
ETAPAS = {"A": ("prechecks de solo lectura", ["P0", "A0"]), "B": ("snapshot y preparación reversible", ["K1", "A1", "A2", "B1", "B2", "B3", "B4"]),
          "C": ("vallado real en entorno aislado (base de laboratorio)", ["C0"]), "D": ("partición y prueba del escritor anterior", ["C1", "C2", "C3", "C4"]), "E": ("reversión y comprobación final", ["R1"])}


def required_authorizations() -> list[str]:
    seen, out = set(), []
    for p in PLAN:
        a = p.get("autoriza")
        if a and a not in seen:
            seen.add(a); out.append(f"{p['id']}: {a}")
    return out


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    print(json.dumps(required_authorizations() if "--authorizations" in argv else PLAN, indent=1, ensure_ascii=False)); return 0


if __name__ == "__main__":
    sys.exit(main())


# Qué afecta a AWS real y qué queda en una base aislada o local.
ALCANCE = {"P0": "local", "A0": "solo lectura (AWS y OCI)", "K1": "local + copia a los nodos (secretos NUEVOS)", "A1": "OCI real (2 PAR del laboratorio; los crea la propietaria)", "A2": "OCI real (objeto hybrid-test/)",
           "B1": "AWS REAL (enciende RDS y EC2)", "B2": "AWS REAL, solo lectura (transacción que se deshace)", "B3": "AWS REAL pero AISLADO: base de laboratorio nexo_fence_lab; sin triggers en tablas de negocio",
           "B4": "AWS REAL: proceso aparte de la EC2 con usuario propio; el servicio de producción no se toca", "C0": "base de laboratorio", "C1": "AWS REAL (detiene la EC2)", "C2": "AWS REAL (regla iptables temporal en la EC2)",
           "C3": "base de laboratorio", "C4": "AWS REAL (revierte C2/C1)", "R1": "AWS+OCI (deshace todo)"}

# Garantías NO demostradas: mientras figuren aquí, NO se activa el failover automático (solo la prueba híbrida con personas al mando).
BLOQUEOS = [
    "pausa del servidor entre la comprobación del commit y su fin: SOLO se excluye con el VALLADO FUERTE (promotion_gate.py: sesiones del primario terminadas y comprobadas, o RDS `stopped` por el plano de control). Falta validarlo en RDS REAL: pg_signal_backend de rds_superuser, track_commit_timestamp, parada de una RDS Multi-AZ y su duración (RTO)",
    "particiones en las que no se alcanza ni la base ni el plano de control de AWS: NO promovibles (modo seguro y alerta); no hay forma automática segura de distinguirlas de un primario vivo",
    "reloj de la base corrido con el guardián sin alcance a la base pero con la aplicación sí: la última concesión alargada no se puede recortar (exige NTP del RDS comprobado)",
    "administrador con rds_superuser puede fijar session_replication_role: precheck en el RDS REAL pendiente (etapa B2)",
    "instalación en las tablas de NEGOCIO reales: el administrador no es propietario; el procedimiento de 3 roles y fases (fence_business.py) está probado solo en COPIA local; falta comprobar en la RDS real quién posee la base y que el migrador puede SET ROLE (fence_business.py preguntas, solo lectura)",
    "ROLLBACK SIMULTÁNEO (lease + sello + base restaurados a un estado antiguo coherente y firmado): REPRODUCIDO y corregido SOLO en local con un TESTIGO de frescura independiente (witness.py). Sin una infraestructura real para el testigo (almacén inmutable e independiente de AWS y OCI) el automático sigue BLOQUEADO",
    "regreso del primario tras la promoción: sello persistente (OCI) + cerrojo en la base + guardia de reinicio probados en LOCAL con dos PostgreSQL; falta probar la guardia contra el reinicio real de una RDS (estado `starting`/`available`, alcance de la base por SSM) y el sellado desde el orquestador alojado fuera del Mac",
    "ROLLBACK DEL SELLO: mecanismo diseñado y probado en LOCAL (registro de apéndice encadenado y firmado + ancla de frescura en el lease + trinquete en la base + inicialización humana). Para OCI REAL se recomienda: bucket de laboratorio INDEPENDIENTE (nunca nexoeventos-recovery: tiene versionado y la retención lo exige desactivado), escritura por identidad con OBJECT_CREATE sin OVERWRITE/DELETE (OciSdkLogStore), lectura por PAR de lectura con listado, y retención con plazo SIN bloquear en el laboratorio; matriz T1–T10 en oci_seal_lab.py. Hasta ejecutarla en OCI real y obtener todas las garantías, `antirollback_validated` sigue FALSE y el automático BLOQUEADO",
    "un PAR de lectura/escritura NO es solo-adición (sobrescribe; observado el 19-nov): no se usa para escribir el sello; un administrador comprometido de OCI puede borrar la regla de retención si no está BLOQUEADA (bloquearla es irreversible y exige 14 días de retraso: decisión posterior a la validación)",
    "If-Match por PAR validado en vivo, pero la identidad desatendida definitiva (usuario de servicio / instance principal) aún no existe",
    "detector y orquestador fuera del Mac, identidad de recuperación en Vault/KMS, DNS y app en solo lectura del standby: sin implementar/probar",
]
