#!/usr/bin/env python3
"""Ráfagas de login y de registro con sondeos de /ready y del catálogo EN PARALELO (contenedor local, 2 workers, tope de 1 536 MB).

Detecta inanición: si las operaciones Argon2 en espera agotan los hilos o las conexiones del pool, los sondeos (que usa el balanceador como
health check) y el tráfico normal se retrasan o fallan. Uso: python3 perf/login_starvation.py --size 100 --label despues
"""
import argparse, importlib.util, sys, time, threading, statistics, json
from concurrent.futures import ThreadPoolExecutor
import httpx
ARGS=argparse.ArgumentParser(); ARGS.add_argument("--size",type=int,default=100); ARGS.add_argument("--label",required=True); ARGS=ARGS.parse_args()
spec=importlib.util.spec_from_file_location("lb","perf/login_burst.py"); lb=importlib.util.module_from_spec(spec); spec.loader.exec_module(lb)
run=lb.run; NAME=lb.NAME; DB=lb.DB; BASE=lb.BASE; H=lb.HEADERS; PW=lb.PASSWORD
key=next(l.split("=",1)[1].strip() for l in open(".env") if l.startswith("TICKET_ENCRYPTION_KEY="))
run(["docker","compose","up","-d","db"]); 
for _ in range(60):
    if run(["docker","exec","nexoeventos-dev-db-1","pg_isready","-U","postgres"]).returncode==0: break
    time.sleep(1)
run(["docker","exec","nexoeventos-dev-db-1","psql","-U","postgres","-q","-c",f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)","-c",f"CREATE DATABASE {DB} OWNER nexoeventos_owner","-c",f"GRANT CONNECT ON DATABASE {DB} TO nexoeventos_app"])
run(["docker","run","--rm","--network",lb.NETWORK,"-e",f"MIGRATION_DATABASE_URL=postgresql+psycopg://postgres:dev-local-only-admin@db:5432/{DB}","nexoeventos-dev-backend","alembic","upgrade","head"])
run(["docker","rm","-f",NAME])
run(["docker","run","-d","--name",NAME,"--network",lb.NETWORK,"--memory","1536m","--memory-swap","1536m","-p",f"127.0.0.1:{lb.PORT}:8000","-e",f"DATABASE_URL=postgresql+psycopg://nexoeventos_app:dev-local-only-app@db:5432/{DB}","-e",f"TICKET_ENCRYPTION_KEY={key}","-e","FRONTEND_ORIGINS=http://localhost:5173","-e","APP_ENV=development","nexoeventos-dev-backend","uvicorn","app.main:app","--host","0.0.0.0","--port","8000","--workers","2"])
out={}
try:
    for _ in range(100):
        try:
            if httpx.get(f"{BASE}/ready",timeout=1).status_code==200: break
        except httpx.HTTPError: time.sleep(0.3)
    N=ARGS.size; users=[f"s{i}@example.com" for i in range(N)]
    with httpx.Client(base_url=BASE,headers=H,timeout=120) as c:
        for u in users: r=c.post("/api/auth/register",json={"email":u,"display_name":"Sonda","password":PW}); assert r.status_code==201, (r.status_code, r.text[:200])
    def burst(kind):
        probes={"ready":[], "catalogo":[]}; stop=threading.Event()
        def probe():
            with httpx.Client(base_url=BASE,headers=H,timeout=120) as c:
                while not stop.is_set():
                    for name,path in (("ready","/ready"),("catalogo","/api/events")):
                        t=time.perf_counter(); 
                        try: r=c.get(path); code=r.status_code
                        except httpx.HTTPError: code=-1
                        probes[name].append(((time.perf_counter()-t)*1000,code))
                    time.sleep(0.1)
        pt=threading.Thread(target=probe); pt.start(); time.sleep(0.5)
        barrier=threading.Barrier(N); lat=[0]*N; codes=[0]*N; clients=[httpx.Client(base_url=BASE,headers=H,timeout=120) for _ in range(N)]
        def one(i):
            barrier.wait(); t=time.perf_counter()
            try:
                if kind=="login": r=clients[i].post("/api/auth/login",json={"email":users[i],"password":PW})
                else: r=clients[i].post("/api/auth/register",json={"email":f"n{kind}{i}@example.com","display_name":"Nueva","password":PW})
                codes[i]=r.status_code
            except httpx.HTTPError: codes[i]=-1
            lat[i]=(time.perf_counter()-t)*1000
        with ThreadPoolExecutor(N) as p: list(p.map(one,range(N)))
        time.sleep(0.5); stop.set(); pt.join()
        pct=lambda v,q: round(sorted(v)[min(len(v)-1,int(q*(len(v)-1)))])
        res={"n":N,"burst_p50":pct(lat,.5),"burst_max":round(max(lat)),"codes":{str(c):codes.count(c) for c in set(codes)}}
        for k,v in probes.items():
            ls=[x[0] for x in v]; res[k]={"sondeos":len(ls),"p95":pct(ls,.95),"max":round(max(ls)),"no200":sum(1 for x in v if x[1]!=200)}
        return res
    out["login"]=burst("login"); time.sleep(3); out["registro"]=burst("reg")
finally:
    run(["docker","rm","-f",NAME]); run(["docker","exec","nexoeventos-dev-db-1","psql","-U","postgres","-q","-c",f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)"])
import pathlib
dest=pathlib.Path("perf/results")/f"login-starvation-{ARGS.label}"; dest.mkdir(parents=True,exist_ok=True)
(dest/"resultado.json").write_text(json.dumps({"schema":1,"label":ARGS.label,"container_memory_mb":1536,"workers":2,**out},indent=2,ensure_ascii=False)+"\n",encoding="utf-8")
print(json.dumps(out,ensure_ascii=False)); print(f"Resultado en {dest}/resultado.json")
