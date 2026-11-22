#!/usr/bin/env bash
# Ejecuta EN la VM las pruebas del testigo (perfil Azure: persistencia kill -9, exclusividad, token por alcance, TLS fijado, almacén alterado/cola truncada/sin permisos) con el paquete --con-pruebas.
# Usa un directorio temporal propio (NO toca /var/lib/witness ni el testigo en servicio). Instala pytest en el venv si falta. Imprime una línea JSON {"ok","passed","failed"}.
set -uo pipefail
V=/opt/nexoeventos/venv/bin; cd /opt/nexoeventos
"$V/python" -c "import pytest" 2>/dev/null || "$V/pip" install --no-cache-dir -q pytest >/dev/null 2>&1
# Como usuario SIN privilegios (opscenter): como root, `chmod` no impide escribir y la prueba «directorio sin permiso de escritura» no mide nada (T4: falló por eso, no por el testigo).
OUT="$(cd /tmp && runuser -u opscenter -- env HOME=/tmp PYTHONPATH=/opt/nexoeventos/backend:/opt/nexoeventos/scripts/multicloud/witness "$V/python" -m pytest --rootdir=/opt/nexoeventos -q -p no:cacheprovider /opt/nexoeventos/scripts/multicloud/tests/test_witness_azure_profile.py /opt/nexoeventos/scripts/multicloud/tests/test_witness_service.py /opt/nexoeventos/scripts/multicloud/tests/test_witness_hardening.py 2>&1 | tail -3)"
P="$(printf '%s\n' "$OUT" | grep -Eo '[0-9]+ passed' | grep -Eo '[0-9]+' || echo 0)"; F="$(printf '%s\n' "$OUT" | grep -Eo '[0-9]+ failed' | grep -Eo '[0-9]+' || echo 0)"
printf '{"ok": %s, "passed": %s, "failed": %s}\n' "$([[ "$F" == 0 && "$P" -gt 0 ]] && echo true || echo false)" "$P" "$F"
