from __future__ import annotations

import base64
import csv
import io
import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from nicegui import app, ui

from db_connection import DatabaseManager
from repository import AsistenciaRepository
from config_notificaciones import cargar_config_correo, cargar_config_whatsapp, cargar_config_db, guardar_config, leer_config_bruta
from correo_notificador import enviar_alerta_correo
from whatsapp_notificador import enviar_whatsapp, normalizar_telefono
from reportes import generar_excel, generar_pdf

logger = logging.getLogger("island.web")

NOMBRE_SISTEMA = "Island"
SECCIONES = ("DS1A", "DS2A", "DS3A")
TODAS = "TODAS"
BASE_DIR = Path(__file__).resolve().parent

COLORES = {
    "fondo": "#0F1923",
    "panel": "#162533",
    "tarjeta": "#1E3448",
    "acento": "#00A8E8",
    "acento_hover": "#0086BA",
    "exito": "#00C897",
    "advertencia": "#FF6B6B",
    "texto_primario": "#E8F1F5",
    "texto_secundario": "#7B98AE",
    "borde": "#263D52",
    "resalte": "#FFD166",
}

# ------------------------------------------------------------------
# Conexión compartida a la base de datos
# ------------------------------------------------------------------
db = DatabaseManager()
repo = AsistenciaRepository(db)
db_lock = threading.Lock()


def with_lock(fn, *args, **kwargs):
    with db_lock:
        return fn(*args, **kwargs)


# ------------------------------------------------------------------
# Sesión / autenticación
# ------------------------------------------------------------------

def usuario_actual() -> dict | None:
    return app.storage.user.get("auth")


def requerir_login() -> dict | None:
    auth = usuario_actual()
    if not auth:
        ui.navigate.to("/login")
        return None
    return auth


def es_admin() -> bool:
    auth = usuario_actual()
    return bool(auth and auth.get("rol") == "ADMIN")


# ------------------------------------------------------------------
# Estilos globales
# ------------------------------------------------------------------

def aplicar_tema():
    ui.colors(primary=COLORES["acento"], secondary=COLORES["tarjeta"], accent=COLORES["resalte"])
    ui.add_head_html(f"""
    <style>
        body {{ background-color: {COLORES['fondo']} !important; }}
        .q-page, .nicegui-content {{ background-color: {COLORES['fondo']}; }}
        .island-card {{
            background-color: {COLORES['panel']};
            border: 1px solid {COLORES['borde']};
            border-radius: 12px;
        }}
        .island-titulo {{ color: {COLORES['acento']}; font-weight: 700; }}
        .island-sub {{ color: {COLORES['texto_secundario']}; }}
        .island-texto {{ color: {COLORES['texto_primario']}; }}
    </style>
    """)


# ------------------------------------------------------------------
# Página de login
# ------------------------------------------------------------------
@ui.page("/login")
def pagina_login():
    aplicar_tema()
    if usuario_actual():
        ui.navigate.to("/")
        return

    with ui.column().classes("w-full h-screen items-center justify-center"):
        with ui.card().classes("island-card p-8 w-96"):
            ui.label("ACCESO AL SISTEMA").classes("island-titulo text-lg")
            ui.label("Ingresa tus credenciales para continuar.").classes("island-sub text-sm mb-4")

            if not with_lock(db.esta_conectado):
                with ui.row().classes("items-center gap-2 mb-3 p-2 rounded").style(
                    f"background-color:#3a1f1f; border:1px solid {COLORES['advertencia']}"
                ):
                    ui.icon("warning").style(f"color:{COLORES['advertencia']}")
                    ui.label(
                        "No hay conexión con la base de datos MySQL. Revisa "
                        "correo_island.env (host, usuario, contraseña, nombre de "
                        "la base) y que el servidor MySQL esté encendido."
                    ).classes("text-xs").style(f"color:{COLORES['advertencia']}")

            campo_usuario = ui.input("Usuario").classes("w-full").props("dark outlined")
            campo_password = ui.input("Contraseña", password=True, password_toggle_button=True).classes("w-full").props("dark outlined")
            lbl_estado = ui.label("").style(f"color: {COLORES['advertencia']}")

            def intentar_login():
                usuario = campo_usuario.value.strip() if campo_usuario.value else ""
                password = campo_password.value or ""
                if not usuario or not password:
                    lbl_estado.text = "Ingresa usuario y contraseña."
                    return
                if not with_lock(db.esta_conectado):
                    lbl_estado.text = (
                        "No se pudo conectar a la base de datos. Verifica la "
                        "configuración de MySQL en correo_island.env."
                    )
                    return
                cuenta = with_lock(repo.verificar_credenciales, usuario, password)
                if cuenta is None:
                    existe_usuario = with_lock(
                        db.obtener_uno,
                        "SELECT 1 AS x FROM usuarios WHERE usuario = ?",
                        (usuario,),
                    )
                    if existe_usuario is None:
                        lbl_estado.text = (
                            f"El usuario '{usuario}' no existe en la tabla usuarios "
                            "(¿se importó schema_mysql.sql?)."
                        )
                    else:
                        lbl_estado.text = "Usuario o contraseña incorrectos."
                    return
                app.storage.user["auth"] = {
                    "usuario": cuenta["usuario"],
                    "nombre": cuenta.get("nombre_completo") or cuenta["usuario"],
                    "rol": cuenta["rol"],
                }
                ui.navigate.to("/")

            campo_password.on("keydown.enter", lambda: intentar_login())
            ui.button("INGRESAR", on_click=intentar_login).classes("w-full mt-2").props("color=primary")


# ------------------------------------------------------------------
# Utilidades de negocio (envío de alertas)
# ------------------------------------------------------------------

