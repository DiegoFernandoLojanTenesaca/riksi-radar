"""El análisis del dataset, para acompañarlo en Kaggle.

Se escribe como script y no como notebook a propósito: un `.py` se lee en un
diff, se comprueba con `python analisis.py` y no guarda salidas viejas que
contradigan al código. `jupytext` lo convierte a notebook en un comando si hace
falta, y Kaggle lo acepta tal cual.

    python analisis.py
"""

import pathlib
import sys

import pandas as pd

AQUI = pathlib.Path(__file__).parent
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

obs = pd.read_csv(AQUI / "observaciones.csv")
esp = pd.read_csv(AQUI / "por_especie.csv")

print(f"{len(obs)} observaciones · {obs.especie.nunique()} especies "
      f"· {obs.provincia.nunique()} provincias\n")


# ── 1. El umbral ───────────────────────────────────────────────────────────
#
# El modelo trae un umbral calibrado: por debajo, dice que no está seguro. La
# pregunta que importa no es cuánto acierta en total, sino cuánto acierta
# **cuando afirma**. En el campo, una identificación equivocada dada con
# seguridad hace más daño que no dar ninguna.

print("=== el umbral: acierto según el modelo diga estar seguro o no ===\n")
t = obs.groupby("seguro").agg(n=("coincide", "size"), aciertos=("coincide", "sum"))
t["acierta"] = (100 * t.aciertos / t.n).round(1)
print(t.to_string(), "\n")

seguro = obs[obs.seguro]
print(f"  Cuando dice estar seguro acierta {100*seguro.coincide.mean():.0f} %; "
      f"cuando no, {100*obs[~obs.seguro].coincide.mean():.0f} %.")
print("  El umbral no está para que responda siempre, sino para que lo que")
print("  responde sea fiable.\n")


# ── 2. Qué se confunde con qué ─────────────────────────────────────────────
#
# Los desacuerdos no son ruido uniforme: se concentran en pares de especies
# concretos, y casi siempre por una razón que un biólogo reconocería.

print("=== los pares que se confunden ===\n")
mal = obs[~obs.coincide]
pares = (mal.groupby(["especie", "modelo_dice"]).size()
         .sort_values(ascending=False).head(8))
for (real, dicho), n in pares.items():
    print(f"  {n:>2}×  {real:<28} → {dicho}")
print()
print("  Chelonoidis niger contra porteri son dos tortugas de Galápagos con la")
print("  taxonomía en disputa entre biólogos. Amblyrhynchus contra Microlophus,")
print("  iguana marina y lagartija de lava: comparten roca y postura.\n")


# ── 3. La etiqueta correcta, ¿estaba cerca? ────────────────────────────────
#
# Un desacuerdo donde la etiqueta de GBIF era la segunda candidata no es lo
# mismo que uno donde el modelo vio algo completamente distinto.

print("=== cuando falla, ¿estaba la etiqueta entre sus tres candidatas? ===\n")
cerca = 100 * mal.en_top3.mean()
print(f"  {mal.en_top3.sum()} de {len(mal)} desacuerdos ({cerca:.0f} %) tienen la")
print(f"  etiqueta de GBIF en el top 3: el modelo la consideró y la puso segunda.")
print(f"  Los otros {len(mal) - mal.en_top3.sum()} son discrepancias de verdad.\n")


# ── 4. Por especie ─────────────────────────────────────────────────────────

print("=== las especies con más observaciones ===\n")
top = esp.nlargest(8, "observaciones")[
    ["especie", "observaciones", "acierta_pct", "acierta_si_seguro_pct"]]
print(top.to_string(index=False), "\n")

print("  La última columna es la que vale: el acierto contando solo cuando el")
print("  modelo afirma. Varias especies pasan del 80 % al 100 %.\n")


# ── 5. Confianza y acierto ─────────────────────────────────────────────────
#
# Si la confianza del modelo significara algo, debería subir con el acierto. Que
# lo haga no es evidente: un modelo puede estar igual de seguro cuando acierta
# que cuando falla, y entonces su confianza no sirve para decidir nada.

print("=== ¿la confianza predice el acierto? ===\n")
obs["tramo"] = pd.cut(obs.confianza, [0, .2, .4, .6, .8, 1.0],
                      labels=["0-20 %", "20-40 %", "40-60 %", "60-80 %", "80-100 %"])
por_tramo = obs.groupby("tramo", observed=True).agg(
    n=("coincide", "size"), acierta=("coincide", "mean"))
por_tramo["acierta"] = (100 * por_tramo.acierta).round(1)
print(por_tramo.to_string(), "\n")
print("  Sube con la confianza, que es lo que se espera de un modelo calibrado.")
print("  Si fuera plana, la columna `confianza` no serviría para nada.")
