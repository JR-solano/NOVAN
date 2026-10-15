from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session
from database import conectar
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = "cambia_esto_por_algo_secreto"

NOTA_MINIMA_APROBATORIA = 3.0

# --- Decorador para proteger rutas que requieren sesión activa ---
def login_required(f):
    @wraps(f)
    def decorada(*args, **kwargs):
        if "profesor_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorada


def calcular_promedios(estudiantes, periodos, evaluaciones, notas):
    resultados = {}

    for estudiante in estudiantes:
        est_id = estudiante["id"]
        promedio_por_periodo = {}
        suma_final = 0
        suma_porcentaje_periodos_calificados = 0

        for periodo in periodos:
            periodo_id = periodo["id"]
            evaluaciones_periodo = [e for e in evaluaciones if e["periodo_id"] == periodo_id]

            suma_ponderada = 0
            suma_porcentaje_evaluaciones = 0

            for evaluacion in evaluaciones_periodo:
                valor = notas.get(est_id, {}).get(evaluacion["id"])
                if valor is not None and valor != "":
                    suma_ponderada += float(valor) * float(evaluacion["porcentaje"])
                    suma_porcentaje_evaluaciones += float(evaluacion["porcentaje"])

            if suma_porcentaje_evaluaciones > 0:
                promedio_periodo = suma_ponderada / suma_porcentaje_evaluaciones
                promedio_por_periodo[periodo_id] = round(promedio_periodo, 1)
                suma_final += promedio_periodo * float(periodo["porcentaje"])
                suma_porcentaje_periodos_calificados += float(periodo["porcentaje"])
            else:
                promedio_por_periodo[periodo_id] = None

        if suma_porcentaje_periodos_calificados > 0:
            promedio_final = suma_final / suma_porcentaje_periodos_calificados
        else:
            promedio_final = None

        # La materia solo se considera completa cuando los periodos
        # calificados suman el 100% (se usa 99.99 para evitar errores
        # de decimales al sumar).
        materia_completa = suma_porcentaje_periodos_calificados >= 99.99

        aprobado = None
        if promedio_final is not None:
            aprobado = promedio_final >= NOTA_MINIMA_APROBATORIA

        resultados[est_id] = {
            "periodos": promedio_por_periodo,
            "final": round(promedio_final, 1) if promedio_final is not None else None,
            "completo": materia_completa,
            "aprobado": aprobado,
        }

    return resultados


@app.route("/")
def inicio():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = request.form.get("correo")
        clave = request.form.get("clave")

        conexion = conectar()
        cursor = conexion.cursor()
        cursor.execute("SELECT * FROM profesor WHERE correo = ?", (correo,))
        profesor = cursor.fetchone()
        conexion.close()

        if profesor and check_password_hash(profesor["password_hash"], clave):
            session["profesor_id"] = profesor["id"]
            session["profesor_nombre"] = profesor["nombre"]
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Correo o contraseña incorrectos")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    conexion = conectar()
    cursor = conexion.cursor()
    cursor.execute(
        "SELECT * FROM plantilla WHERE profesor_id = ?",
        (session["profesor_id"],)
    )
    plantillas = cursor.fetchall()
    conexion.close()

    return render_template(
        "dashboard.html",
        nombre=session["profesor_nombre"],
        plantillas=plantillas
    )

@app.route("/plantilla/nueva", methods=["GET", "POST"])
@login_required
def nueva_plantilla():
    if request.method == "POST":
        nombre_salon = request.form.get("nombre_salon")
        materia = request.form.get("materia")

        conexion = conectar()
        cursor = conexion.cursor()
        cursor.execute(
            "INSERT INTO plantilla (profesor_id, nombre_salon, materia) VALUES (?, ?, ?)",
            (session["profesor_id"], nombre_salon, materia)
        )
        conexion.commit()
        conexion.close()

        return redirect(url_for("dashboard"))

    return render_template("nueva_plantilla.html")

