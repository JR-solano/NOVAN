from database import conectar
from werkzeug.security import generate_password_hash

def crear_profesor_prueba():
    conexion = conectar()
    cursor = conexion.cursor()

    nombre = "Profesor Prueba"
    correo = "prueba@novan.com"
    password_plana = "1234"
    password_hash = generate_password_hash(password_plana)

    cursor.execute(
        "INSERT INTO profesor (nombre, correo, password_hash) VALUES (?, ?, ?)",
        (nombre, correo, password_hash)
    )

    conexion.commit()
    conexion.close()
    print(f"Profesor creado: {correo} / contraseña: {password_plana}")

if __name__ == "__main__":
    crear_profesor_prueba()