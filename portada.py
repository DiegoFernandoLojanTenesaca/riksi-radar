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

ANCHO, ALTO = 1200, 630          # la proporción que Kaggle usa en el listado


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
    izq, base, ancho_barra, hueco = 150, 500, 130, 45
    alto_max = 300

    partes = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{ANCHO}" height="{ALTO}" '
        f'viewBox="0 0 {ANCHO} {ALTO}">',
        f'<rect width="{ANCHO}" height="{ALTO}" fill="{BASALTO}"/>',
        f'<text x="{izq}" y="78" fill="{PAPEL}" font-size="42" font-weight="600" '
        f'font-family="Georgia, serif">Riksi Radar</text>',
        f'<text x="{izq}" y="118" fill="{LIQUEN}" font-size="23" '
        f'font-family="system-ui, sans-serif">'
        f'La confianza del modelo predice el acierto</text>',
        f'<text x="{izq}" y="152" fill="{TENUE}" font-size="17" '
        f'font-family="system-ui, sans-serif">'
        f'{total} observaciones del Ecuador · medido en el campo, no en validación</text>',
    ]

    for i, (tramo, n, acierta) in enumerate(filas):
        x = izq + i * (ancho_barra + hueco)
        alto = max(6, alto_max * acierta / 100)
        y = base - alto
        # La barra se llena en proporción al acierto; el contorno marca el 100 %
        # para que se vea cuánto falta sin tener que leer el eje.
        partes += [
            f'<rect x="{x}" y="{base - alto_max}" width="{ancho_barra}" '
            f'height="{alto_max}" fill="none" stroke="{TENUE}" '
            f'stroke-width="1" opacity=".25"/>',
            f'<rect x="{x}" y="{y:.0f}" width="{ancho_barra}" height="{alto:.0f}" '
            f'fill="{LIQUEN}" rx="4"/>',
            f'<text x="{x + ancho_barra/2:.0f}" y="{y - 14:.0f}" fill="{PAPEL}" '
            f'font-size="27" font-weight="600" text-anchor="middle" '
            f'font-family="system-ui, sans-serif">{acierta:.0f}%</text>',
            f'<text x="{x + ancho_barra/2:.0f}" y="{base + 30}" fill="{PAPEL}" '
            f'font-size="18" text-anchor="middle" '
            f'font-family="system-ui, sans-serif">{tramo}%</text>',
            f'<text x="{x + ancho_barra/2:.0f}" y="{base + 52}" fill="{TENUE}" '
            f'font-size="14" text-anchor="middle" '
            f'font-family="system-ui, sans-serif">n={n}</text>',
        ]

    partes += [
        f'<text x="{izq}" y="{base + 100}" fill="{TENUE}" font-size="16" '
        f'font-family="system-ui, sans-serif">'
        f'confianza que el modelo dio a su respuesta  →  cuánto acertó de verdad</text>',
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
