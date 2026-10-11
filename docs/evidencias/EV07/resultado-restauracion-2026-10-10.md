# R01 — restauración cloud aislada ejecutada

Ejecución `20261010t2347`, realizada el 10 de octubre de 2026 (Lima) mediante PITR. No se conmutaron la aplicación, DNS ni HTTPS. No se muestran endpoints, credenciales, identificadores privados ni tokens QR.

| Medida | Resultado | Alcance |
|---|---:|---|
| desfase T0 − punto recuperable | 3 min 32 s | RPO demostrado al comparar la copia con la línea base exacta |
| T0 → RDS temporal `available` | 20 min 49 s | disponibilidad de infraestructura de datos |
| T0 → datos verificados | 21 min 4 s | recuperación de datos, no del servicio completo |
| recuperación del servicio completo | pendiente | no se conmutaron aplicación, DNS ni HTTPS |

La verificación por SSM confirmó:

- Alembic `0005`;
- coincidencia exacta de las seis tablas incluidas en la huella lógica;
- reservas y propietarios coherentes;
- 135/135 entradas QR descifrables y con hash correcto, sin revelar tokens;
- `VERIFICACION_RESTAURACION=OK`.

Secuencia UTC: escrituras pausadas 23:47:57; línea base 23:48:09; T0 23:52:51; solicitud aceptada 23:52:54; origen reanudado 23:53:06; copia disponible 00:13:40; datos verificados 00:13:55.

La RDS temporal exacta `nexoeventos-academy-restore-20261010t2347` se eliminó mediante su recibo `0600`, hash de ARN y etiquetas de la ejecución. AWS confirmó después cero copias temporales con el prefijo de restauración. La RDS original y EC2 quedaron `stopped` a las 19:23 Lima; reinicio automático estimado de la RDS original: 17 de octubre de 2026, 19:23 Lima.

Incidencia del ejecutable: tras imprimir el resultado correcto, el trap de limpieza devolvía código 1 cuando no había archivo temporal pendiente. Se corrigió `cleanup_local` para que ese estado normal termine en cero; la evidencia de esta ejecución se apoya en las marcas T0–T3 y `VERIFICACION_RESTAURACION=OK`, no en el código defectuoso anterior.
