# EV08 — CloudWatch

Estado al 3 de octubre de 2026: Grupos `/nexoeventos/academy/api` y `/nexoeventos/academy/nginx` y alarma CPU desplegados el 3 de octubre de 2026; la ausencia del token QR completo en el log de API se comprobó en la suite pública. **Captura de consola sanitizada pendiente** (`scripts/cloud/capture-inventory.sh` y checklist en `docs/operacion/procedimientos-sesion-cloud.md` § 2). Mostrar grupos de logs, retención y alarma CPU. Revisar antes que no aparezcan contraseñas, cookies, cabeceras de autorización ni tokens QR.

Lectura API del 7 de octubre: ambos grupos conservan retención de 7 días; la alarma de CPU estaba `OK`, umbral 80 %, dos periodos de 300 s. El escaneo de las últimas 24 h encontró 0 coincidencias para contraseñas, autorización, cookies, tokens de sesión/CSRF, Bearer y DuckDNS. Esto no sustituye la captura de consola.
