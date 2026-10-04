# Sesión AWS del 4 de octubre de 2026

## Resultado

La sesión se detuvo de forma segura antes de la carga y la restauración. Al
iniciar el Learner Lab, Academy arrancó automáticamente la EC2 original. Se
detectó en la consola, se detuvo con apagado controlado y se confirmó como
`Detenida`. La RDS original se confirmó en `Detención temporal`. No se ejecutó
`terraform apply`, `terraform destroy`, la carga ni la restauración temporal.
Esta sesión no creó recursos temporales ni produjo métricas de carga, RTO o RPO.

## Comprobaciones realizadas

- Repositorio limpio en `7e879ad` al inicio.
- Estado Terraform real conservado en
  `work/terraform-state/academy-current/terraform.tfstate`: lineage existente,
  serial 32 y 30 recursos administrados más 4 fuentes de datos. No se inicializó
  ningún estado vacío.
- `work/terraform-envs/academy.tfvars` se reconstruyó desde ese estado, con los
  CIDR, región, tamaños, perfil, retenciones y nombres observados; quedó ignorado
  por Git y con modo `0600`. Los valores sensibles no se imprimieron.
- Learner Lab iniciado y mostrado como `Lab environment ready`, región
  `us-east-1`, sesión de 4 horas.
- Panel del laboratorio: `Used $0.3 of $50`. Es consumo acumulado mostrado, no
  saldo en tiempo real; las instrucciones advierten un retraso típico de 8–12 h.
- Hora del Mac comprobada y coherente; no había variables `AWS_*` sustituyendo
  el perfil aislado.
- Consola AWS autenticada: EC2 autoarrancada por el laboratorio y luego
  confirmada `Detenida`; RDS original confirmada en `Detención temporal`.

## Bloqueo reproducido

`sts:GetCallerIdentity` devolvió `InvalidClientTokenId` usando un bloque completo
recién emitido desde **AWS Details** (access key, secret key y session token de la
misma sesión), el perfil explícito `nexoeventos-lab` y archivos aislados. El fallo
persistió después de iniciar el laboratorio, esperar `Lab environment ready`,
recargar el módulo y volver a emitir el bloque. No se muestran identificadores ni
credenciales en este informe.

Al no funcionar STS no se pudo comprobar el inventario por API. No se envió
ninguna orden de arranque o restauración desde los scripts y no se creó una RDS
temporal. La consola permitió confirmar el estado final de los originales:
EC2 `Detenida` y RDS `Detención temporal`.

## Reporte breve para docente o soporte

- Fecha local: 4 de octubre de 2026 (America/Lima).
- Laboratorio: AWS Academy Learner Lab 184558.
- Estado visible: `Lab environment ready`, sesión de 4 horas, `us-east-1`.
- Error: `InvalidClientTokenId` en `sts:GetCallerIdentity`.
- Controles: bloque temporal completo y recién emitido; perfil y archivos
  explícitos; sin variables `AWS_*`; hora local/UTC coherente; cuenta esperada
  reconstruida desde el estado real sin exponerla.
- Solicitud: verificar la emisión/activación de credenciales temporales del lab.

## Costo

No hubo horas de RDS en ejecución ni RDS temporal. Academy mantuvo la EC2 activa
aproximadamente 6 minutos antes de la detención: con los supuestos documentados,
EC2 + IPv4 representan cerca de USD 0.0026. El panel pasó de mostrar USD 0.20 a
USD 0.30 de uso acumulado, pero por el retraso de AWS Budgets no se atribuye esa
diferencia de USD 0.10 exclusivamente a esta sesión. Los costos persistentes
estimados continúan según `docs/costos-v1.md`.
