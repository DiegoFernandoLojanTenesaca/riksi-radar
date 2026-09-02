<div align="center">

# riksi-radar

**Un pipeline de datos que le lleva la contraria a GBIF.**

Cada día se suben observaciones de fauna del Ecuador con la especie que les puso
quien las fotografió. El radar las pasa por el modelo de
[Riksi](https://github.com/DiegoFernandoLojanTenesaca/riski) y guarda las dos
respuestas: la de la persona y la de la máquina.

</div>

---

## Qué hace

```
GBIF ──► Kafka ──► modelo de Riksi ──► DuckDB ──► dbt
  │        │             │                │        │
filtra   6.000/día   clasifica la    guarda las   modela
las 100              foto sin ver    dos          y comprueba
especies             la etiqueta     versiones
```

Cuando las dos coinciden no hay noticia. Cuando no, hay exactamente tres
explicaciones y ninguna es aburrida: **el modelo se equivocó**, **la observación
está mal identificada**, o **la foto no muestra lo que dice el registro**.

El radar no decide cuál. Guarda las dos versiones con la confianza del modelo y
las ordena para que quien las revise empiece por las que más pesan. Un pipeline
que resolviera el desacuerdo por su cuenta estaría inventando una autoridad que
no tiene.

## Lo que sale

Sobre 39 observaciones reales: **30 coinciden, 9 no**. Y los desacuerdos tienen
sentido biológico, no son ruido:

| GBIF dice | el modelo ve | |
|---|---|---|
| *Chelonoidis niger* | *Chelonoidis porteri* ×3 | dos tortugas de Galápagos con la **taxonomía en disputa** entre biólogos |
| *Amblyrhynchus cristatus* | *Microlophus albemarlensis* | iguana marina y lagartija de lava: comparten roca y postura |
| *Apis mellifera* | *Xylocopa darwini* | abeja europea contra abeja carpintera |

Y de esos nueve, la propia tabla dice que **solo uno merece revisión**: cuatro
son especies parecidas con la etiqueta correcta en el top 3, y cuatro son el
modelo dudando por debajo de su umbral.

**El umbral calibrado se valida solo.** Es el número que más se ve:

| | acierta |
|---|---|
| cuando el modelo dice estar seguro | **85 %** |
| cuando no | 33 % |

Por especie se ve mejor todavía: *Amblyrhynchus cristatus* pasa de 83 % a
**100 %** al filtrar por las respuestas seguras, y *Chuquiraga jussieui* de 89 %
a 100 %.

## Lo que se midió antes de construir

**No se traga todo el flujo, y eso es una decisión medida.** Ecuador recibe unas
130.000 observaciones al día —con picos de 790.000— y el modelo conoce cien
especies. Muestreando seis días: **solo el 1,6 %** del flujo general cae en
ellas.

Bajarse los 130.000 para tirar el 98 % sería malgastar una API que es de otros,
así que el productor filtra en la consulta. Aun así quedan **~6.000 registros
diarios**: flujo de sobra para que Kafka no sea decorado.

## Correrlo

```bash
docker compose up -d              # Kafka, un contenedor

python -m venv .venv
.venv/Scripts/pip install -r requirements.txt

py -3.11 -m venv .venv-dbt        # dbt aparte, ver más abajo
.venv-dbt/Scripts/pip install -r requirements-dbt.txt
.venv-dbt/Scripts/dbt deps --profiles-dir .

python flujo.py --dias 1          # la pasada completa, orquestada
```

O cada pieza por separado:

```bash
python productor.py --dias 3      # GBIF → Kafka
python consumidor.py --tope 50    # Kafka → modelo → DuckDB
.venv-dbt/Scripts/dbt build --profiles-dir .
```

Cada módulo se comprueba solo, sin tocar red ni Kafka:

```bash
python productor.py --comprobar
python consumidor.py --comprobar
python flujo.py --comprobar
```

## Las tablas

| | |
|---|---|
| `base_observaciones` | limpia y normaliza. Todo lo demás lee de aquí |
| `desacuerdos` | donde el modelo y GBIF discrepan, ordenados por confianza |
| `por_especie` | cómo se porta el modelo con cada especie, sobre fotos de campo |

`por_especie` mide algo que las métricas de validación no pueden: allí las
imágenes salen del mismo reparto que las de entrenamiento, y aquí llegan de
gente subiendo fotos con su móvil. Una especie que acierta en validación y falla
aquí es una especie cuyo entrenamiento no se parecía al mundo.

**Trece pruebas de dbt, y dos son propias**: que `coincide` sea de verdad la
igualdad entre las dos especies, y que si coincide, la etiqueta esté en el top 3
por definición. Un booleano mal calculado no da error — da estadísticas falsas
que nadie cuestiona.

## Lo que costó más de lo que parecía

**Kafka no arrancaba, y el error señalaba el sitio equivocado.** Decía
`advertised.listeners cannot use the nonroutable meta-address 0.0.0.0` sobre una
configuración que ya estaba sobrescrita. La causa era el listener `CONTROLLER`
escuchando en `0.0.0.0`: como no tiene un `advertised` propio, Kafka lo deriva de
ahí. En `localhost` arranca, y además es lo correcto — con un solo broker el
controlador solo habla consigo mismo.

De paso, la config va en un fichero montado y no en variables `KAFKA_*`, porque
`StorageTool` valida **antes** de escribir la config final y veía la de la imagen
mezclada con la nuestra. Y `log.dirs` se declara: la imagen guarda en `/tmp`, así
que el volumen quedaba vacío y los datos se perdían sin aviso.

**El cuello de botella era la descarga, no el modelo.** GBIF apunta al original
de cada foto: de 640 KB a 1,7 MB, **23 s por foto**. La inferencia tarda 0,16 s.
iNaturalist sirve la misma imagen en `large` a 181 KB y 768 px —de sobra para un
recorte a 288— en **2 s**.

**Y Kafka daba al consumidor por muerto.** Con lotes de 500 y dos segundos por
foto, procesar uno pasaba de los cinco minutos de margen: el broker reasignaba
las particiones y el `commit` fallaba con *«the group has already rebalanced»*.
Es el fallo típico de meter trabajo lento dentro del bucle de Kafka: no aparece
en pruebas cortas y revienta con volumen.

## Por qué dbt vive aparte

**No corre en Python 3.14.** La versión nueva arrastra
`dbt-core-experimental-parser`, que es Rust sin rueda y se pone a compilar; y si
se esquiva bajando de versión, entonces revienta `mashumaro` con *«Field "schema"
of type Optional[str] is not serializable»*. El resto del proyecto sí corre en
3.14, así que dbt tiene su propio entorno con 3.11 en vez de arrastrar a todo el
proyecto hacia atrás.

Prefect va fijado a `3.8.4` por una razón parecida: sin fijar, pip retrocede
buscando compatibilidad hasta una versión que arrastra SQLAlchemy 1.4 en
`tar.gz` y se pone a compilarlo desde fuente.

## Los reintentos van donde importan

No en todas partes, que es lo fácil:

| paso | reintentos | por qué |
|---|---|---|
| traer de GBIF | 3, con espera creciente | corta la conexión de vez en cuando, y el productor recuerda lo emitido: reintentar no duplica |
| clasificar | 2, espaciados | cada intento cuesta segundos por foto; Kafka guarda el desplazamiento y se sigue donde se quedó |
| `dbt run` / `dbt test` | **0** | si una prueba falla es porque los datos no cumplen lo que se afirma. Repetirla solo lo esconde |

## Licencia

Código bajo MIT. El modelo viene de
[Riksi](https://github.com/DiegoFernandoLojanTenesaca/riski) bajo CC-BY 4.0; las
observaciones y las fotos son de [GBIF](https://www.gbif.org) y de quienes las
subieron, cada una con su licencia, que se guarda en el almacén.
