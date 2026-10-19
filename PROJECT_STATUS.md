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
| Backend (`pytest`, PostgreSQL 14 local, base `nexoeventos_test`) | **38 aprobadas** (corridas repetidas sin interferencia entre ellas) |
| Frontend (`vitest`, incluye axe) | **26 aprobadas** |
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

## 9. Rediseño de la compra, sala de espera y fila virtual (3.ª fase)

**Auditoría previa (capturas reales).** El detalle se mostraba debajo del catálogo, sin portada; el plano 2D del concierto era un rectángulo verde sin zonas; el 3D quedaba tras un botón; textos de 11–13 px; el total y el botón estaban al final de un formulario; había pistas y botones flotantes sobre el 3D y una nota técnica («Representación 3D propia…») dentro del flujo.

| Cambio | Resultado verificado |
|---|---|
| Página de evento propia (`EventPage.tsx`) | Portada con título, fecha, hora, lugar y CTA; el catálogo se oculta mientras se compra; «Volver a eventos». |
| Recinto como vista principal | Mapa 3D por defecto en teatro, estadio, concierto y museo; pestañas **Plano** y **Lista** accesibles; si WebGL falla se pasa al plano con aviso. |
| Vista inicial por recinto | Concierto: frente al escenario con las zonas a la vista; auditorio: desde el fondo de la sala; estadio: vista general con enfoque por tribuna; museo: recorrido general y por sala, sin asientos. |
| Plano 2D real | Concierto: SVG con escenario y zonas proporcionales al aforo; auditorio: filas de asientos por zona; estadio: tribunas clicables + asientos; colores iguales en tarjetas, plano y 3D. |
| Panel de compra | Fijo en escritorio (precio, cantidad, asientos elegidos con quitar, total, CTA). En móvil: barra inferior y hoja desplegable que no tapa el contenido. |
| Limpieza visual | Sin pista flotante, sin nota técnica, sin leyenda dentro del lienzo; botones de perspectiva fuera de la escena; textos ≥ 15–16 px. |
| Inventario sincronizado | Tras reservar se vuelve a leer el detalle: el asiento reservado queda ocupado en 2D y 3D. Precios y disponibilidad siguen viniendo del servidor. |

**Sala de espera y fila virtual** (diseño y costos: [`docs/sala-de-espera-y-cola.md`](docs/sala-de-espera-y-cola.md)). Migración `0008`; reloj de PostgreSQL; fila opcional por evento con tope de personas activas y minutos por turno; admisión por orden de llegada bajo el bloqueo del evento; un turno por compra; renunciar a un turno; recargar no salta la fila; sin tiempos estimados inventados. El organizador lo configura en la pestaña **Ventas y fila**. Eventos existentes no cambian (inicio nulo, fila apagada).

**Pruebas.** Backend 38/38 (incluye 5 de cola: ventana de ventas, orden y tope, expiración, 12 uniones simultáneas, permisos). Frontend 26/26 (cuenta regresiva, posición real, turno, salida de fila, pestaña de ventas, axe en la página con fila). E2E en navegador real: **24 verificaciones aprobadas, 0 fallidas, sin excepciones** ([`resultado-e2e`](docs/evidencias/ui/flujo-completo/)), incluyendo: el servidor rechaza comprar sin turno aunque se salte la interfaz (403 `queue_required`), la segunda persona queda con su posición real, recargar no cambia el lugar y al renunciar la primera se admite a la segunda. Clics reales en 3D: asiento B-6 (auditorio), zona Preferencial (concierto), asiento F-5 de Tribuna Occidente (estadio).

**Evidencias nuevas:** [`compra-v2/`](docs/evidencias/ui/compra-v2/) (4 recintos, escritorio y móvil), [`flujo-completo/`](docs/evidencias/ui/flujo-completo/) (compra, fila, estadísticas, móvil) y [`recintos-3d-v2/`](docs/evidencias/ui/recintos-3d-v2/) (+ contadores de render). Las carpetas anteriores (`recintos-3d/`, `organizador/`) quedan como historial superado. En las capturas móviles de página completa la barra de compra inferior aparece a media página: es un efecto de la captura (elemento fijo), no del diseño.

**Defectos hallados y corregidos durante la verificación:** título de portada y de sala de espera con texto oscuro sobre fondo oscuro; reflector del estadio gigante e inmaculadamente blanco cerca de la cámara; botones de perspectiva cortados en móvil; quien tenía turno no podía renunciar; servidores de prueba huérfanos que servían código antiguo al E2E (el script ahora libera los puertos).

