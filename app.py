import math
import re
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, jsonify
from database import conectar
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
import os
app.secret_key = os.environ.get("SECRET_KEY", "clave-solo-para-desarrollo-local")

# Si el profesor marca "Recordar mi cuenta", la sesión dura 31 días
app.permanent_session_lifetime = timedelta(days=31)

NOTA_MINIMA_APROBATORIA = 3.0
NOTA_MINIMA_ESCALA = 1.0
NOTA_MAXIMA_ESCALA = 5.0

# --- Decorador para proteger rutas que requieren sesión activa ---
def login_required(f):
    @wraps(f)
    def decorada(*args, **kwargs):
        if "profesor_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorada


def redondear_1(valor):
    """Redondea a un decimal como en el colegio: 3.25 -> 3.3 (la mitad sube)."""
    return float(Decimal(str(round(valor, 6))).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))


# ============================================================
# FORMATO DE PORCENTAJES
# 15.0 -> "15"      12.5 -> "12,5"      (para mostrar en pantalla)
# 15.0 -> "15"      12.5 -> "12.5"      (para las casillas de editar,
#                                        que necesitan punto decimal)
# ============================================================

@app.template_filter("pct")
def formato_porcentaje(valor):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return valor
    if numero == int(numero):
        return str(int(numero))
    return ("%g" % round(numero, 2)).replace(".", ",")


@app.template_filter("pct_input")
def formato_porcentaje_input(valor):
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return valor
    if numero == int(numero):
        return str(int(numero))
    return "%g" % round(numero, 2)


def normalizar_nota(texto):
    """
    Convierte lo que escribe el profesor en una nota válida.
      "29"  -> 2.9      "45" -> 4.5      "10" -> 1.0
      "3"   -> 3.0      "2,9" o "2.9" -> 2.9
      ""    -> ""  (casilla vacía, se borra la nota)
    Devuelve None si no es válida (fuera de 1.0 a 5.0 o con formato raro).
    """
    t = (texto or "").strip().replace(",", ".")
    if t == "":
        return ""
    if re.fullmatch(r"\d{2}", t):
        numero = int(t) / 10
    elif re.fullmatch(r"\d(\.\d)?", t):
        numero = float(t)
    else:
        return None
    if numero < NOTA_MINIMA_ESCALA or numero > NOTA_MAXIMA_ESCALA:
        return None
    return round(numero, 1)


