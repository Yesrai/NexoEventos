# 09 · Guion de exposición (≈ 15 minutos)

Apoyo visual: `presentacion/NexoEventos-Final.pptx` (22 diapositivas; el número de cada bloque es la diapositiva). Si el equipo tiene menos personas, una sola oradora puede cubrir todos los bloques; los nombres se completan al ensayar. **Regla durante toda la exposición:** decir siempre «real», «local», «diseño» o «estimado».

| Bloque | Diapositivas | Orador/a | Tiempo |
|---|---|---|---|
| A. Problema y arquitectura | 1–8 | Orador/a 1 | 4:00 |
| B. Pruebas reales T1–T5 | 9–15 | Orador/a 2 | 5:00 |
| C. Recuperación, T6 y T7 | 16–19 | Orador/a 3 | 3:30 |
| D. Costos, límites y cierre | 20–22 | Orador/a 1 | 1:30 |
| Demo local (opcional, si hay tiempo) | — | Orador/a 3 | 1:00 |

## A. Problema y arquitectura (4:00)

- **D1–D2 (0:30):** «NexoEventos vende entradas con QR. Nuestra regla: todo lo que mostramos está rotulado como real, local, diseño o estimado».
- **D3 (0:40):** problema (instancia única, picos, respaldos en el mismo sitio) y requisitos: no sobrevender, cifrar, sobrevivir a la caída de una EC2, recuperarse fuera de AWS, costo acotado por Academy.
- **D4 (0:50):** arquitectura F1. AWS sirve, OCI guarda y reconstruye y aloja el lease, Azure observa. «Las cajas discontinuas son diseño: el failover no se ejecutó».
- **D5 (0:40):** dos puntos de operación en AWS: económico (2 EC2, ≈ 0,13 USD/h) y alta disponibilidad (6 EC2, ≈ 0,26 USD/h). Lo decidió una medición, no una preferencia.
- **D6 (0:30):** redes: VPC/VCN/VNet con subredes privadas para datos; **no hay VPN entre nubes**, solo HTTPS 443.
- **D7–D8 (0:40):** cómputo, BD, IaC (5 raíces Terraform con plan revisado) y seguridad (CMS AES-256, TLS verificado, PAR revocados, fallo cerrado).

## B. Pruebas reales T1–T5 (5:00)

- **D9 (0:40):** tabla resumen. «Cinco pruebas reales con criterios escritos antes; cuatro de ellas fallaron primero y lo conservamos».
- **D10 (0:50):** T1: CAS 20/20 y lease 20/20 en OCI, épocas 2→21 sin retroceso, p95 0,414 s. T2: DNS A→B→A en 62 s, segundo cambio rechazado por el intervalo de 300 s. El primer FAIL de T2 fue Python **rechazando** un certificado sin CA: no desactivamos TLS.
- **D11 (0:50):** T3: FAIL (dnf saturó la VM), FAIL (OOM), PASS 19/19: 136 reservas, 10/10 huellas, humo 11/11 y 23/23, solo 443 abierto. «649 s son reconstrucción, no RTO de failover».
- **D12 (0:40):** T4: alerta real Fired a las 19:03:19Z, correo recibido, 38 ciclos de sondas, panel 18 pruebas.
- **D13–D14 (1:20):** T5: con 2 EC2, 95,21 % (FAIL); causa medida: el ALB envía la mitad del tráfico a la instancia caída durante la detección. Intento 2 abortado por la SCP de Academy. Con 6 EC2 y health check de 5 s: 99,49 %, detección 9,6 s, recuperación 125 s. «Es una ejecución: no es un SLA; tampoco probamos caída abrupta ni escrituras».
- **D15 (0:40):** tiempos medidos como piezas; RTO/RPO del failover **no medidos**.

## C. Recuperación, T6 y T7 (3:30)

- **D16 (0:50):** un solo escritor: lease en OCI (real), testigo en Azure (real, sin anclaje en nube), compuerta y sello (local).
- **D17 (1:00):** flujo T6 con sus barreras D1–D8: **BLOCKED**. Requiere autorización, ventana y cerrar barreras en la nube.
- **D18 (0:50):** lo hecho en local: anclaje anti-rollback (19 pruebas), exploración exhaustiva de 59.049 secuencias sin doble escritor y el control negativo que demuestra que el anclaje es necesario. «Es verificación local de la lógica, no una prueba en la nube».
- **D19 (0:50):** NexoOps: login con contraseña Argon2id y OTP por Gmail funcionando en local, rol `SUPER_ADMIN_TI`, auditoría encadenada, acciones en lista blanca, asistente por reglas (no IA generativa). No desplegado en Azure.

## D. Costos, límites y cierre (1:30)

- **D20 (0:30):** ≈ USD 0,95 estimados en todas las ventanas, incluidos los fallos; no es factura.
- **D21 (0:30):** limitaciones (T6, una ejecución de HA, sin red privada, LabRole, costos estimados).
- **D22 (0:30):** conclusión: «El resultado principal es la metodología verificable: criterios antes, expediente con hash, fallos conservados y fallo cerrado por defecto».

## Preguntas probables y respuestas honestas

| Pregunta | Respuesta |
|---|---|
| ¿Tienen failover AWS→OCI funcionando? | No en la nube. T6 está BLOCKED: tenemos piezas reales (lease T1, DNS T2, reconstrucción T3, observación T4) y la lógica de escritor único verificada en local; las barreras D1–D8 siguen abiertas. |
| ¿Cuál es su RTO? | Del failover, no medido. Medimos piezas: 9,6 s de detección y 125 s de recuperación dentro de AWS (T5), 649 s de reconstrucción en OCI (T3), 62 s de propagación DNS (T2). No las sumamos porque faltan etapas no medidas. |
| ¿Y el RPO? | No medido para el failover. Hoy el último respaldo tiene ≈ 93 h, así que fallaría; por eso diseñamos la secuencia congelar → drenar → respaldo final → verificar → restaurar. |
| ¿Garantizan 99,5 % de disponibilidad? | No. Fue una ejecución con 6 EC2 y parada controlada. Con 2 EC2 obtuvimos 95,21 %. |
| ¿Por qué 6 instancias y no 7? | La SCP de Academy denegó un máximo de 7 (intento 2). No sabemos exactamente qué parámetro la dispara. |
| ¿Por qué no replicación síncrona entre nubes? | Cada COMMIT esperaría el viaje de ida y vuelta a São Paulo, y el vallado de laboratorio no es transferible a RDS. Elegimos respaldo cifrado + escritor único. |
| ¿Cómo evitan dos escritores? | Lease con CAS y época en OCI, firma Ed25519, testigo con cadena de hashes, compuerta de escritura y sello. En la nube solo está probado el lease (T1); el resto, en local. |
| ¿El asistente de NexoOps es IA? | No es IA generativa: es un motor determinista basado en reglas que separa hechos, hipótesis y recomendaciones con su evidencia. |
| ¿Cuánto costó? | ≈ USD 0,95 estimado por expedientes; no tenemos factura (Academy no da Cost Explorer). |
| ¿Por qué hay tantos FAIL? | Porque los conservamos: cada uno tiene causa raíz, corrección con prueba de regresión y nueva autorización. Es parte de la evidencia. |
| ¿Hay red privada entre nubes? | No. Todo es HTTPS 443 con TLS verificado; es un límite declarado y una decisión de costo. |
| ¿El mínimo privilegio en AWS? | `LabRole` lo impone Academy y es más amplio; lo compensamos con SG→SG, sin SSH, cifrado y roles PostgreSQL separados. En OCI y Azure sí aplicamos mínimo privilegio propio. |
