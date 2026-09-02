"""Prepara el dataset para Kaggle: el modelo contra la etiqueta humana.

**Lo que hace único a este dataset** es que cada fila lleva las dos respuestas.
Hay muchos conjuntos de observaciones de fauna y muchos de clasificación de
imágenes; lo que no abunda es uno donde la etiqueta de quien subió la foto y la
de un clasificador estén enfrentadas, con la confianza del modelo al lado.

Eso permite preguntarse cosas que un dataset de etiquetas solas no admite: qué
especies se confunden entre sí en el campo, si un umbral calibrado en validación
aguanta fuera de su reparto, y cuántos desacuerdos son error del modelo frente a
observaciones mal identificadas.

**Qué NO se publica.** La columna `quien` son nombres de personas que subieron
sus fotos a GBIF para ciencia ciudadana, no para aparecer en un dataset de
Kaggle. Se quita. La URL de la foto sí se queda: es pública, y sin ella nadie
puede reproducir la clasificación.

    python publicar.py            # escribe kaggle/
    python publicar.py --comprobar
"""

import argparse
import json
import pathlib
import sys

AQUI = pathlib.Path(__file__).parent
ALMACEN = AQUI / "datos" / "radar.duckdb"
SALIDA = AQUI / "kaggle"

# Las personas que suben observaciones a GBIF lo hacen para ciencia ciudadana.
# Su nombre no pinta nada en un dataset público de Kaggle, y quitarlo no le
# resta nada al conjunto.
FUERA = ("quien",)


