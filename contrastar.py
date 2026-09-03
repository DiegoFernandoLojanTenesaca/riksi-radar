"""¿Los desacuerdos son error del modelo, o etiquetas viejas de GBIF?

**Una duda con fundamento.** La comunidad de iNaturalist reporta que
observaciones ya corregidas siguen apareciendo en GBIF con la identificación
anterior: GBIF publica instantáneas periódicas, no un espejo en vivo. Si eso
pasara aquí, parte de los desacuerdos no serían fallos del modelo sino etiquetas
obsoletas, y la conclusión del proyecto cambiaría.

Se comprueba yendo a la fuente. GBIF guarda en `catalogNumber` el identificador
de la observación en iNaturalist, así que se puede preguntar allí cuál es la
identificación **de hoy** y compararla con la que se clasificó.

**Y sí pasa, pero no como se esperaba.** De 63 desacuerdos, 24 tienen hoy otra
etiqueta, y casi todos son el mismo movimiento taxonómico: una especie que pasó
a ser subespecie de otra. Ahí hay que hilar fino, porque no todos significan lo
mismo:

- `Anous stolidus` → `Anous stolidus galapagensis` es un **refinamiento**: se
  precisó a qué población pertenece, la especie no cambió y el modelo, que dijo
  otra cosa, falló igual;
- `Chelonoidis porteri` → `Chelonoidis niger porteri` es **otra especie**: la
  tortuga de Santa Cruz ahora cuelga de *C. niger*. Y el modelo había dicho
  justamente `Chelonoidis niger`. Bajo la taxonomía de hoy **acertó**, y el
  desacuerdo lo causaba la etiqueta vieja, no el modelo.

Ocho de los 63 son de este último tipo. Es poco, pero cambia lo que significan
los otros 55: sobreviven a la comprobación y son fallos de verdad.

De paso sale algo que ni GBIF ni el radar traían: el grado de calidad y cuántas
personas identificaron cada observación. Los 63 son de grado «research», o sea
que se discrepa contra identificaciones que la comunidad ya confirmó.

    python contrastar.py            # los desacuerdos, contra iNaturalist hoy
    python contrastar.py --comprobar
"""

import argparse
import json
import pathlib
import sys
import time
import urllib.request

AQUI = pathlib.Path(__file__).parent
ALMACEN = AQUI / "datos" / "radar.duckdb"
# Fuera de `datos/`, que está en el .gitignore porque se regenera. Esto no: son
# 63 filas que tardan dos minutos de peticiones a dos APIs y sostienen la cifra
# que se publica, así que se versiona.
SALIDA = AQUI / "contraste.json"

GBIF = "https://api.gbif.org/v1"
INAT = "https://api.inaturalist.org/v1"
AGENTE = "riksi-radar/0.1 (https://github.com/DiegoFernandoLojanTenesaca)"

# iNaturalist pide no pasar de 60 peticiones por minuto. Un segundo entre cada
# una deja margen de sobra y no hay prisa: son decenas de registros.
ESPERA = 1.1


def _pedir(url, intentos=3):
    for n in range(intentos):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": AGENTE})
            with urllib.request.urlopen(req, timeout=45) as r:
                return json.load(r)
        except Exception:
            if n == intentos - 1:
                return None
            time.sleep(2 ** n)


def desacuerdos():
    import duckdb

    cx = duckdb.connect(str(ALMACEN), read_only=True)
    filas = cx.execute("""
        select clave, especie, modelo_dice, confianza, seguro, en_top3
        from observaciones
        where coincide = false and modelo_dice is not null
        order by seguro desc, confianza desc
    """).fetchall()
    cx.close()
    return [dict(zip(("clave", "gbif", "modelo", "confianza", "seguro", "en_top3"), f))
            for f in filas]


def _en_inaturalist(clave_gbif):
    """La identificación de hoy, siguiendo el enlace que guarda GBIF."""
    oc = _pedir(f"{GBIF}/occurrence/{clave_gbif}")
    if not oc:
        return None
    id_inat = oc.get("catalogNumber")
    if not id_inat:
        return None

    time.sleep(ESPERA)
    d = _pedir(f"{INAT}/observations/{id_inat}")
    if not d or not d.get("results"):
        return None

    o = d["results"][0]
    return {
        "id_inat": id_inat,
        "taxon_hoy": (o.get("taxon") or {}).get("name"),
        "grado": o.get("quality_grade"),
        "identificaciones": o.get("identifications_count", 0),
    }


def _es_hijo(taxon, especie):
    """¿`taxon` es la misma especie, precisada a subespecie?

    `Anous stolidus galapagensis` lo es de `Anous stolidus`. Se compara por
    palabras y no con `startswith` a secas, que daría por buena una coincidencia
    a media palabra.
    """
    partes, base = (taxon or "").split(), (especie or "").split()
    return len(partes) > len(base) and partes[:len(base)] == base