def _notificar_alerta_en_hilo(estudiante: dict, registro: dict):
    """Envía correo y WhatsApp en un hilo aparte para no bloquear la interfaz."""

    def tarea():
        correo_destino = str(estudiante.get("correo_encargado", "")).strip()
        telefono_destino = str(estudiante.get("telefono_encargado", "")).strip()

        if correo_destino:
            config_correo = cargar_config_correo()
            exito, detalle = enviar_alerta_correo(estudiante, registro, config_correo)
            nivel = "positive" if exito else "warning"
            ui.notify(f"Correo: {detalle}", type=nivel, position="top-right")

        if telefono_destino:
            config_wa = cargar_config_whatsapp()
            if config_wa.get("activo") and config_wa.get("apikey"):
                nombre = f"{estudiante.get('nombre', '')} {estudiante.get('apellido', '')}".strip()
                icono = "🟢" if registro.get("tipo_evento") == "INGRESO" else "🔴"
                mensaje = (
                    f"{icono} {NOMBRE_SISTEMA} - Alerta de asistencia\n"
                    f"Estudiante: {nombre}\n"
                    f"Sección: {estudiante.get('codigo_seccion', '')}\n"
                    f"Movimiento: {registro.get('tipo_evento', '')} a las {registro.get('hora', '')}\n"
                    f"Turno: {registro.get('turno', '')}\n"
                    f"Alerta: {registro.get('estado_alerta', '')}\n"
                    f"Detalle: {registro.get('detalle_alerta', '')}"
                )
                exito, detalle = enviar_whatsapp(telefono_destino, mensaje, config_wa["apikey"])
                nivel = "positive" if exito else "warning"
                ui.notify(f"WhatsApp: {detalle}", type=nivel, position="top-right")
            elif not config_wa.get("apikey"):
                ui.notify(
                    "El estudiante tiene teléfono, pero falta configurar la apikey de CallMeBot.",
                    type="warning", position="top-right",
                )

    threading.Thread(target=tarea, daemon=True).start()


# ------------------------------------------------------------------
# Tab: Marcar asistencia
# ------------------------------------------------------------------

def construir_tab_asistencia():
    slot_camara = ui.column().classes("w-full")
    campo_id = ui.input("Código / NIE (opcional, por si falla la cámara)").props("dark outlined").classes("w-full")

    ultimo_procesado = {"codigo": None, "ts": 0.0}

    def limpiar():
        campo_id.value = ""

    def procesar():
        codigo = (campo_id.value or "").strip()
        if not codigo:
            lbl_resultado.style(f"color: {COLORES['resalte']}")
            lbl_resultado.text = "Ingresa un código válido."
            return
        if not codigo.isdigit():
            lbl_resultado.style(f"color: {COLORES['advertencia']}")
            lbl_resultado.text = "El código debe contener solo números."
            limpiar()
            return

        ahora = time.monotonic()
        if codigo == ultimo_procesado["codigo"] and (ahora - ultimo_procesado["ts"]) < 4.0:
            return
        ultimo_procesado["codigo"] = codigo
        ultimo_procesado["ts"] = ahora

        auth = usuario_actual() or {}
        estudiante = with_lock(repo.buscar_estudiante, codigo)
        if estudiante is None:
            lbl_resultado.style(f"color: {COLORES['advertencia']}")
            lbl_resultado.text = f"⚠ NIE NO REGISTRADO\nCódigo leído: {codigo}\nNo existe un estudiante activo con este identificador."
            ui.notify(f"Código no registrado: {codigo}", type="negative", position="top-right", timeout=5000)
            ui.run_javascript("window.islandBeep && window.islandBeep(false)")
            limpiar()
            return

        registro = with_lock(repo.registrar_movimiento, codigo, auth.get("usuario", ""))
        if registro is None:
            lbl_resultado.style(f"color: {COLORES['advertencia']}")
            lbl_resultado.text = "No se pudo guardar el movimiento."
            ui.run_javascript("window.islandBeep && window.islandBeep(false)")
            limpiar()
            return

        tipo = registro["tipo_evento"]
        alerta = registro.get("estado_alerta") or "NORMAL"
        if alerta != "NORMAL":
            color = COLORES["resalte"]
        elif tipo == "INGRESO":
            color = COLORES["exito"]
        else:
            color = COLORES["advertencia"]
        icono = "●" if tipo == "INGRESO" else "■"
        nombre = f"{estudiante['nombre']} {estudiante['apellido']}"
        correo_encargado = str(estudiante.get("correo_encargado", "")).strip()

        lbl_resultado.style(f"color: {color}")
        lbl_resultado.text = (
            f"{icono} {tipo}\n"
            f"{nombre}\n"
            f"Sección: {estudiante['codigo_seccion']}  •  {registro['hora']}\n"
            f"Turno: {registro.get('turno', '')}  •  {alerta}\n"
            f"Permiso: {registro.get('permiso_evidencia') or 'NO APLICA'}\n"
            f"Estado actual: {registro.get('estado_actual', '')}\n"
            f"Encargado: {correo_encargado or 'sin correo'}"
        )
        ui.run_javascript(f"window.islandBeep && window.islandBeep({'false' if alerta != 'NORMAL' else 'true'})")

        if alerta != "NORMAL":
            ui.notify(f"⚠ Alerta de asistencia: {alerta} — {nombre}", type="warning", position="top-right", timeout=6000)
            _notificar_alerta_en_hilo(estudiante, registro)
            actualizar_permisos_pendientes()
        else:
            ui.notify(f"{tipo} registrado: {nombre}", type="positive", position="top-right", timeout=3000)

        limpiar()
        actualizar_tabla_movimientos()
        actualizar_estadisticas_rapidas()

    campo_id.on("keydown.enter", procesar)

    with slot_camara:
        with ui.card().classes("island-card p-6 w-full"):
            ui.label("LECTOR QR — SIEMPRE ACTIVO").classes("island-titulo text-lg")
            ui.label("Apunta el carnet a la cámara: el registro se hace solo, no necesitas tocar nada.").classes("island-sub text-sm mb-3")
            _construir_lector_qr(campo_id, procesar)

    with ui.row().classes("w-full gap-4 flex-wrap mt-4"):
        with ui.card().classes("island-card p-4 flex-1").style("min-width: 320px"):
            ui.label("ESTADO DE HOY").classes("island-titulo text-md mb-2")
            with ui.row().classes("gap-6"):
                stat_ingresos = ui.column()
                stat_salidas = ui.column()
                stat_presentes = ui.column()

            def render_stats():
                resumen = with_lock(repo.obtener_resumen_hoy)
                stat_ingresos.clear()
                with stat_ingresos:
                    ui.label(str(resumen["ingresos"])).classes("text-3xl").style(f"color:{COLORES['exito']}")
                    ui.label("Ingresos").classes("island-sub text-xs")
                stat_salidas.clear()
                with stat_salidas:
                    ui.label(str(resumen["salidas"])).classes("text-3xl").style(f"color:{COLORES['advertencia']}")
                    ui.label("Salidas").classes("island-sub text-xs")
                stat_presentes.clear()
                with stat_presentes:
                    ui.label(str(resumen["presentes"])).classes("text-3xl").style(f"color:{COLORES['acento']}")
                    ui.label("Presentes").classes("island-sub text-xs")

            render_stats()
            global actualizar_estadisticas_rapidas
            actualizar_estadisticas_rapidas = render_stats

        with ui.card().classes("island-card p-6 flex-1").style("min-width: 340px"):
            ui.label("ÚLTIMO RESULTADO").classes("island-titulo text-lg")
            ui.label("(esto se llena solo cada vez que se lee un carnet)").classes("island-sub text-xs mb-2")
            lbl_resultado = ui.label("Esperando el primer código...").classes("island-texto whitespace-pre-line")

    ui.label("ÚLTIMOS MOVIMIENTOS").classes("island-titulo text-md mt-4")
    columnas_mov = [
        {"name": "hora", "label": "Hora", "field": "hora", "align": "left"},
        {"name": "nombre_completo", "label": "Estudiante", "field": "nombre_completo", "align": "left"},
        {"name": "codigo_seccion", "label": "Sección", "field": "codigo_seccion", "align": "left"},
        {"name": "tipo_evento", "label": "Movimiento", "field": "tipo_evento", "align": "left"},
        {"name": "estado_alerta", "label": "Alerta", "field": "estado_alerta", "align": "left"},
    ]
    tabla_movimientos = ui.table(columns=columnas_mov, rows=[], row_key="id_asistencia").classes("w-full island-card")

    def render_tabla_movimientos():
        tabla_movimientos.rows = with_lock(repo.obtener_ultimos_movimientos, 50)
        tabla_movimientos.update()

    render_tabla_movimientos()
    global actualizar_tabla_movimientos
    actualizar_tabla_movimientos = render_tabla_movimientos
    ui.timer(10.0, render_tabla_movimientos)

    ui.label("PERMISOS PENDIENTES").classes("island-titulo text-md mt-6")
    ui.label("Aprueba o rechaza directamente desde aquí, sin cambiar de pestaña.").classes("island-sub text-sm mb-2")
    construir_panel_permisos_pendientes(compacto=True)


