import pyodbc

# Dados da conexão
conn_str = (
    "DRIVER={ODBC Driver 18 for SQL Server};"
    "SERVER=cobmais-stage.database.windows.net,1433;"
    "DATABASE=credcom;"
    "UID=credcom;"
    "PWD=wUTZZpWnjlxfxidDe8Av;"
    "Encrypt=yes;"
    "TrustServerCertificate=no;"
    "Connection Timeout=30;"
)

# Conecta ao banco
conn = pyodbc.connect(conn_str)
cursor = conn.cursor()

# Consulta específica
aco_id = 6128259227
query = "SELECT * FROM tb_acordo WHERE aco_id = ?"
cursor.execute(query, (aco_id,))

# Mostra resultados
columns = [col[0] for col in cursor.description]
for row in cursor.fetchall():
    print(dict(zip(columns, row)))

# Fecha conexão
cursor.close()
conn.close()
