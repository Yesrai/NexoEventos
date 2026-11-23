#!/usr/bin/env bash
# Biblioteca (se "importa" con `source`): descifrado CMS con clave privada que puede estar protegida con contraseña (S-01).
# Reglas de seguridad:
#   - la contraseña NUNCA va en argumentos visibles: solo se aceptan `env:NOMBRE`, `file:RUTA` o `fd:N` (los mismos formatos que `openssl -passin`);
#     `pass:...` y cualquier otro formato se rechazan. Lo que se pasa a openssl es el nombre de la variable o la ruta, nunca el valor.
#   - openssl nunca se queda esperando en la terminal (stdin = /dev/null): sin contraseña disponible falla con un mensaje claro;
#   - el stderr de openssl no se muestra ni se conserva (se clasifica en un mensaje fijo): no hay filtración de rutas, de valores ni de la contraseña;
#   - las claves sin contraseña siguen funcionando igual (sin --passin).
# Códigos: 0 correcto · 1 no se pudo descifrar · 2 uso inválido · 3 clave protegida sin contraseña.

key_is_protected() {  # PEM cifrado (PKCS#8 «ENCRYPTED PRIVATE KEY» o PEM tradicional con Proc-Type ENCRYPTED)
  grep -q -E 'BEGIN ENCRYPTED PRIVATE KEY|Proc-Type:.*ENCRYPTED' "$1" 2>/dev/null
}

validate_passin() {  # $1 = especificación (puede ser vacía)
  case "$1" in
    "" | env:?* | file:?* | fd:[0-9]*) return 0 ;;
    pass:*) echo "Rechazado: «pass:» expondría la contraseña en la lista de procesos. Use env:NOMBRE, file:RUTA o fd:N." >&2; return 2 ;;
    *) echo "Formato de --passin no admitido (use env:NOMBRE, file:RUTA o fd:N)." >&2; return 2 ;;
  esac
}

# cms_decrypt_key ENTRADA.cms CLAVE.pem PASSIN SALIDA|-   (SALIDA «-» = stdout, para tuberías sin texto plano en disco)
cms_decrypt_key() {
  local in="$1" key="$2" passin="${3:-}" out="${4:--}" err rc
  [[ -r "$in" ]] || { echo "No se puede leer el archivo cifrado." >&2; return 1; }
  [[ -r "$key" ]] || { echo "No se puede leer la clave privada." >&2; return 1; }
  validate_passin "$passin" || return 2
  if key_is_protected "$key" && [[ -z "$passin" ]]; then
    echo "La clave privada está protegida con contraseña: indique --passin env:NOMBRE | file:RUTA | fd:N." >&2
    return 3
  fi
  local args=(cms -decrypt -binary -inform DER -in "$in" -inkey "$key")
  [[ -n "$passin" ]] && args+=(-passin "$passin")
  [[ "$out" != "-" ]] && args+=(-out "$out")
  err="$(mktemp)"
  set +e; openssl "${args[@]}" 2>"$err" </dev/null; rc=$?; set -e
  if [[ $rc -ne 0 ]]; then
    if grep -q -i -E 'bad decrypt|bad password|Error reading password|PEM routines|unable to load|Could not read|Cannot open|Could not find or decode|unable to get passphrase|UI routines|No environment variable|Error getting password' "$err"; then
      echo "No se pudo abrir la clave privada: contraseña incorrecta, contraseña no disponible (env:/file:/fd:) o clave ilegible." >&2
    elif grep -q -i -E 'cms|recipient|decrypt|asn1' "$err"; then
      echo "No se pudo descifrar: el archivo no corresponde a esta clave o está alterado." >&2
    else
      echo "No se pudo descifrar (error de openssl, código $rc)." >&2
    fi
    rm -f "$err"; return 1
  fi
  rm -f "$err"; return 0
}
