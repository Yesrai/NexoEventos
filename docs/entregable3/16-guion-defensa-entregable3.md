# NexoEventos · Entregable 3 — Guion de sustentación y defensa (borrador, 11-nov-2026)

> **Fechas clave:** RDS se reinicia sola hacia el **18-nov ~16:52 UTC** · Academy expira ≈ **26-nov**. **Antes de la defensa, comprobar el estado de RDS** (puede haberse reiniciado sola) y no encender nada sin necesidad.
Criterio 14 (peso 0,5): «domina la arquitectura, responde decisiones técnicas y demuestra el entorno **sin depender del informe**». Este guion se ensaya; no se lee.

## 1. Estructura (≈ 12 min + preguntas)
| Min | Tema | Qué decir | Qué mostrar |
|---|---|---|---|
| 0–1 | Problema | NexoEventos vende entradas con reservas confirmadas; el riesgo es perder esas reservas y depender de una sola cuenta que expira. | — |
| 1–3 | Arquitectura y decisión | V2 en AWS (ALB+ASG+RDS Multi-AZ), recuperación en OCI, observabilidad en Azure. **Decidimos no hacer replicación síncrona entre nubes**: cada COMMIT esperaría el viaje de ida y vuelta y el fencing de Docker no aplica a RDS. | Diagrama 01 y 02 |
| 3–4 | Qué es real y qué no | Cuatro capas: A respaldo AWS→OCI (real), B restauración local (Docker), C despliegue en OCI (real, 23-oct, respaldo anterior), D failover multicloud (diseño y simulación). | Diagrama 01 |
| 4–6 | Seguridad | Dos claves independientes (AWS y OCI), usuario de OCI que no puede sobrescribir ni borrar, auditorías de solo lectura con enmascarado. | Prueba de no-sobrescribir (`oci-subida-…txt`) |
| 6–9 | **Demo local (≈ 2 min de ejecución)** | Verificar integridad y restaurar el respaldo del 11-nov en un PostgreSQL 18 desechable. | Comando de §2 |
| 9–10 | Costos | Ahorro real: ALB eliminado, RDS detenida con instantánea previa; ventana de respaldo ≈ 0,02 USD. | Tabla §11 del informe |
| 10–12 | Límites y cierre | Respaldo puntual, sin failover real, sin RPO cero; plan de mejora (O1–O3). | §13 del informe |

## 2. Demo local (no enciende AWS ni OCI)
Desde la raíz del repositorio (pide la frase de paso de la clave de OCI; ensayarla antes):
```bash
scripts/multicloud/restore-drill.sh --manifest work/oci-transfer/nexoeventos-rds-20261111T164610Z.manifest.json --cms work/oci-transfer/nexoeventos-rds-20261111T164610Z.oci.cms --key ~/.nexoeventos/recovery-oci/oci-recovery-private.pem --baseline docs/evidencias/multicloud/aws/20261111-respaldo-rds/linea-base-restauracion.json --baseline-key rds-20261111T164610Z --mode docker
```
**Resultado esperado:** 7 líneas `OK` (cifrado SHA-256, descifrado, hash del volcado, catálogo de 119 líneas, restauración, «huella idéntica a la línea base (10 claves)», tiempo ≈ 8–9 s) y código 0. Requiere Docker en marcha y la imagen `postgres:18`.
**Plan B si falla la demo:** mostrar `evidencias/restauracion-aislada-local-rds-20261111.txt` y `prueba-local-pipeline-restauracion-20261111.txt` (16/16 con casos negativos). Decir claramente que es evidencia grabada, no en vivo.
Sin nube, en solo lectura: mostrar el manifiesto SHA-256 y verificar un archivo (`shasum -a 256 -c` sobre `evidencias/MANIFIESTO-SHA256-20261110.txt`).

