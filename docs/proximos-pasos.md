# Próximos pasos

1. Elegir un dominio o subdominio y el método de certificado TLS; hasta entonces HTTPS está preparado pero no operativo.
2. La usuaria completa selección de cuenta/MFA de Azure; verificar por lectura saldo, vencimiento, políticas y cuotas.
3. Con autorización explícita, iniciar Learner Lab y hacer inventario AWS de solo lectura; confirmar `LabInstanceProfile` y acceso mínimo a secretos.
4. Ejecutar `terraform plan` autenticado y guardar el resultado sanitizado como EV09. No ejecutar `apply`.
5. Comparar el plan con la estimación de USD 36.903/mes y pedir aprobación explícita del despliegue.
6. Solo tras esa aprobación, desplegar por etapas, reunir EV02–EV10 y medir rendimiento, RTO y RPO.