**Limitaciones reales.** Sondeo cada 5 s (no WebSockets); sin estimación de espera; sin sorteo ni protección contra bots; una compra por turno; carga de la fila no medida en la nube (≈ 40 transacciones/s con 200 esperando es una estimación, ver el documento de diseño); contraste de color y lector de pantalla reales sin verificar; FPS en GPU real sin medir; el estadio sigue siendo el 3D menos detallado. **La migración `0008` debe aplicarse en cualquier entorno antes de desplegar** (ya aplicada en tu base local, con respaldo previo y datos intactos).

## 10. Rediseño visual «Noche Nexo» — fase 1 (pendiente de aprobación visual)

Alcance de esta fase: **inicio, catálogo y página de evento**. Registro, compra (ya integrada en la página de evento), sala de espera, mis entradas y panel del organizador conservan su diseño anterior hasta que se apruebe esta fase. Backend, reservas, inventario, QR, cola virtual y los recintos 3D (geometría, cámaras e interacciones) **no se modificaron**; solo cambió el marco visual que los rodea.

- **Sistema visual** (`frontend/src/noche.css`): cabecera, portadas y recinto en tono noche; catálogo e información sobre papel claro; turquesa `#10D7B0` como acción; magenta solo en puntos (fecha de las tarjetas, color de zona). Bricolage Grotesque (títulos) e Inter (interfaz), **instaladas como paquetes** (`@fontsource-variable/*`, licencia OFL, sin peticiones externas).
- **Inicio:** portada con fotografía grande, título destacado y CTA; carrusel con rail de destacados; categorías en píldoras desplazables.
- **Catálogo:** filtros en píldoras; tarjetas tipo póster 4:5 con sello de fecha, categoría, lugar, hora, precio y disponibilidad (etiqueta «Últimas entradas» solo cuando la disponibilidad real es baja); esqueletos de carga.
- **Evento:** portada a ancho completo, barra pegajosa con CTA al hacer scroll, recinto 3D en marco oscuro, panel de compra como entrada con muesca, información sobre papel.
- **Móvil:** navegación inferior (Inicio, Buscar, Entradas, Cuenta) que se oculta en la página de evento para no interferir con la selección; en el evento, barra de compra y hoja desplegable.
- **Movimiento:** solo entrada suave de la portada, elevación leve de tarjetas y barra pegajosa; se desactiva con «reducir movimiento».
- **Verificación:** frontend 26/26, build de producción correcto, `npm audit` 0. Capturas reales de escritorio y móvil (página completa y pantalla real) en `docs/evidencias/ui/noche-nexo-fase1/`.
- **Limitaciones:** las fotografías (Wikimedia Commons) tienen 1000–1600 px de ancho en su origen; no hay mayor resolución disponible, por lo que algunas se ven suaves en portadas a pantalla completa. Pendiente: extender el sistema a las demás pantallas tras la aprobación.

## 11. Corrección: selección de asientos numerados (3D primero)

- **Causa:** tres eventos con asientos numerados (1003, 1004, 1012) tienen un plano de tipo `zones`/`concert_zones`; la página solo reconocía `theatre`/`stadium` para el modo asientos, por lo que no ofrecía 3D ni plano y caía a la lista de casillas (una por asiento). No era un error de WebGL ni se mostraban 3D y lista a la vez (los modos son excluyentes).
- **Corrección (solo integración, sin tocar geometría ni cámaras):** `venueKind()` en `EventPage.tsx` decide el recinto: modo asientos → estadio o sala de butacas; así esos eventos abren en el 3D. La lista pasó a secciones por zona con filas plegables y búsqueda («B5», «fila C»); sin casillas. Se quitó la fila de tarifas duplicada.
- **Verificación:** 27 pruebas, build OK; `scripts/verify-seat-selection.mjs` en Chrome (escritorio y móvil, 4 eventos): abre en Mapa 3D, clic sobre butaca la selecciona y aparece en el panel, Lista/Plano sin casillas. Capturas en `docs/evidencias/ui/seleccion-asientos-v2/`. (WebGL por software; no mide FPS en GPU real.)

## 12. Dirección visual: paleta A · Cobalto (fase 1, pendiente de aprobación)

