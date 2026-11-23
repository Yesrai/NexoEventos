"""Contexto TLS con validación OBLIGATORIA (certificado y nombre del servidor). Orden de confianza: certificado fijado (`cafile`) → almacén por defecto de Python si existe
(SSL_CERT_FILE o el del sistema) → `certifi`. Esto cubre Python de python.org en macOS, que no trae CA hasta ejecutar «Install Certificates»; nunca se desactiva la verificación."""
from __future__ import annotations

import os
import ssl


def trusted_context(cafile: str | None = None) -> ssl.SSLContext:
    if cafile:
        ctx = ssl.create_default_context(cafile=cafile)
    else:
        p = ssl.get_default_verify_paths()
        has_default = bool(os.environ.get("SSL_CERT_FILE")) or any(x and os.path.exists(x) for x in (p.cafile, p.openssl_cafile, p.openssl_capath))
        if has_default:
            ctx = ssl.create_default_context()
        else:
            try:
                import certifi
            except ImportError:
                raise ssl.SSLError("sin almacén de CA: instala certifi o ejecuta «Install Certificates.command» de Python") from None
            ctx = ssl.create_default_context(cafile=certifi.where())
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx
