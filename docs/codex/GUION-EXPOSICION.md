# Guion de exposición (8–10 minutos)

## 1. Problema y arquitectura — 45 s

“NexoEventos evolucionó desde AWS V1 hacia una arquitectura multicloud: AWS opera, OCI recupera y Azure observa. No creamos una V3; reutilizamos controles y evidencias existentes.” Mostrar `ARQUITECTURA-T7.md`.

## 2. Evidencia T1–T5 — 2 min

- T1: lease OCI PASS 12/12, exclusividad y cero residuos.
- T2: DNS de prueba PASS 13/13, cambio y reversión en ~62 s.
- T3: recuperación OCI PASS 19/19; aclarar que es tiempo de reconstrucción, no RTO de failover.
- T4: observabilidad Azure PASS 18/18, alerta real y correo.
- T5: PASS 9/9 con seis instancias: 99,49 %, 9,6 s y 125 s.

Decir también: “Con dos instancias T5 dio 95,21 %. Conservamos ese FAIL; el PASS fue una ejecución con seis instancias, parada controlada y solo lectura.”

## 3. NexoOps y autenticación — 1 min

Mostrar login contraseña → OTP. Explicar Argon2id, OTP de un uso y sesión HttpOnly. Sin segundo factor, Overview responde 401. No mostrar credenciales ni OTP en la grabación.

## 4. Monitoreo integrado — 1 min 30 s

Mostrar Overview, Grafana y Zabbix. Señalar fuente, UTC y frescura. “No disponible” significa que la fuente no respondió; no se transforma en cero. OCI en espera es advertencia, no verde.

## 5. Operaciones seguras — 1 min

Mostrar lista blanca: estado, salud, ASG, alertas, barreras y evidencias. Crear una solicitud de intervención y enseñar que queda pendiente/bloqueada. Mostrar que failover y failback no se pueden ejecutar.

## 6. Diagnóstico — 45 s

Mostrar hechos, hipótesis y recomendaciones. Decir: “Es un motor determinista; no lo presentamos como IA generativa porque no hay un modelo conectado.”

## 7. Auditoría — 45 s

Mostrar actor, rol, UTC, operación y resultado; ejecutar verificación de cadena. Relacionar con el criterio T7 de registrar todo sin que el centro ejecute cambios.

## 8. Costos y cierre — 1 min

“Los expedientes estiman ~USD 0,50 para las ventanas T1–T5 citadas; no es una factura.” T6 está pendiente. T7 requiere su expediente final. T8 solo pasará tras inventario, revocaciones y copia cifrada verificada.

## Respuestas cortas a preguntas probables

- **¿Ya hicieron failover real?** No. T6 está pendiente; las barreras lo bloquean.
- **¿99,49 % es una garantía?** No. Es una medición de una ejecución con seis instancias.
- **¿NexoOps puede apagar recursos?** No. Solo consulta y registra solicitudes; las mutaciones están bloqueadas.
- **¿Los datos son simulados?** Las pruebas de código usan clientes simulados; T1–T5 citados provienen de expedientes cloud. Se distinguen explícitamente.
- **¿El costo fue USD 0,50?** Es una estimación de las ventanas documentadas, no consumo facturado.