- Se descarta «Noche Nexo» (turquesa/magenta/oscuro). Nueva capa `frontend/src/theme.css` (sustituye a `noche.css`) y tokens de `styles.css` en cobalto `#2446C6`; Inter como única tipografía (se quitó Bricolage Grotesque).
- Contrastes calculados (WCAG): blanco sobre cobalto 7.6:1, texto 18.1:1, secundario 6.3:1, borde de control 3.1:1.
- Aplicado a: cabecera, inicio (destacado + 3 laterales), categorías, catálogo (tarjetas 16:10 con fecha, título, lugar, precio), detalle del evento (portada contenida, panel de compra) y selección 3D/plano/lista.
- Cambio de **colores** (no de geometría ni lógica) en el 3D: el asiento seleccionado pasa de turquesa a azul vivo `#2F6BFF`; las zonas dejan de ser azul/rosa/turquesa y usan ámbar, verde, violeta y ladrillo (`venue3d-types.ts`, `shared.tsx`, `venue3d-concert.ts`); los acentos decorativos turquesa del escenario/museo pasan a azul. Así «seleccionado» no se confunde con ninguna zona ni con ocupado (gris).
- Pendiente (no tocado): registro/inicio de sesión, compra confirmada, sala de espera, Mis entradas, organizador.
- Evidencias: `docs/evidencias/ui/cobalto-fase1c/` (inicio, concierto, estadio, auditorio, museo; escritorio y móvil), `cobalto-seleccion-3d/` (3D inicial, selección por clic, lista, plano; 4 eventos × 2 pantallas, 8/8 verificados), `cobalto-fase1d/` (inicio tras ajuste final).
- Verificación: 27 pruebas, build OK, `npm audit` 0. WebGL por software; sin medición de FPS en GPU real.

## 13. Sistema tipográfico (Inter, única familia)

- Inter variable (paquete local `@fontsource-variable/inter`), sin Bricolage ni estilos decorativos. Capa final de `frontend/src/theme.css` y normalización de `styles.css`.
- Escala: 14–15 px secundario, 16 px texto, 18 px título de tarjeta, 20 px subtítulo, 24–30 px sección, 32–40 px título principal adaptable (páginas de cuenta/organizador: 28–32 px). Pesos 400 / 500 (etiquetas, botones) / 600 (subtítulos) / 700 (solo título principal y totales). Eliminados 650, 800 y las mayúsculas forzadas; interlineado 1.5–1.6 en texto, medida máxima 66 ch, cifras tabulares en precios.
- También se corrigieron restos del tema anterior: texto oscuro sobre el avatar azul, verdes azulados residuales.
- Verificación en Chrome (`scripts/audit-typography.mjs`, estilos calculados): una sola familia, 0 textos < 14 px, 0 mayúsculas forzadas, sin desbordes; inicio, detalles, ingreso y registro en escritorio y móvil. Organizador, cliente, operador y fila virtual con `scripts/e2e-organizer.sh` (24 comprobaciones, base aislada). 27 pruebas, build OK.
- Evidencias: `docs/evidencias/ui/tipografia-inter-v2/`, `tipografia-flujo-completo/`. Propuesta visual actualizada con la sección 7 en `docs/propuesta-visual/paletas.html`.

## 14. Auditoría visual crítica (pendiente de aprobación; sin implementación)

- Informe: `docs/auditoria-visual/auditoria-visual.html` (veredicto por pantalla, 20 hallazgos con capturas, prioridades P0–P2 y decisiones pendientes). Capturas completas: `docs/evidencias/ui/auditoria-visual-v2/` (escritorio y móvil). Scripts: `scripts/audit-visual.sh` + `audit-visual.mjs` (base aislada `nexoeventos_audit`; no toca la base de desarrollo).
- Conclusión: base visual correcta, pero seis problemas de composición/copy hacen que parezca demo: avisos «académica/ficticios», catálogo largo con botón repetido, compra bajo el pliegue y texto repetido, falta de selección de función, confirmación y «Mis entradas» sin diseño de producto, cabecera desalineada fuera del inicio.
- Nada de lo anterior se ha implementado; no se modificaron datos, backend, reservas, QR, fila virtual ni Cloud.

## 15. Rediseño comercial (cabecera, catálogo, detalle, compra 3D, confirmación, Mis entradas)

