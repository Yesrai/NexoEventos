# NexoEventos — Estado del proyecto

Auditoría y continuación realizadas el **14 de octubre de 2026** sobre el commit `13164c7` y posteriores (`8114ad1`, trabajo sin confirmar de la sesión anterior). Todo lo marcado «Verificado» se ejecutó en esta sesión sobre el código local; lo que depende de AWS se cita de la documentación existente con su fecha y **no se volvió a consultar hoy**.

Convención: **Verificado hoy** = comando o prueba ejecutada con el resultado indicado · **No verificado** = no se pudo o no se debía ejecutar · **Documentado** = tomado de `docs/` con fecha anterior.

## 1. Línea base encontrada

| Comprobación | Resultado (14-oct, antes de modificar) |
|---|---|
| Git | HEAD `8114ad1`; cambios sin confirmar en `App.tsx`, `styles.css`, `docs/recintos-y-planos.md` y archivos nuevos `Venue3D.tsx`, capturas y script. Se confirmaron en `0aa87e8` para no perderlos. |
| Backend | 22 pruebas aprobadas |
| Frontend | 16 pruebas aprobadas; `tsc -b` y `vite build` correctos |
| Terraform | `fmt -check` correcto; `validate` correcto en `infra/aws`, `infra/azure`, `infra/gcp`, `infra/aws-recovery` |
| Problema visual | Los cuatro recintos 3D seguían siendo maquetas: auditorio como caja con muros que tapaban la sala, concierto como losa plana, museo sin techo y estadio sobre suelo blanco. |

## 2. Matriz de funcionalidades

| Funcionalidad | Estado | Problema identificado | Corrección | Prueba de aceptación | Resultado verificado |
|---|---|---|---|---|---|
| Autenticación, sesiones, cierre de sesión, límite de intentos | Funciona | Ninguno | — | `test_logout_invalidates_server_session`, `test_login_attempts_are_limited…`, `test_duplicate_registration…` | Aprobadas |
| Permisos por rol (cliente/organizador/operador) | Funciona | Ninguno | — | `test_private_routes_reject_unauthenticated_access`, `test_public_registration_cannot_assign_privileged_role`, `test_client_cannot_read_another_clients_ticket` | Aprobadas |
| Catálogo y detalle de eventos | Funciona | Ninguno | — | `test_health_and_catalog_come_from_postgresql`; pruebas de filtros en `App.test.tsx` | Aprobadas |
| Reservas transaccionales y control de aforo | Funciona | La concurrencia solo se probaba con 2 clientes | Prueba nueva con **12 clientes simultáneos sobre 4 cupos** | `test_twelve_concurrent_clients_never_oversell_a_four_seat_zone` | 4 × 201, 8 × 409; 4 entradas y `reserved_count = 4` en BD |
| Idempotencia | Funciona | Ninguno | — | `test_idempotency_replay_conflicts_and_is_scoped_to_owner` | Aprobada |
| Precios y disponibilidad validados en backend | Funciona | Faltaban casos de borde | Pruebas nuevas: asiento de otra función, cantidad inconsistente, zona agotada, cantidad mayor a la disponible | `test_seat_from_another_function…`, `test_inconsistent_quantity_and_sold_out_zone…` | Aprobadas; sin reservas parciales |
| Entradas digitales con QR | Funciona | Ninguno | — | `test_numbered_seat_is_visible_on_the_owners_ticket`, prueba de diálogo privado en frontend | Aprobadas |
| Validación de ingreso / doble ingreso | Funciona | Ninguno | — | `test_two_simultaneous_validations_accept_exactly_once`, `test_invalid_and_reused_qr_are_controlled` | Aprobadas |
| Cámara física para leer QR | Implementado, **no probado** | Sin dispositivo de cámara en esta sesión | — | Lectura por código manual sí probada | No verificado (cámara) |
| **Panel del organizador** | **Incompleto** | Solo mostraba una lista de lectura: sin estadísticas ni edición, aunque existía `PATCH` | Nuevo `GET /api/organizer/events/{id}/stats` y panel con indicadores, tabla por zona y formulario de edición | `test_organizer_stats_reflect_sales_entries_and_are_scoped_to_owner`; prueba de UI del organizador con axe | Aprobadas |
| **Edición de eventos por el organizador** | **Defecto de integridad** | `PATCH` permitía cambiar aforo/precio de eventos con zonas o asientos (desincroniza el inventario) y renombrar el recinto de un plano vinculado | Rechazo `409` en esos casos; la UI deshabilita los campos con explicación | `test_organizer_cannot_desync_zone_pricing_or_linked_venue`, `test_organizer_cannot_lower_capacity_below_reservations` | Aprobadas |
| **Gestión de eventos, funciones, recintos y planos por el organizador** | **Implementado (14-oct, 2.ª fase)** | Antes solo por *seed* | `app/organizer.py`, `app/inventory.py`, migración `0007`, `Organizer.tsx` (ver §7) | `tests/test_organizer_management.py` (5) + E2E en navegador (16 verificaciones) | Aprobadas |
| Selección de localidades 2D | Funciona | Ninguno | — | `App.test.tsx` (asiento numerado, estadio, auditorio, accesibilidad axe) | Aprobadas (18/18) |
| **Reconstrucción de recintos 3D** | Mejorado | Maquetas (ver §1). Además, `seats=[]`/`zones=[]` por defecto reconstruían toda la escena en cada render | Nuevos ambientes procedurales; valores por defecto estables | Capturas reales y clics reales (ver §3) | Verificado hoy |
| Selección 3D ↔ estado de reserva | Funciona | — | — | Clic real sobre el canvas con Chrome headless | Auditorio → asiento **B-4**; Concierto → zona **Preferencial**; Estadio → **Tribuna Occidente F-5**, total S/ 65.00 |
| Alternativa accesible cuando WebGL falla | Funciona | Sin prueba | Prueba nueva | `keeps the accessible 2D plan and selection when WebGL is unavailable…` | Aprobada |
| Interfaz móvil | Mejorada | En vertical los recintos se recortaban y los controles tapaban la escena | Campo de visión y distancia adaptativos, vistas en una fila, pista oculta en pantallas pequeñas | Capturas 390×844 | Verificado hoy |
| Accesibilidad | Parcial | `axe` en jsdom **no evalúa contraste** (sin motor de layout) | — | Pruebas axe de catálogo, selección y panel del organizador | Aprobadas; contraste **no verificado** automáticamente |
| Build de producción | Funciona | — | — | `npm run build` | Correcto; Three.js sigue en *chunks* de carga diferida (índice 109 kB gzip) |
| Seguridad del repositorio | Correcto | — | — | Búsqueda de secretos versionados; `npm audit --omit=dev` | Sin secretos; 0 vulnerabilidades. `pip-audit` **no instalado**: dependencias Python sin auditar |

