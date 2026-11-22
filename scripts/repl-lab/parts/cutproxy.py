"""Proxy de FALLA para el laboratorio: reenvía HTTP a app-aws y, si la petición trae `X-Lab-Drop-Response: 1`, RETIENE la respuesta (la app ya confirmó en la BD)
hasta que el control la suelte: `drop` corta la conexión del cliente sin enviar nada. Control: GET :8001/held · POST :8001/release?mode=drop|forward."""
import asyncio

UP = ("app-aws", 8000)
S = {"held": 0, "mode": None}
REL = None


async def read_http(r):
    head = await r.readuntil(b"\r\n\r\n")
    n = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            n = int(line.split(b":")[1])
    return head, (await r.readexactly(n) if n else b"")


async def handle(cr, cw):
    global REL
    try:
        head, body = await read_http(cr)
        drop = b"x-lab-drop-response: 1" in head.lower()
        ur, uw = await asyncio.open_connection(*UP)
        uw.write(head + body); await uw.drain()
        rh, rb = await read_http(ur)
        uw.close()
        if drop:
            REL = asyncio.Event(); S["held"] += 1; S["mode"] = None
            await REL.wait()
            if S["mode"] == "drop":
                cw.transport.abort(); return
        cw.write(rh + rb); await cw.drain()
    except Exception:
        pass
    finally:
        try:
            cw.close()
        except Exception:
            pass


async def control(cr, cw):
    global REL
    try:
        head, _ = await read_http(cr)
        line = head.split(b"\r\n")[0].decode()
        if "/release" in line:
            S["mode"] = "drop" if "mode=drop" in line else "forward"
            if REL: REL.set()
            out = b'{"released":true}'
        else:
            out = ('{"held":%d}' % S["held"]).encode()
        cw.write(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: %d\r\nConnection: close\r\n\r\n" % len(out) + out); await cw.drain()
    except Exception:
        pass
    finally:
        cw.close()


async def main():
    a = await asyncio.start_server(handle, "0.0.0.0", 8000)
    b = await asyncio.start_server(control, "0.0.0.0", 8001)
    async with a, b:
        await asyncio.gather(a.serve_forever(), b.serve_forever())

asyncio.run(main())
