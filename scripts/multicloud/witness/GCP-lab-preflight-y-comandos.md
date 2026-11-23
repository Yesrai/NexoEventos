# GCP lab — preflight (solo lectura) y comandos PREPARADOS, NO EJECUTADOS

## A. Estado verificado (solo lectura local, fecha 2026-11-20)
- `gcloud`: NO instalado (ni en PATH, ni en ~/google-cloud-sdk, ni Homebrew). Sin `~/.config/gcloud`, sin credenciales ADC, sin variables `GOOGLE_*`/`CLOUDSDK_*`, sin librería `google.auth` en python3.
- Por tanto: **no hay acceso real a Google Cloud desde esta máquina**; proyectos accesibles, cuentas de facturación, cuotas y permisos NO se han podido consultar (no se inventan). Requiere intervención humana: instalar el SDK y `gcloud auth login` (sesión de la persona, no de Claude).
- Nada creado, nada habilitado.

## B. Comprobaciones de solo lectura a ejecutar cuando exista sesión (no modifican nada)
```bash
gcloud auth list --format="value(account,status)"
gcloud projects list --format="value(projectId,name,lifecycleState)"
gcloud billing accounts list --format="value(name,displayName,open)"          # requiere billing.accounts.list
gcloud organizations list; gcloud resource-manager folders list --organization=ORG_ID
gcloud billing accounts get-iam-policy BILLING_ID --format=json | grep -c '"role"'   # permiso billing.user para vincular
gcloud services list --available --filter="name:(run.googleapis.com cloudkms.googleapis.com storage.googleapis.com artifactregistry.googleapis.com iam.googleapis.com cloudbilling.googleapis.com serviceusage.googleapis.com)" --project=PROYECTO_EXISTENTE
gcloud kms locations list | grep -E "us-central1|us-east1|europe-west1"      # HSM disponible en la región
gcloud run regions list 2>/dev/null || gcloud run domain-mappings list --region us-central1 >/dev/null
gcloud alpha services quota list --service=cloudkms.googleapis.com --consumer=projects/PROYECTO --format=json   # solo lectura
```
Permisos humanos necesarios: `resourcemanager.projects.create` (Project Creator en org/carpeta), `billing.resourceAssociations.create` (Billing Account User), y en el proyecto nuevo `owner` temporal. Si la organización tiene políticas (p. ej. `iam.allowedPolicyMemberDomains`, `run.requireInvokerIam`), pueden bloquear pasos: se detectan en el preflight del proyecto.

## C. Precios consultados (documentación pública, a reconfirmar en la consola; algunos fragmentos ambiguos)
- KMS HSM, versión de clave ECDSA: ≈0,0034 USD/h (~2,5 USD/mes) → 8 h ≈ 0,03 USD. Operaciones: 0,03–0,15 USD por 10 000 (la fuente es ambigua; se toma el peor caso 0,15).
- Cloud Run: capa gratuita mensual (2 M peticiones, 180 000 vCPU-s, 360 000 GiB-s por solicitud); con min-instances=0 el lab cae dentro.
- Artifact Registry: 0,5 GiB gratis; luego ≈0,10 USD/GiB-mes (imagen ≈ 0,15 GiB).
- Cloud Storage: céntimos para <1 MB y miles de operaciones; no se pudo confirmar la tarifa exacta, es despreciable.
- **Estimación conservadora (8 h, 5 000 firmas, tráfico del lab):** KMS 0,03 + 0,08 (ops, peor caso) + Run 0 + AR 0 + GCS < 0,05 + margen de error ×5 → **≈ 1 USD; techo operativo 5 USD**. Riesgos de coste: olvidar la clave HSM activa (~2,5 USD/mes), bucle de peticiones (Run con `max-instances` alto), egress. Reconfirmar con la calculadora antes de ejecutar.

