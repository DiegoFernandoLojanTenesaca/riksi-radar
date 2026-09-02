"""La imagen de perfil: el ojo de Riksi, adaptado a redondo y pequeño.

**No es el icono del sitio reescalado.** Un avatar se ve a 40-100 px y casi
siempre recortado en círculo, y el icono original está pensado para un cuadrado
con esquinas redondeadas: al recortarlo en círculo se comía el borde de la
vesica, y sus trazos de 2,5 px desaparecían al reducir.

Aquí la misma figura —la vesica que se lee como ojo y como hoja, que es lo que
significa *riksiy*— con tres cambios que solo importan a tamaño pequeño: trazos
del doble de gruesos, la forma encogida para que quepa dentro del círculo con
margen, y la pupila más grande, porque es lo único que se distingue a 40 px.

    python perfil.py
"""

import pathlib
import sys

AQUI = pathlib.Path(__file__).parent
SALIDA = AQUI / "kaggle" / "perfil.png"

BASALTO, LIQUEN, PAPEL = "#14181b", "#c7c24b", "#e4e5df"

# Cuadrado y grande: los sitios lo recortan y reducen ellos, y de un original
# grande sale nítido. Al revés no.
LADO = 512


SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{LADO}" height="{LADO}"
     viewBox="0 0 128 128" role="img" aria-label="Riksi">
  <!-- Fondo a sangre. Sin esquinas redondeadas: quien recorte en círculo se
       las come, y quien lo deje cuadrado no las echa de menos. -->
  <rect width="128" height="128" fill="{BASALTO}"/>

  <!-- La vesica, encogida respecto al original para que sobreviva al recorte
       circular: de 6-58 sobre 64 pasa a 24-104 sobre 128, o sea de tocar el
       borde a dejar un 19 % de margen. -->
  <path d="M24 64C46 28 82 28 104 64 82 100 46 100 24 64Z"
        fill="none" stroke="{LIQUEN}" stroke-width="5" stroke-linejoin="round"/>

  <!-- La nervadura, que es lo que la hace hoja además de ojo. -->
  <path d="M24 64H104" stroke="{LIQUEN}" stroke-width="3" opacity=".35"/>

  <!-- El iris va proporcionalmente mayor que en el icono original: a 40 px es
       lo único que se distingue, y con el tamaño de allí quedaba en un punto. -->
  <circle cx="64" cy="64" r="21" fill="{LIQUEN}"/>
  <circle cx="64" cy="64" r="8.5" fill="{BASALTO}"/>
  <circle cx="57.5" cy="57.5" r="3.6" fill="{PAPEL}" opacity=".92"/>
</svg>
"""


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    marca = AQUI / "kaggle" / "perfil.svg"
    marca.parent.mkdir(exist_ok=True)
    marca.write_text(SVG, encoding="utf-8")

    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            nav = pw.chromium.launch()
            pag = nav.new_page(viewport={"width": LADO, "height": LADO})
            pag.goto(marca.resolve().as_uri())
            pag.screenshot(path=str(SALIDA))
            nav.close()
    except Exception as err:
        print(f"  no se pudo rasterizar ({type(err).__name__}); queda el SVG")
        return

    print(f"  {SALIDA.name}: {SALIDA.stat().st_size/1024:.0f} KB · {LADO}x{LADO}")


if __name__ == "__main__":
    main()
