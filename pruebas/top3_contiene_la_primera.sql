-- Si la primera candidata coincide con GBIF, la etiqueta tiene que estar en el
-- top3 por definición: la primera es parte de las tres. Que esto falle
-- significaría que las dos columnas se calcularon sobre listas distintas.

select clave, especie_gbif, especie_modelo, coincide, en_top3
from {{ ref('base_observaciones') }}
where coincide and not en_top3
