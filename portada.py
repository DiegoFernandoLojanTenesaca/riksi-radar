"""La imagen de portada del dataset: la curva de calibración.

**Se dibuja el hallazgo, no un logotipo.** Lo que hace interesante a este
conjunto es que la confianza del modelo predice el acierto —31 % en el tramo más
bajo, 98 % en el más alto— y eso medido sobre fotos de campo, no de validación.
Una portada bonita sin datos no dice nada; ésta se lee en tres segundos.

Sin matplotlib: son cinco barras y un SVG se escribe a mano en menos líneas que
las que costaría configurar una figura. Se convierte a PNG porque Kaggle no
acepta SVG de portada.

    python portada.py
"""

import pathlib
import sys

AQUI = pathlib.Path(__file__).parent
ALMACEN = AQUI / "datos" / "radar.duckdb"
SALIDA = AQUI / "kaggle" / "portada.png"

# La paleta de Riksi: basalto, liquen, papel. Los tres proyectos se ven de la
# misma familia sin tener que decirlo.
BASALTO, LIQUEN, PAPEL, TENUE = "#14181b", "#c7c24b", "#e4e5df", "#8a938d"

# **Kaggle la enseña a 280x140, no a tamaño completo.** Medido en la página: la
# cabecera del dataset la pinta a 280 px de ancho y el listado a unos 180. Eso
# cambia el diseño entero, porque a esa escala un texto de 18 px del original se
# convierte en 4 px y desaparece.
#
# La primera versión tenía tres líneas de título, etiquetas bajo cada barra y un
# pie explicativo: a 280 px todo eso era una mancha gris. Aquí se queda lo que
# sobrevive al encogerse -pocas palabras, muy grandes- y el detalle se deja para
# quien abra la imagen entera.
#
# Se dibuja a 1200x600 y se sirve así porque el original grande se ve nítido al
# ampliarlo; lo que cambia son las proporciones, no el tamaño del lienzo.
ANCHO, ALTO = 1200, 600


def datos():
    import duckdb

    cx = duckdb.connect(str(ALMACEN), read_only=True)
    filas = cx.execute("""
        select case when confianza < 0.2 then '0-20'
                    when confianza < 0.4 then '20-40'
                    when confianza < 0.6 then '40-60'
                    when confianza < 0.8 then '60-80'
                    else '80-100' end             as tramo,
               count(*)                           as n,
               avg(case when coincide then 1.0 else 0 end) * 100 as acierta
        from observaciones
        where modelo_dice is not null
        group by 1
        order by min(confianza)
    """).fetchall()
    total = cx.execute("select count(*) from observaciones "
                       "where modelo_dice is not null").fetchone()[0]
    cx.close()
    return filas, total


def svg(filas, total):
    """Un dibujo que aguanta reducido a una cuarta parte.

    Todo se dimensiona pensando en el 23 % —280 de 1200—, que es a lo que Kaggle
    lo enseña. Un título de 46 px queda en 11; uno de 76, en 18, que sí se lee.
    """
    izq, der, arriba, abajo = 60, 60, 210, 118
    util = ANCHO - izq - der
    base = ALTO - abajo
    alto_max = base - arriba

    hueco = 18
    ancho_barra = (util - hueco * (len(filas) - 1)) / len(filas)

    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ANCHO}" height="{ALTO}" '
        f'viewBox="0 0 {ANCHO} {ALTO}">',
        f'<rect width="{ANCHO}" height="{ALTO}" fill="{BASALTO}"/>',

        # Dos líneas y nada más. El subtítulo largo y el pie explicativo de la
        # versión anterior no se leían y solo añadían ruido gris.
        f'<text x="{izq}" y="82" fill="{PAPEL}" font-size="76" font-weight="700" '
        f'font-family="Georgia, serif">Riksi Radar</text>',
        f'<text x="{izq}" y="146" fill="{LIQUEN}" font-size="42" font-weight="500" '
        f'font-family="system-ui, sans-serif">'
        f'La confianza predice el acierto</text>',
    ]

    for i, (tramo, n, acierta) in enumerate(filas):
        x = izq + i * (ancho_barra + hueco)
        alto = max(10, alto_max * acierta / 100)
        y = base - alto
        centro = x + ancho_barra / 2
        partes += [
            f'<rect x="{x:.0f}" y="{arriba}" width="{ancho_barra:.0f}" '
            f'height="{alto_max}" fill="{PAPEL}" opacity=".06" rx="6"/>',
            f'<rect x="{x:.0f}" y="{y:.0f}" width="{ancho_barra:.0f}" '
            f'height="{alto:.0f}" fill="{LIQUEN}" rx="6"/>',
            # La cifra es lo único que tiene que sobrevivir a la reducción, así
            # que va grande y dentro de la barra cuando cabe: sobre fondo liquen
            # contrasta más que sobre el negro.
            f'<text x="{centro:.0f}" y="{(y + 52) if alto > 78 else (y - 18):.0f}" '
            f'fill="{BASALTO if alto > 78 else PAPEL}" font-size="46" '
            f'font-weight="700" text-anchor="middle" '
            f'font-family="system-ui, sans-serif">{acierta:.0f}%</text>',
            f'<text x="{centro:.0f}" y="{base + 42}" fill="{TENUE}" '
            f'font-size="30" text-anchor="middle" '
            f'font-family="system-ui, sans-serif">{tramo}</text>',
        ]

    partes += [
        f'<text x="{izq}" y="{ALTO - 26}" fill="{TENUE}" font-size="27" '
        f'font-family="system-ui, sans-serif">'
        f'{total} observaciones · confianza del modelo → acierto real</text>',
        "</svg>",
    ]
    return "\n".join(partes)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    filas, total = datos()
    marca = AQUI / "kaggle" / "portada.svg"
    marca.write_text(svg(filas, total), encoding="utf-8")

    # Kaggle no acepta SVG de portada, así que hay que rasterizarlo. Se intenta
    # con lo que haya y, si no hay nada, se dice: subir el dataset sin portada
    # es mejor que fallar entero por una imagen.
    try:
        import cairosvg
        cairosvg.svg2png(url=str(marca), write_to=str(SALIDA),
                         output_width=ANCHO, output_height=ALTO)
    except Exception:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                nav = pw.chromium.launch()
                pag = nav.new_page(viewport={"width": ANCHO, "height": ALTO})
                pag.goto(marca.resolve().as_uri())
                pag.screenshot(path=str(SALIDA))
                nav.close()
        except Exception as err:
            print(f"  no se pudo rasterizar ({type(err).__name__}). "
                  f"Queda el SVG en {marca.name}.")
            return

    print(f"  {SALIDA.name}: {SALIDA.stat().st_size/1024:.0f} KB · "
          f"{ANCHO}x{ALTO} · {len(filas)} tramos sobre {total} observaciones")


if __name__ == "__main__":
    main()
