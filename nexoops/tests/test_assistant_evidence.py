from nexoops.assistant import diagnose


def test_diagnostico_traza_hipotesis_a_hechos_y_no_ejecuta():
    overview = {
        "collector": {"status": "ok", "detail": "vigente", "observed_at": "2026-11-23T03:00:00Z"},
        "clouds": {"aws": {"estado": "ERROR", "detalle": "ready=503", "observed_at": "2026-11-23T03:00:00Z"}},
    }
    recovery = {"barreras": {"barriers": []}, "fencing": None, "epoch_autorizado": None, "generated_at": "2026-11-23T03:00:00Z"}
    problems = {"status": "ok", "data": {"problems": []}, "observed_at": "2026-11-23T03:00:01Z"}
    result = diagnose("incidentes de AWS", overview, recovery, problems)
    ids = {f["id"] for f in result["hechos"]}
    assert all(f["type"] == "hecho" and f["source"] for f in result["hechos"])
    assert result["hipotesis"] and all(h["type"] == "hipotesis" and set(h["based_on"]) <= ids for h in result["hipotesis"])
    assert all(r["execution"] == "no_ejecutada" for r in result["recomendaciones"])
    assert result["borrador_solicitud"]["nota"].startswith("Borrador: NO se envió")


def test_diagnostico_degrada_con_entradas_incompletas_sin_inventar():
    result = diagnose("estado", {}, {}, {})
    assert result["engine"] == "determinista (reglas)"
    assert result["hechos"][0]["source"] == "Recolector T4"
    assert any("no entrega datos" in f["text"] for f in result["hechos"])
    assert result["llm"]["estado"] == "pendiente"

