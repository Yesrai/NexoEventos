# Arquitectura operativa de T7

```mermaid
flowchart LR
    U[SUPER_ADMIN_TI\nNavegador] -->|HTTPS · cookie HttpOnly · CSRF| N[NexoOps\nFastAPI + SPA]
    N --> A[(SQLite 0600\nusuarios · desafíos OTP · sesiones)]
    N --> AU[Auditoría encadenada\nops_center.audit]
    N -->|API Viewer · TLS verificado| G[Grafana en Azure]
    N -->|JSON-RPC solo lectura · TLS| Z[Zabbix en Azure]
    N -->|describe/list autorizados| W[AWS: ASG · ALB · RDS · alarmas]
    N -->|lee instantánea e historial| C[Recolector T4 en Azure]
    C -->|sondas HTTPS| AWS[AWS]
    C -->|sondas HTTPS| OCI[OCI en espera/recuperación]
    C --> AZ[Estado local Azure]
    N --> B[Barreras y ledger\nT1–T6]
    N -. bloqueado .-> X[Failover / failback]
    N -->|SMTP TLS| M[Proveedor de correo]
```

## Fronteras de confianza

- El navegador nunca recibe credenciales de Grafana, Zabbix, AWS ni SMTP.
- Grafana y Zabbix usan permisos de solo lectura y TLS verificado; una fuente no disponible se muestra como tal.
- Las acciones de NexoOps son una lista blanca. No existe ejecución arbitraria de comandos.
- Failover y failback siguen bloqueados hasta T6 y aprobación independiente.
- El recolector conserva fuente y hora UTC; una instantánea obsoleta no se presenta como estado actual.

## Flujo operativo permitido

```mermaid
sequenceDiagram
    actor TI as SUPER_ADMIN_TI
    participant UI as NexoOps
    participant API as API/Acciones
    participant AUD as Auditoría
    participant MON as Grafana/Zabbix/Recolector
    TI->>UI: Contraseña + OTP
    UI->>API: Solicitud autenticada + CSRF
    API->>MON: Consulta de solo lectura
    MON-->>API: Datos + fuente + UTC o error explícito
    API->>AUD: actor, rol, operación, resultado, request_id
    API-->>UI: Hechos verificables
    Note over API,AUD: Acciones mutantes quedan bloqueadas o pendientes de aprobación independiente
```

