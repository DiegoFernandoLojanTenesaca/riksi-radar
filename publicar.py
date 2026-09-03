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

    # **Los metadatos no son adorno: Kaggle calcula con ellos una nota de
    # usabilidad**, y un dataset sin subtítulo ni descripción de sus ficheros
    # aparece con 3,5 sobre 10 aunque los datos sean buenos. Cada campo de aquí
    # responde a uno de los avisos que Kaggle muestra al publicar.
    (SALIDA / "dataset-metadata.json").write_text(json.dumps({
        # El título va corto porque Kaggle lo limita a 50 caracteres.
        "title": "Riksi Radar: modelo vs humano en fauna EC",
        "id": "diegofernandoljtn/riksi-radar-ecuador",
        # Entre 20 y 80 caracteres: Kaggle rechaza la version si se pasa.
        "subtitle": "400 observaciones del Ecuador: la etiqueta humana "
                    "contra la del modelo",
        "description": _descripcion(n, esp, ok),
        "licenses": [{"name": "CC-BY-SA-4.0"}],

        # **La portada va aquí, no se sube como fichero.** Kaggle la trata como
        # metadato: `dataset_metadata_update` la lee de este campo y la sube
        # aparte. Dejarla suelta en la carpeta la publica como un CSV más y la
        # portada sigue siendo la genérica.
        "image": "portada.png",
        # **Kaggle no acepta etiquetas inventadas**: son un vocabulario cerrado
        # y rechaza la actualizacion entera si una no existe. «biodiversity» o
        # «citizen-science» suenan razonables y no estan.
        "keywords": ["biology", "computer vision", "classification",
                     "animals", "south america"],

        # Los cuatro campos que Kaggle pide y que suben la nota de usabilidad.
        # No son burocracia: quien descarga un dataset necesita saber de dónde
        # salieron los datos y si van a seguir creciendo.
        "userSpecifiedSources": (
            "Observaciones y fotografías de GBIF (gbif.org), filtradas a Ecuador "
            "y a las 100 especies que el clasificador reconoce. Cada foto se "
            "pasó por el modelo sin dejarle ver la etiqueta que traía. Las "
            "fotos son de quienes las tomaron, cada una con su licencia en la "
            "columna correspondiente."),
        "collectionMethodology": (
            "Un pipeline de streaming toma las observaciones nuevas de la API "
            "de GBIF, las emite a Kafka y un consumidor descarga cada foto y la "
            "clasifica con el modelo de Riksi, un EfficientNet-Lite0 de 3,8 MB. "
            "Las dos etiquetas y la confianza se guardan en DuckDB y dbt las "
            "modela. El código está en github.com/DiegoFernandoLojanTenesaca/"
            "riksi-radar y se puede reproducir entero."),
        "expectedUpdateFrequency": "quarterly",
        # **En `resources` y no en `data`.** El cliente convierte el primero al
        # segundo -renombrando `path` a `name` y `schema.fields` a `columns`-,
        # pero solo si `data` no existe. Poniéndolo ya en `data` con la forma de
        # `resources`, la conversión se salta y las descripciones se pierden sin
        # que nada avise.
        "resources": [
            {
                "path": "observaciones.csv",
                "description": f"Las {n} observaciones, una por fila, con la "
                               f"etiqueta de GBIF y la del modelo enfrentadas.",
                "schema": {"fields": [
                    {"name": "clave", "description": "Identificador de la observación en GBIF."},
                    {"name": "especie", "description": "La especie que puso quien subió la foto."},
                    {"name": "cuando", "description": "Fecha de la observación."},
                    {"name": "provincia", "description": "Provincia del Ecuador, normalizada."},
                    {"name": "sitio", "description": "Localidad, cuando el registro la trae."},
                    {"name": "latitud", "description": "Grados decimales."},
                    {"name": "longitud", "description": "Grados decimales."},
                    {"name": "altura", "description": "Metros sobre el nivel del mar, cuando consta."},
                    {"name": "conjunto", "description": "Colección de GBIF de la que procede."},
                    {"name": "licencia", "description": "La de la foto, que es de quien la tomó."},
                    {"name": "foto", "description": "URL pública de la imagen clasificada."},
                    {"name": "modelo_dice", "description": "La especie que vio el clasificador, sin conocer la etiqueta."},
                    {"name": "confianza", "description": "Probabilidad de su primera candidata, de 0 a 1."},
                    {"name": "seguro", "description": "Si superó el umbral calibrado del modelo (0,20)."},
                    {"name": "en_top3", "description": "Si la etiqueta de GBIF estaba entre sus tres candidatas."},
                    {"name": "coincide", "description": "Si especie == modelo_dice."},
                    {"name": "clasificada", "description": "Cuándo pasó por el modelo."},
                ]},
            },
            {
                "path": "por_especie.csv",
                "description": f"Lo mismo agregado por especie, {esp} en total: "
                               f"cuántas observaciones, cuántas acierta y el "
                               f"acierto contando solo cuando el modelo afirma.",
                "schema": {"fields": [
                    {"name": "especie", "description": "Nombre científico."},
                    {"name": "observaciones", "description": "Cuántas se clasificaron."},
                    {"name": "aciertos", "description": "En cuántas coincidió con GBIF."},
                    {"name": "acierta_pct", "description": "Porcentaje de acierto sobre todas."},
                    {"name": "en_las_tres_pct", "description": "Porcentaje en que la etiqueta estaba en el top 3."},
                    {"name": "acierta_si_seguro_pct", "description": "Acierto contando solo cuando el modelo superó su umbral. Es el número que importa."},
                    {"name": "veces_seguro", "description": "Cuántas veces superó el umbral."},
                    {"name": "confianza_media", "description": "Confianza media de su primera candidata."},
                    {"name": "provincias", "description": "En cuántas provincias se registró."},
                ]},
            },
            {
                "path": "README.md",
                "description": "La ficha completa: qué es, qué sale de mirarlo "
                               "y qué se dejó fuera a propósito.",
            },
        ],
        # `ensure_ascii=True` a propósito, aunque el fichero quede feo: el
        # cliente de Kaggle abre este JSON con `open(f, "r")` sin encoding, y en
        # Windows eso es cp1252. Con los acentos en UTF-8 crudo llegaban rotos
        # -«subiÃ³», «GalÃ¡pagos»- a la página pública. Con los escapes \uXXXX
        # el fichero es ASCII puro y cualquier lectura lo interpreta igual.
    }, ensure_ascii=True, indent=2), encoding="utf-8")

    (SALIDA / "README.md").write_text(_ficha(n, esp, ok), encoding="utf-8")
    print(f"  {n} observaciones · {esp} especies · {ok} coinciden ({100*ok/n:.0f}%)")
    print(f"  escrito en {SALIDA.name}/: " +
          ", ".join(sorted(f.name for f in SALIDA.iterdir())))
    return n