## D. Control REAL del gasto (las alertas de presupuesto NO son un límite)
Las alertas llegan con horas de retraso y no detienen nada. Controles propuestos, de menor a mayor dureza:
1. **Topes estructurales en el diseño:** `--max-instances=1`, `--min-instances=0`, `--concurrency=8`, `--timeout=10s`; una sola clave KMS y una sola versión; sin otros servicios; región única.
2. **Cuotas de proyecto** reducidas (Service Usage consumer quota override) para KMS (peticiones criptográficas/min) y Cloud Run (instancias).
3. **Reloj del operador:** `cleanup.sh` ejecutado a mano a las 8 h máx., y `ttl` en etiqueta; el operador marca la hora en el calendario. (Un scheduler automático añadiría recursos; no se usa.)
4. **Presupuesto 5 USD con Pub/Sub → función que desvincula la facturación** (patrón documentado "disable billing with notifications"): detiene todo el proyecto, pero es **retardado y a-menos-una-vez**, no un tope exacto, y la función es un recurso extra: se usa solo si el humano lo acepta; si no, solo alertas.
5. **Parada manual inmediata:** `gcloud billing projects unlink PROYECTO` (detiene todos los servicios del proyecto) y `gcloud projects delete`.
Conclusión honesta: el coste máximo real queda acotado por los topes estructurales (1–2), no por el presupuesto.

## E. Retención de 1 día y limpieza inmediata
- Con retención de **bucket sin bloquear**, los objetos no se pueden borrar hasta cumplir la retención; sí se puede **reducir o eliminar la política** (solo mientras no esté bloqueada) y entonces borrar. Con **Object Retention Lock en modo unlocked**, borrar/acortar exige `--override-unlocked-retention`. Con retención **bloqueada** sería irreversible: PROHIBIDO en el lab.
- Esto sí dificulta la limpieza "inmediata" si no se prepara: por eso la prueba previa y el orden: quitar política → borrar objetos → borrar bucket. Alternativa sin retención en el lab (el cumplimiento WORM se valida en un bucket separado y desechable).
- **Prueba de limpieza (en el proyecto temporal, antes de cargar datos del testigo):** crear `lab-canary-bucket` con la misma política, subir un objeto, ejecutar el procedimiento de limpieza completo, verificar listados vacíos. Si falla, no se continúa.

## F. El servicio no expone /report ni /attest de forma anónima
Dos capas, ya probadas en local (401 anónimo, 403 sin alcance, 409 firma no autorizada): Bearer propio con alcances. En Cloud Run se añade `--no-allow-unauthenticated` (IAM `run.invoker` por identidad) y se verifica tras desplegar: `curl -s -o /dev/null -w '%{http_code}' $URL/attest?nonce=...` sin cabecera → 401/403; `getIamPolicy` del servicio sin `allUsers`/`allAuthenticatedUsers`. `/healthz` solo devuelve `{"ok":true}`.

