-- La capa que toca la tabla cruda. Todo lo demás lee de aquí, así que el día
-- que el consumidor cambie un nombre de columna solo hay que arreglar este
-- fichero.
--
-- Aquí no se agrega ni se decide nada: se limpia, se tipa y se nombra. Las
-- preguntas se responden en `marca`.

with cruda as (
    select * from observaciones
),

limpia as (
    select
        clave,
        especie                                          as especie_gbif,
        modelo_dice                                      as especie_modelo,
        cuando                                           as fecha,
        confianza,
        seguro,
        en_top3,
        coincide,
        latitud,
        longitud,
        altura,
        foto,
        licencia,
        clasificada,

        -- GBIF escribe la provincia de varias formas para el mismo sitio:
        -- «Pichincha», «Pichincha prov», «Pichincha Province». Sin normalizar,
        -- cualquier agrupación las cuenta como sitios distintos.
        case
            when provincia is null or trim(provincia) = '' then null
            else trim(regexp_replace(provincia, '(?i)\s+(prov\.?|province)$', ''))
        end                                              as provincia,

        nullif(trim(coalesce(sitio, '')), '')            as sitio,
        nullif(trim(coalesce(quien, '')), '')            as quien,
        nullif(trim(coalesce(conjunto, '')), '')         as conjunto,

        -- Una observación sin coordenadas no se puede mapear, y conviene poder
        -- filtrarla sin repetir la condición en cada consulta.
        (latitud is not null and longitud is not null)    as ubicada,

        -- Las que el modelo no pudo mirar: sin esto, «coincide = false» mezcla
        -- los desacuerdos reales con las fotos que nunca se descargaron.
        (especie_modelo is null)                          as sin_clasificar

    from cruda
)

select * from limpia