def _construir_lector_qr(campo_id, procesar_callback):
    contenedor_id = "qr-reader"
    ui.add_head_html(
        '<script src="https://cdn.jsdelivr.net/npm/html5-qrcode@2.3.8/html5-qrcode.min.js"></script>'
    )

    with ui.column().classes("items-center w-full"):
        ui.html(
            f'<div id="{contenedor_id}" style="width:100%;max-width:420px;height:340px;'
            f'border:2px dashed {COLORES["borde"]};border-radius:12px;overflow:hidden;'
            f'background:#0b141c;display:flex;align-items:center;justify-content:center;">'
            f'<span style="color:{COLORES["texto_secundario"]};font-size:12px;'
            f'text-align:center;padding:16px">Iniciando cámara automáticamente...</span></div>'
        )
        boton_estado = ui.label("Iniciando cámara...").classes("island-sub text-xs mt-2 text-center w-full")

    ui.run_javascript(
        f"""
        window._islandQr = window._islandQr || null;
        window._islandUltimoCodigo = null;
        window._islandUltimoTiempo = 0;

        window.islandBeep = function(exito) {{
            try {{
                const ContextAudio = window.AudioContext || window.webkitAudioContext;
                const ctx = new ContextAudio();
                const osc = ctx.createOscillator();
                const gain = ctx.createGain();
                osc.frequency.value = exito ? 880 : 220;
                osc.type = "sine";
                gain.gain.setValueAtTime(0.001, ctx.currentTime);
                gain.gain.exponentialRampToValueAtTime(0.25, ctx.currentTime + 0.01);
                gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + (exito ? 0.18 : 0.35));
                osc.connect(gain);
                gain.connect(ctx.destination);
                osc.start();
                osc.stop(ctx.currentTime + (exito ? 0.2 : 0.4));
            }} catch (err) {{ }}
        }};

        window._islandOnScan = function(decodedText) {{
            const ahora = Date.now();
            if (decodedText === window._islandUltimoCodigo && (ahora - window._islandUltimoTiempo) < 4000) {{
                return;
            }}
            window._islandUltimoCodigo = decodedText;
            window._islandUltimoTiempo = ahora;
            emitEvent("qr_scanned", decodedText);
            if (window._islandQr) {{
                try {{ window._islandQr.pause(true); }} catch (e) {{}}
                setTimeout(() => {{
                    try {{ if (window._islandQr) window._islandQr.resume(); }} catch (e) {{}}
                }}, 1500);
            }}
        }};

        window._islandIniciarCon = function(config) {{
            window._islandQr = new Html5Qrcode("{contenedor_id}");
            return window._islandQr.start(
                config,
                {{ fps: 10, qrbox: {{ width: 240, height: 240 }} }},
                window._islandOnScan,
                (errorMessage) => {{}}
            );
        }};

        window.islandAutoIniciar = async function() {{
            if (window._islandQr) return;
            if (!window.isSecureContext) {{
                emitEvent("qr_error", "Tu navegador bloquea la cámara porque esta página no usa HTTPS (ni es 'localhost'). Abre la app como https:// o desde http://localhost:8080 en esta misma computadora.");
                return;
            }}
            if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {{
                emitEvent("qr_error", "Este navegador no permite acceder a la cámara.");
                return;
            }}
            emitEvent("qr_status", "Pidiendo permiso de cámara...");
            try {{
                await window._islandIniciarCon({{ facingMode: "environment" }});
                emitEvent("qr_status", "Cámara activa. Escaneando de forma continua...");
                return;
            }} catch (err) {{
                window._islandQr = null;
            }}
            try {{
                const camaras = await Html5Qrcode.getCameras();
                if (!camaras || camaras.length === 0) {{
                    emitEvent("qr_error", "No se detectó ninguna cámara en este dispositivo.");
                    return;
                }}
                await window._islandIniciarCon(camaras[0].id);
                emitEvent("qr_status", "Cámara activa (" + (camaras[0].label || "cámara detectada") + "). Escaneando...");
            }} catch (err) {{
                window._islandQr = null;
                emitEvent("qr_error", "No se pudo acceder a la cámara (¿diste permiso?): " + String(err));
            }}
        }};

        window.islandReiniciarQr = function() {{
            const arrancar = () => window.islandAutoIniciar();
            if (window._islandQr) {{
                window._islandQr.stop().then(() => {{
                    window._islandQr.clear();
                    window._islandQr = null;
                    arrancar();
                }}).catch(() => {{ window._islandQr = null; arrancar(); }});
            }} else {{
                arrancar();
            }}
        }};

        window.islandVigilarCamara = function() {{
            if (!window._islandQr) {{
                window.islandAutoIniciar();
                return;
            }}
            try {{
                const estado = window._islandQr.getState();
                if (estado === 1) {{
                    window._islandQr = null;
                    window.islandAutoIniciar();
                }}
            }} catch (err) {{
                window._islandQr = null;
                window.islandAutoIniciar();
            }}
        }};
        """
    )

    def _primer_arg(evento) -> str:
        valor = evento.args
        if isinstance(valor, list):
            valor = valor[0] if valor else ""
        return "" if valor is None else str(valor)

    def on_scanned(evento):
        codigo = _primer_arg(evento).strip()
        if not codigo:
            return
        campo_id.value = codigo
        procesar_callback()

    def on_error(evento):
        boton_estado.style(f"color:{COLORES['advertencia']}")
        boton_estado.text = _primer_arg(evento)

    def on_status(evento):
        boton_estado.style(f"color:{COLORES['texto_primario']}")
        boton_estado.text = _primer_arg(evento)

    ui.on("qr_scanned", on_scanned)
    ui.on("qr_error", on_error)
    ui.on("qr_status", on_status)

    ui.timer(0.8, lambda: ui.run_javascript("window.islandAutoIniciar()"), once=True)
    ui.timer(5.0, lambda: ui.run_javascript("window.islandVigilarCamara()"))

    with ui.row().classes("gap-2 mt-2"):
        ui.button("Reiniciar cámara", on_click=lambda: ui.run_javascript("window.islandReiniciarQr()")).props("outline color=primary dense")

    ui.label(
        "La cámara queda escaneando todo el tiempo: solo acerca el carnet, "
        "espera el sonido de confirmación y listo. Si no arranca sola, usa "
        "'Reiniciar cámara'. Recuerda: solo funciona con https:// o desde "
        "http://localhost en esta computadora."
    ).classes("island-sub text-xs mt-2 text-center")


