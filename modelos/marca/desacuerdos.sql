-- **La tabla que justifica el proyecto.** Donde el modelo y GBIF dicen cosas
-- distintas hay algo que mirar; donde coinciden, no hay noticia.
--
-- No se decide quién tiene razón. Hay tres explicaciones posibles y el radar no
-- puede distinguirlas: el modelo se equivocó, la observación está mal
-- identificada, o la foto no muestra lo que dice el registro. Lo que sí se hace
-- es ordenarlas por lo único objetivo que hay -cuánta confianza tenía el
-- modelo- para que quien las revise empiece por las que más pesan.

with base as (
    select * from {{ ref('base_observaciones') }}
    where not sin_clasificar
      and not coincide
)

select
    clave,
    especie_gbif,
    especie_modelo,
    confianza,
    seguro,

    -- Que la etiqueta de GBIF esté entre las tres candidatas cambia mucho la
    -- lectura: significa que el modelo la consideró y la puso segunda, no que
    -- vio algo completamente distinto.
    en_top3,

    provincia,
    fecha,
    foto,

    -- Para revisar por orden, no a ojo. Un desacuerdo con 92 % de confianza y
    -- la etiqueta fuera del top3 es una discrepancia de verdad; uno con 11 % es
    -- el modelo encogiéndose de hombros.
    case
        when seguro and not en_top3 then 'revisar primero'
        when seguro and en_top3     then 'especies parecidas'
        else                             'el modelo dudaba'
    end as lectura

from base
order by seguro desc, en_top3, confianza desc
