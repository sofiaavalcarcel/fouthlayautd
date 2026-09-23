# Persistencia SQLite

`connection.py` prepara la base de datos y `repository.py` contiene las operaciones SQL. El resto del backend utiliza estos repositorios para impedir que SQL y reglas de negocio se mezclen en rutas o automatizaciones.
