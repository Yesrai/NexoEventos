# Incidencia: la sesión de Academy venció con V2 y la RDS encendidas (4-nov-2026, saneado)

- 12:04 (Perú): fin de la prueba de notificación de V2; se espera la confirmación de la usuaria para la Fase E.
- 15:53: la usuaria confirma los correos y autoriza la Fase E. El perfil `nexoeventos-lab` responde a STS, pero **todos los servicios devuelven `AccessDenied` por una denegación explícita de la política `voc-cancel-cred`** (credenciales de una sesión cancelada/vencida; escritas a las 15:51). No se intentó eludir la restricción.
- Consecuencia: **no se ejecutó ningún prechequeo ni destroy**; V2 (27 recursos) y la RDS siguen sin desmontar/detener (no verificable por la CLI hoy). Coste del hueco 12:04–15:53 ≈ 3,8 h × ≈ 0,13 USD/h ≈ 0,5 USD (estimación; el comportamiento de Academy al vencer la sesión con RDS/EC2 no está verificado).
- Qué hace falta: iniciar el laboratorio, copiar credenciales nuevas del bloque «AWS Details» de ESA sesión y pedir que se repitan los prechequeos de la Fase E (el plan de destroy se regenera).