## 3. Recintos 3D (evidencia real)

Capturas en [`docs/evidencias/ui/recintos-3d/`](docs/evidencias/ui/recintos-3d/), generadas con [`scripts/capture-venues.mjs`](scripts/capture-venues.mjs) (Chrome headless, WebGL por software, escritorio 1440×1000 y móvil 390×844). Cada recinto se construye de forma procedural; no se usan modelos, texturas ni imágenes de terceros.

| Recinto | Contenido | Vistas de cámara |
|---|---|---|
| Auditorio Nexo | Sala cerrada con techo artesonado, paneles de madera, proscenio dorado, telón con pliegues, escenario con barras de luz, platea escalonada con butacas instanciadas, luces de pasillo, puertas y señal de salida | Desde la sala · Platea · Vista general |
| Arena Parque Sur (concierto) | Noche con horizonte urbano; escenario con truss, tres pantallas LED, línea de PA, monitores, batería y amplificadores; foso con vallas, torre de sonido, carpas, torres de luz y acceso. Zonas luminosas con profundidad proporcional al aforo; la de mayor precio queda junto al escenario | Desde la entrada · Zonas · Frente al escenario · Lateral |
| Museo de la Ciudad | Vestíbulo y tres salas con pisos distintos, claraboyas, pinturas, esculturas en pedestales con cordones, vitrinas, instalación suspendida, proyección y recorrido señalizado. Los muros exteriores se dibujan solo hacia adentro (corte arquitectónico) | General · Ingreso · Sala 1 · Sala 2 · Sala 3 |
| Estadio Nexo | Cancha, tribunas con inventario real, cubiertas y torres (ya existentes) + entorno nuevo: cielo, fachada con columnas y portales, avenida, estacionamiento con vehículos, bloques de escaleras en las esquinas y horizonte | Enfoque por tribuna (existente) |

Reglas que se mantienen: el inventario vendible proviene **solo** del backend (los asientos/zonas del evento); el decorado no crea localidades; los museos reservan por horario y cantidad, no por sala; los eventos generales conservan el selector de cantidad y no cargan Three.js.

**Rendimiento medido** ([`rendimiento-2026-10-14.json`](docs/evidencias/ui/recintos-3d/rendimiento-2026-10-14.json); contadores de `renderer.info` en modo desarrollo):

| Recinto | Escritorio: llamadas / triángulos | Móvil: llamadas / triángulos |
|---|---|---|
| Auditorio | 128 / 7 200 | 106 / 6 824 |
| Concierto | 279 / 8 210 | 250 / 6 182 |
| Museo | 226 / 17 780 | 184 / 12 352 |

