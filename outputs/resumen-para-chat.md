# Resumen breve para planificación

NexoEventos quedó preparado para Amazon Linux 2023 con Nginx, FastAPI/systemd sin privilegios, Python 3.11 aislado y Node/dependencias fijados. Terraform ahora exige cuenta esperada, estado separado por cuenta, perfil IAM explícito y snapshot final; `fmt`/`validate` pasan. El plan 30/0/0 de `25a12c1` es histórico. El intento nuevo quedó bloqueado por credenciales Academy canceladas (`voc-cancel-cred`); se eliminó el plan incompleto. Hay que iniciar el Lab en Chrome y renovar credenciales antes de regenerarlo.

El costo corregido es USD 36.465 por 720 horas/30 días continuos. Para 37 horas activas y persistencia hipotética del 5 de octubre al 26 de noviembre: subtotal USD 10.267 + margen USD 3.000 = techo USD 13.267. Se revisará consumo al observar USD 30 y USD 40; no son límites automáticos.

Secretos: carga sin eco, archivos root-only, identidades RDS maestra/migración/aplicación separadas; el permiso para leer el secreto maestro se probará en la EC2 real. DuckDNS + Let's Encrypt es la decisión: `nexoeventos-demo.duckdns.org` no resolvía, pero falta reclamarlo. La usuaria solo debe comunicar el FQDN aceptado, nunca el token. Restore local, snapshot final, backup cifrado externo y migración entre cuentas están documentados; cloud, copia externa y migración real siguen pendientes. No hubo `apply` ni `destroy`.