def calcular_promedios(estudiantes, periodos, evaluaciones, notas):
    resultados = {}

    for estudiante in estudiantes:
        est_id = estudiante["id"]
        promedio_por_periodo = {}
        detalle_por_periodo = {}
        suma_final = 0
        suma_porcentaje_periodos_calificados = 0

        for periodo in periodos:
            periodo_id = periodo["id"]
            evaluaciones_periodo = [e for e in evaluaciones if e["periodo_id"] == periodo_id]

            suma_ponderada = 0
            suma_porcentaje_evaluaciones = 0
            porcentaje_total_periodo = 0
            evaluaciones_con_nota = 0

            for evaluacion in evaluaciones_periodo:
                peso = float(evaluacion["porcentaje"])
                porcentaje_total_periodo += peso
                valor = notas.get(est_id, {}).get(evaluacion["id"])
                if valor is not None and valor != "":
                    suma_ponderada += float(valor) * peso
                    suma_porcentaje_evaluaciones += peso
                    evaluaciones_con_nota += 1

            # --- Resumen de este periodo ---
            # nota: promedio del periodo con lo que lleva
            # estado: ganado / perdido (solo si tiene TODAS las notas),
            #         curso (faltan notas) o sin_notas
            # para_ganar: 3.0 si el periodo está completo; si faltan notas,
            #             lo que debe sacar en las evaluaciones que faltan
            detalle = {"nota": None, "estado": "sin_notas", "para_ganar": None}

            if evaluaciones_periodo and porcentaje_total_periodo > 0:
                completo = evaluaciones_con_nota == len(evaluaciones_periodo)

                if suma_porcentaje_evaluaciones > 0:
                    nota_periodo = redondear_1(suma_ponderada / suma_porcentaje_evaluaciones)
                    detalle["nota"] = nota_periodo
                    if completo:
                        if nota_periodo >= NOTA_MINIMA_APROBATORIA:
                            detalle["estado"] = "ganado"
                        else:
                            detalle["estado"] = "perdido"
                    else:
                        detalle["estado"] = "curso"

                if completo:
                    detalle["para_ganar"] = {"tipo": "minimo", "valor": NOTA_MINIMA_APROBATORIA}
                else:
                    restante = porcentaje_total_periodo - suma_porcentaje_evaluaciones
                    necesario = (NOTA_MINIMA_APROBATORIA * porcentaje_total_periodo - suma_ponderada) / restante
                    if necesario > NOTA_MAXIMA_ESCALA:
                        detalle["para_ganar"] = {"tipo": "imposible", "valor": None}
                    else:
                        valor_necesario = max(math.ceil(round(necesario * 10, 6)) / 10, NOTA_MINIMA_ESCALA)
                        detalle["para_ganar"] = {"tipo": "necesita", "valor": valor_necesario}

            detalle_por_periodo[periodo_id] = detalle

            # --- Aporte del periodo a la materia ---
            if suma_porcentaje_evaluaciones > 0:
                # La nota del periodo se redondea a un decimal ANTES de
                # multiplicarla por el porcentaje del periodo.
                promedio_periodo = redondear_1(suma_ponderada / suma_porcentaje_evaluaciones)
                promedio_por_periodo[periodo_id] = promedio_periodo
                suma_final += promedio_periodo * float(periodo["porcentaje"])
                suma_porcentaje_periodos_calificados += float(periodo["porcentaje"])
            else:
                promedio_por_periodo[periodo_id] = None

        if suma_porcentaje_periodos_calificados > 0:
            promedio_final = redondear_1(suma_final / suma_porcentaje_periodos_calificados)
        else:
            promedio_final = None

        # La materia solo se considera completa cuando los periodos
        # calificados suman el 100% (se usa 99.99 para evitar errores
        # de decimales al sumar).
        materia_completa = suma_porcentaje_periodos_calificados >= 99.99

        aprobado = None
        if promedio_final is not None:
            aprobado = promedio_final >= NOTA_MINIMA_APROBATORIA

        # --- Cálculo de toda la materia (por si se necesita más adelante) ---
        puntos_acumulados = suma_final / 100
        porcentaje_restante = 100 - suma_porcentaje_periodos_calificados

        # Nombres de los periodos que todavía no tienen ninguna nota
        periodos_faltantes = [
            p["nombre"] for p in periodos if promedio_por_periodo[p["id"]] is None
        ]

        meta = None
        if suma_porcentaje_periodos_calificados > 0 and not materia_completa:
            necesario = (NOTA_MINIMA_APROBATORIA - puntos_acumulados) / (porcentaje_restante / 100)
            if necesario <= NOTA_MINIMA_ESCALA:
                meta = {"tipo": "ganada", "valor": None}
            elif necesario > NOTA_MAXIMA_ESCALA:
                meta = {"tipo": "imposible", "valor": None}
            else:
                # Se redondea hacia arriba a un decimal para que la nota alcance
                valor = math.ceil(round(necesario * 10, 6)) / 10
                meta = {"tipo": "necesita", "valor": valor}

        resultados[est_id] = {
            "periodos": promedio_por_periodo,
            "detalle": detalle_por_periodo,
            "final": promedio_final,
            "completo": materia_completa,
            "aprobado": aprobado,
            "acumulado": round(puntos_acumulados, 2),
            "restante": round(porcentaje_restante, 1),
            "faltantes": periodos_faltantes,
            "meta": meta,
        }

    return resultados