def exportar():
    import duckdb

    if not ALMACEN.exists():
        raise SystemExit(f"No hay almacén en {ALMACEN}. Corre antes: python flujo.py")

    SALIDA.mkdir(exist_ok=True)
    cx = duckdb.connect(str(ALMACEN), read_only=True)

    columnas = [c[0] for c in cx.execute("describe observaciones").fetchall()
                if c[0] not in FUERA]
    lista = ", ".join(columnas)

    # Solo lo que el modelo llegó a mirar: una fila sin clasificar no aporta
    # nada al propósito del dataset y confundiría a quien lo use.
    cx.execute(f"""
        COPY (SELECT {lista} FROM observaciones
              WHERE modelo_dice IS NOT NULL
              ORDER BY cuando DESC, clave)
        TO '{(SALIDA / "observaciones.csv").as_posix()}'
        (HEADER, DELIMITER ',')
    """)
    cx.execute(f"""
        COPY (SELECT * FROM por_especie ORDER BY observaciones DESC)
        TO '{(SALIDA / "por_especie.csv").as_posix()}' (HEADER, DELIMITER ',')
    """)

    n = cx.execute("SELECT count(*) FROM observaciones "
                   "WHERE modelo_dice IS NOT NULL").fetchone()[0]
    esp = cx.execute("SELECT count(*) FROM por_especie").fetchone()[0]
    ok = cx.execute("SELECT count(*) FROM observaciones WHERE coincide").fetchone()[0]
    cx.close()

    (SALIDA / "dataset-metadata.json").write_text(json.dumps({
        "title": "Riksi Radar: modelo vs etiqueta humana en fauna del Ecuador",
        "id": "PONER_USUARIO/riksi-radar-ecuador",
        "licenses": [{"name": "CC-BY-SA-4.0"}],
        "keywords": ["biology", "computer-vision", "ecuador", "biodiversity",
                     "model-evaluation", "citizen-science"],
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    (SALIDA / "README.md").write_text(_ficha(n, esp, ok), encoding="utf-8")
    print(f"  {n} observaciones · {esp} especies · {ok} coinciden ({100*ok/n:.0f}%)")
    print(f"  escrito en {SALIDA.name}/: " +
          ", ".join(sorted(f.name for f in SALIDA.iterdir())))
    return n


def _ficha(n, esp, ok):
    return f"""# Riksi Radar: el modelo contra la etiqueta humana

{n} observaciones de fauna y flora del Ecuador, cada una con **dos respuestas a
la misma pregunta**: la especie que puso quien subió la foto a GBIF, y la que
vio un clasificador que nunca supo esa etiqueta.

Coinciden en {100*ok/n:.0f} % de los casos. Lo interesante es el resto.

## Por qué existe

Hay muchos datasets de observaciones de fauna y muchos de clasificación de
imágenes. Lo que no abunda es uno donde las dos etiquetas estén enfrentadas con
la confianza del modelo al lado, que es lo que permite preguntarse:

- ¿Qué especies se confunden entre sí **en el campo**, no en un banco de prueba?
- ¿Un umbral calibrado en validación aguanta fuera de su reparto?
- De los desacuerdos, ¿cuántos son error del modelo y cuántos observaciones mal
  identificadas?

El dataset no responde esa última: guarda las dos versiones y deja la pregunta
abierta, porque decidir quién tiene razón no le corresponde a un pipeline.

## Las columnas

| | |
|---|---|
| `especie` | lo que dice GBIF: la etiqueta de quien subió la foto |
| `modelo_dice` | lo que vio el clasificador, sin conocer la anterior |
| `confianza` | cuánta le dio a su primera candidata, de 0 a 1 |
| `seguro` | si superó el umbral calibrado del modelo (0,20) |
| `en_top3` | si la etiqueta de GBIF estaba entre sus tres candidatas |
| `coincide` | si `especie == modelo_dice` |
| `provincia`, `sitio`, `latitud`, `longitud`, `altura` | dónde |
| `cuando` | fecha de la observación |
| `foto` | URL pública de la imagen, para reproducir la clasificación |
| `licencia` | la de la foto, que es de quien la tomó |

`por_especie.csv` agrega lo mismo por especie: cuántas observaciones, cuántas
acierta, y el acierto **cuando el modelo dice estar seguro**, que es el número
que de verdad importa.

## Lo que sale de mirarlo

**El umbral funciona.** El modelo acierta un 85 % cuando dice estar seguro y un
33 % cuando no. El umbral no existe para que responda siempre, sino para que las
respuestas dadas sean fiables.

**Los desacuerdos tienen sentido biológico**, no son ruido:

- *Chelonoidis niger* contra *Chelonoidis porteri*: dos tortugas de Galápagos con
  la taxonomía **en disputa entre biólogos**.
- *Amblyrhynchus cristatus* contra *Microlophus albemarlensis*: iguana marina y
  lagartija de lava, que comparten roca y postura.
- *Apis mellifera* contra *Xylocopa darwini*: abeja europea contra carpintera.

**Y no hay deriva.** El mismo modelo acierta 78,0 % en su banco de validación y
84,2 % aquí, sobre fotos que se subieron después y de gente distinta. Que suba no
significa que el modelo haya mejorado: significa que al campo llegan sobre todo
especies fáciles y muy fotografiadas.

## Qué NO está aquí

El nombre de quien subió cada observación. Esas personas suben sus fotos a GBIF
para ciencia ciudadana, no para aparecer en un dataset de Kaggle.

## De dónde sale

El pipeline que lo genera está en
[riksi-radar](https://github.com/DiegoFernandoLojanTenesaca/riksi-radar): Kafka
para el flujo, DuckDB como almacén y dbt para el modelado. El clasificador es
[Riksi](https://github.com/DiegoFernandoLojanTenesaca/riski), un
EfficientNet-Lite0 de 3,8 MB que corre en el navegador.

Observaciones y fotos de [GBIF](https://www.gbif.org), cada una con la licencia
que le puso quien la tomó — está en la columna `licencia`.
"""


def prueba():
    """Que lo exportado no lleve datos personales y cuadre con el almacén."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    import csv

    n = exportar()
    csv_obs = SALIDA / "observaciones.csv"
    with csv_obs.open(encoding="utf-8") as f:
        filas = list(csv.DictReader(f))

    assert len(filas) == n, f"el CSV tiene {len(filas)} filas y el almacén {n}"

    # Lo que no puede estar: el nombre de quien subió la foto.
    assert "quien" not in filas[0], "se coló la columna con nombres de personas"

    # Y lo que sí, porque sin ello el dataset no sirve para lo que promete.
    for c in ("especie", "modelo_dice", "confianza", "seguro", "coincide", "foto"):
        assert c in filas[0], f"falta la columna {c}"

    assert all(f["modelo_dice"] for f in filas), \
        "hay filas sin clasificar: no aportan nada y confunden"

    # La licencia de cada foto viaja con ella: publicar la URL sin decir bajo qué
    # licencia está sería dejar el problema a quien use el dataset.
    con_licencia = sum(1 for f in filas if f.get("licencia"))
    assert con_licencia > len(filas) * 0.9, \
        f"solo {con_licencia}/{len(filas)} traen licencia"

    print(f"ok · {len(filas)} filas · sin nombres de personas · "
          f"{con_licencia} con licencia · {len(filas[0])} columnas")


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--comprobar", action="store_true")
    args = a.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    prueba() if args.comprobar else exportar()


if __name__ == "__main__":
    main()
