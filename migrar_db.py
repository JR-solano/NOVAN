import sqlite3

conexion = sqlite3.connect("novan.db")
cursor = conexion.cursor()

try:
    cursor.execute("ALTER TABLE periodo ADD COLUMN porcentaje REAL NOT NULL DEFAULT 0")
    print("Columna 'porcentaje' agregada a la tabla periodo")
except sqlite3.OperationalError as error:
    print("periodo.porcentaje:", error)

try:
    cursor.execute("ALTER TABLE evaluacion ADD COLUMN periodo_id INTEGER")
    print("Columna 'periodo_id' agregada a la tabla evaluacion")
except sqlite3.OperationalError as error:
    print("evaluacion.periodo_id:", error)

conexion.commit()
conexion.close()
print("Migración completa")