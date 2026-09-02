"""Lee de Kafka, clasifica la foto y guarda el resultado en DuckDB.

**Aquí es donde el radar hace algo que GBIF no hace.** Cada observación llega
con la especie que le puso quien la subió y con la URL de su foto. El modelo de
Riksi mira la foto sin saber esa etiqueta, y las dos respuestas se guardan
juntas.

Cuando coinciden, no hay noticia. Cuando no, hay exactamente tres explicaciones
y ninguna es aburrida: el modelo se equivocó, la observación está mal
identificada, o la foto no muestra lo que dice el registro. **El radar no decide
cuál**; guarda las dos versiones y la confianza, y deja que eso se mire después.
Un pipeline que resolviera el desacuerdo por su cuenta estaría inventando una
autoridad que no tiene.

    python consumidor.py --comprobar      # sin red ni Kafka
    python consumidor.py --tope 50        # consume 50 y para
"""

import argparse
import io
import json
import pathlib
import sys
import time
import urllib.request
from functools import lru_cache

import numpy as np

AQUI = pathlib.Path(__file__).parent
ALMACEN = AQUI / "datos" / "radar.duckdb"
MODELO = pathlib.Path(r"D:\CLAUDE PROYECTOS\riksi\docs\modelo")

TEMA = "observaciones"
AGENTE = "riksi-radar/0.1 (https://github.com/DiegoFernandoLojanTenesaca)"

# **El tamaño de la foto es lo que decide la velocidad del pipeline.** La URL
# que da GBIF apunta al original, y medido son de 640 KB a 1,7 MB: 23 segundos
# por foto, contra 0,16 que tarda el modelo en mirarla. El cuello de botella no
# es la inferencia, es la descarga.
#
#     original   640-1.700 KB            18-23 s
#     large            181 KB · 768 px    1,95 s   ← este
#     medium            53 KB · 375 px    6,60 s
#     small             17 KB · 180 px    1,02 s
#
# `large` a 768 px entra holgado en el recorte de 288 que hace el modelo.
# `medium`, a 375, dejaría el recorte al borde del original y `small` obligaría
# a ampliar, que es introducir borrosidad que el entrenamiento nunca vio.
TAMANO = "large"


@lru_cache(maxsize=1)
def _riksi():
    """El modelo de Riksi. Se referencia, no se copia.

    Son 3,8 MB que ya están versionados en su repositorio y que cambian cuando
    se reentrena allí. Copiarlos aquí crearía dos verdades que se separan.
    """
    import onnxruntime as ort

    sesion = ort.InferenceSession(str(MODELO / "riksi-int8.onnx"),
                                  providers=["CPUExecutionProvider"])
    leer = lambda n: json.loads((MODELO / n).read_text(encoding="utf-8"))
    return (sesion, leer("clases.json"), leer("preprocesado.json"),
            leer("umbral.json")["umbral"])


def _preparar(datos, pre):
    """El mismo preprocesado que usó el entrenamiento.

    Si difiere, el modelo no falla: acierta menos, que es peor porque no se nota
    y se le echa la culpa al modelo.
    """
    from PIL import Image

    im = Image.open(io.BytesIO(datos)).convert("RGB")
    escala = pre["resize"] / min(im.size)
    im = im.resize((round(im.width * escala), round(im.height * escala)),
                   Image.BILINEAR)
    tam = pre["tam"]
    izq, arriba = (im.width - tam) // 2, (im.height - tam) // 2
    im = im.crop((izq, arriba, izq + tam, arriba + tam))
    x = np.asarray(im, dtype=np.float32) / 255.0
    x = (x - np.array(pre["media"], dtype=np.float32)) / np.array(pre["desv"], dtype=np.float32)
    return x.transpose(2, 0, 1)[None]