def actualizar_tabla_movimientos():
    pass


def actualizar_estadisticas_rapidas():
    pass


_permisos_listeners: list = []


def actualizar_permisos_pendientes():
    for fn in list(_permisos_listeners):
        try:
            fn()
        except Exception:
            logger.exception("Error refrescando panel de permisos.")


def construir_panel_permisos_pendientes(compacto: bool = False):
    columnas = [
        {"name": "fecha", "label": "Fecha", "field": "fecha", "align": "left"},
        {"name": "nombre_completo", "label": "Estudiante", "field": "nombre_completo", "align": "left"},
        {"name": "codigo_seccion", "label": "Sección", "field": "codigo_seccion", "align": "left"},
        {"name": "tipo_evento", "label": "Tipo", "field": "tipo_evento", "align": "left"},
        {"name": "motivo", "label": "Motivo", "field": "motivo", "align": "left"},
        {"name": "estado", "label": "Estado", "field": "estado", "align": "left"},
    ]
    tabla = ui.table(
        columns=columnas, rows=[], row_key="id_permiso", selection="single",
        pagination=5 if compacto else None,
    ).classes("w-full island-card")

    def cargar():
        tabla.rows = with_lock(repo.obtener_permisos_pendientes)
        tabla.update()

    _permisos_listeners.append(cargar)

    def resolver(estado: str):
        if not tabla.selected:
            ui.notify("Selecciona un permiso pendiente.", type="warning")
            return
        permiso = tabla.selected[0]
        auth = usuario_actual() or {}
        with_lock(repo.resolver_permiso, permiso["id_permiso"], estado, auth.get("usuario", ""))
        actualizar_permisos_pendientes()
        ui.notify(f"Permiso {estado.lower()}.", type="positive")

    with ui.row().classes("gap-2 mt-2"):
        ui.button("Aprobar", on_click=lambda: resolver("APROBADO")).props("color=positive")
        ui.button("Rechazar", on_click=lambda: resolver("RECHAZADO")).props("color=negative")

    cargar()
    return tabla


# ------------------------------------------------------------------
# Tab: Estudiantes
# ------------------------------------------------------------------

