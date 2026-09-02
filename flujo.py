"""El pipeline entero, orquestado: GBIF → Kafka → modelo → DuckDB → dbt.

**Qué añade Prefect que no da un `.bat` con cuatro líneas.** Tres cosas, y
ninguna es el diagrama:

- **Reintentos donde importan.** Bajar de GBIF falla por red cada tanto; que se
  reintente solo esa parte, sin repetir lo ya clasificado, es la diferencia
  entre perder un minuto y perder la pasada entera.
- **Saber qué falló.** Cuando el pipeline corre de madrugada, «falló» no sirve:
  hay que ver en qué paso, con qué error y cuántos registros llevaba.
- **Que un fallo no borre lo bueno.** Si dbt revienta, las observaciones ya
  clasificadas siguen en DuckDB. Cada paso deja su trabajo hecho antes de que
  empiece el siguiente.

    python flujo.py                    # una pasada completa
    python flujo.py --dias 3 --tope 200
    python flujo.py --comprobar        # sin tocar red, Kafka ni dbt
"""

import argparse
import pathlib
import subprocess
import sys

from prefect import flow, get_run_logger, task

AQUI = pathlib.Path(__file__).parent
DBT = AQUI / ".venv-dbt" / "Scripts" / "dbt.exe"


@task(retries=3, retry_delay_seconds=[10, 30, 90], task_run_name="traer de GBIF")
def paso_productor(dias: int, tope: int | None, servidor: str) -> int:
    """Baja las observaciones nuevas y las emite a Kafka.

    Tres reintentos con espera creciente: GBIF corta la conexión de vez en
    cuando y volver a intentarlo a los diez segundos suele bastar. El productor
    recuerda lo emitido, así que reintentar no duplica nada.
    """
    import productor

    registro = get_run_logger()
    n = productor.emitir(dias=dias, tope=tope, servidor=servidor)
    registro.info(f"{n} observaciones nuevas en Kafka")
    return n


@task(retries=2, retry_delay_seconds=30, task_run_name="clasificar")
def paso_consumidor(tope: int | None, servidor: str) -> int:
    """Lee de Kafka, clasifica cada foto y guarda las dos versiones.

    Menos reintentos que el productor y más espaciados: aquí cada intento
    cuesta segundos por foto, así que reintentar en bucle sale caro. Kafka
    guarda el desplazamiento confirmado, de modo que un reintento sigue donde
    se quedó en vez de empezar de cero.
    """
    import consumidor

    registro = get_run_logger()
    n = consumidor.consumir(tope=tope, servidor=servidor)
    registro.info(f"{n} observaciones clasificadas")
    return n


@task(task_run_name="dbt {orden}")
def paso_dbt(orden: str) -> str:
    """Corre dbt y devuelve su resumen.

    Sin reintentos, a propósito: si `dbt test` falla es porque los datos no
    cumplen lo que se afirma de ellos, y repetir la misma consulta no lo
    arregla. Un reintento aquí solo escondería el problema un rato.
    """
    registro = get_run_logger()
    if not DBT.exists():
        raise RuntimeError(
            f"Falta el entorno de dbt en {DBT}. dbt no corre en Python 3.14, "
            f"así que vive aparte: py -3.11 -m venv .venv-dbt && "
            f".venv-dbt/Scripts/pip install -r requirements-dbt.txt")

    r = subprocess.run([str(DBT), orden, "--profiles-dir", "."],
                       cwd=AQUI, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600)
    resumen = next((l for l in reversed((r.stdout or "").splitlines())
                    if "PASS=" in l or "Completed" in l), "")

    if r.returncode != 0:
        # El error de dbt, no el código de salida: «returncode 1» no dice qué
        # prueba falló ni sobre qué modelo.
        fallos = [l.strip() for l in (r.stdout or "").splitlines()
                  if "Failure in" in l or "Error in" in l]
        raise RuntimeError(f"dbt {orden} falló. {' · '.join(fallos[:3]) or resumen}")

    registro.info(f"dbt {orden}: {resumen.strip()}")
    return resumen


@flow(name="radar", log_prints=True)
def radar(dias: int = 1, tope: int | None = None, servidor: str = "localhost:9092"):
    """Una pasada completa del radar.

    Los pasos van en serie y no en paralelo porque cada uno depende del
    anterior: no hay nada que clasificar hasta que el productor emite, ni nada
    que modelar hasta que el consumidor guarda.
    """
    emitidas = paso_productor(dias, tope, servidor)
    clasificadas = paso_consumidor(tope, servidor, wait_for=[emitidas])

    # `dbt run` reconstruye los modelos y `dbt test` comprueba que lo
    # reconstruido tiene sentido. En ese orden: probar antes de construir mide
    # los datos de la pasada anterior.
    construido = paso_dbt("run", wait_for=[clasificadas])
    paso_dbt("test", wait_for=[construido])

    print(f"pasada terminada · {emitidas} emitidas · {clasificadas} clasificadas")
    return {"emitidas": emitidas, "clasificadas": clasificadas}


def prueba():
    """Que el flujo esté bien montado, sin tocar red ni Kafka.

    Lo que se comprueba es lo que se puede romper al editar: que las tareas
    existan, que los reintentos sean los que se decidieron y que el entorno de
    dbt esté donde el flujo lo busca.
    """
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    assert paso_productor.retries == 3, paso_productor.retries
    assert paso_consumidor.retries == 2, paso_consumidor.retries

    # dbt sin reintentos: un test que falla no se arregla repitiéndolo.
    assert paso_dbt.retries == 0, "reintentar dbt escondería un fallo de datos"

    # La espera creciente importa: reintentar tres veces seguidas contra un
    # servidor que está cayéndose es insistir, no reintentar.
    assert paso_productor.retry_delay_seconds == [10, 30, 90], \
        paso_productor.retry_delay_seconds

    assert DBT.exists(), (f"falta {DBT}: dbt vive en su propio entorno porque no "
                          f"corre en Python 3.14")

    import productor, consumidor
    assert productor.TEMA == consumidor.TEMA == "observaciones", \
        "el productor y el consumidor hablan de temas distintos"

    print(f"ok · 4 pasos · reintentos 3/2/0 · dbt en {DBT.parent.parent.name} · "
          f"ambos extremos en el tema «{productor.TEMA}»")


def main():
    a = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    a.add_argument("--dias", type=int, default=1)
    a.add_argument("--tope", type=int)
    a.add_argument("--servidor", default="localhost:9092")
    a.add_argument("--comprobar", action="store_true")
    args = a.parse_args()

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if args.comprobar:
        return prueba()
    radar(dias=args.dias, tope=args.tope, servidor=args.servidor)


if __name__ == "__main__":
    main()
