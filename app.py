from flask import Flask, render_template, request, redirect, url_for, session
from database import conectar
from werkzeug.security import check_password_hash

app = Flask(__name__)
app.secret_key = "cambia_esto_por_algo_secreto"  # necesario para usar session

@app.route("/")
def inicio():
    # Por ahora, la raíz simplemente muestra el login.
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
            return "¡Login exitoso! Bienvenido, " + profesor["nombre"]
        else:
            return render_template("login.html", error="Correo o contraseña incorrectos")

    return render_template("login.html")

if __name__ == "__main__":
    app.run(debug=True)