def construir_tab_estudiantes():
    with ui.row().classes("w-full gap-4 items-end flex-wrap"):
        filtro_seccion = ui.select([TODAS, *SECCIONES], value=TODAS, label="Sección").props("dark outlined").classes("w-40")
        filtro_texto = ui.input("Buscar por nombre o código").props("dark outlined").classes("flex-1")
        boton_nuevo = ui.button("+ NUEVO ESTUDIANTE").props("color=primary")

    columnas = [
        {"name": "id_estudiante", "label": "Código", "field": "id_estudiante", "align": "left"},
        {"name": "nombre", "label": "Nombre", "field": "nombre", "align": "left"},
        {"name": "apellido", "label": "Apellido", "field": "apellido", "align": "left"},
        {"name": "codigo_seccion", "label": "Sección", "field": "codigo_seccion", "align": "left"},
        {"name": "correo_encargado", "label": "Correo encargado", "field": "correo_encargado", "align": "left"},
        {"name": "telefono_encargado", "label": "WhatsApp encargado", "field": "telefono_encargado", "align": "left"},
        {"name": "activo", "label": "Activo", "field": "activo", "align": "center"},
    ]
    tabla = ui.table(columns=columnas, rows=[], row_key="id_estudiante", selection="single").classes("w-full island-card mt-3")

    with ui.row().classes("gap-2 mt-2"):
        boton_editar = ui.button("Editar seleccionado").props("outline color=primary")
        boton_desactivar = ui.button("Desactivar seleccionado").props("outline color=negative")

    def cargar():
        seccion = None if filtro_seccion.value == TODAS else filtro_seccion.value
        filas = with_lock(repo.obtener_estudiantes, seccion, True)
        texto = (filtro_texto.value or "").strip().lower()
        if texto:
            filas = [
                f for f in filas
                if texto in f["id_estudiante"].lower()
                or texto in f["nombre"].lower()
                or texto in f["apellido"].lower()
            ]
        for f in filas:
            f["activo"] = "Sí" if f.get("activo") else "No"
        tabla.rows = filas
        tabla.update()

    filtro_seccion.on("update:model-value", lambda: cargar())
    filtro_texto.on("keydown.enter", lambda: cargar())
    filtro_texto.on("blur", lambda: cargar())

    def abrir_formulario(datos: dict | None = None):
        modo_edicion = datos is not None
        with ui.dialog() as dialogo, ui.card().classes("island-card p-6").style("min-width: 420px"):
            ui.label("EDITAR ESTUDIANTE" if modo_edicion else "NUEVO ESTUDIANTE").classes("island-titulo text-lg")

            campo_codigo = ui.input("Código / NIE", value=(datos or {}).get("id_estudiante", "")).props("dark outlined").classes("w-full")
            campo_nombre = ui.input("Nombre", value=(datos or {}).get("nombre", "")).props("dark outlined").classes("w-full")
            campo_apellido = ui.input("Apellido", value=(datos or {}).get("apellido", "")).props("dark outlined").classes("w-full")
            campo_seccion = ui.select(list(SECCIONES), value=(datos or {}).get("codigo_seccion", SECCIONES[0]), label="Sección").props("dark outlined").classes("w-full")
            campo_correo = ui.input("Correo del encargado", value=(datos or {}).get("correo_encargado", "")).props("dark outlined").classes("w-full")
            campo_telefono = ui.input(
                "WhatsApp del encargado (ej. +50370000000)",
                value=(datos or {}).get("telefono_encargado", ""),
            ).props("dark outlined").classes("w-full")
            lbl_error = ui.label("").style(f"color:{COLORES['advertencia']}")

            def guardar():
                codigo = (campo_codigo.value or "").strip()
                nombre = (campo_nombre.value or "").strip()
                apellido = (campo_apellido.value or "").strip()
                seccion = campo_seccion.value
                correo = (campo_correo.value or "").strip()
                telefono = normalizar_telefono(campo_telefono.value or "") if (campo_telefono.value or "").strip() else ""

                if not codigo or not nombre or not apellido:
                    lbl_error.text = "Código, nombre y apellido son obligatorios."
                    return

                if modo_edicion:
                    exito = with_lock(
                        repo.actualizar_estudiante,
                        datos["id_estudiante"], codigo, nombre, apellido, seccion, correo, telefono, True,
                    )
                else:
                    exito = with_lock(repo.registrar_estudiante, codigo, nombre, apellido, seccion, correo, telefono)

                if not exito:
                    lbl_error.text = "No se pudo guardar (¿código duplicado?)."
                    return
                ui.notify("Estudiante guardado.", type="positive")
                dialogo.close()
                cargar()

            with ui.row().classes("gap-2 mt-3 justify-end"):
                ui.button("Cancelar", on_click=dialogo.close).props("flat")
                ui.button("Guardar", on_click=guardar).props("color=primary")

        dialogo.open()

    boton_nuevo.on_click(lambda: abrir_formulario(None))

    def obtener_seleccion():
        return tabla.selected[0] if tabla.selected else None

    def editar():
        sel = obtener_seleccion()
        if not sel:
            ui.notify("Selecciona un estudiante en la tabla.", type="warning")
            return
        completo = with_lock(repo.buscar_estudiante_por_id, sel["id_estudiante"])
        abrir_formulario(completo)

    def desactivar():
        sel = obtener_seleccion()
        if not sel:
            ui.notify("Selecciona un estudiante en la tabla.", type="warning")
            return

        with ui.dialog() as confirmar, ui.card().classes("island-card p-4"):
            ui.label(f"¿Desactivar a {sel['nombre']} {sel['apellido']}?").classes("island-texto")
            with ui.row().classes("gap-2 mt-3 justify-end"):
                ui.button("Cancelar", on_click=confirmar.close).props("flat")

                def confirmar_accion():
                    with_lock(repo.eliminar_estudiante, sel["id_estudiante"])
                    confirmar.close()
                    cargar()
                    ui.notify("Estudiante desactivado.", type="positive")

                ui.button("Desactivar", on_click=confirmar_accion).props("color=negative")
        confirmar.open()

    boton_editar.on_click(editar)
    boton_desactivar.on_click(desactivar)

    cargar()


# ------------------------------------------------------------------
# Tab: Estadísticas
# ------------------------------------------------------------------

def construir_tab_estadisticas():
    contenedor_cards = ui.row().classes("w-full gap-4 flex-wrap")
    ui.label("ASISTENCIA POR SECCIÓN (HOY)").classes("island-titulo text-md mt-4")
    columnas = [
        {"name": "codigo_seccion", "label": "Sección", "field": "codigo_seccion", "align": "left"},
        {"name": "total_estudiantes", "label": "Total estudiantes", "field": "total_estudiantes", "align": "center"},
        {"name": "activos", "label": "Activos", "field": "activos", "align": "center"},
        {"name": "ingresos", "label": "Ingresos hoy", "field": "ingresos", "align": "center"},
        {"name": "salidas", "label": "Salidas hoy", "field": "salidas", "align": "center"},
    ]
    tabla = ui.table(columns=columnas, rows=[], row_key="codigo_seccion").classes("w-full island-card")

    def render():
        stats = with_lock(repo.obtener_estadisticas_generales)
        contenedor_cards.clear()
        tarjetas = [
            ("Total estudiantes", stats["total_estudiantes"], COLORES["acento"]),
            ("Activos", stats["activos"], COLORES["exito"]),
            ("Inactivos", stats["inactivos"], COLORES["texto_secundario"]),
            ("Ingresos hoy", stats["ingresos_hoy"], COLORES["exito"]),
            ("Salidas hoy", stats["salidas_hoy"], COLORES["advertencia"]),
            ("Presentes hoy", stats["presentes_hoy"], COLORES["resalte"]),
        ]
        with contenedor_cards:
            for titulo, valor, color in tarjetas:
                with ui.card().classes("island-card p-4").style("min-width: 150px"):
                    ui.label(str(valor)).classes("text-3xl").style(f"color:{color}")
                    ui.label(titulo).classes("island-sub text-xs")

        secciones = {s["codigo_seccion"]: dict(s) for s in stats["secciones"]}
        for a in stats["asistencia_por_seccion"]:
            if a["codigo_seccion"] in secciones:
                secciones[a["codigo_seccion"]]["ingresos"] = a["ingresos"]
                secciones[a["codigo_seccion"]]["salidas"] = a["salidas"]
        filas = list(secciones.values())
        for f in filas:
            f.setdefault("ingresos", 0)
            f.setdefault("salidas", 0)
        tabla.rows = filas
        tabla.update()

    render()
    ui.timer(15.0, render)


