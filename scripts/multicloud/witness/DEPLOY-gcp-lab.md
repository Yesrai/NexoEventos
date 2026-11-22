# Laboratorio GCP del testigo — procedimiento PREPARADO, NO EJECUTADO

Estado: nada de esto se ha ejecutado. No hay proyecto, facturación, APIs, claves, buckets ni IAM creados. `independent_infrastructure_validated=false`, `validated_antirollback=false`, `automatic=false` se mantienen.

## 1. Recursos exactos del primer laboratorio (proyecto temporal `nexo-witness-lab-<fecha>`)
| Recurso | Configuración | Identidad con acceso |
|---|---|---|
| Proyecto | uno nuevo, solo para el lab, con etiqueta `ttl=<fecha>` | admin humano (separado de las SA) |
| Facturación | cuenta de laboratorio con **presupuesto 5 USD**, alertas 50/90/100 % | — |
| APIs | solo `run`, `cloudkms`, `storage`, `artifactregistry`, `iam` | — |
| Bucket GCS (región única, uniform access, public access prevention) | **sin versionado de borrado manual; Object Retention en modo *unlocked* (1 día)**; NUNCA bucket lock/retención bloqueada en el lab | SA del testigo: `roles/storage.objectCreator` + `objectViewer` **solo en este bucket** (sin `objectAdmin`, sin delete/overwrite) |
| Clave KMS (anillo + clave ECDSA P-256 **HSM**, `ASYMMETRIC_SIGN`) | no exportable | SA del testigo: `roles/cloudkms.signerVerifier` **solo en esta clave**; `publicKeyViewer` para publicar la clave pública |
| Artifact Registry (1 repo Docker) | imagen construida desde `Dockerfile` | build: `artifactregistry.writer` (humano) |
| Cloud Run (1 servicio, min instances 0, max 2, ingress all + **sin `allUsers`**) | `WITNESS_STORE=gcs:…`, `WITNESS_SIGNER=kms:…`, `WITNESS_REPORTERS_FILE`, `WITNESS_INVOKER_TOKENS_FILE` desde Secret Manager (opcional) o montaje | `roles/run.invoker` solo a las SA de los consumidores (ID token) además del token Bearer del servicio |
| SA del testigo | única con acceso a KMS+bucket; sin claves JSON (identidad del servicio) | — |
| Informantes (AWS/OCI) | **sin credenciales Google**; firman con sus propias claves Ed25519 (`~/.nexoeventos/hybrid-lease-keys`), distintas de la clave KMS (el servicio lo exige: `assert_key_separation`) | solo token Bearer con alcance `report` |

## 2. Despliegue (resumen, no ejecutar sin autorización)
1. Crear proyecto, vincular facturación con presupuesto y alertas **antes** de habilitar APIs.
2. Habilitar APIs; crear SA, bucket (retención unlocked), clave KMS HSM; conceder roles mínimos; comprobar con `get-iam-policy` que no hay `owner/editor` ni `allUsers`.
3. `docker build` (contexto = layout del repo, ver `test_witness_hardening.py::imagen`), push, `gcloud run deploy` con la SA.
4. Prueba de humo: anónimo→401/403; atestación con token; informe génesis firmado por el operador; reinicio (nueva revisión) y recuperación; borrado/sobrescritura desde la SA → **debe fallar**.
5. Pruebas contra GCP real pendientes: ver §5.

## 3. Limpieza (orden)
1. Eliminar el servicio Cloud Run. 2. Eliminar objetos (retención unlocked: reducir retención y borrar) y el bucket. 3. Destruir versiones de la clave KMS (queda programada 24 h; el anillo no se borra). 4. Eliminar SA y repositorio. 5. Eliminar el proyecto (`gcloud projects delete`, 30 días en papelera) y desvincular facturación. 6. Verificar con listados que no quedan recursos y que el coste es 0.

## 4. Gasto máximo y condiciones de parada
- Estimación: Cloud Run con escala a cero ≈ 0 USD; GCS < 0,01 USD; KMS HSM ≈ 1–2,5 USD/mes por versión de clave activa (proporcional si se destruye el mismo día: < 1 USD); Artifact Registry ≈ 0. **Tope: 5 USD**; esperado < 1 USD en 1 día.
- Parar y limpiar si: alerta de presupuesto ≥ 50 %; cambio inesperado de IAM/retención; recurso no listado; error de identidad/proyecto; la limpieza falla; > 8 h de laboratorio; cualquier 5xx sin explicar.

## 5. Qué solo se puede comprobar contra GCP real
`ifGenerationMatch=0` en `GcsAppendStore` bajo concurrencia; consistencia del listado; denegación de sobrescritura/borrado con retención; firma KMS HSM P-256 (formato DER) y `GcpKmsSigner`; ID tokens de Cloud Run / invoker; arranque en frío y latencia frente al plazo del guardián; cuotas de KMS; alertas de presupuesto. Los adaptadores `GcsAppendStore` y `GcpKmsSigner` no están validados.

## 6. Segundo dominio independiente (recomendación)
Un único testigo, aunque inmutable, no impide que un atacante con control de ese dominio retroceda el estado a un prefijo válido: se necesitan **≥2 testigos en dominios distintos con cuórum 2/2**. AWS es el primario vallado y OCI aloja el sello, por lo que el segundo debe ser **Azure** (Blob Storage inmutable con retención por tiempo/legal hold + Key Vault Managed HSM o clave HSM ECDSA P-256), con suscripción, facturación, administradores/MFA y alertas separados de GCP. Garantías mínimas: almacén solo-añadir con creación condicional atómica (`If-None-Match: *`), borrado/sobrescritura denegados a la identidad del servicio, clave de firma no exportable y distinta de las de los informantes, clave pública fijada en los consumidores, región/zona de fallo distinta, sin credenciales compartidas con GCP, monitorización independiente. Alternativa de menor independencia: otra cuenta AWS con S3 Object Lock (compliance) + KMS, descartable si comparte administración con el primario.

## 7. Garantía de no perder actualizaciones simultáneas
El almacén real **debe** ofrecer «crear si no existe» atómico por número de secuencia (GCS `ifGenerationMatch=0`; Azure `If-None-Match:*`; archivo con flock). El testigo reintenta tras `PreconditionFailed`, relee la cadena y vuelve a validar (marca de agua monótona). Sin esa operación, dos instancias pueden aceptar dos informes y perder uno (control negativo en `test_requisito_del_almacen_...`). Requisito para escalado: instancias compartiendo el mismo almacén; o `max instances=1`.
