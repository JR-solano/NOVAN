import sqlite3

conexion = sqlite3.connect("novan.db")
cursor = conexion.cursor()

# Renombra el periodo de prueba "1" a "Primer periodo" y le pone su porcentaje
cursor.execute(
    "UPDATE periodo SET nombre = 'Primer periodo', porcentaje = 20 WHERE nombre = '1'"
)

# Liga las evaluaciones sueltas (sin periodo) a "Primer periodo"
cursor.execute(
    "UPDATE evaluacion SET periodo_id = (SELECT id FROM periodo WHERE nombre = 'Primer periodo') WHERE periodo_id IS NULL"
)

conexion.commit()
conexion.close()
print("Datos de prueba actualizados")