# ------------------------------------------------------------------
# Tab: Registros (historial completo)
# ------------------------------------------------------------------

def construir_tab_registros():
    ui.label("BUSCADOR DE REPORTES").classes("island-titulo text-lg")
    with ui.row().classes("w-full gap-4 items-end flex-wrap"):
        filtro_texto = ui.input("Buscar (código, nombre o sección)").props("dark outlined").classes("flex-1")
        filtro_desde = ui.input("Desde").props("dark outlined type=date").classes("w-40")
        filtro_hasta = ui.input("Hasta").props("dark outlined type=date").classes("w-40")
        boton_buscar = ui.button("Buscar").props("color=primary")
        boton_limpiar = ui.button("Limpiar filtros").props("outline color=primary")

    with ui.row().classes("w-full gap-2 flex-wrap mt-2"):
        boton_csv = ui.button("Exportar CSV").props("outline color=primary")
        boton_excel = ui.button("Exportar Excel").props("outline color=primary")
        boton_pdf = ui.button("Vista previa PDF").props("outline color=primary")
        boton_imprimir = ui.button("Imprimir").props("outline color=primary")

    columnas = [
        {"name": "fecha", "label": "Fecha", "field": "fecha", "align": "left"},
        {"name": "hora", "label": "Hora", "field": "hora", "align": "left"},
        {"name": "id_estudiante", "label": "Código", "field": "id_estudiante", "align": "left"},
        {"name": "nombre_completo", "label": "Estudiante", "field": "nombre_completo", "align": "left"},
        {"name": "codigo_seccion", "label": "Sección", "field": "codigo_seccion", "align": "left"},
        {"name": "tipo_evento", "label": "Movimiento", "field": "tipo_evento", "align": "left"},
        {"name": "turno", "label": "Turno", "field": "turno", "align": "left"},
        {"name": "estado_alerta", "label": "Alerta", "field": "estado_alerta", "align": "left"},
        {"name": "detalle_alerta", "label": "Detalle", "field": "detalle_alerta", "align": "left"},
    ]
    tabla = ui.table(columns=columnas, rows=[], row_key="id_asistencia", pagination=25).classes("w-full island-card mt-3")
    lbl_total = ui.label("").classes("island-sub text-xs mt-1")
    contenedor_preview_pdf = ui.column().classes("w-full mt-4")

    filas_actuales: list[dict] = []

    def _fecha_en_rango(fila: dict) -> bool:
        desde = (filtro_desde.value or "").strip()
        hasta = (filtro_hasta.value or "").strip()
        if not desde and not hasta:
            return True
        try:
            fecha_fila = datetime.strptime(fila["fecha"], "%d/%m/%Y").date()
        except (ValueError, TypeError, KeyError):
            return True
        if desde:
            try:
                if fecha_fila < datetime.strptime(desde, "%Y-%m-%d").date():
                    return False
            except ValueError:
                pass
        if hasta:
            try:
                if fecha_fila > datetime.strptime(hasta, "%Y-%m-%d").date():
                    return False
            except ValueError:
                pass
        return True

    def cargar():
        nonlocal filas_actuales
        filas = with_lock(repo.obtener_historial_completo, 500)
        texto = (filtro_texto.value or "").strip().lower()
        if texto:
            filas = [
                f for f in filas
                if texto in str(f.get("id_estudiante", "")).lower()
                or texto in str(f.get("nombre_completo", "")).lower()
                or texto in str(f.get("codigo_seccion", "")).lower()
            ]
        filas = [f for f in filas if _fecha_en_rango(f)]
        filas_actuales = filas
        tabla.rows = filas
        tabla.update()
        lbl_total.text = f"{len(filas)} registro(s) encontrados."

    def limpiar_filtros():
        filtro_texto.value = ""
        filtro_desde.value = ""
        filtro_hasta.value = ""
        cargar()

    def exportar_csv():
        if not filas_actuales:
            ui.notify("No hay registros para exportar.", type="warning")
            return
        buffer = io.StringIO()
        encabezados = ["fecha", "hora", "id_estudiante", "nombre_completo", "codigo_seccion", "tipo_evento", "turno", "estado_alerta", "detalle_alerta"]
        escritor = csv.DictWriter(buffer, fieldnames=encabezados, extrasaction="ignore")
        escritor.writeheader()
        for fila in filas_actuales:
            escritor.writerow(fila)
        nombre_archivo = f"registros_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ui.download(buffer.getvalue().encode("utf-8-sig"), nombre_archivo)

    def exportar_excel():
        if not filas_actuales:
            ui.notify("No hay registros para exportar.", type="warning")
            return
        datos = generar_excel(filas_actuales, "Reporte de registros")
        nombre_archivo = f"reporte_asistencia_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
        ui.download(datos, nombre_archivo)
        ui.notify("Excel generado y descargado.", type="positive")

    def _mostrar_preview_pdf(datos: bytes):
        b64 = base64.b64encode(datos).decode("ascii")
        contenedor_preview_pdf.clear()
        with contenedor_preview_pdf:
            ui.label("Vista previa del PDF").classes("island-titulo text-md mb-1")
            ui.html(
                f'<iframe src="data:application/pdf;base64,{b64}" '
                f'style="width:100%;height:600px;border:1px solid {COLORES["borde"]};'
                f'border-radius:8px;background:white"></iframe>'
            )

    def vista_previa_pdf():
        if not filas_actuales:
            ui.notify("No hay registros para generar el PDF.", type="warning")
            return
        datos = generar_pdf(filas_actuales, "Reporte de registros")
        _mostrar_preview_pdf(datos)
        nombre_archivo = f"reporte_asistencia_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        ui.download(datos, nombre_archivo)
        ui.notify("PDF generado. Puedes verlo abajo, descargarlo o imprimirlo.", type="positive")

    def imprimir():
        if not filas_actuales:
            ui.notify("No hay registros para imprimir.", type="warning")
            return
        datos = generar_pdf(filas_actuales, "Reporte de registros")
        _mostrar_preview_pdf(datos)
        b64 = base64.b64encode(datos).decode("ascii")
        ui.run_javascript(
            f"""
            const ventana = window.open("", "_blank");
            if (ventana) {{
                ventana.document.write(
                    '<iframe src="data:application/pdf;base64,{b64}" style="width:100%;height:100%;border:0" '
                    + 'onload="this.contentWindow.focus(); this.contentWindow.print();"></iframe>'
                );
            }}
            """
        )

    boton_buscar.on_click(cargar)
    boton_limpiar.on_click(limpiar_filtros)
    filtro_texto.on("keydown.enter", cargar)
    filtro_desde.on("change", cargar)
    filtro_hasta.on("change", cargar)
    boton_csv.on_click(exportar_csv)
    boton_excel.on_click(exportar_excel)
    boton_pdf.on_click(vista_previa_pdf)
    boton_imprimir.on_click(imprimir)
    cargar()


