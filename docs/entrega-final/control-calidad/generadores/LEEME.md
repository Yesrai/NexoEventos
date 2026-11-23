# Generadores del paquete final

Scripts usados para construir el informe, los anexos, el inventario, la matriz, los gráficos y el ZIP (ejecutados desde un entorno virtual temporal con python-docx, matplotlib, PyMuPDF y openpyxl; LibreOffice 26.8 para actualizar índices y exportar a PDF mediante `lo_update.sh`). Leen las fuentes en modo solo lectura; las rutas absolutas corresponden al equipo de la autora. Orden: `inventario.py` → `graficos.py` → `inventario.py` → `matriz.py` → `informe.py` → `anexos.py` → `lo_update.sh` (informe y anexos) → `finalizar.py` → `qc.py`. No se incluyen en el ZIP.