@app.route("/")
def inicio():
    return render_template("login.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        correo = (request.form.get("correo") or "").strip().lower()
        clave = request.form.get("clave")

        conexion = conectar()
        cursor = conexion.cursor()
        cursor.execute("SELECT * FROM profesor WHERE LOWER(correo) = ?", (correo,))
        profesor = cursor.fetchone()
        conexion.close()

        if profesor and check_password_hash(profesor["password_hash"], clave):
            # Con la casilla "Recordar mi cuenta" marcada, la sesión
            # sigue activa aunque se cierre el navegador (31 días).
            session.permanent = bool(request.form.get("recordar"))
            session["profesor_id"] = profesor["id"]
            session["profesor_nombre"] = profesor["nombre"]
            return redirect(url_for("dashboard"))
        else:
            return render_template("login.html", error="Correo o contraseña incorrectos")

    return render_template("login.html")


# ============================================================
# REGISTRO DE PROFESORES
# Crea una cuenta nueva con la contraseña cifrada y entra directo
# al panel. El correo se guarda en minúsculas y no se puede repetir.
# ============================================================

@app.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "POST":
        nombre = (request.form.get("nombre") or "").strip()
        correo = (request.form.get("correo") or "").strip().lower()
        clave = request.form.get("clave") or ""
        confirmar = request.form.get("confirmar") or ""

        error = None
        if not nombre or not correo or not clave:
            error = "Completa todos los campos."
        elif "@" not in correo or "." not in correo.split("@")[-1]:
            error = "Escribe un correo válido."
        elif len(clave) < 6:
            error = "La contraseña debe tener al menos 6 caracteres."
        elif clave != confirmar:
            error = "Las contraseñas no coinciden."

        if error is None:
            conexion = conectar()
            cursor = conexion.cursor()
            cursor.execute("SELECT id FROM profesor WHERE LOWER(correo) = ?", (correo,))
            if cursor.fetchone() is not None:
                error = "Ya existe una cuenta con ese correo."
                conexion.close()
            else:
                cursor.execute(
                    "INSERT INTO profesor (nombre, correo, password_hash) VALUES (?, ?, ?)",
                    (nombre, correo, generate_password_hash(clave))
                )
                conexion.commit()
                profesor_id = cursor.lastrowid
                conexion.close()

                session["profesor_id"] = profesor_id
                session["profesor_nombre"] = nombre
                return redirect(url_for("dashboard"))

        return render_template("registro.html", error=error, nombre=nombre, correo=correo)

    return render_template("registro.html")


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


# ============================================================
# ELIMINAR UNA CLASE COMPLETA
# Borra la clase y todo lo que tiene adentro: notas, asistencia,
# evaluaciones, periodos y estudiantes (de hijos a padre, porque
# SQLite no borra en cascada por defecto). Solo si la clase
# pertenece al profesor que tiene la sesión iniciada.
# ============================================================

@app.route("/plantilla/<int:plantilla_id>/eliminar", methods=["POST"])
@login_required
def eliminar_plantilla(plantilla_id):
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT id FROM plantilla WHERE id = ? AND profesor_id = ?",
        (plantilla_id, session["profesor_id"])
    )
    if cursor.fetchone() is None:
        conexion.close()
        return redirect(url_for("dashboard"))

    # 1) notas (de los estudiantes y de las evaluaciones de esta clase)
    cursor.execute("""
        DELETE FROM nota
        WHERE estudiante_id IN (SELECT id FROM estudiante WHERE plantilla_id = ?)
    """, (plantilla_id,))
    cursor.execute("""
        DELETE FROM nota
        WHERE evaluacion_id IN (SELECT id FROM evaluacion WHERE plantilla_id = ?)
    """, (plantilla_id,))
    # 2) asistencia (de los periodos y de los estudiantes de esta clase)
    cursor.execute("""
        DELETE FROM asistencia
        WHERE periodo_id IN (SELECT id FROM periodo WHERE plantilla_id = ?)
    """, (plantilla_id,))
    cursor.execute("""
        DELETE FROM asistencia
        WHERE estudiante_id IN (SELECT id FROM estudiante WHERE plantilla_id = ?)
    """, (plantilla_id,))
    # 3) evaluaciones, periodos y estudiantes
    cursor.execute("DELETE FROM evaluacion WHERE plantilla_id = ?", (plantilla_id,))
    cursor.execute("DELETE FROM periodo WHERE plantilla_id = ?", (plantilla_id,))
    cursor.execute("DELETE FROM estudiante WHERE plantilla_id = ?", (plantilla_id,))
    # 4) la clase
    cursor.execute("DELETE FROM plantilla WHERE id = ?", (plantilla_id,))

    conexion.commit()
    conexion.close()

    return redirect(url_for("dashboard"))