# ------------------------------------------------------------------
# Tab: Permisos
# ------------------------------------------------------------------

def construir_tab_permisos():
    ui.label("PERMISOS PENDIENTES").classes("island-titulo text-lg")
    construir_panel_permisos_pendientes(compacto=False)

    ui.separator().classes("my-4")
    ui.label("SOLICITAR PERMISO PARA UNA SECCIÓN").classes("island-titulo text-md")
    with ui.row().classes("gap-3 items-end flex-wrap"):
        sel_seccion = ui.select(list(SECCIONES), value=SECCIONES[0], label="Sección").props("dark outlined").classes("w-40")
        sel_tipo = ui.select(["INGRESO", "SALIDA"], value="INGRESO", label="Tipo").props("dark outlined").classes("w-40")
        campo_motivo = ui.input("Motivo").props("dark outlined").classes("flex-1")

        def otorgar():
            auth = usuario_actual() or {}
            creados = with_lock(
                repo.otorgar_permiso_seccion,
                sel_seccion.value, datetime.now().date().isoformat(), sel_tipo.value,
                campo_motivo.value or "", auth.get("usuario", ""),
            )
            ui.notify(f"Se crearon {creados} permisos para {sel_seccion.value}.", type="positive")
            actualizar_permisos_pendientes()

        ui.button("Otorgar a la sección", on_click=otorgar).props("color=primary")

    ui.separator().classes("my-4")
    ui.label("HISTORIAL DE PERMISOS").classes("island-titulo text-md")
    columnas_hist = [
        {"name": "fecha", "label": "Fecha", "field": "fecha", "align": "left"},
        {"name": "nombre_completo", "label": "Estudiante", "field": "nombre_completo", "align": "left"},
        {"name": "codigo_seccion", "label": "Sección", "field": "codigo_seccion", "align": "left"},
        {"name": "tipo_evento", "label": "Tipo", "field": "tipo_evento", "align": "left"},
        {"name": "motivo", "label": "Motivo", "field": "motivo", "align": "left"},
        {"name": "estado", "label": "Estado", "field": "estado", "align": "left"},
        {"name": "autorizado_por", "label": "Autorizado por", "field": "autorizado_por", "align": "left"},
    ]
    tabla_hist = ui.table(columns=columnas_hist, rows=[], row_key="id_permiso", pagination=15).classes("w-full island-card")
    tabla_hist.rows = with_lock(repo.obtener_historial_permisos, 200)


# ------------------------------------------------------------------
# Tab: Usuarios (solo ADMIN)
# ------------------------------------------------------------------

def construir_tab_usuarios():
    ui.label("USUARIOS DEL SISTEMA").classes("island-titulo text-lg")
    columnas = [
        {"name": "usuario", "label": "Usuario", "field": "usuario", "align": "left"},
        {"name": "nombre_completo", "label": "Nombre", "field": "nombre_completo", "align": "left"},
        {"name": "rol", "label": "Rol", "field": "rol", "align": "left"},
        {"name": "activo", "label": "Activo", "field": "activo", "align": "center"},
    ]
    tabla = ui.table(columns=columnas, rows=[], row_key="id_usuario", selection="single").classes("w-full island-card")

    def cargar():
        filas = with_lock(repo.obtener_usuarios)
        for f in filas:
            f["activo"] = "Sí" if f.get("activo") else "No"
        tabla.rows = filas
        tabla.update()

    with ui.row().classes("gap-3 items-end flex-wrap mt-3"):
        campo_usuario = ui.input("Usuario").props("dark outlined")
        campo_password = ui.input("Contraseña", password=True).props("dark outlined")
        campo_nombre = ui.input("Nombre completo").props("dark outlined")
        campo_rol = ui.select(["PROFESOR", "ADMIN"], value="PROFESOR", label="Rol").props("dark outlined")

        def crear():
            if not (campo_usuario.value or "").strip() or not (campo_password.value or "").strip():
                ui.notify("Usuario y contraseña son obligatorios.", type="warning")
                return
            exito = with_lock(
                repo.crear_usuario, campo_usuario.value, campo_password.value,
                campo_nombre.value or "", campo_rol.value,
            )
            if exito:
                ui.notify("Usuario creado.", type="positive")
                campo_usuario.value = ""
                campo_password.value = ""
                campo_nombre.value = ""
                cargar()
            else:
                ui.notify("No se pudo crear (¿usuario duplicado?).", type="negative")

        ui.button("Crear usuario", on_click=crear).props("color=primary")

    def desactivar():
        if not tabla.selected:
            ui.notify("Selecciona un usuario.", type="warning")
            return
        with_lock(repo.eliminar_usuario, tabla.selected[0]["id_usuario"])
        cargar()
        ui.notify("Usuario desactivado.", type="positive")

    ui.button("Desactivar seleccionado", on_click=desactivar).props("outline color=negative").classes("mt-2")
    cargar()


# ------------------------------------------------------------------
# Tab: Configuración (solo ADMIN)
# ------------------------------------------------------------------

