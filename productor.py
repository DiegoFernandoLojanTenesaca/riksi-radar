"""Lee las observaciones nuevas de GBIF y las emite a Kafka.

**Filtra en la consulta, no después.** Ecuador recibe unas 130.000 observaciones
al día y el modelo de Riksi conoce cien especies: medido sobre seis días,
**solo el 1,6%** del flujo general cae en ellas. Tragarse los 130.000 para tirar
el 98% sería malgastar una API que es de otros; GBIF acepta varias especies por
consulta, así que se le pide exactamente lo que sirve. Aun así son unos 6.000
registros diarios: flujo de sobra para que Kafka tenga sentido.

**Y recuerda lo que ya emitió.** GBIF reindexa registros viejos, así que la
misma observación reaparece en consultas de días distintos. Sin memoria, cada
pasada volvería a emitir lo mismo y el almacén contaría dos veces la misma ave.

    python productor.py --dias 3          # lo subido en los últimos 3 días
    python productor.py --comprobar       # sin tocar Kafka ni la red
"""

import argparse
import json
import os
import pathlib
import sqlite3
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

AQUI = pathlib.Path(__file__).parent
VISTOS = AQUI / "datos" / "vistos.db"
# La ruta sale del entorno, con la de esta máquina como respaldo. Estaba fija y
# el CI no podía correr: allí el modelo se clona en /tmp, y una ruta de Windows
# escrita a mano no existe en ningún otro sitio.
CLASES = pathlib.Path(os.environ.get(
    "RIKSI_MODELO", r"D:\CLAUDE PROYECTOS\riksi\docs\modelo")) / "clases.json"

GBIF = "https://api.gbif.org/v1"
AGENTE = "riksi-radar/0.1 (https://github.com/DiegoFernandoLojanTenesaca)"
TEMA = "observaciones"

# Cuántas especies por consulta. GBIF acepta repetir el parámetro, pero una URL
# con las cien se vuelve enorme y el servidor tarda más en responderla. Con 20
# tarda unos doce segundos, que es aceptable.
POR_TANDA = 20

# Página de GBIF. El máximo es 300 y pedir menos multiplica las peticiones.
PAGINA = 300


def _pedir(ruta, intentos=4, **params):
    """Una consulta a GBIF, con reintentos.

    GBIF corta la conexión de vez en cuando y sin reintento una descarga larga
    se pierde entera por un tropiezo de red.
    """
    pares = [(k, v) for k, vs in params.items()
             for v in (vs if isinstance(vs, list) else [vs])]
    url = f"{GBIF}/{ruta}?{urllib.parse.urlencode(pares)}"
    for n in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(req, timeout=90) as r:
                return json.load(r)
        except Exception:
            if n == intentos - 1:
                raise
            time.sleep(2 ** n)


def _bd():
    VISTOS.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(VISTOS)
    cx.execute("CREATE TABLE IF NOT EXISTS vistos ("
               "clave TEXT PRIMARY KEY, cuando REAL NOT NULL)")
    cx.commit()
    return cx


def especies():
    """Las cien que el modelo reconoce, con el nombre que usa GBIF."""
    clases = json.loads(CLASES.read_text(encoding="utf-8"))
    return [c.replace("_", " ") for c in clases]


def _limpiar(oc):
    """De la ficha de GBIF a lo que de verdad se necesita aguas abajo.

    GBIF devuelve más de cien campos por observación y casi todos sobran. Se
    emite lo justo: quién, dónde, cuándo y la foto, que es lo que el
    clasificador necesita.
    """
    fotos = [m.get("identifier") for m in (oc.get("media") or [])
             if m.get("type") == "StillImage" and m.get("identifier")]
    return {
        "clave": str(oc.get("key")),
        "especie": oc.get("species"),
        "cuando": (oc.get("eventDate") or "")[:10],
        "provincia": oc.get("stateProvince"),
        "sitio": oc.get("locality"),
        "latitud": oc.get("decimalLatitude"),
        "longitud": oc.get("decimalLongitude"),
        "altura": oc.get("elevation"),
        "quien": oc.get("recordedBy"),
        "conjunto": oc.get("datasetName"),
        "licencia": oc.get("license"),
        "foto": fotos[0] if fotos else None,
        "visto_en": time.time(),
    }


def buscar(dias=1, tope=None):
    """Las observaciones subidas en los últimos `dias`, de las cien especies."""
    hasta = date.today()
    desde = hasta - timedelta(days=dias)
    rango = f"{desde.isoformat()},{hasta.isoformat()}"
    todas, lista = [], especies()

    for i in range(0, len(lista), POR_TANDA):
        tanda = lista[i:i + POR_TANDA]
        desplazamiento = 0
        while True:
            d = _pedir("occurrence/search", country="EC", scientificName=tanda,
                       lastInterpreted=rango, mediaType="StillImage",
                       limit=PAGINA, offset=desplazamiento)
            filas = d.get("results", [])
            todas += filas
            desplazamiento += len(filas)
            if d.get("endOfRecords", True) or not filas:
                break
            if tope and len(todas) >= tope:
                return todas[:tope]
        print(f"  especies {i+1}-{i+len(tanda)}: {desplazamiento} registros",
              file=sys.stderr)
    return todas[:tope] if tope else todas