def _descripcion(n, esp, ok):
    """La descripción que Kaggle enseña en la portada del dataset.

    Corta a propósito: quien llega decide en diez segundos si le sirve, y para
    lo demás está el README.
    """
    return (
        f"{n} observaciones de fauna y flora del Ecuador, cada una con **dos "
        f"respuestas a la misma pregunta**: la especie que puso quien subió la "
        f"foto a GBIF, y la que vio un clasificador que nunca supo esa "
        f"etiqueta. Coinciden en {100*ok/n:.0f} % de los casos; lo interesante "
        f"es el resto.\n\n"
        f"Hay muchos datasets de fauna y muchos de clasificación de imágenes. "
        f"Lo que no abunda es uno donde las dos etiquetas estén enfrentadas con "
        f"la confianza del modelo al lado, que es lo que permite preguntarse "
        f"qué especies se confunden **en el campo** y si un umbral calibrado en "
        f"validación aguanta fuera de su reparto.\n\n"
        f"Y aguanta: el mismo modelo acierta 78,0 % en su banco de validación y "
        f"78,7 % aquí promediando especies, sobre fotos subidas después y por "
        f"gente distinta. La confianza además está calibrada — 31 % de acierto "
        f"en el tramo 0-20 % y 98 % en el 80-100 %, subiendo en cada tramo "
        f"intermedio.\n\n"
        f"**Ojo con el acierto global.** Por observación sale 84,2 %, pero una "
        f"sola especie -la iguana marina- es el 32 % del conjunto y las tres "
        f"primeras son la mitad. Promediando especies baja a 78,7 %, y ése es "
        f"el número comparable. No es un fallo del pipeline: es cómo se reparte "
        f"la ciencia ciudadana, y por eso el conjunto trae `por_especie.csv`.\n\n"
        f"Los desacuerdos no son ruido. Tres veces *Chelonoidis niger* contra "
        f"*porteri*, dos tortugas de Galápagos con la taxonomía en disputa entre "
        f"biólogos; la iguana marina contra la lagartija de lava, que comparten "
        f"roca y postura.\n\n"
        f"**No incluye** el nombre de quien subió cada observación: esas "
        f"personas suben sus fotos para ciencia ciudadana, no para aparecer en "
        f"un dataset. La URL de la foto sí, con su licencia al lado.\n\n"
        f"Lo genera [riksi-radar](https://github.com/DiegoFernandoLojanTenesaca/"
        f"riksi-radar) — Kafka, DuckDB y dbt — clasificando con "
        f"[Riksi](https://github.com/DiegoFernandoLojanTenesaca/riski), un "
        f"EfficientNet-Lite0 de 3,8 MB que corre en el navegador."
    )


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

**El conjunto está sesgado, y conviene saberlo antes de usarlo.** Una sola
especie —*Amblyrhynchus cristatus*— es el 32 % de las observaciones, y las tres
primeras son la mitad. Solo aparecen 20 de las 100 especies que el modelo
conoce. Así se reparte la ciencia ciudadana: la gente fotografía lo que ve.

Por eso el acierto global tiene dos lecturas, y la segunda es la que compara:

| | acierto |
|---|---|
| por observación | 84,2 % |
| **promediando especies** | **78,7 %** |

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
**78,7 %** aquí promediando especies, sobre fotos que se subieron después y de
gente distinta. Se comporta igual fuera del reparto donde se entrenó — que es
una conclusión más aburrida que «mejora», y bastante más creíble.

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