def construir_tab_configuracion():
    config_correo = cargar_config_correo()
    config_wa = cargar_config_whatsapp()
    config_db = cargar_config_db()

    with ui.row().classes("w-full gap-4 flex-wrap items-start"):
        with ui.card().classes("island-card p-6").style("min-width: 340px"):
            ui.label("CORREO SMTP (alertas por correo)").classes("island-titulo text-md")
            c_host = ui.input("Host SMTP", value=config_correo["host"]).props("dark outlined").classes("w-full")
            c_port = ui.input("Puerto", value=str(config_correo["port"])).props("dark outlined").classes("w-full")
            c_user = ui.input("Usuario / correo", value=config_correo["username"]).props("dark outlined").classes("w-full")
            c_pass = ui.input("Contraseña de aplicación", password=True, value=config_correo["password"]).props("dark outlined").classes("w-full")
            c_from = ui.input("Correo remitente", value=config_correo["from"]).props("dark outlined").classes("w-full")
            c_tls = ui.checkbox("Usar STARTTLS (puerto 587)", value=config_correo["tls"])

            def guardar_correo():
                try:
                    puerto = int(c_port.value)
                except ValueError:
                    puerto = 587
                guardar_config(correo={
                    "host": c_host.value.strip(), "port": puerto, "username": c_user.value.strip(),
                    "password": c_pass.value, "from": c_from.value.strip() or c_user.value.strip(),
                    "tls": c_tls.value,
                })
                ui.notify("Configuración de correo guardada.", type="positive")

            ui.button("Guardar correo", on_click=guardar_correo).props("color=primary").classes("mt-2")

        with ui.card().classes("island-card p-6").style("min-width: 340px"):
            ui.label("WHATSAPP (CallMeBot)").classes("island-titulo text-md")
            ui.label(
                "Cada encargado debe agregar al bot de CallMeBot y enviarle "
                "'I allow callmebot to send me messages' desde su WhatsApp para "
                "obtener la apikey que se configura aquí."
            ).classes("island-sub text-xs mb-2")
            w_activo = ui.checkbox("Enviar avisos por WhatsApp", value=config_wa["activo"])
            w_apikey = ui.input("Apikey de CallMeBot", value=config_wa["apikey"]).props("dark outlined").classes("w-full")

            def guardar_wa():
                guardar_config(whatsapp={"activo": w_activo.value, "apikey": w_apikey.value.strip()})
                ui.notify("Configuración de WhatsApp guardada.", type="positive")

            ui.button("Guardar WhatsApp", on_click=guardar_wa).props("color=primary").classes("mt-2")
            ui.link("Cómo obtener la apikey de CallMeBot", "https://www.callmebot.com/blog/free-api-whatsapp-messages/", new_tab=True).classes("island-sub text-xs")

        with ui.card().classes("island-card p-6").style("min-width: 340px"):
            ui.label("BASE DE DATOS (MySQL / phpMyAdmin)").classes("island-titulo text-md")
            ui.label(
                "Estos datos se configuran con variables de entorno o en "
                "correo_island.env y se leen al iniciar la app."
            ).classes("island-sub text-xs mb-2")
            for etiqueta, valor in [
                ("Host", config_db["host"]), ("Puerto", config_db["port"]),
                ("Usuario", config_db["user"]), ("Base de datos", config_db["database"]),
            ]:
                with ui.row().classes("justify-between w-full"):
                    ui.label(etiqueta).classes("island-sub")
                    ui.label(valor).classes("island-texto")
            estado = "Conectada" if with_lock(db.esta_conectado) else "Desconectada"
            color = COLORES["exito"] if estado == "Conectada" else COLORES["advertencia"]
            ui.label(f"● BD {estado}").style(f"color:{color}").classes("mt-2")


# ------------------------------------------------------------------
# Página principal
# ------------------------------------------------------------------
@ui.page("/")
def pagina_principal():
    aplicar_tema()
    auth = requerir_login()
    if not auth:
        return

    with ui.header().classes("items-center justify-between").style(f"background-color:{COLORES['panel']}"):
        with ui.row().classes("items-center gap-3"):
            ui.label(NOMBRE_SISTEMA).classes("text-xl font-bold").style(f"color:{COLORES['acento']}")
            ui.label("Sistema de control de asistencia").classes("island-sub text-sm")
        with ui.row().classes("items-center gap-3"):
            reloj = ui.label("").classes("island-texto")
            ui.timer(1.0, lambda: reloj.set_text(datetime.now().strftime("%d/%m/%Y  %H:%M:%S")))
            ui.label(f"{auth['nombre']} ({auth['rol']})").classes("island-texto text-sm")

            def salir():
                app.storage.user.clear()
                ui.navigate.to("/login")

            ui.button("Salir", on_click=salir).props("flat color=white")

    admin = es_admin()

    with ui.tabs().classes("w-full") as tabs:
        t_asistencia = ui.tab("Marcar asistencia")
        t_permisos = ui.tab("Permisos")
        t_registros = ui.tab("Registros y reportes")
        if admin:
            t_estudiantes = ui.tab("Estudiantes")
            t_estadisticas = ui.tab("Estadísticas")
            t_usuarios = ui.tab("Usuarios")
            t_config = ui.tab("Configuración")

    with ui.tab_panels(tabs, value=t_asistencia).classes("w-full"):
        with ui.tab_panel(t_asistencia):
            construir_tab_asistencia()
        with ui.tab_panel(t_permisos):
            construir_tab_permisos()
        with ui.tab_panel(t_registros):
            construir_tab_registros()
        if admin:
            with ui.tab_panel(t_estudiantes):
                construir_tab_estudiantes()
            with ui.tab_panel(t_estadisticas):
                construir_tab_estadisticas()
            with ui.tab_panel(t_usuarios):
                construir_tab_usuarios()
            with ui.tab_panel(t_config):
                construir_tab_configuracion()


if __name__ in {"__main__", "__mp_main__"}:
    puerto = int(os.getenv("ASISTENCIA_WEB_PORT", "8080"))
    secreto = os.getenv("ASISTENCIA_WEB_SECRET", "").strip()
    if not secreto:
        secreto = leer_config_bruta().get("ASISTENCIA_WEB_SECRET", "").strip()
    if not secreto:
        secreto = "cambia-esta-clave-por-una-propia-y-secreta"
        logger.warning(
            "ASISTENCIA_WEB_SECRET no está configurada: se está usando una "
            "clave de repuesto. Define ASISTENCIA_WEB_SECRET en "
            "correo_island.env con una clave única antes de publicar el "
            "link."
        )

    ui.run(
        title=NOMBRE_SISTEMA,
        host="0.0.0.0",
        port=puerto,
        storage_secret=secreto,
        dark=True,
        reload=False,
    )