Limitaciones: el tiempo de construcción (≈2.1–3.1 s) se midió con **render por software (SwiftShader)** e incluye compilación de *shaders*; **no representa los FPS de una GPU real**, que no se midieron. Las sombras se desactivan en móvil y en el concierto.

## 4. Pruebas ejecutadas hoy

| Suite | Resultado |
|---|---|
| Backend (`pytest`, PostgreSQL 14 local, base `nexoeventos_test`) | **33 aprobadas** (corridas repetidas sin interferencia entre ellas) |
| Frontend (`vitest`, incluye axe) | **20 aprobadas** |
| `tsc -b` + `vite build` | Correcto |
| `terraform fmt -check` y `terraform validate` (4 módulos) | Correcto |
| Clics reales en 3D (auditorio, concierto, estadio) | 3 de 3 selecciones correctas |
| `scripts/check-local.sh` completo | Correcto |

No ejecutado: pruebas con cámara física, FPS en GPU real, contraste automático, `pip-audit`, restauración de respaldo local (existe `scripts/test-restore-local.sh`; no se corrió para no tocar datos).

## 5. Infraestructura Cloud

> **No se ejecutó `terraform apply`, `destroy` ni ninguna operación que cree recursos facturables. No se usaron credenciales de AWS ni de Azure en esta sesión.** Los saldos de crédito no se asumen vigentes.

| Capa | Arquitectura propuesta | Implementado (código en el repositorio) | Verificado en la nube |
|---|---|---|---|
| AWS V1 (`infra/aws`) | VPC, subred pública y dos privadas, EC2 `t3.small`, RDS PostgreSQL privada, S3 privado, CloudWatch | Terraform (30 recursos según `docs/estado-proyecto.md`), Ansible, Nginx/systemd, HTTPS con Let's Encrypt, scripts de respaldo y recuperación | **Documentado** al 12-oct: desplegado, HTTPS probado, carga y restauración medidas; EC2 y RDS **detenidas**. **No reverificado hoy.** |
| Cambios locales sin aplicar | AMI fija, autoescalado RDS, prefijo S3 | Corregidos localmente; `validate` correcto hoy | Sin plan autenticado (el *refresh* falla por una SCP del laboratorio); **sin aplicar** |
| AWS V2 (ALB + 2 EC2, `docs/arquitectura-v2.md`) | Balanceo y redundancia | Solo diseño | No implementado ni desplegado |
| Azure (`infra/azure`) | Continuidad | Solo `versions.tf` (sin recursos) | No implementado |
| GCP (`infra/gcp`) | Analítica | Solo `versions.tf` | No implementado |
| Frontend/API actuales (3D, panel del organizador) | — | Código local | **No desplegado**: el sitio público sigue en la versión del 7-oct |

Puntos únicos de falla declarados en la documentación: una EC2 y una RDS Single-AZ; no hay ALB, Multi-AZ ni NAT.

**Decisiones que requieren tu aprobación** (no tomadas):
1. Autorizar una ventana cloud para desplegar esta versión (Ansible + migraciones; el backend nuevo **no requiere migración**) con costo estimado según `docs/costos-v1.md` y renovar credenciales del laboratorio.
2. Decidir si se despliega la V2 (ALB + 2 EC2) y/o se implementa Azure; hoy no hay presupuesto verificado.
3. Aprobar o rechazar el cambio de Terraform pendiente cuando exista un plan autenticado.

## 6. Pendientes reales

1. ~~Gestión desde la interfaz del organizador~~ — **resuelto**, ver §7. Quedan fuera de alcance (justificado) la creación de recintos nuevos y la subida de imágenes.
2. Despliegue de esta versión y verificación pública (requiere aprobación y credenciales).
3. Capturas de consola EV02–EV04/EV06–EV08 y de la barra de direcciones con HTTPS/fecha (ver `docs/estado-proyecto.md`).
4. Recuperación completa del servicio hasta HTTPS (RTO completo sin medir).
5. Medición de FPS en GPU real y en un teléfono físico.
6. Contraste de color verificado con herramienta de navegador real; `pip-audit`.
7. Repositorio remoto (`git remote` vacío) y confirmación del identificador de equipo.
8. ~~Verificación visual del panel del organizador~~ — **resuelta** con el E2E sobre base aislada (§7).

## 7. Gestión del organizador y flujo completo (2.ª fase)

**Modelo (sin tablas nuevas).** Una *función* es una fila de `events` con inventario propio; el recinto y el plano son `venues`/`venue_layouts` existentes. Migración aditiva `0007`: columna `events.status` (`draft`/`published`; todo lo existente queda `published`, así que catálogo y reservas no cambian) y permisos de escritura acotados para el rol de aplicación (las FK `RESTRICT` impiden borrar eventos con reservas o entradas). **Requiere aplicar la migración en cualquier entorno antes de desplegar esta versión**; en desarrollo ya se aplicó tras un respaldo (34 eventos, 16 reservas y 17 entradas intactos).