- **Hecho** (commits `5759919`, `29f44c3`, `5bd4637` y el de cierre): cabecera consistente; sin franjas ni textos de demo (aviso «Pago simulado» solo en compra y confirmación); catálogo con tarjetas clicables, 12 por tanda, eventos pasados ocultos e iconos Lucide; detalle con compra a la vista y descripción única; pantalla de confirmación; «Mis entradas» como monedero (Próximas/Pasadas); esqueleto de carga inicial; museo con 3D opcional; en móvil se omiten solo el arco de entrada y el puesto de sonido del concierto (decoración que tapaba la vista).
- **Datos** (con copia previa en `work/backups/`, ignorada por git): 31 descripciones reescritas con `scripts/update-demo-descriptions.py` (solo `description`); 5 fotos sustituidas con `scripts/add-demo-images.py` (licencia CC verificada vía API de Commons; atribuciones en `docs/atribuciones-imagenes.md`). Conteos intactos: 34 eventos, 17 reservas.
- **Funciones**: se agrupan solo eventos con el mismo nombre y recinto (`functionKey` en `App.tsx`), sin migración ni cambios de identificadores o inventarios.
- **Verificación**: 29 pruebas de interfaz, 38 de backend, build OK; flujo completo en base aislada 25/25 (incluye confirmación, QR, operador y fila virtual; una primera pasada agotó el tiempo esperando el botón «Mapa 3D» de la vista previa del organizador y las siguientes pasaron: intermitencia no diagnosticada); selección por clic en el 3D 8/8 (escritorio y móvil).
- **Pendiente**: rediseño de organizador/operador; organizador y condiciones (la API no expone esos datos); ver el selector de funciones con datos reales; fotos de cerámica y conferencia por revisar; FPS en GPU real y lector de pantalla.
- Evidencias: `docs/evidencias/ui/redisenio-despues/` (después), `auditoria-visual-v2/` (antes), `redisenio-seleccion-3d/`, `redisenio-flujo-completo-c/`. Comparación: `docs/auditoria-visual/antes-despues.html`.

## 16. Pulido del flujo de compra (recorrido del comprador)

- Panel de compra con filas de resumen (cantidad × precio unitario, subtotal) y «Total · N entradas»; «Mis entradas» con QR visible en la tarjeta y botón «Ver entrada QR»; el registro con una compra pendiente vuelve directo al evento con la selección intacta; el aviso de sesión ya no queda pegado tras comprar; botón «Atrás» del navegador sube un nivel (evento → catálogo) en lugar de salir del sitio.
- Fallo intermitente de «Mapa 3D» en la vista previa del organizador: causa = el e2e usaba el servidor de desarrollo y una edición de archivos mientras corría provocaba una recarga completa. `e2e-organizer.sh` y `audit-visual.sh` ahora usan una compilación aislada (`vite build` + `vite preview`). Dos pasadas consecutivas 25/25.
- Nuevo `scripts/journey-buyer.sh` (base aislada): 16 comprobaciones en escritorio y móvil (3D → asiento → registro → confirmación → Mis entradas → QR). Evidencias en `docs/evidencias/ui/recorrido-comprador-3/`.

## 17. Paneles de organizador y operador

- **Operador** (`frontend/src/Operator.tsx`, antes dentro de `App.tsx`): evento asignado identificado (nombre, fecha, lugar), resultado inmediato a pantalla grande con cuatro estados (ingreso aceptado, entrada ya utilizada, código no válido / de otro evento, sin autorización) además de «sin conexión», lectura continua de QR con cámara cuando el navegador lo ofrece (rellena el campo; la entrada solo se consume al pulsar «Validar ingreso»), campo manual que se limpia tras cada validación y botón principal de ≥ 52 px en móvil. Reglas de validación y permisos del backend sin cambios.
- **Organizador**: encabezado sin texto técnico, filtro Todos/Publicados/Borradores con conteos, estado vacío con acción, lista en tira horizontal en móvil para ver el detalle de inmediato, vista previa en una sola columna sin barra/hoja flotantes, textos de «Ventas y fila» sin rutas de archivos ni jerga, estados vacíos sin recuadro punteado.
- **Pruebas**: 31 de interfaz (nueva: resultados de validación del operador), 38 de backend, flujo e2e aislado 27/27 con capturas de organizador (resumen, ventas y fila, operadores, móvil) y operador (escritorio y móvil) en `docs/evidencias/ui/paneles-2/`.
- **Pendiente**: el organizador no puede consultar el listado de reservas/entradas individuales (la API solo expone estadísticas agregadas; requiere endpoint nuevo); no hay edición de fecha/hora tras tener ventas (regla vigente del backend).

