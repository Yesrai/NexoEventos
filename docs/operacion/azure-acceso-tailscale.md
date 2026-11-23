# Acceso a Grafana y Zabbix (Azure) por Tailscale — guía de uso (9-nov-2026)

## Cómo está montado
`vm-nexoeventos-obs` está en una tailnet personal (solo el Mac y la VM). La VM lleva la etiqueta `tag:obs`; la política de la tailnet permite únicamente a la cuenta propietaria llegar a esa etiqueta por el puerto 443. Tailscale en la VM corre con `--accept-dns=false --netfilter-mode=off`, y UFW permite `443/tcp` por la interfaz `tailscale0` (además de 22 y 443 desde la IP pública autorizada, sin cambios). El NSG no se modificó: sigue abierto solo para la IP autorizada. La IP de Tailscale de la VM es `[IP-tailnet-oculta]` (se conserva al apagar y encender).

## Encender, usar y apagar
1. Encender (desde cualquier red; solo la API de Azure): `az vm start -g rg-nexoeventos-observabilidad -n vm-nexoeventos-obs` y esperar `VM running` (≈ 15–60 s). Cuesta ≈ 0,108 USD/h. El apagado automático la detiene a las 17:38 UTC (12:38 hora de Perú).
2. Esperar ≈ 1–2 min a que arranquen los servicios y Tailscale (aparece «online» en la consola de Tailscale).
3. Con Tailscale conectado en el Mac (tailnet personal): abrir `https://[IP-tailnet-oculta]/grafana/` y `https://[IP-tailnet-oculta]/zabbix/` (aceptar la advertencia del certificado autofirmado). Las credenciales están en `work/ansible-secrets/monitoring/` (ver el procedimiento con `pbcopy`; no se muestran en pantalla).
4. Apagar: `az vm deallocate -g rg-nexoeventos-observabilidad -n vm-nexoeventos-obs` y comprobar `VM deallocated`.
Con la VM apagada no responde nada; Tailscale no la enciende.

## Si algo falla
- No carga: comprobar que Tailscale está conectado en el Mac y en la **tailnet personal** (no en una compartida); `tailscale ping [IP-tailnet-oculta]`.
- Si aparece «no UDP or DERP addr» en la VM o el tráfico no pasa: desconectar y reconectar Tailscale en el Mac.
- SSH a la VM: sigue limitado a la IP pública autorizada (NSG y UFW); por Tailscale solo está abierto el 443.

## Reversión
`sudo ufw delete allow in on tailscale0 to any port 443 proto tcp` (y la variante v6), o restaurar las copias en `/var/backups/nexoeventos-ufw-*`; `sudo tailscale down` y quitar el dispositivo en la consola de Tailscale; `sudo apt remove tailscale`. Para volver a la política por defecto de la tailnet: pegar `{"acls":[{"action":"accept","src":["*"],"dst":["*:*"]}]}` en Access controls.

## Política de ejemplo (sustituir TU_CORREO)
```
{
  "tagOwners": { "tag:obs": ["<cuenta-tailscale>"] },
  "acls": [ { "action": "accept", "src": ["<cuenta-tailscale>"], "dst": ["tag:obs:443"] } ],
  "tests": [
    { "src": "<cuenta-tailscale>", "accept": ["tag:obs:443"], "deny": ["tag:obs:22", "tag:obs:80", "tag:obs:3000", "tag:obs:5432", "tag:obs:10050", "tag:obs:10051"] },
    { "src": "tag:obs", "deny": ["<cuenta-tailscale>:22", "<cuenta-tailscale>:443"] }
  ]
}
```
Recomendado: activar *Device approval* en la consola de Tailscale y MFA en la cuenta.

## Pendientes
Prueba desde otra red (Internet del celular) en el próximo encendido; revisar en la consola que la VM figure con la etiqueta `tag:obs` y la caducidad de clave deshabilitada.
