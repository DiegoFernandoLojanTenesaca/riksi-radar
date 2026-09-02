-- Cómo se porta el modelo con cada especie, sobre fotos que nunca vio.
--
-- Esto es lo que las métricas de validación no dan: allí las imágenes salen del
-- mismo reparto que las de entrenamiento, y aquí llegan de gente subiendo fotos
-- a iNaturalist con su móvil. Una especie que acierta en validación y falla
-- aquí es una especie cuyo entrenamiento no se parecía al mundo.

with base as (
    select * from {{ ref('base_observaciones') }}
    where not sin_clasificar
),

por_especie as (
    select
        especie_gbif                                              as especie,
        count(*)                                                  as observaciones,
        sum(case when coincide then 1 else 0 end)                 as aciertos,
        sum(case when en_top3 then 1 else 0 end)                  as en_las_tres,
        sum(case when seguro then 1 else 0 end)                   as veces_seguro,
        sum(case when seguro and coincide then 1 else 0 end)      as seguro_y_acierta,
        round(avg(confianza), 3)                                  as confianza_media,
        count(distinct provincia)                                 as provincias
    from base
    group by 1
)

select
    especie,
    observaciones,
    aciertos,
    round(100.0 * aciertos / observaciones, 1)                    as acierta_pct,
    round(100.0 * en_las_tres / observaciones, 1)                 as en_las_tres_pct,

    -- El acierto **cuando el modelo dice estar seguro**, que es el número que
    -- de verdad importa: el umbral existe para que las respuestas dadas sean
    -- fiables, no para que responda siempre.
    case when veces_seguro = 0 then null
         else round(100.0 * seguro_y_acierta / veces_seguro, 1) end as acierta_si_seguro_pct,

    veces_seguro,
    confianza_media,
    provincias

from por_especie
-- Con dos o tres observaciones el porcentaje no dice nada, pero tirarlas
-- escondería justo las especies que apenas se fotografían. Se dejan y se ordena
-- por volumen, que es lo que avisa de cuáles leer con reservas.
order by observaciones desc, acierta_pct
