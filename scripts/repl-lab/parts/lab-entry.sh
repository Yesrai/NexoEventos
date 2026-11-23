#!/bin/bash
# Arranque CERRADO de PostgreSQL en el laboratorio: este nodo solo abre el acceso de red a la aplicación si el witness lo declara escritor
# (o si el laboratorio aun no se inicializó: época 0). Si el witness no responde o declara a otro nodo, arranca con un pg_hba que RECHAZA todo acceso
# por red (la administración local por socket sigue disponible). El estado vive en un archivo del volumen de datos, así que sobrevive a reinicios del contenedor.
# (Los signos de dólar van duplicados por el escape de interpolación de Compose.)
HBA=/var/lib/postgresql/lab-hba.conf
mode=fenced; why="el witness no respondió (falla cerrada)"
for try in 1 2 3 4; do
  body=$$( (exec 3<>/dev/tcp/172.29.241.10/8000 && printf 'GET /state HTTP/1.0\r\n\r\n' >&3 && timeout 3 cat <&3) 2>/dev/null )
  [ -n "$$body" ] && break
  sleep 1
done
if [ -n "$$body" ]; then
  if [[ "$$body" =~ \"epoch\":\ *0[,\}] ]]; then mode=open; why="laboratorio sin inicializar (época 0)"
  elif [[ "$$body" =~ \"writer\":\ *\"$$NODE_NAME\" ]]; then mode=open; why="el witness me declara escritor"
  else mode=fenced; why="el witness declara a otro nodo (o a ninguno) como escritor"; fi
fi
if [ "$$mode" = open ]; then
cat > "$$HBA" <<'HBA_OPEN'
local all all trust
host all all 127.0.0.1/32 trust
host all all ::1/128 trust
host all all all scram-sha-256
HBA_OPEN
else
cat > "$$HBA" <<'HBA_FENCED'
local all all trust
host all all all reject
HBA_FENCED
fi
chown postgres:postgres "$$HBA"; chmod 600 "$$HBA"
echo "[lab-entry] $$NODE_NAME arranca en modo $$mode: $$why" >&2
exec docker-entrypoint.sh "$$@" -c "hba_file=$$HBA"