def bajar(url, intentos=3):
    """La foto, en un tamaño razonable. None si no se pudo.

    iNaturalist sirve variantes cambiando el último tramo de la URL. GBIF
    siempre apunta al original, que pesa diez veces más de lo necesario.
    """
    for grande in ("original.jpg", "original.jpeg", "original.png"):
        if url.endswith(grande):
            url = url[:-len(grande)] + f"{TAMANO}.jpg"
            break
    for n in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read()
        except Exception:
            if n == intentos - 1:
                return None
            time.sleep(1.5 ** n)


def clasificar(datos):
    """Qué ve el modelo en la foto: las tres candidatas y si está seguro."""
    sesion, clases, pre, umbral = _riksi()
    salida = sesion.run(None, {sesion.get_inputs()[0].name: _preparar(datos, pre)})[0][0]
    e = np.exp(salida - salida.max())
    probs = e / e.sum()
    top = np.argsort(-probs)[:3]
    return {
        "dice": clases[top[0]].replace("_", " "),
        "confianza": round(float(probs[top[0]]), 4),
        "seguro": bool(probs[top[0]] >= umbral),
        "top3": [clases[i].replace("_", " ") for i in top],
    }


ESQUEMA = """
CREATE TABLE IF NOT EXISTS observaciones (
    clave        VARCHAR PRIMARY KEY,
    especie      VARCHAR,          -- lo que dice GBIF
    cuando       DATE,
    provincia    VARCHAR,
    sitio        VARCHAR,
    latitud      DOUBLE,
    longitud     DOUBLE,
    altura       INTEGER,
    quien        VARCHAR,
    conjunto     VARCHAR,
    licencia     VARCHAR,
    foto         VARCHAR,

    -- Lo que ve el modelo, sin haber visto la etiqueta.
    modelo_dice  VARCHAR,
    confianza    DOUBLE,
    seguro       BOOLEAN,
    en_top3      BOOLEAN,          -- ¿la etiqueta de GBIF está entre las tres?
    coincide     BOOLEAN,          -- ¿coincide con la primera?
    clasificada  TIMESTAMP
);
"""


def _almacen():
    import duckdb

    ALMACEN.parent.mkdir(parents=True, exist_ok=True)
    cx = duckdb.connect(str(ALMACEN))
    cx.execute(ESQUEMA)
    return cx


def _guardar(cx, m, visto):
    """Una fila con las dos versiones: la de GBIF y la del modelo."""
    cx.execute(
        "INSERT OR REPLACE INTO observaciones VALUES "
        "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [m["clave"], m["especie"], m["cuando"] or None, m["provincia"], m["sitio"],
         m["latitud"], m["longitud"], m["altura"], m["quien"], m["conjunto"],
         m["licencia"], m["foto"],
         visto["dice"] if visto else None,
         visto["confianza"] if visto else None,
         visto["seguro"] if visto else None,
         (m["especie"] in visto["top3"]) if visto else None,
         (m["especie"] == visto["dice"]) if visto else None,
         time.strftime("%Y-%m-%d %H:%M:%S")])


