"""
db_connection.py
================
Modulo de conexion a MySQL (compatible con phpMyAdmin).

Expone exactamente la misma API publica que la version anterior basada en
SQLite (ejecutar_query, obtener_uno, obtener_todos, esta_conectado, cerrar),
por lo que `repository.py` no necesita cambios: toda la logica de negocio
sigue siendo la misma, solo cambia el motor de base de datos por debajo.

Las consultas en repository.py usan "?" como marcador de parametros (estilo
SQLite). Aqui se traducen automaticamente a "%s" (estilo MySQL/PyMySQL) antes
de ejecutarlas, y se activa el modo SQL "PIPES_AS_CONCAT" para que las
concatenaciones con "||" que ya existian en el codigo (ej. nombre || ' ' ||
apellido) sigan funcionando igual que en SQLite.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path

import pymysql
import pymysql.cursors

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler("app.log", encoding="utf-8"), logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = BASE_DIR / "schema_mysql.sql"
CONFIG_PATH = BASE_DIR / "correo_island.env"


def _leer_config_archivo() -> dict:
    if not CONFIG_PATH.exists():
        return {}
    valores: dict[str, str] = {}
    try:
        for linea in CONFIG_PATH.read_text(encoding="utf-8").splitlines():
            limpia = linea.strip()
            if not limpia or limpia.startswith("#") or "=" not in limpia:
                continue
            clave, valor = limpia.split("=", 1)
            valores[clave.strip()] = valor.strip().strip('"').strip("'")
    except OSError:
        return {}
    return valores


def _config_mysql() -> dict:
    archivo = _leer_config_archivo()

    def _valor(clave: str, defecto: str = "") -> str:
        return os.getenv(clave, archivo.get(clave, defecto)).strip()

    return {
        "host": _valor("ASISTENCIA_DB_HOST", "127.0.0.1"),
        "port": int(_valor("ASISTENCIA_DB_PORT", "3306") or 3306),
        "user": _valor("ASISTENCIA_DB_USER", "root"),
        "password": _valor("ASISTENCIA_DB_PASSWORD", ""),
        "database": _valor("ASISTENCIA_DB_NAME", "control_asistencia"),
    }


# Convierte "SELECT * FROM x WHERE a = ? AND b = ?" -> "... a = %s AND b = %s"
_PLACEHOLDER_RE = re.compile(r"\?")


def _traducir_placeholders(query: str) -> str:
    return _PLACEHOLDER_RE.sub("%s", query)


class DatabaseManager:
    """Gestiona la conexion a MySQL y normaliza el acceso a filas dict.

    Mantiene la misma interfaz publica que la version SQLite original para
    que `repository.py` (y toda la logica de negocio) no requiera cambios.
    """

    def __init__(self, config: dict | None = None):
        self._config = config or _config_mysql()
        self._connection = None
        self.conectar()

    # ------------------------------------------------------------------
    # Conexion
    # ------------------------------------------------------------------
    def conectar(self) -> bool:
        if self._connection is not None:
            try:
                self._connection.ping(reconnect=True)
                return True
            except pymysql.MySQLError:
                self._connection = None

        try:
            self._connection = pymysql.connect(
                host=self._config["host"],
                port=self._config["port"],
                user=self._config["user"],
                password=self._config["password"],
                database=self._config["database"],
                charset="utf8mb4",
                cursorclass=pymysql.cursors.DictCursor,
                autocommit=False,
            )
            with self._connection.cursor() as cursor:
                # Permite que las consultas con "||" (concatenacion estilo
                # SQLite ya existentes en repository.py) sigan funcionando.
                cursor.execute("SET SESSION sql_mode = CONCAT(@@sql_mode, ',PIPES_AS_CONCAT')")
            self._connection.commit()
            self._inicializar_schema()
            self._migrar()
            logger.info(
                "Conexion a MySQL establecida (%s@%s/%s).",
                self._config["user"], self._config["host"], self._config["database"],
            )
            return True
        except pymysql.MySQLError as exc:
            logger.error("No se pudo conectar a MySQL: %s", exc)
            self._connection = None
            return False

    def _inicializar_schema(self):
        """Crea las tablas/vistas si la base de datos esta vacia."""
        if not SCHEMA_PATH.exists():
            return
        try:
            with self._connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) AS total FROM information_schema.tables "
                    "WHERE table_schema = %s AND table_name = 'estudiantes'",
                    (self._config["database"],),
                )
                existe = (cursor.fetchone() or {}).get("total", 0)
            if existe:
                return

            schema_sql = SCHEMA_PATH.read_text(encoding="utf-8")
            for sentencia in self._dividir_sentencias(schema_sql):
                with self._connection.cursor() as cursor:
                    cursor.execute(sentencia)
            self._connection.commit()
            logger.info("Esquema MySQL inicializado desde schema_mysql.sql.")
        except pymysql.MySQLError as exc:
            logger.error("Error al inicializar el esquema MySQL: %s", exc)
            self._connection.rollback()

    @staticmethod
    def _dividir_sentencias(schema_sql: str) -> list:
        lineas = [l for l in schema_sql.splitlines() if not l.strip().startswith("--")]
        limpio = "\n".join(lineas)
        return [s.strip() for s in limpio.split(";") if s.strip()]

    def _migrar(self):
        """Agrega columnas nuevas si la base de datos ya existia con un
        esquema anterior (equivalente a las migraciones que hacia la
        version SQLite)."""
        columnas_nuevas = {
            "estudiantes": {
                "telefono_encargado": "ALTER TABLE estudiantes ADD COLUMN telefono_encargado VARCHAR(30) NOT NULL DEFAULT ''",
                "correo_encargado": "ALTER TABLE estudiantes ADD COLUMN correo_encargado VARCHAR(190) NOT NULL DEFAULT ''",
            },
            "asistencia": {
                "turno": "ALTER TABLE asistencia ADD COLUMN turno VARCHAR(20) NOT NULL DEFAULT 'MATUTINO'",
                "estado_alerta": "ALTER TABLE asistencia ADD COLUMN estado_alerta VARCHAR(30) NOT NULL DEFAULT 'NORMAL'",
                "detalle_alerta": "ALTER TABLE asistencia ADD COLUMN detalle_alerta VARCHAR(255) NOT NULL DEFAULT 'Dentro del horario'",
            },
            "permisos": {
                "observacion": "ALTER TABLE permisos ADD COLUMN observacion VARCHAR(255) NOT NULL DEFAULT ''",
                "hora_permiso": "ALTER TABLE permisos ADD COLUMN hora_permiso VARCHAR(8) NOT NULL DEFAULT ''",
            },
        }
        try:
            for tabla, columnas in columnas_nuevas.items():
                existentes = {
                    fila["COLUMN_NAME"]
                    for fila in self.obtener_todos(
                        "SELECT COLUMN_NAME FROM information_schema.columns "
                        "WHERE table_schema = %s AND table_name = %s",
                        (self._config["database"], tabla),
                    )
                }
                for columna, sql in columnas.items():
                    if columna not in existentes:
                        with self._connection.cursor() as cursor:
                            cursor.execute(sql)
                        self._connection.commit()
        except pymysql.MySQLError as exc:
            logger.error("Error al migrar el esquema: %s", exc)

    # ------------------------------------------------------------------
    # Operaciones (misma interfaz publica que la version SQLite)
    # ------------------------------------------------------------------
    def _verificar_conexion(self) -> bool:
        try:
            return self.conectar()
        except pymysql.MySQLError:
            return False

    def ejecutar_query(self, query: str, params=None) -> bool:
        if not self._verificar_conexion():
            logger.error("No hay conexion disponible para ejecutar la consulta.")
            return False

        try:
            query = _traducir_placeholders(query)
            with self._connection.cursor() as cursor:
                cursor.execute(query, params or ())
            self._connection.commit()
            return True
        except pymysql.MySQLError as exc:
            logger.error("Error al ejecutar query: %s\nQuery: %s\nParams: %s", exc, query, params)
            try:
                self._connection.rollback()
            except pymysql.MySQLError:
                pass
            return False

    def obtener_uno(self, query: str, params=None):
        if not self._verificar_conexion():
            return None

        try:
            query = _traducir_placeholders(query)
            with self._connection.cursor() as cursor:
                cursor.execute(query, params or ())
                fila = cursor.fetchone()
            return dict(fila) if fila is not None else None
        except pymysql.MySQLError as exc:
            logger.error("Error en obtener_uno: %s", exc)
            return None

    def obtener_todos(self, query: str, params=None) -> list:
        if not self._verificar_conexion():
            return []

        try:
            query = _traducir_placeholders(query)
            with self._connection.cursor() as cursor:
                cursor.execute(query, params or ())
                filas = cursor.fetchall()
            return [dict(fila) for fila in filas]
        except pymysql.MySQLError as exc:
            logger.error("Error en obtener_todos: %s", exc)
            return []

    def esta_conectado(self) -> bool:
        try:
            if self._connection is None:
                return False
            self._connection.ping(reconnect=False)
            return True
        except pymysql.MySQLError:
            return False

    def cerrar(self):
        try:
            if self._connection is not None:
                self._connection.close()
                self._connection = None
                logger.info("Conexion MySQL cerrada.")
        except pymysql.MySQLError as exc:
            logger.error("Error al cerrar conexion: %s", exc)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cerrar()
