-- ============================================================
-- SISTEMA DE CONTROL DE INGRESO Y SALIDA - MySQL / phpMyAdmin
-- Equivalente del schema.sql original (SQLite) para poder
-- administrar la base de datos desde phpMyAdmin.
-- Importa este archivo desde phpMyAdmin (pestaña "Importar")
-- en una base de datos vacía, por ejemplo "control_asistencia".
-- ============================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 1;

-- Secciones o grados disponibles.
CREATE TABLE IF NOT EXISTS secciones (
    codigo_seccion  VARCHAR(20) PRIMARY KEY,
    nombre          VARCHAR(150) NOT NULL,
    activo          TINYINT(1) NOT NULL DEFAULT 1,
    fecha_registro  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Registro principal de estudiantes.
CREATE TABLE IF NOT EXISTS estudiantes (
    id_estudiante     VARCHAR(30) PRIMARY KEY,
    nombre            VARCHAR(150) NOT NULL,
    apellido          VARCHAR(150) NOT NULL,
    codigo_seccion    VARCHAR(20) NOT NULL,
    correo_encargado  VARCHAR(190) NOT NULL DEFAULT '',
    telefono_encargado VARCHAR(30) NOT NULL DEFAULT '',
    activo            TINYINT(1) NOT NULL DEFAULT 1,
    fecha_registro    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT fk_estudiantes_seccion FOREIGN KEY (codigo_seccion) REFERENCES secciones(codigo_seccion)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_estudiantes_seccion ON estudiantes(codigo_seccion);
CREATE INDEX idx_estudiantes_nombre ON estudiantes(apellido, nombre);

-- Tabla que registra todas las entradas y salidas.
CREATE TABLE IF NOT EXISTS asistencia (
    id_asistencia   INT AUTO_INCREMENT PRIMARY KEY,
    id_estudiante   VARCHAR(30) NOT NULL,
    fecha           VARCHAR(10) NOT NULL,
    hora            VARCHAR(8)  NOT NULL,
    tipo_evento     ENUM('INGRESO', 'SALIDA') NOT NULL,
    turno           VARCHAR(20) NOT NULL DEFAULT 'MATUTINO',
    estado_alerta   VARCHAR(30) NOT NULL DEFAULT 'NORMAL',
    detalle_alerta  VARCHAR(255) NOT NULL DEFAULT 'Dentro del horario',
    CONSTRAINT fk_asistencia_estudiante FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_asistencia_fecha ON asistencia(fecha);
CREATE INDEX idx_asistencia_estudiante_fecha ON asistencia(id_estudiante, fecha);
CREATE INDEX idx_asistencia_fecha_hora ON asistencia(fecha, hora, id_asistencia);

-- Cuentas de acceso al sistema (administrador, profesor/coordinador).
CREATE TABLE IF NOT EXISTS usuarios (
    id_usuario      INT AUTO_INCREMENT PRIMARY KEY,
    usuario         VARCHAR(100) NOT NULL UNIQUE,
    password        VARCHAR(255) NOT NULL,
    nombre_completo VARCHAR(190) NOT NULL DEFAULT '',
    rol             ENUM('ADMIN', 'PROFESOR') NOT NULL DEFAULT 'PROFESOR',
    activo          TINYINT(1) NOT NULL DEFAULT 1,
    fecha_registro  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Permisos/autorizaciones para entradas tardias o salidas antes de horario.
CREATE TABLE IF NOT EXISTS permisos (
    id_permiso       INT AUTO_INCREMENT PRIMARY KEY,
    id_estudiante    VARCHAR(30) NOT NULL,
    fecha            VARCHAR(10) NOT NULL,
    tipo_evento      ENUM('INGRESO', 'SALIDA') NOT NULL,
    motivo           VARCHAR(255) NOT NULL DEFAULT '',
    observacion      VARCHAR(255) NOT NULL DEFAULT '',
    hora_permiso     VARCHAR(8) NOT NULL DEFAULT '',
    estado           ENUM('PENDIENTE', 'APROBADO', 'RECHAZADO') NOT NULL DEFAULT 'PENDIENTE',
    aplicado         TINYINT(1) NOT NULL DEFAULT 0,
    solicitado_por   VARCHAR(190) NOT NULL DEFAULT '',
    autorizado_por   VARCHAR(190) NOT NULL DEFAULT '',
    fecha_solicitud  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fecha_resolucion DATETIME NULL,
    CONSTRAINT fk_permisos_estudiante FOREIGN KEY (id_estudiante) REFERENCES estudiantes(id_estudiante)
        ON UPDATE CASCADE
        ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE INDEX idx_permisos_estudiante_fecha ON permisos(id_estudiante, fecha, tipo_evento);
CREATE INDEX idx_permisos_estado ON permisos(estado);

-- Vista para ver todos los estudiantes registrados.
CREATE OR REPLACE VIEW v_registros_estudiantes AS
    SELECT
        e.id_estudiante,
        e.nombre,
        e.apellido,
        CONCAT(e.nombre, ' ', e.apellido) AS nombre_completo,
        e.codigo_seccion,
        e.correo_encargado,
        e.telefono_encargado,
        COALESCE(s.nombre, e.codigo_seccion) AS seccion,
        e.activo,
        e.fecha_registro
    FROM estudiantes e
    LEFT JOIN secciones s ON s.codigo_seccion = e.codigo_seccion
    ORDER BY e.codigo_seccion, e.apellido, e.nombre;

-- Vista completa para reportes de quien entro y quien salio.
CREATE OR REPLACE VIEW v_reporte_movimientos AS
    SELECT
        a.id_asistencia,
        a.id_estudiante,
        CONCAT(e.nombre, ' ', e.apellido) AS nombre_completo,
        e.codigo_seccion,
        e.correo_encargado,
        e.telefono_encargado,
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

CREATE OR REPLACE VIEW v_ultimos_movimientos AS
    SELECT
        a.id_asistencia,
        a.id_estudiante,
        CONCAT(e.nombre, ' ', e.apellido) AS nombre_completo,
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
    ORDER BY a.fecha DESC, a.hora DESC, a.id_asistencia DESC;

-- Vista para el panel de permisos (entrada tardia / salida antes de horario).
CREATE OR REPLACE VIEW v_permisos AS
    SELECT
        p.id_permiso,
        p.id_estudiante,
        CONCAT(e.nombre, ' ', e.apellido) AS nombre_completo,
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

INSERT IGNORE INTO usuarios (usuario, password, nombre_completo, rol) VALUES
('admin', 'admin123', 'Administrador del sistema', 'ADMIN'),
('profesor', 'profesor123', 'Profesor / Coordinador', 'PROFESOR');

INSERT IGNORE INTO secciones (codigo_seccion, nombre) VALUES
('DS1A', 'Desarrollo de Software 1A'),
('DS2A', 'Desarrollo de Software 2A'),
('DS3A', 'Desarrollo de Software 3A');

INSERT IGNORE INTO estudiantes (id_estudiante, nombre, apellido, codigo_seccion) VALUES
('6052414', 'Ana Maria',   'Garcia Lopez',     'DS1A'),
('6052415', 'Carlos',      'Martinez Ruiz',    'DS1A'),
('6052416', 'Sofia',       'Hernandez Paz',    'DS1A'),
('6053414', 'Diego',       'Lopez Morales',    'DS2A'),
('6053415', 'Valentina',   'Rodriguez Cruz',   'DS2A'),
('6053416', 'Andres',      'Perez Fuentes',    'DS2A'),
('6054414', 'Isabella',    'Ramirez Vega',     'DS3A'),
('6054415', 'Sebastian',   'Torres Castillo',  'DS3A'),
('6054416', 'Lucia',       'Flores Mendoza',   'DS3A');
