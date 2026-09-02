# Riksi Radar: el modelo contra la etiqueta humana

400 observaciones de fauna y flora del Ecuador, cada una con **dos respuestas a
la misma pregunta**: la especie que puso quien subió la foto a GBIF, y la que
vio un clasificador que nunca supo esa etiqueta.

Coinciden en 84 % de los casos. Lo interesante es el resto.

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