def emitir(dias=1, tope=None, servidor="localhost:9092"):
    """Busca, descarta lo ya visto y manda lo nuevo a Kafka."""
    from kafka import KafkaProducer

    crudas = buscar(dias, tope)
    cx = _bd()
    ya = {f[0] for f in cx.execute("SELECT clave FROM vistos")}

    productor = KafkaProducer(
        bootstrap_servers=servidor,
        value_serializer=lambda v: json.dumps(v, ensure_ascii=False).encode("utf-8"),
        # La clave decide la partición: con la especie, todas las observaciones
        # de un ave caen en la misma y se leen en orden. Aquí da igual con una
        # partición, pero es lo que hace que el día que haya varias no cambie
        # nada aguas abajo.
        key_serializer=lambda k: (k or "").encode("utf-8"),
        acks="all",
    )

    nuevas = repetidas = sin_foto = 0
    for oc in crudas:
        m = _limpiar(oc)
        if m["clave"] in ya:
            repetidas += 1
            continue
        if not m["foto"]:
            sin_foto += 1
            continue
        productor.send(TEMA, key=m["especie"], value=m)
        cx.execute("INSERT OR REPLACE INTO vistos VALUES (?,?)",
                   (m["clave"], time.time()))
        ya.add(m["clave"])
        nuevas += 1

    productor.flush()
    productor.close()
    cx.commit()
    cx.close()

    print(f"\n{len(crudas)} de GBIF · {nuevas} emitidas · {repetidas} ya vistas "
          f"· {sin_foto} sin foto")
    return nuevas


# Una observación de verdad, recortada. Sirve para comprobar `_limpiar` sin red.
EJEMPLO = {
    "key": 4512345678, "species": "Sula nebouxii", "eventDate": "2026-08-30T09:15:00",
    "stateProvince": "Galápagos", "locality": "Isla Española",
    "decimalLatitude": -1.37, "decimalLongitude": -89.66, "elevation": 12,
    "recordedBy": "A. Ruiz", "datasetName": "iNaturalist research-grade",
    "license": "http://creativecommons.org/licenses/by-nc/4.0/",
    "media": [{"type": "StillImage", "identifier": "https://ejemplo/foto.jpg"}],
}


def prueba():
    """Lo único con lógica propia: el recorte y que la memoria no repita."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    m = _limpiar(EJEMPLO)
    assert m["clave"] == "4512345678" and m["especie"] == "Sula nebouxii", m
    assert m["cuando"] == "2026-08-30", "la fecha tiene que venir recortada al día"
    assert m["foto"] == "https://ejemplo/foto.jpg", m

    # Sin foto no sirve: el clasificador no tiene qué mirar.
    assert _limpiar({**EJEMPLO, "media": []})["foto"] is None

    # Y un vídeo no es una foto, aunque venga en el mismo campo.
    solo_video = _limpiar({**EJEMPLO, "media": [
        {"type": "MovingImage", "identifier": "https://ejemplo/v.mp4"}]})
    assert solo_video["foto"] is None, "coló un vídeo como si fuera foto"

    esp = especies()
    assert len(esp) == 100 and "Sula nebouxii" in esp, len(esp)
    assert "_" not in "".join(esp), "GBIF usa espacios, no guiones bajos"

    # La memoria: la misma observación no se emite dos veces. GBIF reindexa
    # registros viejos y sin esto el almacén contaría dos veces la misma ave.
    global VISTOS
    VISTOS = AQUI / "datos" / "prueba-vistos.db"
    VISTOS.unlink(missing_ok=True)
    cx = _bd()
    cx.execute("INSERT INTO vistos VALUES (?,?)", ("4512345678", time.time()))
    cx.commit()
    ya = {f[0] for f in cx.execute("SELECT clave FROM vistos")}
    assert m["clave"] in ya, "la memoria no reconoce lo que acaba de guardar"
    cx.close()
    VISTOS.unlink(missing_ok=True)

    print(f"ok · el recorte deja {len(m)} campos · descarta vídeos y lo que no "
          f"trae foto · {len(esp)} especies · la memoria evita repetir")


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--dias", type=int, default=1)
    a.add_argument("--tope", type=int, help="para probar sin bajarlo todo")
    a.add_argument("--servidor", default="localhost:9092")
    a.add_argument("--comprobar", action="store_true")
    args = a.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.comprobar:
        return prueba()
    emitir(args.dias, args.tope, args.servidor)


if __name__ == "__main__":
    main()
