# Verificación controlada de la versión pública (AWS V1, commit 82d1384) · 19-oct-2026

Evento ficticio `[ENSAYO]` id 90101 (copia de la estructura del 1028), publicado con `is_demo=false`: **no aparece en el catálogo público** (32 eventos listados antes y durante) y es accesible por id. Cuentas `ensayo-*@example.com`. Sin tokens ni contraseñas en esta evidencia.

| Verificación | Resultado |
|---|---|
| Evento de ensayo fuera del catálogo; accesible por id con 96 asientos y 2 zonas | OK |
| Registro e inicio de sesión de cliente y operadora; sesión válida en 40/40 lecturas (2 workers) | OK |
| Reserva de 2 asientos (201) y repetición idempotente (200, misma reserva) | OK |
| Mis entradas: 1 reserva, 2 entradas con QR | OK |
| Operadora asignada: valida (200) y la segunda lectura se rechaza (409); evento no asignado 403; cliente 403 | OK |
| Fila virtual (máx. 2): 5 cuentas simultáneas → 2 admitidas, 3 en espera (1..3); sin turno se rechaza (403) | OK |
| Disputa del mismo asiento entre 5 cuentas: 1 ganador (201), resto 403/409 | OK |
| UI real (Chrome, escritorio y móvil): detalle abre el recinto 3D, clic en butaca, panel con total, registro y retorno con la selección intacta, sin excepciones de página (10/10) | OK |

La UI se detuvo antes de «Confirmar compra» porque la navegación es por estado y solo llega a eventos listados en el catálogo (comerciales): ahí no se crean reservas. La compra completa (reserva, entradas, QR, validación) se verificó por API sobre el evento de ensayo.

## Limpieza
Evento, zonas, asientos, reservas, entradas, filas de fila virtual y las 9 cuentas de ensayo borrados por id/prefijo. Estado posterior: 135 reservas (mismo hash), 135 entradas, 25 usuarios, inventario de los 31 eventos originales con el mismo hash que antes, eventos 1028-1031 sin reservas ni asientos ocupados, 9 registros de acceso (los mismos de antes), Alembic 0008.

## Incidente de la ejecución (sin pérdida de datos)
La primera limpieza falló y se revirtió por completo (transacción): el intento de validar en un evento no asignado dejó **una fila de `access_logs` sobre el evento 1028** (`wrong_event`) que impedía borrar a la operadora de ensayo. Se corrigió el script para borrar los registros de acceso de las cuentas de ensayo y se repitió la limpieza; esa fila quedó eliminada. El aviso «excepciones de página: FALLÓ» de esa ejecución fue un error de lectura del informe del script (corregido); el JSON de la UI no tiene excepciones.
