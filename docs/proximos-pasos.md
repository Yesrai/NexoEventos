# Próximos pasos

1. Elegir dominio/subdominio y método de certificado TLS; hasta entonces HTTPS está preparado pero no operativo.
2. Decidir el mecanismo de secretos de aplicación. El acceso mínimo de `LabInstanceProfile` a Secrets Manager no pudo verificarse porque Learner Lab deniega la lectura de políticas.
3. Revisar y aprobar explícitamente el plan autenticado de 30 altas y su estimación de USD 0.404 por 8 h / USD 36.903 por 730 h. No ejecutar `apply` sin esa aprobación.
4. Si se aprueba, desplegar por etapas y comprobar cada permiso real; un plan correcto no prueba autorización de creación ni cuota.
5. Reunir EV02–EV10, emitir/probar HTTPS y medir rendimiento, RTO y RPO. No marcar evidencia cloud como completa antes de observar el recurso y la prueba.
6. Completar aparte la selección de cuenta/MFA de Azure para verificar saldo, vencimiento, políticas y cuotas.