| Capacidad | Cómo funciona |
|---|---|
| Crear evento | `POST /api/organizer/events`: nombre, fecha, hora, categoría, imagen, descripción, recinto/plano e inventario. Nace como **borrador** (no público, no reservable). |
| Recintos y planos | `GET /api/organizer/venues` (catálogo compartido, solo lectura). El tipo del plano determina la modalidad: teatro/estadio → asientos numerados por secciones; zonas/concierto → zonas con aforo y precio; museo/general → cupo único (el museo exige hora = cupo por horario). Reglas en `app/inventory.py`; combinaciones inválidas devuelven 422. |
| Funciones | `POST /events/{id}/functions` copia plano e inventario con fecha nueva; reservas y asientos independientes. |
| Vista previa | La pestaña reutiliza los mismos selectores 2D/3D que el cliente (`shared.tsx`) con el detalle del borrador; no reserva. |
| Publicar / despublicar | Publicar valida aforo, fecha futura, zonas/asientos coherentes y hora en museos. Despublicar solo sin ventas. |
| Inmutabilidad | Con reservas o entradas: no cambian recinto, plano, inventario, fecha ni hora; no se despublica ni se elimina (409, y la interfaz bloquea los controles). Siguen editables nombre, descripción y categoría. Los borradores sin ventas se pueden reconfigurar y eliminar. |
| Operadores | El organizador asigna/retira operadores por correo; sin esto un evento nuevo no podría validarse. |
| Aislamiento | Todas las rutas filtran por organizador; ajeno → 404, cliente → 403, anónimo → 401, sin CSRF → rechazo (`test_organizers_cannot_see_or_change_each_others_events…`). |

**Flujo completo en navegador real** ([`scripts/e2e-organizer.sh`](scripts/e2e-organizer.sh), base aislada `nexoeventos_e2e`, API y frontend en puertos propios, cuentas con contraseñas aleatorias; resultado en [`docs/evidencias/ui/organizador/resultado-e2e-2026-10-14.json`](docs/evidencias/ui/organizador/resultado-e2e-2026-10-14.json), 10 capturas): organizador crea el evento y elige recinto/plano → configura 96 asientos → vista previa 2D (96 asientos) y 3D → asigna operador → publica (aparece en el catálogo) → cliente se registra, elige el asiento 1 y reserva → entrada emitida (Platea A-1) → operador valida el QR → segunda validación rechazada → estadísticas (1 de 96, S/ 35.00, 1 ingresado) → inventario y fecha bloqueados, no se puede despublicar → nueva función con 96 asientos libres → móvil sin desborde. **16 verificaciones aprobadas, 0 fallidas, sin excepciones de página.**

## 8. Auditoría final

| Área | Hallazgos |
|---|---|
| **Seguridad** | Verificado: permisos por rol y aislamiento entre organizadores en las 12 rutas nuevas; CSRF y origen en mutaciones; modelos estrictos (`extra=forbid`) y límites de tamaño; `image_path` restringido por patrón; precios y disponibilidad siempre desde el servidor; permisos de BD acotados (sin `SELECT` nuevo sobre `access_logs`); sin secretos versionados; `npm audit` 0. **Residual:** no hay límite de tasa en la creación de eventos; al asignar un operador un organizador puede saber si un correo es de operador (mensaje 404 distinto); `pip-audit` sigue sin ejecutarse; la cookie `Secure` depende de la configuración de producción. |
| **Accesibilidad** | axe sin violaciones en catálogo, selección, panel del organizador (resumen, creación) y diálogos; pestañas con teclado (flechas), `fieldset`/`legend`, mensajes `role=status/alert`, tabla con `caption` y `scope`; el 3D tiene alternativa 2D/lista. **No verificado:** contraste automático, lector de pantalla real. |
| **Rendimiento** | Panel del organizador carga diferido (7.3 kB gzip); índice principal 107.6 kB gzip; Three.js diferido; contadores 3D en §3. FPS en GPU real sin medir. |
| **Funcionalidad** | Flujo completo verificado. Límites conocidos: el 3D del auditorio admite hasta 12 filas × 12 asientos y el estadio nombres «Tribuna Norte/Sur/Oriente/Occidente»; no se crean recintos nuevos (catálogo compartido sin propietario) ni se suben imágenes (se elige una de la galería); `scripts/seed-demo-catalog.py` conserva su propia generación de inventario (no se reescribió para no tocar el catálogo existente); cámara física de QR sin probar. |
| **Bloqueos restantes para cerrar la fase cloud** | Aplicar `0007` en RDS durante el despliegue, aprobación de costo y credenciales, capturas de consola, recuperación completa hasta HTTPS. Ninguno afecta a la aplicación local. |