## G. Comandos concretos (NO ejecutar sin autorización; variables a rellenar por el humano)
```bash
export P=nexo-witness-lab-$(date +%y%m%d%H) R=us-central1 BILLING=XXXXXX-XXXXXX-XXXXXX
export SA=witness-sa BUCKET=$P-log KR=witness-ring KEY=witness-sign REPO=witness
# --- crear ---
gcloud projects create $P --labels=ttl=$(date -v+1d +%Y%m%d),purpose=witness-lab
gcloud billing projects link $P --billing-account=$BILLING
gcloud billing budgets create --billing-account=$BILLING --display-name=$P --budget-amount=5USD --filter-projects=projects/$P --threshold-rule=percent=0.5 --threshold-rule=percent=0.9
gcloud services enable run.googleapis.com cloudkms.googleapis.com storage.googleapis.com artifactregistry.googleapis.com iam.googleapis.com --project=$P
gcloud iam service-accounts create $SA --project=$P
gcloud storage buckets create gs://$BUCKET --project=$P --location=$R --uniform-bucket-level-access --public-access-prevention --default-storage-class=STANDARD
gcloud storage buckets update gs://$BUCKET --retention-period=1d          # SIN lock
gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member=serviceAccount:$SA@$P.iam.gserviceaccount.com --role=roles/storage.objectCreator
gcloud storage buckets add-iam-policy-binding gs://$BUCKET --member=serviceAccount:$SA@$P.iam.gserviceaccount.com --role=roles/storage.objectViewer
gcloud kms keyrings create $KR --location=$R --project=$P
gcloud kms keys create $KEY --keyring=$KR --location=$R --project=$P --purpose=asymmetric-signing --default-algorithm=ec-sign-p256-sha256 --protection-level=hsm
gcloud kms keys add-iam-policy-binding $KEY --keyring=$KR --location=$R --project=$P --member=serviceAccount:$SA@$P.iam.gserviceaccount.com --role=roles/cloudkms.signerVerifier
gcloud artifacts repositories create $REPO --repository-format=docker --location=$R --project=$P
# imagen (contexto = layout del repo, ver test_witness_hardening.py::imagen) y despliegue
gcloud auth configure-docker $R-docker.pkg.dev
docker build -t $R-docker.pkg.dev/$P/$REPO/witness:1 CONTEXTO && docker push $R-docker.pkg.dev/$P/$REPO/witness:1
gcloud run deploy witness --project=$P --region=$R --image=$R-docker.pkg.dev/$P/$REPO/witness:1 --service-account=$SA@$P.iam.gserviceaccount.com \
  --no-allow-unauthenticated --min-instances=0 --max-instances=1 --concurrency=8 --timeout=10s \
  --set-env-vars=WITNESS_STORE=gcs:$BUCKET,WITNESS_SIGNER=kms:projects/$P/locations/$R/keyRings/$KR/cryptoKeys/$KEY/cryptoKeyVersions/1,WITNESS_REPORTERS_FILE=...,WITNESS_INVOKER_TOKENS_FILE=...
# --- probar ---
gcloud run services get-iam-policy witness --region=$R --project=$P | grep -E "allUsers|allAuthenticatedUsers" && echo FALLO
curl -s -o /dev/null -w '%{http_code}\n' "$URL/attest?nonce=$(openssl rand -hex 16)"          # esperado 401/403
# + atestación con token, génesis firmado, 2 informes simultáneos, reinicio de revisión, borrado/sobrescritura desde la SA -> debe fallar
# --- limpiar (orden) ---
gcloud run services delete witness --region=$R --project=$P --quiet
gcloud storage buckets update gs://$BUCKET --clear-retention-period
gcloud storage rm -r gs://$BUCKET                      # añadir --override-unlocked-retention si se usó Object Retention
gcloud kms keys versions destroy 1 --key=$KEY --keyring=$KR --location=$R --project=$P
gcloud artifacts repositories delete $REPO --location=$R --project=$P --quiet
gcloud iam service-accounts delete $SA@$P.iam.gserviceaccount.com --project=$P --quiet
gcloud billing projects unlink $P && gcloud projects delete $P --quiet
# verificar vacío
gcloud projects describe $P --format="value(lifecycleState)"   # DELETE_REQUESTED
```
Nota: las claves KMS destruidas pasan 24 h programadas y el proyecto 30 días en papelera; la clave deja de facturarse al destruir la versión. Los nombres de variables de entorno del servicio (`WITNESS_STORE=gcs:`, `kms:`) coinciden con `build_from_env`; los tokens/claves se montan como archivos 0600 (nunca en la línea de comandos).

## H. Evidencia para marcar el primer testigo como validado (y no más)
Capturas/saneadas en `docs/evidencias/`: (1) listados de IAM del bucket, la clave y el servicio sin `allUsers`/owner/editor para la SA; (2) anónimo→401/403 contra Cloud Run real; (3) 2 informes simultáneos contra `GcsAppendStore` real sin pérdida (conteo de objetos = informes aceptados + génesis); (4) intento de sobrescribir/borrar un objeto desde la SA → denegado; (5) firma KMS HSM P-256 verificada con la clave pública fijada; (6) reinicio/nueva revisión y recuperación de la cadena; (7) coste final del proyecto y limpieza verificada (listados vacíos). Aun así: `independent_infrastructure_validated` seguirá false hasta el segundo testigo.
**Pendiente del segundo testigo independiente (Azure u otro dominio):** mismo conjunto de evidencias en su propio dominio de confianza, cuórum 2/2 real extremo a extremo, caída de un testigo bloquea promoción, retroceso de uno detectado por el otro, clave de firma y administradores distintos. `validated_antirollback` y `automatic` solo cambian con esa evidencia y autorización explícita.