# ============================================================
# PLANTILLA DE LA CLASE (la hoja completa)
# Estudiantes, periodos, evaluaciones, notas y asistencia en una
# sola pantalla. En la asistencia: A = asistió, F = falta,
# E = excusa y la casilla vacía significa sin registrar.
# ============================================================

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

    # Agregar un estudiante (y volver a cargar la hoja)
    if request.method == "POST":
        nombre_estudiante = (request.form.get("nombre") or "").strip()
        if nombre_estudiante:
            cursor.execute(
                "INSERT INTO estudiante (plantilla_id, nombre) VALUES (?, ?)",
                (plantilla_id, nombre_estudiante)
            )
            conexion.commit()
        conexion.close()
        return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))

    cursor.execute(
        "SELECT * FROM estudiante WHERE plantilla_id = ? ORDER BY id",
        (plantilla_id,)
    )
    estudiantes = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM periodo WHERE plantilla_id = ? ORDER BY id",
        (plantilla_id,)
    )
    periodos = cursor.fetchall()

    cursor.execute(
        "SELECT * FROM evaluacion WHERE plantilla_id = ? ORDER BY id",
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

    # Asistencia de todos los periodos de esta clase:
    #   asistencia[periodo][estudiante][clase] = "A", "F" o "E"
    #   conteos[periodo][estudiante] = {"A": cuántas, "F": cuántas, "E": cuántas}
    cursor.execute("""
        SELECT asistencia.* FROM asistencia
        JOIN periodo ON asistencia.periodo_id = periodo.id
        WHERE periodo.plantilla_id = ?
    """, (plantilla_id,))
    filas_asistencia = cursor.fetchall()

    conexion.close()

    asistencia = {}
    conteos = {}
    for fila in filas_asistencia:
        estado = (fila["estado"] or "").lower()
        if "falta" in estado:
            marca = "F"
        elif "excusa" in estado:
            marca = "E"
        elif "asisti" in estado:
            marca = "A"
        else:
            continue  # vacío: sin registrar
        asistencia.setdefault(fila["periodo_id"], {}).setdefault(
            fila["estudiante_id"], {}
        )[fila["numero_clase"]] = marca
        cuenta = conteos.setdefault(fila["periodo_id"], {}).setdefault(
            fila["estudiante_id"], {"A": 0, "F": 0, "E": 0}
        )
        cuenta[marca] += 1

    # Cuánto suman las evaluaciones de cada periodo y los periodos entre sí
    suma_evaluaciones = {
        p["id"]: sum(float(e["porcentaje"]) for e in evaluaciones if e["periodo_id"] == p["id"])
        for p in periodos
    }
    suma_periodos = sum(float(p["porcentaje"]) for p in periodos)

    promedios = calcular_promedios(estudiantes, periodos, evaluaciones, notas)

    return render_template(
        "plantilla.html",
        plantilla=plantilla,
        estudiantes=estudiantes,
        evaluaciones=evaluaciones,
        notas=notas,
        periodos=periodos,
        promedios=promedios,
        asistencia=asistencia,
        conteos=conteos,
        suma_evaluaciones=suma_evaluaciones,
        suma_periodos=suma_periodos
    )


# ============================================================
# GUARDAR UNA CASILLA DE ASISTENCIA (se llama sin recargar la página)
# A -> "Asistio", F -> "Falta", E -> "Excusa", vacío -> se borra
# ============================================================

@app.route("/plantilla/<int:plantilla_id>/asistencia/guardar", methods=["POST"])
@login_required
def guardar_asistencia(plantilla_id):
    estados = {"A": "Asistio", "F": "Falta", "E": "Excusa", "": None}
    marca = (request.form.get("marca") or "").strip().upper()
    if marca not in estados:
        return jsonify(ok=False, error="Marca no válida"), 400

    try:
        estudiante_id = int(request.form.get("estudiante_id"))
        periodo_id = int(request.form.get("periodo_id"))
        numero_clase = int(request.form.get("numero_clase"))
    except (TypeError, ValueError):
        return jsonify(ok=False, error="Datos incompletos"), 400

    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute(
        "SELECT id FROM plantilla WHERE id = ? AND profesor_id = ?",
        (plantilla_id, session["profesor_id"])
    )
    if cursor.fetchone() is None:
        conexion.close()
        return jsonify(ok=False, error="Clase no encontrada"), 404

    cursor.execute(
        "SELECT numero_clases FROM periodo WHERE id = ? AND plantilla_id = ?",
        (periodo_id, plantilla_id)
    )
    periodo = cursor.fetchone()
    cursor.execute(
        "SELECT id FROM estudiante WHERE id = ? AND plantilla_id = ?",
        (estudiante_id, plantilla_id)
    )
    estudiante = cursor.fetchone()

    if (
        periodo is None
        or estudiante is None
        or numero_clase < 1
        or numero_clase > int(periodo["numero_clases"])
    ):
        conexion.close()
        return jsonify(ok=False, error="Datos no válidos"), 400

    cursor.execute(
        "DELETE FROM asistencia WHERE periodo_id = ? AND estudiante_id = ? AND numero_clase = ?",
        (periodo_id, estudiante_id, numero_clase)
    )
    if estados[marca] is not None:
        cursor.execute(
            "INSERT INTO asistencia (periodo_id, estudiante_id, numero_clase, estado) VALUES (?, ?, ?, ?)",
            (periodo_id, estudiante_id, numero_clase, estados[marca])
        )

    conexion.commit()
    conexion.close()
    return jsonify(ok=True)


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

    # Convierte lo escrito (29 -> 2.9) y rechaza lo que esté fuera de 1.0 a 5.0
    valor = normalizar_nota(request.form.get("valor"))
    if valor is None:
        conexion.close()
        return redirect(url_for("ver_plantilla", plantilla_id=plantilla_id))

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
# Por estudiante: cuántas veces asistió (A), faltó (F), tuvo
# excusa (E), cuántas clases están sin registrar y el porcentaje
# de fallas sobre el total de clases del periodo.
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
        "SELECT * FROM estudiante WHERE plantilla_id = ? ORDER BY id",
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

    conteos = {}
    for fila in filas:
        estado = (fila["estado"] or "").lower()
        cuenta = conteos.setdefault(
            fila["estudiante_id"], {"asistio": 0, "fallas": 0, "excusas": 0}
        )
        if "falta" in estado:
            cuenta["fallas"] += fila["total"]
        elif "excusa" in estado:
            cuenta["excusas"] += fila["total"]
        elif "asisti" in estado:
            cuenta["asistio"] += fila["total"]

    numero_clases = int(periodo["numero_clases"])
    resumen = []
    for estudiante in estudiantes:
        cuenta = conteos.get(estudiante["id"], {"asistio": 0, "fallas": 0, "excusas": 0})
        asistio = cuenta["asistio"]
        fallas = cuenta["fallas"]
        excusas = cuenta["excusas"]
        sin_registrar = max(numero_clases - asistio - fallas - excusas, 0)
        porcentaje_fallas = round(fallas / numero_clases * 100, 1) if numero_clases > 0 else 0
        resumen.append({
            "nombre": estudiante["nombre"],
            "asistio": asistio,
            "fallas": fallas,
            "excusas": excusas,
            "sin_registrar": sin_registrar,
            "porcentaje_fallas": porcentaje_fallas,
        })

    return render_template(
        "reporte_asistencia.html",
        periodo=periodo,
        resumen=resumen
    )


if __name__ == "__main__":
    app.run(debug=True)