@app.route("/plantilla/<int:plantilla_id>", methods=["GET", "POST"])
@login_required
def ver_plantilla(plantilla_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM plantilla WHERE id = ? AND profesor_id = ?",
        (plantilla_id, session["profesor_id"])
    )
    plantilla = cursor.fetchone()

    if plantilla is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        nombre_estudiante = request.form.get("nombre")
        cursor.execute(
            "INSERT INTO estudiante (plantilla_id, nombre) VALUES (?, ?)",
            (plantilla_id, nombre_estudiante)
        )
        conexion.commit()

    cursor.execute(
        "SELECT * FROM estudiante WHERE plantilla_id = ?",
        (plantilla_id,)
    )
    estudiantes = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM periodo WHERE plantilla_id = ?",
        (plantilla_id,)
    )
    periodos = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM evaluacion WHERE plantilla_id = ?",
        (plantilla_id,)
    )
    evaluaciones = cursor.fetchall()

    cursor.execute("""
        SELECT nota.* FROM nota
        JOIN estudiante ON nota.estudiante_id = estudiante.id
        WHERE estudiante.plantilla_id = ?
    """, (plantilla_id,))
    filas_notas = cursor.fetchall()

    notas = {}
    for fila in filas_notas:
        est_id = fila["estudiante_id"]
        eva_id = fila["evaluacion_id"]
        if est_id not in notas:
            notas[est_id] = {}
        notas[est_id][eva_id] = fila["valor"]

    conexion.close()

    promedios = calcular_promedios(estudiantes, periodos, evaluaciones, notas)

    return render_template(
        "plantilla.html",
        plantilla=plantilla,
        estudiantes=estudiantes,
        evaluaciones=evaluaciones,
        notas=notas,
        periodos=periodos,
        promedios=promedios
    )

@app.route("/plantilla/<int:plantilla_id>/evaluacion/nueva", methods=["POST"])
@login_required
def nueva_evaluacion(plantilla_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM plantilla WHERE id = ? AND profesor_id = ?",
        (plantilla_id, session["profesor_id"])
    )
    plantilla = cursor.fetchone()
    if plantilla is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    nombre = request.form.get("nombre")
    porcentaje = request.form.get("porcentaje")
    periodo_id = request.form.get("periodo_id")

    cursor.execute(
        "INSERT INTO evaluacion (plantilla_id, periodo_id, nombre, porcentaje) VALUES (?, ?, ?, ?)",
        (plantilla_id, periodo_id, nombre, porcentaje)
    )
    conexion.commit()
    conexion.close()

    return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))


@app.route("/plantilla/<int:plantilla_id>/nota/guardar", methods=["POST"])
@login_required
def guardar_nota(plantilla_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM plantilla WHERE id = ? AND profesor_id = ?",
        (plantilla_id, session["profesor_id"])
    )
    plantilla = cursor.fetchone()
    if plantilla is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    estudiante_id = request.form.get("estudiante_id")
    evaluacion_id = request.form.get("evaluacion_id")
    valor = request.form.get("valor")

    cursor.execute(
        "SELECT * FROM nota WHERE estudiante_id = ? AND evaluacion_id = ?",
        (estudiante_id, evaluacion_id)
    )
    nota_existente = cursor.fetchone()

    if nota_existente:
        cursor.execute(
            "UPDATE nota SET valor = ? WHERE id = ?",
            (valor, nota_existente["id"])
        )
    else:
        cursor.execute(
            "INSERT INTO nota (evaluacion_id, estudiante_id, valor) VALUES (?, ?, ?)",
            (evaluacion_id, estudiante_id, valor)
        )

    conexion.commit()
    conexion.close()

    return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))


@app.route("/plantilla/<int:plantilla_id>/periodo/nuevo", methods=["POST"])
@login_required
def nuevo_periodo(plantilla_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT * FROM plantilla WHERE id = ? AND profesor_id = ?",
        (plantilla_id, session["profesor_id"])
    )
    plantilla = cursor.fetchone()
    if plantilla is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    nombre = request.form.get("nombre")
    numero_clases = request.form.get("numero_clases")
    porcentaje = request.form.get("porcentaje")

    cursor.execute(
        "INSERT INTO periodo (plantilla_id, nombre, numero_clases, porcentaje) VALUES (?, ?, ?, ?)",
        (plantilla_id, nombre, numero_clases, porcentaje)
    )
    conexion.commit()
    conexion.close()

    return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))


