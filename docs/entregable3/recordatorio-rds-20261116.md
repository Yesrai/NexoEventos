# RECORDATORIO — 16-nov-2026: RDS se reinicia sola hacia el 18-nov

> **ACTUALIZADO 11-nov (ventana del respaldo):** RDS se encendió y volvió a detener; nueva parada **2026-11-11 16:52:03 UTC** → reinicio automático previsto **≈ 2026-11-18 16:52 UTC** (≈ 11:52 hora de Perú/Colombia). Lo de abajo con 14:38 UTC queda superado.

- RDS `nexoeventos-academy-postgres` se detuvo el **2026-11-11 14:38:33 UTC**. AWS la reinicia sola tras 7 días: **≈ 2026-11-18 14:38 UTC** (≈ 09:38 hora de Perú/Colombia).
- Acción el 16-nov (o en la primera sesión de laboratorio): iniciar Academy, comprobar `aws rds describe-db-instances` (estado) y `describe-events --duration 10080`.
- Si no se va a usar: detenerla de nuevo (requiere autorización; reinicia el contador). Si se va a usar: `start-db-instance` y esperar `available` (≈ 5–8 min); luego reconstruir el ALB (informe 10 §6) antes de encender V2.
- Cada hora encendida cuesta ≈ 0,04 USD (Multi-AZ). Consultar el estado no reinicia el contador.
- No hay monitoreo en la nube para esto (no genera cargos): el aviso es solo este archivo/tu calendario.

## Lista mínima para la próxima sesión autorizada de AWS Academy (preparada el 16-nov; NADA ejecutado)
Hoy 16-nov ≈ 22:30 (Perú): faltan ≈ 37 h para el reinicio automático (18-nov 16:52 UTC = 11:52 Perú). Solo lecturas hasta que autorices cada cambio.
1. **Sesión y cuenta:** `bash scripts/cloud/cloud-session.sh status` (solo lectura; muestra EC2, RDS y la fecha límite). Si falla con «STS no respondió», renueva el laboratorio.
2. **RDS:** `stopped` (¿sigue detenida?) o `available/starting` (ya se reinició sola: ≈ 0,04 USD/h desde ese momento). `describe-events` de 7 días: busca «being started due to it exceeding». Decidir con tu autorización: detenerla (reinicia el contador 7 días) o aprovecharla para C-04.
3. **Saldo:** capturar el indicador «$ usados de 50» del panel de Academy (estimación del 11-nov ≈ 27 USD; sin Cost Explorer). Presupuesto de C-04 ≤ 0,2 USD.
4. **Temporizador:** tiempo restante de la sesión (≈ 4 h); no iniciar C-04 con menos de 1,5 h. Fecha de expiración de Academy (≈ 26-nov).
5. **Posibles cargos (lecturas):** EC2 de V1 (`running`/`stopped`; Academy puede reencenderla), ALB 0, NAT 0, EIP sin asociar 0, volúmenes sin uso 0, instantáneas (5 manuales + automáticas), AMI (2), secretos (2), alarmas.
6. **Recursos para C-04 (3 ciclos de `backup_cycle.py`):** EC2 de V1 con SSM `Online` y `pg_dump` 18; RDS `available`; en la EC2 (por SSM, sin imprimir secretos): `scripts/multicloud/backup_cycle.py` y `backup_freshness.py`, certificado **público** de OCI, `backup.env` con el `DATABASE_URL` de un rol mínimo, y la **URL del PAR de escritura de OCI** (la creas tú en OCI, con caducidad corta y sin lectura ni borrado; archivo 0600). Ejecutar el servicio a mano 3 veces (**no habilitar el timer**), medir intervalos y duración con `cycles.jsonl`, verificar los 3 objetos en OCI (hash) y que el PAR no deje reescribir; **revocar el PAR**; detener EC2 y RDS y anotar la nueva fecha de reinicio.
7. **Pendiente de decidir contigo:** quién crea/revoca el PAR en OCI, y qué rol de base de datos usa el volcado (el de migración da más permisos de los necesarios).
