# Propuesta: dominio estable para V2 (6-nov-2026; SOLO investigación, nada comprado ni cambiado)

## Hechos comprobados
- DuckDNS solo ofrece registros A/AAAA (una IP por solicitud) y TXT; no documenta CNAME y no admite varias IP (spec oficial de DuckDNS).
- Las IP de un ALB pueden cambiar; la recomendación de AWS es usar su nombre DNS con un CNAME o un alias de Route 53 (TTL de 60 s).
- ACM valida con un registro CNAME (no TXT) que hay que poder crear en el DNS del dominio; el certificado público es gratuito y se renueva solo mientras el CNAME siga en su sitio y el certificado esté en uso (documentación de ACM).
- Route 53: zona alojada 0,50 USD/mes (sin prorrateo; si se borra en menos de 12 h no se cobra); consultas alias a un ALB gratuitas; el registro de dominios se cobra aparte. En AWS Academy, `route53domains:RegisterDomain` está denegado de forma explícita; `CreateHostedZone` y `acm:RequestCertificate` aparecen permitidos en la simulación de políticas (sin probar).
- La aplicación solo acepta peticiones con `Origin` listado en `FRONTEND_ORIGINS` (variable de entorno, separada por comas; backend/app/config.py). V2 la lee del secreto compartido `nexoeventos/academy/backend-env`. Acceder a V2 con otro nombre exige añadir ese origen (`https://nombre-nuevo`); con `/etc/hosts` no hizo falta porque el nombre es el mismo.
- V1 puede seguir en `nexoeventos-demo.duckdns.org` (su temporizador actualiza DuckDNS cada 5 min); V2 puede usar un nombre distinto sin afectarla.

## Opciones
| # | Opción | Costo | CNAME / ACM / HTTPS | Requisitos | Riesgos |
|---|---|---|---|---|---|
| 1 | Dominio propio barato + DNS gratuito (registrador o Cloudflare): CNAME `v2.<dominio>` → ALB; certificado ACM por DNS | dominio ≈ 1–12 USD/año (GitHub Student Pack: .me gratis el primer año, renovación ≈ 20 USD; a confirmar elegibilidad) ; DNS y ACM 0 | Sí / Sí (renovación automática) / Sí | comprar (tú), crear 2 CNAME, solicitar el certificado en ACM, añadir el origen a `FRONTEND_ORIGINS`, cambiar `certificate_arn` de V2 | compra y datos personales; el CNAME de validación debe permitir guion bajo (casi todos); el apex no admite CNAME (usar subdominio) |
| 2 | Dominio de otro registrador + Route 53 (zona alojada, alias al ALB, validación ACM con registros en Route 53) | +0,50 USD/mes | Sí / Sí / Sí; automatizable con Terraform | igual que 1 + crear la zona y delegar NS | Academy podría restringir Route 53 (no probado); coste fijo mensual |
| 3 | Subdominio gratuito de FreeDNS (afraid.org) | 0 | CNAME según foros: contradictorio (a veces exige permiso/cuenta premium); ACM sin confirmar | cuenta propia | dominios compartidos con mala reputación; sin delegación NS; fiabilidad desconocida |
| 4 | Segundo nombre de DuckDNS para V2 (registro A manual) | 0 | Sin CNAME; certificado Let's Encrypt por TXT importado a ACM (renovación manual cada ~90 días) | token DuckDNS, importar certificado | una sola IP del ALB que puede cambiar: se rompe sin aviso; no es estable |
| 5 | DuckDNS + IP fija con NLB y IP elásticas delante del ALB (o Global Accelerator) | ≈ 0,03–0,07 USD/h adicionales | Sí con el certificado importado | recursos nuevos en Terraform; permisos de Academy sin verificar | más complejidad y gasto; sigue sin certificado propio de ACM |
| 6 | `/etc/hosts` (lo que ya funciona) | 0 | Sí (mismo nombre y certificado) | solo tu Mac | no sirve para que otras personas vean V2 |

## Recomendación
Para la demostración: seguir con `/etc/hosts` en tu Mac (ya probado). Para una URL pública y estable: **opción 1** con un subdominio (`v2.` o `app.`), CNAME al nombre del ALB (que no cambia mientras el ALB exista) y certificado gratuito de ACM; no hace falta Route 53. V1 sigue en DuckDNS sin cambios.

## Secuencia futura (cada paso con autorización propia)
1. Tú: comprar o elegir el dominio y confirmar que el DNS permite CNAME con guion bajo.
2. AWS: solicitar el certificado ACM para `v2.<dominio>` (validación DNS) → tú creas los 2 CNAME → esperar `ISSUED`.
3. Secreto compartido: añadir `https://v2.<dominio>` a `FRONTEND_ORIGINS` (valor sensible: se edita sin imprimirlo).
4. Terraform de V2: cambiar `certificate_arn` (modificación en el listener 443; el envoltorio `v2-terraform.sh` hoy bloquea cualquier cambio distinto del ASG, por lo que se haría como paso aparte revisado).
5. Encender V2, probar con `curl --resolve` y con el navegador, y reversión: volver al certificado anterior.