@app.route("/periodo/<int:periodo_id>", methods=["GET", "POST"])
@login_required
def ver_periodo(periodo_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT periodo.*, plantilla.id AS plantilla_id, plantilla.profesor_id,
               plantilla.nombre_salon, plantilla.materia
        FROM periodo
        JOIN plantilla ON periodo.plantilla_id = plantilla.id
        WHERE periodo.id = ?
    """, (periodo_id,))
    periodo = cursor.fetchone()

    if periodo is None or periodo["profesor_id"] != session["profesor_id"]:
        conexion.close()
        return redirect(url_for("dashboard"))

    cursor.execute(
        "SELECT * FROM estudiante WHERE plantilla_id = ?",
        (periodo["plantilla_id"],)
    )
    estudiantes = cursor.fetchall()

    if request.method == "POST":
        for estudiante in estudiantes:
            for numero_clase in range(1, periodo["numero_clases"] + 1):
                campo = f"asistencia_{estudiante['id']}_{numero_clase}"
                estado = request.form.get(campo)
                if estado:
                    cursor.execute(
                        "SELECT * FROM asistencia WHERE periodo_id = ? AND estudiante_id = ? AND numero_clase = ?",
                        (periodo_id, estudiante["id"], numero_clase)
                    )
                    existente = cursor.fetchone()
                    if existente:
                        cursor.execute(
                            "UPDATE asistencia SET estado = ? WHERE id = ?",
                            (estado, existente["id"])
                        )
                    else:
                        cursor.execute(
                            "INSERT INTO asistencia (periodo_id, estudiante_id, numero_clase, estado) VALUES (?, ?, ?, ?)",
                            (periodo_id, estudiante["id"], numero_clase, estado)
                        )
        conexion.commit()

    cursor.execute(
        "SELECT * FROM asistencia WHERE periodo_id = ?",
        (periodo_id,)
    )
    filas_asistencia = cursor.fetchall()

    asistencia = {}
    for fila in filas_asistencia:
        est_id = fila["estudiante_id"]
        num = fila["numero_clase"]
        if est_id not in asistencia:
            asistencia[est_id] = {}
        asistencia[est_id][num] = fila["estado"]

    conexion.close()

    return render_template(
        "periodo.html",
        periodo=periodo,
        estudiantes=estudiantes,
        asistencia=asistencia
    )


# ============================================================
# RUTAS DE BORRADO
# Todas usan POST (nunca GET) para que un enlace no pueda borrar
# datos por accidente, y verifican que el registro pertenezca
# a una plantilla del profesor que tiene la sesión iniciada.
# SQLite no borra en cascada por defecto, así que borramos
# manualmente los datos dependientes, de hijos a padre.
# ============================================================

@app.route("/estudiante/<int:estudiante_id>/eliminar", methods=["POST"])
@login_required
def eliminar_estudiante(estudiante_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT estudiante.id, estudiante.plantilla_id
        FROM estudiante
        JOIN plantilla ON estudiante.plantilla_id = plantilla.id
        WHERE estudiante.id = ? AND plantilla.profesor_id = ?
    """, (estudiante_id, session["profesor_id"]))
    estudiante = cursor.fetchone()

    if estudiante is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    plantilla_id = estudiante["plantilla_id"]

    cursor.execute("DELETE FROM nota WHERE estudiante_id = ?", (estudiante_id,))
    cursor.execute("DELETE FROM asistencia WHERE estudiante_id = ?", (estudiante_id,))
    cursor.execute("DELETE FROM estudiante WHERE id = ?", (estudiante_id,))

    conexion.commit()
    conexion.close()

    return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))


@app.route("/evaluacion/<int:evaluacion_id>/eliminar", methods=["POST"])
@login_required
def eliminar_evaluacion(evaluacion_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT evaluacion.id, evaluacion.plantilla_id
        FROM evaluacion
        JOIN plantilla ON evaluacion.plantilla_id = plantilla.id
        WHERE evaluacion.id = ? AND plantilla.profesor_id = ?
    """, (evaluacion_id, session["profesor_id"]))
    evaluacion = cursor.fetchone()

    if evaluacion is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    plantilla_id = evaluacion["plantilla_id"]

    cursor.execute("DELETE FROM nota WHERE evaluacion_id = ?", (evaluacion_id,))
    cursor.execute("DELETE FROM evaluacion WHERE id = ?", (evaluacion_id,))

    conexion.commit()
    conexion.close()

    return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))


@app.route("/periodo/<int:periodo_id>/eliminar", methods=["POST"])
@login_required
def eliminar_periodo(periodo_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT periodo.id, periodo.plantilla_id
        FROM periodo
        JOIN plantilla ON periodo.plantilla_id = plantilla.id
        WHERE periodo.id = ? AND plantilla.profesor_id = ?
    """, (periodo_id, session["profesor_id"]))
    periodo = cursor.fetchone()

    if periodo is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    plantilla_id = periodo["plantilla_id"]

    # 1) notas de las evaluaciones de este periodo
    cursor.execute("""
        DELETE FROM nota
        WHERE evaluacion_id IN (SELECT id FROM evaluacion WHERE periodo_id = ?)
    """, (periodo_id,))
    # 2) las evaluaciones del periodo
    cursor.execute("DELETE FROM evaluacion WHERE periodo_id = ?", (periodo_id,))
    # 3) la asistencia del periodo
    cursor.execute("DELETE FROM asistencia WHERE periodo_id = ?", (periodo_id,))
    # 4) el periodo
    cursor.execute("DELETE FROM periodo WHERE id = ?", (periodo_id,))

    conexion.commit()
    conexion.close()

    return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))


