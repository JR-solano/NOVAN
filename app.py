from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session
from database import conectar
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = "cambia_esto_por_algo_secreto"

# --- Decorador para proteger rutas que requieren sesión activa ---
def login_required(f):
    @wraps(f)
    def decorada(*args, **kwargs):
        if "profesor_id" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorada

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

if __name__ == "__main__":
    app.run(debug=True)