def _juzgar(caso, hoy):
    """Qué era en realidad ese desacuerdo, ahora que se sabe la etiqueta de hoy.

    Tres desenlaces, y solo uno absuelve al modelo.
    """
    gbif, dice, ahora = caso["gbif"], caso["modelo"], hoy["taxon_hoy"]

    if ahora == gbif:
        return "sigue igual"           # la etiqueta aguanta: fallo del modelo
    if _es_hijo(ahora, gbif):
        return "precisada"             # misma especie, más detalle: falló igual
    if ahora == dice or _es_hijo(ahora, dice):
        return "el modelo tenía razón"  # la etiqueta era vieja, no el modelo
    return "cambió de especie"         # cambió, y a algo que tampoco es lo dicho


def contrastar(tope=None):
    """Cada desacuerdo, contra lo que dice iNaturalist ahora."""
    casos = desacuerdos()[:tope] if tope else desacuerdos()
    salida, cuenta, sin_datos = [], {}, 0

    for n, c in enumerate(casos, 1):
        hoy = _en_inaturalist(c["clave"])
        if not hoy:
            sin_datos += 1
            salida.append({**c, "estado": "no se pudo consultar"})
            print(f"  [{n}/{len(casos)}] {c['gbif']:<26} sin datos")
            continue

        estado = _juzgar(c, hoy)
        cuenta[estado] = cuenta.get(estado, 0) + 1
        salida.append({**c, **hoy, "estado": estado})

        marca = estado if estado == "sigue igual" else f"{estado} → {hoy['taxon_hoy']}"
        print(f"  [{n}/{len(casos)}] {c['gbif']:<26} {marca:<52} "
              f"{hoy['grado']} · {hoy['identificaciones']} id")
        time.sleep(ESPERA)

    SALIDA.parent.mkdir(parents=True, exist_ok=True)
    SALIDA.write_text(json.dumps(salida, ensure_ascii=False, indent=2), encoding="utf-8")

    absueltos = cuenta.get("el modelo tenía razón", 0)
    print(f"\n{len(casos)} desacuerdos contrastados contra iNaturalist")
    for estado, k in sorted(cuenta.items(), key=lambda p: -p[1]):
        print(f"  {k:>3}  {estado}")
    if sin_datos:
        print(f"  {sin_datos:>3}  sin datos")
    print(f"\n{len(casos) - absueltos} son fallos reales del modelo; en {absueltos} "
          f"la etiqueta de GBIF se había quedado vieja")

    # Contra qué se discrepa. Un desacuerdo contra una identificación que
    # respaldaron varias personas no es lo mismo que contra una sin confirmar.
    con_grado = [s for s in salida if s.get("grado")]
    if con_grado:
        investigacion = sum(1 for s in con_grado if s["grado"] == "research")
        sola = sum(1 for s in con_grado if s.get("identificaciones", 0) <= 1)
        print(f"\n  {investigacion} de {len(con_grado)} son de grado «research», "
              f"confirmados por la comunidad")
        print(f"  {sola} tienen una sola identificación, sin nadie que la respalde")
    return salida


def prueba():
    """El juicio —donde está la lógica— y que el enlace a iNaturalist funcione."""
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    def juzgar(gbif, modelo, ahora):
        return _juzgar({"gbif": gbif, "modelo": modelo}, {"taxon_hoy": ahora})

    # Los cuatro desenlaces, con los casos reales que aparecieron.
    assert juzgar("Butorides sundevalli", "Egretta thula",
                  "Butorides sundevalli") == "sigue igual"
    assert juzgar("Anous stolidus", "Sula nebouxii",
                  "Anous stolidus galapagensis") == "precisada"
    assert juzgar("Chelonoidis porteri", "Chelonoidis niger",
                  "Chelonoidis niger porteri") == "el modelo tenía razón"
    assert juzgar("Sula nebouxii", "Sula sula", "Fregata magnificens") == \
        "cambió de especie"

    # Lo que separa este juicio de un `startswith` a secas: una especie cuyo
    # nombre empieza igual que otra no es una subespecie suya.
    assert not _es_hijo("Anous stolidusa", "Anous stolidus"), \
        "coincidir a media palabra no convierte una especie en subespecie de otra"
    assert not _es_hijo("Anous stolidus", "Anous stolidus"), "ni es hija de sí misma"
    assert _es_hijo("Chelonoidis niger porteri", "Chelonoidis niger")

    casos = desacuerdos()
    assert casos, "no hay desacuerdos que contrastar"
    assert all(c["gbif"] != c["modelo"] for c in casos), \
        "un desacuerdo con las dos etiquetas iguales no es un desacuerdo"

    hoy = _en_inaturalist(casos[0]["clave"])
    assert hoy and hoy["taxon_hoy"], f"no se pudo seguir el enlace: {hoy}"
    assert hoy["grado"] in ("research", "needs_id", "casual"), hoy

    print(f"ok · el juicio distingue los cuatro casos · {len(casos)} desacuerdos "
          f"· el enlace a iNaturalist funciona (la primera es {hoy['taxon_hoy']})")


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--tope", type=int, help="para probar con unos pocos")
    a.add_argument("--comprobar", action="store_true")
    args = a.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    prueba() if args.comprobar else contrastar(args.tope)


if __name__ == "__main__":
    main()