## 3. Preguntas probables y respuestas honestas
1. **¿Tienen failover entre AWS y OCI?** No. Hay diseño y simulaciones en Docker. Lo real es respaldo cifrado, transferencia, restauración y un despliegue temporal en OCI.
2. **¿El RPO es cero?** No. El respaldo es puntual (RPO = momento del volcado). En Docker, con replicación síncrona, no se observaron pérdidas en ≈ 7 500 reservas, pero eso es una observación, no una garantía.
3. **¿Qué RTO tienen?** Recuperación completa en OCI 32 min 42 s (23-oct, medida); restauración de datos 8–24 s; conmutación de BD 3–4 s **solo entre contenedores Docker**.
4. **¿Por qué no replicación síncrona entre nubes?** Latencia por COMMIT (≈ 100–130 ms estimada, no verificada), sin garantía de poder configurar RDS Academy y el fencing de Docker no es transferible.
5. **¿Qué es una instantánea de RDS frente a su respaldo?** La instantánea es copia de bloques solo restaurable como RDS en AWS y se pierde con la cuenta; el `pg_dump` es portable, cifrado y verificado en OCI.
6. **¿Cómo saben que el respaldo sirve?** Se restauró y la huella de datos (usuarios, eventos, reservas, entradas, hashes md5) coincide en 10/10 claves, incluso con la clave privada de OCI de la propietaria.
7. **¿Qué pasa si pierden la clave de OCI?** Se pierde el acceso al respaldo de OCI y a la copia cifrada local; es un riesgo declarado, sin custodia alternativa documentada.
8. **¿Qué no está en el respaldo?** `TICKET_ENCRYPTION_KEY` y `SECURITY_HASH_KEY`: se custodian aparte; sin ellas no se validan las entradas QR ya emitidas.
9. **¿Por qué eliminaron el ALB?** Para ahorrar crédito (≈ 0,04 USD/h) sin perder datos; se hizo con `destroy` dirigido y plan guardado (8 bajas, 0 cambios) y se reconstruye con un `apply` revisado.
10. **¿Y si RDS se reinicia sola?** AWS la enciende a los 7 días de detenida (≈ 18-nov 16:52 UTC); se vigila por estado y eventos, y se vuelve a detener si no se usa.
11. **¿Qué demuestra Docker?** Que el mecanismo de testigo, fencing y sincronía se comporta como se diseñó en condiciones controladas. No demuestra nada sobre la red real entre AWS y OCI.
12. **¿Cuánto costó?** La ventana del respaldo ≈ 0,02 USD; la VM temporal de OCI ≈ 0,06 USD; residual con RDS detenida ≈ 0,015–0,025 USD/h (tarifas públicas; no hay facturación en Academy).
13. **¿Qué mejorarían con más tiempo/crédito?** Respaldos programados con RPO medido, restauración del respaldo nuevo en una VM de OCI y una conmutación controlada real con punto de entrada público.
14. **¿Por qué no GCP/cuatro nubes?** No lo exige la rúbrica y no aporta a la protección de datos; se priorizó una integración AWS–OCI verificable.
15. **¿Qué construyeron para el failover y está en producción?** Componentes **locales y simulados**: un lease de escritor único con escrituras condicionales, una compuerta que rechaza escrituras sin lease (apagada por defecto), un cambio de DNS preparado y un orquestador simulado. Se probaron con simulaciones (400 escenarios sin doble escritor) y pruebas locales; **no están desplegados ni validados en AWS ni en OCI**.
16. **¿Pueden garantizar que nunca habrá dos escritores?** No. El diseño lo evita bajo supuestos (comparación atómica en el almacén, deriva de reloj acotada, pausas cortas) y falla cerrado, pero un sitio sin compuerta no se detiene (se detecta), y AWS y OCI no comparten base de datos.
17. **¿Qué falta para validarlo?** La autoprueba del almacén del lease en un bucket real, un cambio de DNS real en un subdominio de pruebas y un simulacro AWS→OCI con adaptadores reales (procedimientos preparados, sin ejecutar).

## 4. Frases a evitar
«RPO cero», «disponibilidad continua», «failover automático entre nubes», «producción multicloud», «probado en OCI» para lo que solo se probó en Docker, «cuatro nubes».

## 5. Lista de comprobación del día
Docker activo e imagen `postgres:18` presente · frase de paso de la clave de OCI a mano · terminal en la raíz del repositorio · informe 15 y diagramas abiertos · no iniciar el laboratorio de Academy salvo necesidad (puede reencender EC2) · plan B de la demo preparado.