# ============================================================
# RUTAS PARA EDITAR PORCENTAJES
# Validan que el valor sea un número entre 0 y 100 y que el
# registro pertenezca a una plantilla del profesor en sesión.
# ============================================================

def porcentaje_valido(texto):
    try:
        valor = float(texto)
    except (TypeError, ValueError):
        return None
    if valor < 0 or valor > 100:
        return None
    return valor


@app.route("/periodo/<int:periodo_id>/porcentaje", methods=["POST"])
@login_required
def editar_periodo_porcentaje(periodo_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT periodo.id, periodo.plantilla_id
        FROM periodo
        JOIN plantilla ON periodo.plantilla_id = plantilla.id
        WHERE periodo.id = ? AND plantilla.profesor_id = ?
    """, (periodo_id, session["profesor_id"]))
    periodo = cursor.fetchone()

    if periodo is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    plantilla_id = periodo["plantilla_id"]
    porcentaje = porcentaje_valido(request.form.get("porcentaje"))

    if porcentaje is not None:
        cursor.execute(
            "UPDATE periodo SET porcentaje = ? WHERE id = ?",
            (porcentaje, periodo_id)
        )
        conexion.commit()

    conexion.close()
    return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))


@app.route("/evaluacion/<int:evaluacion_id>/porcentaje", methods=["POST"])
@login_required
def editar_evaluacion_porcentaje(evaluacion_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT evaluacion.id, evaluacion.plantilla_id
        FROM evaluacion
        JOIN plantilla ON evaluacion.plantilla_id = plantilla.id
        WHERE evaluacion.id = ? AND plantilla.profesor_id = ?
    """, (evaluacion_id, session["profesor_id"]))
    evaluacion = cursor.fetchone()

    if evaluacion is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    plantilla_id = evaluacion["plantilla_id"]
    porcentaje = porcentaje_valido(request.form.get("porcentaje"))

    if porcentaje is not None:
        cursor.execute(
            "UPDATE evaluacion SET porcentaje = ? WHERE id = ?",
            (porcentaje, evaluacion_id)
        )
        conexion.commit()

    conexion.close()
    return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))


# ============================================================
# REPORTE DE ASISTENCIA POR PERIODO
# Cuenta, por estudiante, cuántas veces tiene cada estado
# (Asistió, Falta, Excusa...) y calcula el porcentaje de fallas
# sobre el número de clases del periodo.
# ============================================================

@app.route("/periodo/<int:periodo_id>/reporte")
@login_required
def reporte_asistencia(periodo_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        SELECT periodo.*, plantilla.profesor_id,
               plantilla.nombre_salon, plantilla.materia
        FROM periodo
        JOIN plantilla ON periodo.plantilla_id = plantilla.id
        WHERE periodo.id = ?
    """, (periodo_id,))
    periodo = cursor.fetchone()

    if periodo is None or periodo["profesor_id"] != session["profesor_id"]:
        conexion.close()
        return redirect(url_for("dashboard"))

    cursor.execute(
        "SELECT * FROM estudiante WHERE plantilla_id = ?",
        (periodo["plantilla_id"],)
    )
    estudiantes = cursor.fetchall()

    cursor.execute("""
        SELECT estudiante_id, estado, COUNT(*) AS total
        FROM asistencia
        WHERE periodo_id = ?
        GROUP BY estudiante_id, estado
    """, (periodo_id,))
    filas = cursor.fetchall()
    conexion.close()

    # Estados que existen realmente en la base de datos (columnas del reporte)
    estados = sorted({fila["estado"] for fila in filas})

    conteos = {}
    for fila in filas:
        conteos.setdefault(fila["estudiante_id"], {})[fila["estado"]] = fila["total"]

    numero_clases = int(periodo["numero_clases"])
    resumen = []
    for estudiante in estudiantes:
        por_estado = conteos.get(estudiante["id"], {})
        registradas = sum(por_estado.values())
        fallas = sum(
            total for estado, total in por_estado.items()
            if "falta" in estado.lower()
        )
        porcentaje_fallas = round(fallas / numero_clases * 100, 1) if numero_clases > 0 else 0
        resumen.append({
            "nombre": estudiante["nombre"],
            "por_estado": por_estado,
            "fallas": fallas,
            "porcentaje_fallas": porcentaje_fallas,
            "sin_registrar": max(numero_clases - registradas, 0),
        })

    return render_template(
        "reporte_asistencia.html",
        periodo=periodo,
        estados=estados,
        resumen=resumen
    )


if __name__ == "__main__":
    app.run(debug=True)