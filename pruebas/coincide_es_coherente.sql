-- `coincide` tiene que ser exactamente «la etiqueta de GBIF es igual a lo que
-- dijo el modelo». Lo calcula Python al guardar, así que aquí se comprueba que
-- no se ha desviado: un booleano mal puesto no da error, da estadísticas
-- falsas que nadie cuestiona.
--
-- Una prueba de dbt pasa cuando NO devuelve filas.

select clave, especie_gbif, especie_modelo, coincide
from {{ ref('base_observaciones') }}
where especie_modelo is not null
  and coincide != (especie_gbif = especie_modelo)
