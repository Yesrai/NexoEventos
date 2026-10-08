# EV03 — subredes y rutas

Estado al 3 de octubre de 2026: Las tres subredes, la tabla pública con IGW y la tabla de datos sin ruta por defecto existen desde el 3 de octubre de 2026; la conectividad EC2→RDS se comprobó. **Captura de consola sanitizada pendiente** (`scripts/cloud/capture-inventory.sh` y checklist en `docs/operacion/procedimientos-sesion-cloud.md` § 2). Mostrar las tres subredes V1, zonas, asociaciones de tablas de ruta e Internet Gateway; comprobar que las subredes RDS no tienen ruta por defecto a Internet.

Lectura API del 7 de octubre: pública `10.20.1.0/24` en `us-east-1a` con IPv4 automática y ruta `0.0.0.0/0 → IGW`; datos `10.20.21.0/24` y `10.20.22.0/24` en dos AZ sin ruta por defecto. Captura de consola pendiente.
