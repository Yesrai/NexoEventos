# Propuesta: acceso a Grafana y Zabbix (Azure) independiente de la red (8-nov-2026; SOLO diagnóstico y propuesta)

## Diagnóstico (solo lectura, 23:06 hora de Perú)
- Suscripción «Azure for Students» activa; grupo `rg-nexoeventos-observabilidad` en `Succeeded` (centralus).
- `vm-nexoeventos-obs` (Standard_D2s_v4, Ubuntu 24.04, Trusted Launch): **deallocated** (la apagó el apagado automático del 6-nov a las 12:38 hora de Perú). IP privada 10.40.1.4; IP pública estática Standard.
- Apagado automático `shutdown-computevm-vm-nexoeventos-obs`: **habilitado, todos los días 17:38 UTC (12:38 hora de Perú)**.
- NSG: entrada permitida solo 22 (`admin-ssh`) y 443 (`admin-https`) desde `<IP-autorizada>/32`; `deny-all-inbound`. Salida: TCP 80/443 a Internet, 53 y 123, tráfico de la plataforma Azure; el resto denegado.
- La IP pública actual de la usuaria es de nuevo `<IP-autorizada>` (coincide con las reglas).
- Por qué depende de la IP: tres capas con la misma IP — (1) NSG (`admin_cidr` en Terraform), (2) UFW dentro de la VM (`ufw allow from {{ monitoring_admin_cidr }} to any port …` en `ansible/roles/monitoring_zabbix_grafana/tasks/base.yml`; es la única capa que no se cambia desde Azure) y (3) claves SSH. VM sin contraseña (solo 1 clave SSH), extensiones y Run Command deshabilitados, Serial Console sin usuario con contraseña.
- Administración segura disponible hoy: **solo SSH/HTTPS desde la IP permitida**. Como la IP actual coincide, mientras la usuaria esté en esa red basta encender la VM. Cambio de disco (procedimiento B) solo como último recurso. Bastion no sirve por sí solo: entra desde una dirección privada de Azure que el UFW de la VM rechaza.
- Servicios (Nginx, Grafana, Zabbix): no se pueden comprobar con la VM apagada; el 5-nov respondían por HTTPS (Grafana 13.2.4, Zabbix 7.0.32).

## Costos mientras esté apagada (tarifas públicas, sin facturación)
Compute 0. Siguen facturando: disco de SO + 2 discos copia sin adjuntar (`disk-prueba…`, `disk-trabajo…`; Standard SSD de 64 GiB cada uno), instantánea incremental, IP pública estática Standard y Log Analytics ≈ 0,4–0,7 USD/día. Encendida: ≈ 0,108 USD/h más. Los discos copia y la instantánea tienen bloqueos `CanNotDelete`; borrarlos ahorraría ≈ 0,3 USD/día pero requiere quitar los bloqueos (no se hace sin autorización).

## Alternativa recomendada: Tailscale (VPN WireGuard, plan Personal gratuito)
- Plan Personal: 0 USD, hasta 6 usuarios y dispositivos de usuario ilimitados; solo uso no comercial (página de precios de Tailscale). Aplica a este trabajo académico.
- Funciona con el NSG actual sin abrir nada: solo necesita salida TCP 443 (servidores de coordinación y relevos DERP) y TCP 80 opcional, que el NSG ya permite; UDP 41641 y STUN 3478 están bloqueados por `deny-internet-out`, así que el tráfico irá por los relevos (más lento, suficiente para paneles). No requiere reglas de entrada.
- Desde el Mac: instalar la app de Tailscale con la misma cuenta; abrir `https://<IP 100.x de la VM>/grafana/` y `/zabbix/` (o el nombre MagicDNS) desde cualquier Wi-Fi, con el certificado autofirmado actual (advertencia conocida). Con la VM apagada no responde (Tailscale no la enciende).
- Hace falta una vez: encender la VM **desde la red permitida**, entrar por SSH, instalar Tailscale y añadir en UFW una regla solo para la interfaz `tailscale0` (puertos 443 y, opcionalmente, 22). No se tocan ni el NSG ni las reglas de la IP actual (cambio aditivo: sin riesgo de quedarse sin acceso).

### Pasos (cada uno con autorización)
1. Estando en la red `<IP-autorizada>`: `az vm start` y esperar `running` (+≈ 0,108 USD/h).
2. SSH con la clave local (`nexoeventos_azure`), verificando la huella SHA-256 ya documentada.
3. Copia de `/etc/ufw/user.rules`; instalar Tailscale desde el repositorio oficial (apt, con comprobación de la clave GPG) y `sudo tailscale up --hostname=vm-nexoeventos-obs` (no usar `--shields-up`); iniciar sesión con el enlace que muestra (sin claves de autenticación guardadas).
4. `sudo ufw allow in on tailscale0 to any port 443 proto tcp` (y 22 si se quiere SSH por la red privada); `ufw status verbose`.
5. Probar desde el Mac usando otra red (por ejemplo, el celular como punto de acceso): `curl -k https://<ip 100.x>/grafana/api/health`.
6. Endurecer: ACL de la tailnet para que solo los dispositivos de la usuaria lleguen a esa VM; MFA en la cuenta de identidad; revisar la caducidad de la clave del dispositivo.
7. Registrar el cambio en el rol de Ansible (regla de `tailscale0`) y en la documentación para que una reaplicación no lo borre.
8. Apagar la VM al terminar (o dejar que lo haga el apagado automático de las 12:38).
Reversión: `sudo tailscale down`, `sudo ufw delete allow in on tailscale0 to any port 443 proto tcp`, quitar el dispositivo en la consola de Tailscale y `apt remove tailscale`.

### Riesgos
Plano de control de un tercero (el tráfico va cifrado de extremo a extremo, pero Tailscale ve metadatos); la cuenta de Tailscale se vuelve la llave de los paneles (MFA y ACL); se instala software en la VM de evidencias (se documenta); relé más lento; la VM sigue teniendo que estar encendida; el apagado automático diario sigue vigente.

## Comparación
| Opción | Costo | Cambia el NSG/UFW | Cambio de Wi-Fi | Comentario |
|---|---|---|---|---|
| Tailscale | 0 | UFW: regla aditiva en `tailscale0`; NSG sin cambios | Sí | Recomendada |
| Azure Bastion | Developer: gratis pero solo SSH/RDP por el portal y con disponibilidad limitada; Basic/Standard de pago (no se pudo confirmar el precio; del orden de decenas a más de cien USD/mes) | UFW igualmente (rechaza la dirección de Bastion) | Sí para SSH | No da acceso HTTPS a los paneles; no recomendada |
| Ampliar la IP permitida a un rango (/16) | 0 | NSG y UFW | Parcial | Abre a miles de IP ajenas; no recomendada |
| Actualizar NSG con un script al cambiar de red | 0 | NSG (y UFW sigue bloqueando) | No | Insuficiente: el UFW también filtra |
| VPN Point-to-Site de Azure | ≈ 140 USD/mes (puerta de enlace) | VNet | Sí | Excede el presupuesto |
| Cloudflare Tunnel | 0–bajo | Ninguno entrante | Sí | Requiere dominio propio y más software en la VM |
