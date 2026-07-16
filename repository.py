"""
repository.py
=============
Capa de acceso a datos (repositorio) para SQLite.
Contiene toda la lógica SQL separada de la interfaz gráfica.
"""

from __future__ import annotations

from datetime import date, datetime, time

from db_connection import DatabaseManager


class AsistenciaRepository:
    """Repositorio con los métodos de negocio del sistema de asistencia."""

    HORARIOS = {
        "MATUTINO": {"inicio": time(7, 0), "fin": time(11, 45)},
        "VESPERTINO": {"inicio": time(13, 0), "fin": time(17, 45)},
    }

    def __init__(self, db: DatabaseManager):
        self._db = db

    # ─────────────────────────────────────────────────────────
    # ESTUDIANTES
    # ─────────────────────────────────────────────────────────

    def buscar_estudiante(self, id_estudiante: str) -> dict | None:
        query = """
            SELECT id_estudiante, nombre, apellido, codigo_seccion, correo_encargado, telefono_encargado, activo
            FROM estudiantes
            WHERE id_estudiante = ?
              AND activo = 1
        """
        return self._db.obtener_uno(query, (id_estudiante.strip().upper(),))

    def registrar_estudiante(
        self,
        id_estudiante: str,
        nombre: str,
        apellido: str,
        codigo_seccion: str,
        correo_encargado: str = "",
        telefono_encargado: str = "",
    ) -> bool:
        query = """
            INSERT INTO estudiantes (
                id_estudiante,
                nombre,
                apellido,
                codigo_seccion,
                correo_encargado,
                telefono_encargado
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """
        return self._db.ejecutar_query(
            query,
            (
                str(id_estudiante).strip(),
                str(nombre).strip().title(),
                str(apellido).strip().title(),
                str(codigo_seccion).strip().upper(),
                str(correo_encargado).strip().lower(),
                str(telefono_encargado).strip(),
            ),
        )

    def actualizar_estudiante(
        self,
        id_estudiante_original: str,
        id_estudiante_nuevo: str,
        nombre: str,
        apellido: str,
        codigo_seccion: str,
        correo_encargado: str = "",
        telefono_encargado: str = "",
        activo: bool = True,
    ) -> bool:
        query = """
            UPDATE estudiantes
            SET id_estudiante = ?,
                nombre = ?,
                apellido = ?,
                codigo_seccion = ?,
                correo_encargado = ?,
                telefono_encargado = ?,
                activo = ?
            WHERE id_estudiante = ?
        """
        return self._db.ejecutar_query(
            query,
            (
                str(id_estudiante_nuevo).strip(),
                str(nombre).strip().title(),
                str(apellido).strip().title(),
                str(codigo_seccion).strip().upper(),
                str(correo_encargado).strip().lower(),
                str(telefono_encargado).strip(),
                1 if activo else 0,
                str(id_estudiante_original).strip(),
            ),
        )

    def buscar_estudiante_por_id(self, id_estudiante: str) -> dict | None:
        query = """
            SELECT id_estudiante, nombre, apellido, codigo_seccion, correo_encargado, telefono_encargado, activo
            FROM estudiantes
            WHERE id_estudiante = ?
        """
        return self._db.obtener_uno(query, (id_estudiante.strip(),))

    def eliminar_estudiante(self, id_estudiante: str) -> bool:
        query = """
            UPDATE estudiantes
            SET activo = 0
            WHERE id_estudiante = ?
        """
        return self._db.ejecutar_query(query, (str(id_estudiante).strip(),))

    def obtener_estudiantes(
        self,
        codigo_seccion: str | None = None,
        incluir_inactivos: bool = False,
    ) -> list[dict]:
        query = """
            SELECT
                id_estudiante,
                nombre,
                apellido,
                codigo_seccion,
                correo_encargado,
                telefono_encargado,
                activo,
                fecha_registro
            FROM estudiantes
        """
        filtros = []
        params: list[object] = []

        if codigo_seccion and codigo_seccion != "TODAS":
            filtros.append("codigo_seccion = ?")
            params.append(codigo_seccion.strip().upper())

        if not incluir_inactivos:
            filtros.append("activo = 1")

        if filtros:
            query += " WHERE " + " AND ".join(filtros)

        query += " ORDER BY codigo_seccion, apellido, nombre"
        return self._db.obtener_todos(query, tuple(params))

    # ─────────────────────────────────────────────────────────
    # ASISTENCIA
    # ─────────────────────────────────────────────────────────

    def determinar_tipo_evento(self, id_estudiante: str) -> str:
        """Determina si el siguiente movimiento del dia es INGRESO o SALIDA.

        El sistema ya no limita a un solo par de entrada/salida por dia: los
        registros se alternan indefinidamente (1ro entrada, 2do salida, 3ro
        entrada, 4to salida, ...) segun cual fue el ultimo evento registrado.
        """
        query = """
            SELECT tipo_evento
            FROM asistencia
            WHERE id_estudiante = ?
              AND fecha = ?
            ORDER BY id_asistencia DESC
            LIMIT 1
        """
        ultimo = self._db.obtener_uno(query, (id_estudiante, date.today().isoformat()))
        if ultimo is None or ultimo["tipo_evento"] == "SALIDA":
            return "INGRESO"
        return "SALIDA"

    def obtener_estado_estudiante_hoy(self, id_estudiante: str) -> str:
        query = """
            SELECT tipo_evento
            FROM asistencia
            WHERE id_estudiante = ?
              AND fecha = ?
            ORDER BY id_asistencia DESC
            LIMIT 1
        """
        ultimo = self._db.obtener_uno(query, (id_estudiante, date.today().isoformat()))
        if ultimo is None or ultimo["tipo_evento"] == "SALIDA":
            return "FUERA"
        return "DENTRO"

    # Tipos de alerta que requieren un permiso autorizado antes de registrarse.
    ALERTAS_QUE_REQUIEREN_PERMISO = ("ENTRADA TARDIA", "SALIDA TEMPRANA")

    def registrar_movimiento(self, id_estudiante: str, usuario_actual: str = "") -> dict | None:
        ahora = datetime.now()
        tipo_evento = self.determinar_tipo_evento(id_estudiante)

        fecha = ahora.date().isoformat()
        hora = ahora.strftime("%H:%M:%S")
        turno, estado_alerta, detalle_alerta = self._evaluar_alerta(tipo_evento, ahora.time())

        permiso_aplicado = None
        permiso_evidencia = "NO APLICA"
        permiso_estado = ""
        if estado_alerta in self.ALERTAS_QUE_REQUIEREN_PERMISO:
            permiso = self.obtener_permiso_del_dia(id_estudiante, fecha, tipo_evento)

            if permiso is None:
                permiso = self.crear_solicitud_permiso(
                    id_estudiante, fecha, tipo_evento, detalle_alerta, usuario_actual
                )
            if permiso is not None:
                permiso_estado = str(permiso.get("estado") or "")
                hora_permiso = str(permiso.get("hora_permiso") or "").strip()
                hora_texto = f" {hora_permiso}" if hora_permiso else ""
                if permiso_estado == "APROBADO":
                    permiso_aplicado = permiso
                    detalle_alerta = f"{detalle_alerta} | CON PERMISO{hora_texto} ({permiso.get('autorizado_por') or 'coordinación'})"
                    permiso_evidencia = f"CON PERMISO{hora_texto}".strip()
                elif permiso_estado == "PENDIENTE":
                    detalle_alerta = f"{detalle_alerta} | SIN PERMISO (pendiente{hora_texto})"
                    permiso_evidencia = "SIN PERMISO"
                elif permiso_estado == "RECHAZADO":
                    detalle_alerta = f"{detalle_alerta} | SIN PERMISO (rechazado{hora_texto})"
                    permiso_evidencia = "SIN PERMISO"
                else:
                    detalle_alerta = f"{detalle_alerta} | SIN PERMISO"
                    permiso_evidencia = "SIN PERMISO"
            else:
                detalle_alerta = f"{detalle_alerta} | SIN PERMISO"
                permiso_evidencia = "SIN PERMISO"

        query = """
            INSERT INTO asistencia (
                id_estudiante,
                fecha,
                hora,
                tipo_evento,
                turno,
                estado_alerta,
                detalle_alerta
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        exito = self._db.ejecutar_query(
            query,
            (id_estudiante, fecha, hora, tipo_evento, turno, estado_alerta, detalle_alerta),
        )

        if not exito:
            return None

        if permiso_aplicado is not None:
            self.marcar_permiso_aplicado(permiso_aplicado["id_permiso"])

        return {
            "id_estudiante": id_estudiante,
            "fecha": ahora.strftime("%d/%m/%Y"),
            "hora": hora,
            "tipo_evento": tipo_evento,
            "turno": turno,
            "estado_alerta": estado_alerta,
            "detalle_alerta": detalle_alerta,
            "permiso_evidencia": permiso_evidencia,
            "permiso_estado": permiso_estado,
            "estado_actual": "DENTRO" if tipo_evento == "INGRESO" else "FUERA",
        }

    def obtener_ultimos_movimientos(self, limite: int = 50) -> list[dict]:
        query = """
            SELECT
                a.id_asistencia,
                e.nombre || ' ' || e.apellido AS nombre_completo,
                e.codigo_seccion,
                e.correo_encargado,
                e.telefono_encargado,
                a.fecha,
                a.hora,
                a.tipo_evento,
                a.turno,
                a.estado_alerta,
                a.detalle_alerta
            FROM asistencia a
            INNER JOIN estudiantes e ON a.id_estudiante = e.id_estudiante
            WHERE a.fecha = ?
            ORDER BY a.hora DESC, a.id_asistencia DESC
            LIMIT ?
        """
        filas = self._db.obtener_todos(query, (date.today().isoformat(), limite))
        for fila in filas:
            fila["fecha"] = self._formatear_fecha(fila["fecha"])
        return filas

    def obtener_historial_completo(self, limite: int = 200) -> list[dict]:
        query = """
            SELECT
                a.id_asistencia,
                a.id_estudiante,
                e.nombre || ' ' || e.apellido AS nombre_completo,
                e.codigo_seccion,
                e.correo_encargado,
                e.telefono_encargado,
                a.fecha,
                a.hora,
                a.tipo_evento,
                a.turno,
                a.estado_alerta,
                a.detalle_alerta
            FROM asistencia a
            INNER JOIN estudiantes e ON a.id_estudiante = e.id_estudiante
            ORDER BY a.fecha DESC, a.hora DESC, a.id_asistencia DESC
            LIMIT ?
        """
        filas = self._db.obtener_todos(query, (limite,))
        for fila in filas:
            fila["fecha"] = self._formatear_fecha(fila["fecha"])
        return filas

    def obtener_reporte_movimientos(self) -> list[dict]:
        query = """
            SELECT
                a.id_asistencia,
                a.id_estudiante,
                e.nombre || ' ' || e.apellido AS nombre_completo,
                e.codigo_seccion,
                e.correo_encargado,
                e.telefono_encargado,
                a.fecha,
                a.hora,
                a.tipo_evento,
                a.turno,
                a.estado_alerta,
                a.detalle_alerta
            FROM asistencia a
            INNER JOIN estudiantes e ON a.id_estudiante = e.id_estudiante
            ORDER BY a.fecha DESC, a.hora DESC, a.id_asistencia DESC
        """
        filas = self._db.obtener_todos(query)
        for fila in filas:
            fila["fecha"] = self._formatear_fecha(fila["fecha"])
        return filas

    def obtener_resumen_hoy(self) -> dict:
        query = """
            SELECT
                SUM(CASE WHEN tipo_evento = 'INGRESO' THEN 1 ELSE 0 END) AS total_ingresos,
                SUM(CASE WHEN tipo_evento = 'SALIDA' THEN 1 ELSE 0 END) AS total_salidas
            FROM asistencia
            WHERE fecha = ?
        """
        resultado = self._db.obtener_uno(query, (date.today().isoformat(),)) or {}
        ingresos = int(resultado.get("total_ingresos") or 0)
        salidas = int(resultado.get("total_salidas") or 0)
        return {
            "ingresos": ingresos,
            "salidas": salidas,
            "presentes": self.obtener_presentes_hoy(),
        }

    def _evaluar_alerta(self, tipo_evento: str, hora_actual: time) -> tuple[str, str, str]:
        turno = self._determinar_turno(hora_actual)
        horario = self.HORARIOS[turno]

        if tipo_evento == "INGRESO" and hora_actual < horario["inicio"]:
            return (
                turno,
                "ENTRADA TEMPRANA",
                f"Entrada antes de las {horario['inicio'].strftime('%H:%M')}",
            )

        if tipo_evento == "INGRESO" and hora_actual > horario["inicio"]:
            return (
                turno,
                "ENTRADA TARDIA",
                f"Entrada despues de las {horario['inicio'].strftime('%H:%M')}",
            )

        if tipo_evento == "SALIDA" and hora_actual < horario["fin"]:
            return (
                turno,
                "SALIDA TEMPRANA",
                f"Salida antes de las {horario['fin'].strftime('%H:%M')}",
            )

        if tipo_evento == "SALIDA" and hora_actual > horario["fin"]:
            return (
                turno,
                "SALIDA TARDIA",
                f"Salida despues de las {horario['fin'].strftime('%H:%M')}",
            )

        return turno, "NORMAL", "Dentro del horario"

    def _determinar_turno(self, hora_actual: time) -> str:
        if hora_actual < time(12, 30):
            return "MATUTINO"
        return "VESPERTINO"

    def obtener_presentes_hoy(self) -> int:
        query = """
            SELECT COUNT(*) AS total_presentes
            FROM (
                SELECT a.id_estudiante, a.tipo_evento
                FROM asistencia a
                INNER JOIN (
                    SELECT id_estudiante, MAX(id_asistencia) AS id_asistencia
                    FROM asistencia
                    WHERE fecha = ?
                    GROUP BY id_estudiante
                ) ultimos ON ultimos.id_asistencia = a.id_asistencia
            ) x
            WHERE x.tipo_evento = 'INGRESO'
        """
        resultado = self._db.obtener_uno(query, (date.today().isoformat(),)) or {}
        return int(resultado.get("total_presentes") or 0)

    def obtener_estadisticas_generales(self) -> dict:
        resumen_estudiantes = self._db.obtener_uno(
            """
            SELECT
                COUNT(*) AS total_estudiantes,
                SUM(CASE WHEN activo = 1 THEN 1 ELSE 0 END) AS activos,
                SUM(CASE WHEN activo = 0 THEN 1 ELSE 0 END) AS inactivos
            FROM estudiantes
            """,
        ) or {}

        resumen_hoy = self._db.obtener_uno(
            """
            SELECT
                SUM(CASE WHEN tipo_evento = 'INGRESO' THEN 1 ELSE 0 END) AS ingresos,
                SUM(CASE WHEN tipo_evento = 'SALIDA' THEN 1 ELSE 0 END) AS salidas
            FROM asistencia
            WHERE fecha = ?
            """,
            (date.today().isoformat(),),
        ) or {}

        secciones = self._db.obtener_todos(
            """
            SELECT
                codigo_seccion,
                COUNT(*) AS total_estudiantes,
                SUM(CASE WHEN activo = 1 THEN 1 ELSE 0 END) AS activos
            FROM estudiantes
            GROUP BY codigo_seccion
            ORDER BY codigo_seccion
            """
        )

        asistencia_por_seccion = self._db.obtener_todos(
            """
            SELECT
                e.codigo_seccion,
                SUM(CASE WHEN a.tipo_evento = 'INGRESO' THEN 1 ELSE 0 END) AS ingresos,
                SUM(CASE WHEN a.tipo_evento = 'SALIDA' THEN 1 ELSE 0 END) AS salidas
            FROM asistencia a
            INNER JOIN estudiantes e ON a.id_estudiante = e.id_estudiante
            WHERE a.fecha = ?
            GROUP BY e.codigo_seccion
            ORDER BY e.codigo_seccion
            """,
            (date.today().isoformat(),),
        )

        return {
            "total_estudiantes": int(resumen_estudiantes.get("total_estudiantes") or 0),
            "activos": int(resumen_estudiantes.get("activos") or 0),
            "inactivos": int(resumen_estudiantes.get("inactivos") or 0),
            "ingresos_hoy": int(resumen_hoy.get("ingresos") or 0),
            "salidas_hoy": int(resumen_hoy.get("salidas") or 0),
            "presentes_hoy": self.obtener_presentes_hoy(),
            "secciones": secciones,
            "asistencia_por_seccion": asistencia_por_seccion,
        }

    # ─────────────────────────────────────────────────────────
    # PERMISOS (entrada tardía / salida antes de horario)
    # ─────────────────────────────────────────────────────────

    def obtener_permiso_del_dia(self, id_estudiante: str, fecha: str, tipo_evento: str) -> dict | None:
        """Devuelve el permiso más reciente (no aplicado aún) para ese estudiante/día/tipo."""
        query = """
            SELECT *
            FROM permisos
            WHERE id_estudiante = ?
              AND fecha = ?
              AND tipo_evento = ?
              AND aplicado = 0
            ORDER BY id_permiso DESC
            LIMIT 1
        """
        return self._db.obtener_uno(query, (id_estudiante, fecha, tipo_evento))

    def crear_solicitud_permiso(
        self,
        id_estudiante: str,
        fecha: str,
        tipo_evento: str,
        motivo: str = "",
        solicitado_por: str = "",
        observacion: str = "",
        hora_permiso: str = "",
    ) -> dict | None:
        query = """
            INSERT INTO permisos (
                id_estudiante, fecha, tipo_evento, motivo, observacion, hora_permiso, estado, solicitado_por
            )
            VALUES (?, ?, ?, ?, ?, ?, 'PENDIENTE', ?)
        """
        exito = self._db.ejecutar_query(
            query, (id_estudiante, fecha, tipo_evento, motivo, observacion, hora_permiso, solicitado_por)
        )
        if not exito:
            return None
        return self.obtener_permiso_del_dia(id_estudiante, fecha, tipo_evento)

    def solicitar_permiso_manual(
        self,
        id_estudiante: str,
        fecha: str,
        tipo_evento: str,
        motivo: str,
        solicitado_por: str = "",
    ) -> bool:
        """Permite crear una solicitud de permiso de forma anticipada (antes del escaneo)."""
        existente = self.obtener_permiso_del_dia(id_estudiante, fecha, tipo_evento)
        if existente is not None and existente["estado"] == "PENDIENTE":
            return False
        return (
            self.crear_solicitud_permiso(id_estudiante, fecha, tipo_evento, motivo, solicitado_por)
            is not None
        )

    def otorgar_permiso_seccion(
        self,
        codigo_seccion: str,
        fecha: str,
        tipo_evento: str,
        motivo: str = "",
        solicitado_por: str = "",
        hora_permiso: str = "",
    ) -> int:
        """Crea una solicitud de permiso para todos los estudiantes activos de una sección."""
        estudiantes = self.obtener_estudiantes(codigo_seccion=codigo_seccion, incluir_inactivos=False)
        creados = 0
        for estudiante in estudiantes:
            existente = self._db.obtener_uno(
                """
                SELECT id_permiso
                FROM permisos
                WHERE id_estudiante = ?
                  AND fecha = ?
                  AND tipo_evento = ?
                LIMIT 1
                """,
                (estudiante["id_estudiante"], fecha, tipo_evento),
            )
            if existente is not None:
                continue
            if self.crear_solicitud_permiso(
                estudiante["id_estudiante"],
                fecha,
                tipo_evento,
                motivo,
                solicitado_por,
                "",
                hora_permiso,
            ) is not None:
                creados += 1
        return creados

    def resolver_permiso(
        self,
        id_permiso: int,
        estado: str,
        autorizado_por: str = "",
        observacion: str = "",
        hora_permiso: str = "",
    ) -> bool:
        if estado not in ("APROBADO", "RECHAZADO"):
            return False

        permiso = self._db.obtener_uno(
            "SELECT id_estudiante, fecha, tipo_evento, hora_permiso FROM permisos WHERE id_permiso = ?",
            (id_permiso,),
        )
        if permiso is None:
            return False

        query = """
            UPDATE permisos
            SET estado = ?,
                autorizado_por = ?,
                observacion = COALESCE(NULLIF(?, ''), observacion),
                hora_permiso = COALESCE(NULLIF(?, ''), hora_permiso),
                fecha_resolucion = datetime('now', 'localtime')
            WHERE id_permiso = ?
        """
        exito = self._db.ejecutar_query(query, (estado, autorizado_por, observacion, hora_permiso, id_permiso))
        if not exito:
            return False

        self._actualizar_evidencia_permiso_en_asistencia(
            str(permiso["id_estudiante"]),
            str(permiso["fecha"]),
            str(permiso["tipo_evento"]),
            estado,
            autorizado_por,
            str(hora_permiso or permiso.get("hora_permiso") or ""),
        )
        return True

    def marcar_permiso_aplicado(self, id_permiso: int) -> bool:
        query = "UPDATE permisos SET aplicado = 1 WHERE id_permiso = ?"
        return self._db.ejecutar_query(query, (id_permiso,))

    def _actualizar_evidencia_permiso_en_asistencia(
        self,
        id_estudiante: str,
        fecha: str,
        tipo_evento: str,
        estado_permiso: str,
        autorizado_por: str = "",
        hora_permiso: str = "",
    ) -> None:
        filas = self._db.obtener_todos(
            """
            SELECT id_asistencia, detalle_alerta
            FROM asistencia
            WHERE id_estudiante = ?
              AND fecha = ?
              AND tipo_evento = ?
            ORDER BY id_asistencia DESC
            """,
            (id_estudiante, fecha, tipo_evento),
        )
        if not filas:
            return

        hora_texto = f" {hora_permiso.strip()}" if hora_permiso.strip() else ""
        if estado_permiso == "APROBADO":
            evidencia = f"CON PERMISO{hora_texto} ({autorizado_por or 'coordinación'})"
        else:
            evidencia = f"SIN PERMISO (rechazado{hora_texto})"

        for fila in filas:
            detalle_actual = str(fila.get("detalle_alerta") or "").strip()
            base = detalle_actual.split("|", 1)[0].strip() if "|" in detalle_actual else detalle_actual
            nuevo_detalle = f"{base} | {evidencia}" if base else evidencia
            self._db.ejecutar_query(
                "UPDATE asistencia SET detalle_alerta = ? WHERE id_asistencia = ?",
                (nuevo_detalle, fila["id_asistencia"]),
            )

    def obtener_permisos_pendientes(self) -> list[dict]:
        query = """
            SELECT * FROM v_permisos
            WHERE estado = 'PENDIENTE'
            ORDER BY fecha_solicitud ASC
        """
        return self._db.obtener_todos(query)

    def obtener_historial_permisos(self, limite: int = 200) -> list[dict]:
        query = "SELECT * FROM v_permisos ORDER BY fecha_solicitud DESC LIMIT ?"
        return self._db.obtener_todos(query, (limite,))

    def contar_permisos_pendientes(self) -> int:
        resultado = self._db.obtener_uno(
            "SELECT COUNT(*) AS total FROM permisos WHERE estado = 'PENDIENTE'"
        ) or {}
        return int(resultado.get("total") or 0)

    # ─────────────────────────────────────────────────────────
    # USUARIOS (control de acceso: administrador / profesor-coordinador)
    # ─────────────────────────────────────────────────────────

    def verificar_credenciales(self, usuario: str, password: str) -> dict | None:
        query = """
            SELECT id_usuario, usuario, nombre_completo, rol
            FROM usuarios
            WHERE usuario = ?
              AND password = ?
              AND activo = 1
        """
        return self._db.obtener_uno(query, (usuario.strip(), password))

    def obtener_usuarios(self) -> list[dict]:
        query = """
            SELECT id_usuario, usuario, nombre_completo, rol, activo, fecha_registro
            FROM usuarios
            ORDER BY rol, usuario
        """
        return self._db.obtener_todos(query)

    def crear_usuario(
        self, usuario: str, password: str, nombre_completo: str, rol: str
    ) -> bool:
        if rol not in ("ADMIN", "PROFESOR"):
            rol = "PROFESOR"
        query = """
            INSERT INTO usuarios (usuario, password, nombre_completo, rol)
            VALUES (?, ?, ?, ?)
        """
        return self._db.ejecutar_query(
            query, (usuario.strip().lower(), password.strip(), nombre_completo.strip(), rol)
        )

    def eliminar_usuario(self, id_usuario: int) -> bool:
        query = "UPDATE usuarios SET activo = 0 WHERE id_usuario = ?"
        return self._db.ejecutar_query(query, (id_usuario,))

    @staticmethod
    def _formatear_fecha(fecha) -> str:
        # MySQL/PyMySQL puede devolver la fecha como str, bytes, datetime.date
        # o datetime.datetime segun como haya quedado definida la columna;
        # esto la normaliza a texto "dd/mm/aaaa" sin importar el tipo recibido.
        if fecha is None:
            return ""
        if isinstance(fecha, (datetime, date)):
            return fecha.strftime("%d/%m/%Y")
        if isinstance(fecha, bytes):
            fecha = fecha.decode("utf-8", errors="ignore")
        fecha = str(fecha).strip()
        if not fecha:
            return ""
        try:
            return datetime.fromisoformat(fecha[:10]).strftime("%d/%m/%Y")
        except ValueError:
            return fecha