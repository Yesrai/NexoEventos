"""Contexto TLS VERIFICADO para los clientes HTTPS del failover (PAR de OCI, sondas, testigo, DuckDNS). La verificación del certificado y del nombre NUNCA se desactiva.
Origen: el 22-nov-2026 T2 falló al llamar a DuckDNS porque el Python 3.12.0 del entorno no traía almacén de certificados (`cafile: None`) y rechazaba, con razón, el certificado
(«unable to get local issuer certificate»). Se usa el almacén del sistema (o SSL_CERT_FILE/SSL_CERT_DIR) y, solo si no hay ninguna CA cargada, el paquete `certifi`."""
from __future__ import annotations

import ssl


def verified_ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs():
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass    # sin certifi se sigue verificando contra lo que haya: falla cerrado, nunca abierto
    return ctx
