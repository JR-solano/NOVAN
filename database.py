import sqlite3

def conectar():
    conexion = sqlite3.connect("novan.db")
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion

def crear_tablas():
    conexion = conectar()
    cursor = conexion.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS profesor (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            correo TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS plantilla (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            profesor_id INTEGER NOT NULL,
            nombre_salon TEXT NOT NULL,
            materia TEXT NOT NULL,
            FOREIGN KEY (profesor_id) REFERENCES profesor(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estudiante (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plantilla_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            FOREIGN KEY (plantilla_id) REFERENCES plantilla(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS evaluacion (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plantilla_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            porcentaje REAL NOT NULL,
            FOREIGN KEY (plantilla_id) REFERENCES plantilla(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS nota (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            evaluacion_id INTEGER NOT NULL,
            estudiante_id INTEGER NOT NULL,
            valor REAL NOT NULL,
            FOREIGN KEY (evaluacion_id) REFERENCES evaluacion(id),
            FOREIGN KEY (estudiante_id) REFERENCES estudiante(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS periodo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plantilla_id INTEGER NOT NULL,
            nombre TEXT NOT NULL,
            numero_clases INTEGER NOT NULL,
            FOREIGN KEY (plantilla_id) REFERENCES plantilla(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS asistencia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            periodo_id INTEGER NOT NULL,
            estudiante_id INTEGER NOT NULL,
            numero_clase INTEGER NOT NULL,
            estado TEXT NOT NULL,
            FOREIGN KEY (periodo_id) REFERENCES periodo(id),
            FOREIGN KEY (estudiante_id) REFERENCES estudiante(id)
        )
    """)

    conexion.commit()
    conexion.close()

if __name__ == "__main__":
    crear_tablas()
    print("Todas las tablas fueron creadas correctamente")
    