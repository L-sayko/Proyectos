-- ============================================================
-- SISTEMA DE CONTROL DE INGRESO Y SALIDA - SQLite
-- ============================================================

PRAGMA foreign_keys = ON;

-- Secciones o grados disponibles.
CREATE TABLE IF NOT EXISTS secciones (
    codigo_seccion  TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    activo          INTEGER NOT NULL DEFAULT 1,
    fecha_registro  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Registro principal de estudiantes.
CREATE TABLE IF NOT EXISTS estudiantes (
    id_estudiante   TEXT PRIMARY KEY,
    nombre          TEXT NOT NULL,
    apellido        TEXT NOT NULL,
    codigo_seccion  TEXT NOT NULL,
    correo_encargado TEXT NOT NULL DEFAULT '',
    activo          INTEGER NOT NULL DEFAULT 1,
    fecha_registro  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    FOREIGN KEY (codigo_seccion) REFERENCES secciones(codigo_seccion)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_estudiantes_seccion ON estudiantes(codigo_seccion);
CREATE INDEX IF NOT EXISTS idx_estudiantes_nombre ON estudiantes(apellido, nombre);

-- Tabla que registra todas las entradas y salidas.
CREATE TABLE IF NOT EXISTS asistencia (
    id_asistencia   INTEGER PRIMARY KEY AUTOINCREMENT,
    id_estudiante   TEXT NOT NULL,
    fecha           TEXT NOT NULL,
    hora            TEXT NOT NULL,
    tipo_evento     TEXT NOT NULL CHECK (tipo_evento IN ('INGRESO', 'SALIDA')),
    turno           TEXT NOT NULL DEFAULT 'MATUTINO',
    estado_alerta   TEXT NOT NULL DEFAULT 'NORMAL',
    detalle_alerta  TEXT NOT NULL DEFAULT 'Dentro del horario',
    FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_asistencia_fecha ON asistencia(fecha);
CREATE INDEX IF NOT EXISTS idx_asistencia_estudiante_fecha ON asistencia(id_estudiante, fecha);
CREATE INDEX IF NOT EXISTS idx_asistencia_fecha_hora ON asistencia(fecha, hora, id_asistencia);

-- Cuentas de acceso al sistema (administrador, profesor/coordinador).
CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario      INTEGER PRIMARY KEY AUTOINCREMENT,
    usuario         TEXT NOT NULL UNIQUE,
    password        TEXT NOT NULL,
    nombre_completo TEXT NOT NULL DEFAULT '',
    rol             TEXT NOT NULL CHECK (rol IN ('ADMIN', 'PROFESOR')) DEFAULT 'PROFESOR',
    activo          INTEGER NOT NULL DEFAULT 1,
    fecha_registro  TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);

-- Permisos/autorizaciones para entradas tardias o salidas antes de horario.
CREATE TABLE IF NOT EXISTS permisos (
    id_permiso       INTEGER PRIMARY KEY AUTOINCREMENT,
    id_estudiante    TEXT NOT NULL,
    fecha            TEXT NOT NULL,
    tipo_evento      TEXT NOT NULL CHECK (tipo_evento IN ('INGRESO', 'SALIDA')),
    motivo           TEXT NOT NULL DEFAULT '',
    observacion      TEXT NOT NULL DEFAULT '',
    hora_permiso     TEXT NOT NULL DEFAULT '',
    estado           TEXT NOT NULL CHECK (estado IN ('PENDIENTE', 'APROBADO', 'RECHAZADO')) DEFAULT 'PENDIENTE',
    aplicado         INTEGER NOT NULL DEFAULT 0,
    solicitado_por   TEXT NOT NULL DEFAULT '',
    autorizado_por   TEXT NOT NULL DEFAULT '',
    fecha_solicitud  TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    fecha_resolucion TEXT,
    FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
);

CREATE INDEX IF NOT EXISTS idx_permisos_estudiante_fecha ON permisos(id_estudiante, fecha, tipo_evento);
CREATE INDEX IF NOT EXISTS idx_permisos_estado ON permisos(estado);

DROP VIEW IF EXISTS v_registros_estudiantes;
DROP VIEW IF EXISTS v_reporte_movimientos;
DROP VIEW IF EXISTS v_ultimos_movimientos;
DROP VIEW IF EXISTS v_permisos;

-- Vista para ver todos los estudiantes registrados.
CREATE VIEW IF NOT EXISTS v_registros_estudiantes AS
    SELECT
        e.id_estudiante,
        e.nombre,
        e.apellido,
        e.nombre || ' ' || e.apellido AS nombre_completo,
        e.codigo_seccion,
        e.correo_encargado,
        COALESCE(s.nombre, e.codigo_seccion) AS seccion,
        e.activo,
        e.fecha_registro
    FROM estudiantes e
    LEFT JOIN secciones s ON s.codigo_seccion = e.codigo_seccion
    ORDER BY e.codigo_seccion, e.apellido, e.nombre;

-- Vista completa para reportes de quien entro y quien salio.
CREATE VIEW IF NOT EXISTS v_reporte_movimientos AS
    SELECT
        a.id_asistencia,
        a.id_estudiante,
        e.nombre || ' ' || e.apellido AS nombre_completo,
        e.codigo_seccion,
        e.correo_encargado,
        a.fecha,
        a.hora,
        a.tipo_evento,
        a.turno,
        a.estado_alerta,
        a.detalle_alerta,
        CASE
            WHEN a.tipo_evento = 'INGRESO' THEN 'ENTRO'
            ELSE 'SALIO'
        END AS movimiento
    FROM asistencia a
    INNER JOIN estudiantes e ON a.id_estudiante = e.id_estudiante
    ORDER BY a.fecha DESC, a.hora DESC, a.id_asistencia DESC;

CREATE VIEW IF NOT EXISTS v_ultimos_movimientos AS
    SELECT
        a.id_asistencia,
        a.id_estudiante,
        e.nombre || ' ' || e.apellido AS nombre_completo,
        e.codigo_seccion,
        e.correo_encargado,
        a.fecha,
        a.hora,
        a.tipo_evento,
        a.turno,
        a.estado_alerta,
        a.detalle_alerta
    FROM asistencia a
    INNER JOIN estudiantes e ON a.id_estudiante = e.id_estudiante
    ORDER BY a.fecha DESC, a.hora DESC, a.id_asistencia DESC;

-- Vista para el panel de permisos (entrada tardia / salida antes de horario).
CREATE VIEW IF NOT EXISTS v_permisos AS
    SELECT
        p.id_permiso,
        p.id_estudiante,
        e.nombre || ' ' || e.apellido AS nombre_completo,
        e.codigo_seccion,
        p.fecha,
        p.tipo_evento,
        p.motivo,
        p.observacion,
        p.hora_permiso,
        p.estado,
        p.aplicado,
        p.solicitado_por,
        p.autorizado_por,
        p.fecha_solicitud,
        p.fecha_resolucion
    FROM permisos p
    INNER JOIN estudiantes e ON e.id_estudiante = p.id_estudiante
    ORDER BY p.fecha_solicitud DESC, p.id_permiso DESC;

INSERT OR IGNORE INTO usuarios (usuario, password, nombre_completo, rol) VALUES
('admin', 'admin123', 'Administrador del sistema', 'ADMIN'),
('profesor', 'profesor123', 'Profesor / Coordinador', 'PROFESOR');

INSERT OR IGNORE INTO secciones (codigo_seccion, nombre) VALUES
('DS1A', 'Desarrollo de Software 1A'),
('DS2A', 'Desarrollo de Software 2A'),
('DS3A', 'Desarrollo de Software 3A');

INSERT OR IGNORE INTO estudiantes (id_estudiante, nombre, apellido, codigo_seccion) VALUES
('6052414', 'Ana Maria',   'Garcia Lopez',     'DS1A'),
('6052415', 'Carlos',      'Martinez Ruiz',    'DS1A'),
('6052416', 'Sofia',       'Hernandez Paz',    'DS1A'),
('6053414', 'Diego',       'Lopez Morales',    'DS2A'),
('6053415', 'Valentina',   'Rodriguez Cruz',   'DS2A'),
('6053416', 'Andres',      'Perez Fuentes',    'DS2A'),
('6054414', 'Isabella',    'Ramirez Vega',     'DS3A'),
('6054415', 'Sebastian',   'Torres Castillo',  'DS3A'),
('6054416', 'Lucia',       'Flores Mendoza',   'DS3A');