def consumir(tope=None, servidor="localhost:9092", grupo="radar"):
    from kafka import KafkaConsumer

    consumidor = KafkaConsumer(
        TEMA, bootstrap_servers=servidor, group_id=grupo,
        auto_offset_reset="earliest", consumer_timeout_ms=20000,
        # Se confirma a mano después de guardar: con el autocommit, un fallo
        # entre leer y escribir daría el mensaje por procesado sin estarlo.
        enable_auto_commit=False,

        # **Lotes pequeños, porque procesar cada mensaje cuesta segundos.** Por
        # defecto Kafka entrega 500 por `poll()` y espera que el siguiente
        # llegue en 5 minutos; a 2 s por foto eso son 17 minutos, así que el
        # broker daba al consumidor por muerto, reasignaba las particiones y el
        # `commit` fallaba con «the group has already rebalanced».
        #
        # Es el fallo típico de meter trabajo lento dentro del bucle de Kafka:
        # no aparece en pruebas cortas y revienta con volumen. Con lotes de 20 y
        # quince minutos de margen hay sitio de sobra.
        max_poll_records=20,
        max_poll_interval_ms=900_000,
        value_deserializer=lambda v: json.loads(v.decode("utf-8")))

    cx = _almacen()
    n = aciertos = desacuerdos = sin_foto = dudosas = 0

    for msj in consumidor:
        m = msj.value
        datos = bajar(m["foto"]) if m.get("foto") else None
        visto = clasificar(datos) if datos else None

        _guardar(cx, m, visto)
        n += 1
        if not visto:
            sin_foto += 1
        elif not visto["seguro"]:
            dudosas += 1
        elif m["especie"] == visto["dice"]:
            aciertos += 1
        else:
            desacuerdos += 1
            print(f"  ~ {m['especie']:<28} el modelo ve {visto['dice']:<28} "
                  f"({visto['confianza']:.0%})")

        consumidor.commit()
        if tope and n >= tope:
            break

    consumidor.close()
    ciertas = aciertos + desacuerdos
    print(f"\n{n} procesadas · {aciertos} coinciden · {desacuerdos} en desacuerdo "
          f"· {dudosas} sin confianza · {sin_foto} sin foto")
    if ciertas:
        print(f"  de las {ciertas} que el modelo dio por seguras, coincide en "
              f"{100*aciertos/ciertas:.0f}%")
    cx.close()
    return n


def prueba():
    """Lo único con lógica propia: el modelo y el almacén, sin red ni Kafka."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    # El modelo, sobre una foto que Riksi ya usa de prueba: si el preprocesado
    # se desviara, esto acertaría menos y nadie se enteraría.
    foto = pathlib.Path(r"D:\CLAUDE PROYECTOS\riksi\docs\prueba\1677344033_196.jpg")
    visto = clasificar(foto.read_bytes())
    assert visto["dice"] == "Aglaeactis cupripennis", visto
    assert visto["confianza"] > 0.7 and visto["seguro"], visto
    assert len(visto["top3"]) == 3, visto

    # El almacén: que guarde las dos versiones y sepa distinguirlas.
    global ALMACEN
    ALMACEN = AQUI / "datos" / "prueba.duckdb"
    ALMACEN.unlink(missing_ok=True)
    cx = _almacen()

    base = {"clave": "1", "especie": "Aglaeactis cupripennis", "cuando": "2026-08-30",
            "provincia": "Pichincha", "sitio": None, "latitud": -0.2, "longitud": -78.5,
            "altura": 3000, "quien": "x", "conjunto": "y", "licencia": "z",
            "foto": "https://ejemplo/f.jpg"}
    _guardar(cx, base, visto)
    _guardar(cx, {**base, "clave": "2", "especie": "Sula nebouxii"}, visto)

    filas = cx.execute("SELECT clave, coincide, en_top3 FROM observaciones "
                       "ORDER BY clave").fetchall()
    assert filas[0][1] is True, "la etiqueta correcta debería coincidir"
    assert filas[1][1] is False, "una etiqueta distinta NO puede dar coincidencia"
    assert filas[1][2] is False, "y tampoco estar en el top3"

    # Insertar dos veces la misma clave no puede duplicar la fila: Kafka puede
    # reentregar un mensaje si el proceso muere antes de confirmar.
    _guardar(cx, base, visto)
    assert cx.execute("SELECT count(*) FROM observaciones").fetchone()[0] == 2, \
        "una reentrega duplicó la fila"

    cx.close()
    ALMACEN.unlink(missing_ok=True)
    print(f"ok · el modelo ve {visto['dice']} ({visto['confianza']:.0%}) · "
          f"el almacén distingue las dos versiones · una reentrega no duplica")


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--tope", type=int)
    a.add_argument("--servidor", default="localhost:9092")
    a.add_argument("--grupo", default="radar")
    a.add_argument("--comprobar", action="store_true")
    args = a.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.comprobar:
        return prueba()
    consumir(args.tope, args.servidor, args.grupo)


if __name__ == "__main__":
    main()