## 18. Docker, CI y Trivy (sin cambios en AWS)

- Añadidos `backend/Dockerfile`, `backend/.dockerignore`, `docker-compose.yml`, `scripts/docker-dev.sh`, `.trivyignore` y reescrito `.github/workflows/ci.yml`; guía en `docs/operacion/ci-docker.md`.
- Trivy encontró **cryptography 49.0.0 con CVE-2026-69247 (HIGH, corregido en 50.0.0)**; se actualizó a 50.0.0 en los tres archivos de dependencias (la app solo usa Fernet; 38/38 pruebas y QR descifrables). Sin excepciones.
- El análisis de configuración informa de decisiones V1 conocidas en Terraform (egreso 443 abierto, IP pública de la EC2, S3 sin clave propia, RDS de recuperación); quedan visibles y sin bloquear.
- **Nota para el despliegue Cloud:** `cryptography` 50.0.0 formará parte de la próxima actualización (Fernet no cambia de formato).

## 19. Fase 2 · rendimiento e integridad con k6 (solo local, sin AWS)

- `perf/`: escenarios k6 (`catalog`, `detail`, `availability`, `reserve`, `same_seat`), fixture aislado, verificación de integridad en PostgreSQL y orquestador (`perf/run_local.py`); guía y criterios de aceptación en `perf/README.md`. k6 corre en Docker (`grafana/k6:2.3.0`); los scripts rechazan cualquier base distinta de la local del Compose.
- Resultados reutilizables para comparar V1/V2 en `perf/results/local-smoke-validacion/` y `local-progresivo-20261019/` (JSON, esquema 1).
- Resultado: 0 errores inesperados, 0 violaciones de integridad en las 11 comprobaciones y exactamente 1 ganador por asiento en 1 000 intentos concurrentes. Observación: 50 inicios de sesión simultáneos tardan p95 ≈ 2.4 s (Argon2, 1 worker); no es un defecto de las reservas.
- Pendiente (AWS, con autorización y presupuesto): 100/500/1 000 usuarios y comparación V1/V2.

## 20. Preparación local de la actualización de AWS V1 (sin AWS)

- `scripts/rehearsal/run.sh` reproduce en una base desechable (puerto 55433, se destruye al terminar): esquema 0005 con el código desplegado (`7955e7e`) y reservas reales de ensayo → upgrade a 0008 con el código actual → código antiguo sobre 0008 → código nuevo con 2 workers → rollback puro y con tráfico posterior → reintento del upgrade. Resultado: huella de reservas, entradas, usuarios e inventario idéntica tras migrar; el código antiguo funciona con 0008 (incluida una reserva nueva); `downgrade` a 0005 sin pérdida de reservas, entradas ni usuarios; con 2 workers la sesión es válida en 80/80 lecturas, la fila admite exactamente el máximo con posiciones consistentes y 1 ganador de 12 por asiento.
- `scripts/update-demo-dates.py`: dry-run por defecto; solo reprograma eventos demo **pasados y sin reservas ni entradas** (los que tienen ventas se informan como omitidos); idempotente.
- `perf/run_cloud.py` + `perf/cloud_fixture.py`: lanzador k6 de un peldaño por ejecución con guardas (`NEXO_LOAD_TEST_APPROVED` = `--run-id`, solo `https://<nombre>.duckdns.org`, ≤ 50 usuarios, ≤ 30 min, corte automático si p95 > 2 s o errores > 1 %) y SQL de fixture/limpieza (se ejecuta en la EC2 con la identidad migradora; el rol de la aplicación no tiene DELETE sobre `users`). Probado **solo en local** (humo y peldaño de 10 usuarios con 2 workers; limpieza deja 0 usuarios k6 y 0 eventos de fixture, y las reservas ajenas intactas). Nunca se ejecutó contra un host público.
- Hallazgos del ensayo: los asientos de la disputa (evento 90004) se consumen en cada ejecución → el lanzador exige recrear el fixture antes de repetir `same_seat`; cada escenario registra sus propios usuarios para no chocar.
- Pendiente (AWS, con autorización): comprobar estado de EC2/RDS, respaldo con recibo, deploy, datos demo, fixture, peldaños y limpieza. Riesgos abiertos: IP de origen detrás de un ALB, conexiones al pool con N instancias, migraciones únicas en Auto Scaling, secretos idénticos entre instancias, memoria sin métrica verificada.
