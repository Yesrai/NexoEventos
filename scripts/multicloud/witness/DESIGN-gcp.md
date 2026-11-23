# Testigo de frescura en Google Cloud — diseño, límites y primera prueba (NADA creado todavía)

## Qué es y qué NO es
Referencia independiente que solo avanza. Protege contra el **rollback simultáneo** (lease + sello + base de AWS restaurados a un estado antiguo, coherente y firmado). **No** protege contra: un administrador de Google Cloud
comprometido con permisos de borrado sobre el bucket sin retención bloqueada; un atacante que retroceda **todos** los testigos a la vez; ni contra la compromisión de la clave de firma del testigo.

## Arquitectura (proyecto de Google Cloud PROPIO, separado de AWS y OCI)
| Pieza | Elección | Por qué / restricción verificada en la documentación |
|---|---|---|
| Servicio | Cloud Run (1 servicio, `min-instances=0`, ingreso HTTPS con IAM de invocador **o** URL pública con firma de cada respuesta) | escala a cero; el servicio no guarda estado; las respuestas están **firmadas**, así que no depende del canal |
| Historial | Cloud Storage, bucket **dedicado**, **retención** (política de retención del bucket) y creación con `ifGenerationMatch=0` | un objeto por informe (`log/<seq>`): jamás se sobrescribe. **Bloquear** la política de retención es IRREVERSIBLE (no se puede quitar ni acortar; el bucket solo se borra cuando todos los objetos cumplieron la retención). Para el laboratorio: política SIN bloquear |
| Firma | Cloud KMS, clave asimétrica **ECDSA P-256/SHA-256 con nivel HSM** | Ed25519 en KMS solo existe con nivel SOFTWARE; con HSM se firma con P-256/P-384. El verificador del cliente (`EcdsaP256Verifier`) ya lo soporta. La clave no es exportable; solo la cuenta de servicio del servicio puede firmar |
| Quórum | ≥ 2 testigos en **dominios distintos** (p. ej. Google Cloud + otro proyecto/nube) y `quorum_k = 2` | con un solo testigo, restaurar su almacén a un prefijo válido retrocede a un consumidor nuevo; con k=2 el atacante debe retroceder los dos |

## Identidades (ninguna comparte privilegios con las de AWS/OCI)
- `witness-runtime@…` (cuenta de servicio del Cloud Run): `roles/cloudkms.signerVerifier` **solo sobre la clave**, `roles/storage.objectCreator` + `roles/storage.objectViewer` **solo sobre el bucket del historial**. Sin `delete`, sin `update` de objetos, sin permisos de proyecto.
- `witness-admin` (personas, MFA, cuenta distinta de las de AWS/OCI): administra el proyecto, la retención y la clave; **nunca** la usa un servicio y no puede firmar.
- Informantes (OCI, titulares del lease, operador): no tienen credenciales de Google; firman sus informes con sus propias claves Ed25519 (el servicio solo conoce las **públicas**).
- Consumidores (AWS): solo leen la atestación; anclan la **clave pública** del testigo en su configuración.

## Detección
- **Restauración de historial:** consumidores con `WitnessMemory` (cantidad de informes y cabeza vistas) lo delatan; el quórum usa el máximo; los informantes comprueban sus **recibos** (`entry(seq)`) y alertan si su informe ya no está.
- **Falsificación de respuestas:** firma del testigo anclada + reto (nonce) propio + fecha reciente.
- **Pérdida del testigo:** servicio sin inicializar ⇒ todo se bloquea; recuperación solo con una génesis del operador a la altura **verificada fuera de banda**; los nodos con memoria rechazan una génesis más baja.
- **Compromiso de credenciales:** alertas sobre los registros de auditoría (llamadas de `Sign` de KMS fuera de la cuenta del servicio; cualquier `storage.objects.delete/update`; cambios de IAM o de retención); un informante comprometido solo puede AVANZAR, y el salto de época está acotado y las cabezas del sello se verifican contra el registro real.

## Si Google Cloud falla
Nuevas adquisiciones y **promociones se bloquean** (falla cerrado; sellar exige que el testigo registre la cabeza). El titular ya activo puede renovar la MISMA época durante una gracia acotada (`renew_grace_s`); pasada la gracia también se bloquea. Nunca hay doble escritura: nadie adquiere sin testigo.

## Costos estimados (a verificar con la página oficial; son órdenes de magnitud)
Cloud KMS: clave con nivel HSM ≈ 1–2,5 USD por versión activa al mes + ≈ 0,03 USD por 10 000 firmas; Cloud Run: cubierto por el nivel gratuito a este volumen (se factura por uso y las solicitudes rechazadas por IAM no se cobran);
Cloud Storage: centavos (objetos de bytes). Total del laboratorio ≈ 1–3 USD/mes si la clave HSM se deja activa; con una clave SOFTWARE de prueba y destruyéndola, ≈ 0.

## Primera prueba real pequeña y reversible (requiere autorización específica; NO ejecutada)
Proyecto temporal `nexo-witness-lab-*`, facturación con **presupuesto de 5 USD y alerta al 50 %**, APIs: Cloud Run, Cloud KMS, Cloud Storage, IAM. Recursos: 1 bucket (retención SIN bloquear, 1 día), 1 llavero + 1 clave **ECDSA P-256 HSM**
(o SOFTWARE para el primer ensayo), 2 cuentas de servicio (runtime y un informante de prueba sin permisos extra), 1 servicio Cloud Run. Pruebas: arranque, génesis, informes, atestación firmada verificada con el cliente local, reinicio del servicio (el estado vuelve del bucket),
intento de sobrescribir/borrar con la cuenta del servicio (debe fallar), intento de firmar con una cuenta ajena (debe fallar), caída (servicio detenido ⇒ el guardián bloquea). Limpieza: borrar servicio, objetos (tras la retención, o el proyecto entero), destruir la versión de la clave, borrar cuentas y **cerrar el proyecto**.
