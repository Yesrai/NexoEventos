import markdown,re,sys,pathlib
src=pathlib.Path('informe-entregable2.md').read_text()
html=markdown.markdown(src,extensions=['tables','sane_lists'])
css="""body{font-family:Helvetica,Arial,sans-serif;font-size:10.5pt;line-height:1.35;color:#111;margin:0}
h1{font-size:20pt;color:#12355b}h2{font-size:15pt;color:#12355b;border-bottom:1px solid #12355b;margin-top:22pt}h3{font-size:12pt;color:#12355b}
table{border-collapse:collapse;width:100%;margin:8pt 0;font-size:8.5pt}th,td{border:1px solid #999;padding:3pt 4pt;vertical-align:top}th{background:#dfe8f3}
img{max-width:100%;height:auto}code{font-family:Menlo,monospace;font-size:8.5pt;background:#f2f2f2}a{color:#12355b}
@page{size:A4;margin:16mm 14mm}tr{page-break-inside:avoid}img{page-break-inside:avoid}"""
pathlib.Path('_build.html').write_text(f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Entregable 2 — NexoEventos</title><style>{css}</style></head><body>{html}</body></html>')
