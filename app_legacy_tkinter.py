"""
app.py
======
Interfaz principal del Sistema de Control de Asistencia.
Construida con Tkinter + ttk y conectada a SQLite.
"""

import csv
import logging
import math
import os
import smtplib
import ssl
import threading
import tkinter as tk
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from tkinter import filedialog, ttk

from db_connection import DatabaseManager
from repository import AsistenciaRepository

logger = logging.getLogger("island.correo")


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
    "entrada_fondo": "#0D1F2D",
    "resalte": "#FFD166",
}

FUENTES = {
    "titulo": ("Segoe UI", 18, "bold"),
    "subtitulo": ("Segoe UI", 11),
    "boton": ("Segoe UI", 12, "bold"),
    "entrada": ("Consolas", 22, "bold"),
    "tabla": ("Segoe UI", 10),
    "tabla_cab": ("Segoe UI", 10, "bold"),
    "stat": ("Segoe UI", 24, "bold"),
    "stat_label": ("Segoe UI", 9),
    "hora": ("Segoe UI", 13, "bold"),
}

SECCIONES = ("DS1A", "DS2A", "DS3A")
TODAS = "TODAS"
NOMBRE_SISTEMA = "Island"
BASE_DIR = Path(__file__).resolve().parent
REPORTES_DIR = BASE_DIR / "reportes"
CORREO_CONFIG_PATH = BASE_DIR / "correo_island.env"


class ControlAsistenciaApp(tk.Tk):
    """Ventana principal de la aplicación."""

    def __init__(self):
        super().__init__()

        self._db = DatabaseManager()
        self._repo = AsistenciaRepository(self._db)
        self._usuario_actual = None
        self._rol_actual = None
        self._modo_estudiante = "crear"
        self._codigo_estudiante_original = None
        self._qr_scan_thread = None
        self._qr_scan_active = False
        self._qr_scan_lock = threading.Lock()
        self._qr_scan_last_code = None
        self._qr_scan_last_ts = 0.0
        self._qr_registration_busy = False
        self._qr_preview_image = None
        self._qr_preview_error = False
        self._config_correo = self._cargar_config_correo()
        REPORTES_DIR.mkdir(parents=True, exist_ok=True)

        self.title("Login - Sistema de Asistencia")
        self.geometry("1250x780")
        self.minsize(900, 620)
        self.resizable(True, True)
        self.configure(bg=COLORES["fondo"])
        self._maximizar_ventana(self)

        self._configurar_estilo()
        self._construir_login()
        self.deiconify()
        self.protocol("WM_DELETE_WINDOW", self._al_cerrar)

    # ------------------------------------------------------------------
    # Configuración
    # ------------------------------------------------------------------
    def _centrar_ventana(self, ancho: int, alto: int):
        x = (self.winfo_screenwidth() - ancho) // 2
        y = (self.winfo_screenheight() - alto) // 2
        self.geometry(f"{ancho}x{alto}+{x}+{y}")

    def _maximizar_ventana(self, ventana):
        try:
            ventana.state("zoomed")
        except tk.TclError:
            ventana.attributes("-fullscreen", True)

    def _configurar_estilo(self):
        estilo = ttk.Style(self)
        estilo.theme_use("clam")

        estilo.configure(
            "Custom.Treeview",
            background=COLORES["tarjeta"],
            foreground=COLORES["texto_primario"],
            fieldbackground=COLORES["tarjeta"],
            rowheight=32,
            font=FUENTES["tabla"],
            borderwidth=0,
        )
        estilo.configure(
            "Custom.Treeview.Heading",
            background=COLORES["panel"],
            foreground=COLORES["acento"],
            font=FUENTES["tabla_cab"],
            relief="flat",
            borderwidth=0,
        )
        estilo.map(
            "Custom.Treeview",
            background=[("selected", COLORES["acento"])],
            foreground=[("selected", "#FFFFFF")],
        )
        estilo.map(
            "Custom.Treeview.Heading",
            background=[("active", COLORES["tarjeta"])],
        )

        estilo.configure(
            "Custom.Vertical.TScrollbar",
            background=COLORES["panel"],
            troughcolor=COLORES["fondo"],
            arrowcolor=COLORES["acento"],
            borderwidth=0,
        )

        estilo.configure(
            "TNotebook",
            background=COLORES["fondo"],
            borderwidth=0,
        )
        estilo.configure(
            "TNotebook.Tab",
            background=COLORES["panel"],
            foreground=COLORES["texto_primario"],
            padding=(16, 8),
        )
        estilo.map(
            "TNotebook.Tab",
            background=[("selected", COLORES["tarjeta"])],
            foreground=[("selected", COLORES["acento"])],
        )

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _construir_login(self):
        cont = tk.Frame(self, bg=COLORES["fondo"])
        cont.pack(fill="both", expand=True, padx=28, pady=26)

        tarjeta = tk.Frame(cont, bg=COLORES["panel"], padx=28, pady=26, width=430, height=340)
        tarjeta.place(relx=0.5, rely=0.5, anchor="center")
        tarjeta.pack_propagate(False)

        tk.Label(
            tarjeta,
            text="ACCESO AL SISTEMA",
            font=("Segoe UI", 13, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w")

        tk.Label(
            tarjeta,
            text="Ingresa tus credenciales para continuar.",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w", pady=(4, 18))

        self._var_login_usuario = tk.StringVar()
        self._var_login_password = tk.StringVar()

        self._entry_login_usuario = self._crear_campo_login(
            tarjeta,
            "Usuario",
            self._var_login_usuario,
        )
        self._entry_login_password = self._crear_campo_login(
            tarjeta,
            "Contraseña",
            self._var_login_password,
            mostrar="*",
        )
        self._entry_login_password.bind("<Return>", self._validar_login)
        self._entry_login_password.bind("<KP_Enter>", self._validar_login)

        self._lbl_login_estado = tk.Label(
            tarjeta,
            text="",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["advertencia"],
            wraplength=330,
            justify="left",
        )
        self._lbl_login_estado.pack(anchor="w", pady=(4, 10))

        tk.Button(
            tarjeta,
            text="ENTRAR",
            font=FUENTES["boton"],
            bg=COLORES["acento"],
            fg="#FFFFFF",
            activebackground=COLORES["acento_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=10,
            cursor="hand2",
            command=self._validar_login,
        ).pack(fill="x", pady=(4, 0))

        self._entry_login_usuario.focus_set()

    def _crear_campo_login(self, padre, etiqueta, variable, mostrar=None):
        tk.Label(
            padre,
            text=etiqueta,
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w")

        entrada = tk.Entry(
            padre,
            textvariable=variable,
            show=mostrar,
            font=("Segoe UI", 11),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=9,
        )
        entrada.pack(fill="x", pady=(4, 12))
        return entrada

    def _validar_login(self, evento=None):
        usuario = self._var_login_usuario.get().strip()
        password = self._var_login_password.get().strip()

        cuenta = self._repo.verificar_credenciales(usuario, password) if usuario and password else None

        if cuenta is not None:
            self._usuario_actual = cuenta["usuario"]
            self._rol_actual = cuenta["rol"]
            self._nombre_usuario_actual = cuenta.get("nombre_completo") or cuenta["usuario"]
            self._iniciar_sistema()
            return

        self._lbl_login_estado.config(
            text="Usuario o contraseña incorrectos.",
            fg=COLORES["advertencia"],
        )
        self._var_login_password.set("")
        self._entry_login_password.focus_set()

    def _iniciar_sistema(self):
        for widget in self.winfo_children():
            widget.destroy()

        self._busqueda_estudiantes = tk.StringVar()
        self._busqueda_estadisticas = tk.StringVar()
        self._filtro_reporte_seccion = tk.StringVar(value=TODAS)
        self._busqueda_registros = tk.StringVar()

        self.title("Sistema de Control de Asistencia")
        self.resizable(True, True)
        self.geometry("1250x780")
        self.minsize(1120, 700)
        self._maximizar_ventana(self)

        self._construir_ui()
        self._actualizar_tabla_movimientos()
        self._actualizar_lista_estudiantes()
        self._actualizar_estadisticas_basicas()
        self._actualizar_tabla_estadisticas()
        self._actualizar_tabla_registros()
        self._actualizar_permisos_rapidos()
        self._tick_reloj()
        self.after(500, self._iniciar_escaneo_qr_embebido)

    def _construir_ui(self):
        raiz = tk.Frame(self, bg=COLORES["fondo"])
        raiz.pack(fill="both", expand=True, padx=16, pady=12)

        self._cabecera(raiz)

        self._notebook = ttk.Notebook(raiz)
        self._notebook.pack(fill="both", expand=True, pady=(10, 0))

        self._tab_asistencia = tk.Frame(self._notebook, bg=COLORES["fondo"])
        self._tab_estudiantes = tk.Frame(self._notebook, bg=COLORES["fondo"])
        self._tab_estadisticas = tk.Frame(self._notebook, bg=COLORES["fondo"])
        self._tab_permisos = tk.Frame(self._notebook, bg=COLORES["fondo"])

        self._notebook.add(self._tab_asistencia, text="Asistencia")
        self._notebook.add(self._tab_estudiantes, text="Estudiantes")
        self._notebook.add(self._tab_estadisticas, text="Reportes e historial")
        self._notebook.add(self._tab_permisos, text="Permisos")

        self._contenido_asistencia = self._crear_pagina_scrollable(self._tab_asistencia)
        self._contenido_estudiantes = self._crear_pagina_scrollable(self._tab_estudiantes)
        self._contenido_estadisticas = self._crear_pagina_scrollable(self._tab_estadisticas)
        self._contenido_permisos = self._crear_pagina_scrollable(self._tab_permisos)

        self._construir_tab_asistencia()
        self._construir_tab_estudiantes()
        self._construir_tab_estadisticas()
        self._tab_registros = tk.Frame(self._contenido_estadisticas, bg=COLORES["fondo"])
        self._tab_registros.pack(fill="both", expand=True, pady=(12, 0))
        self._construir_tab_registros()
        self._construir_tab_permisos()
        self._aplicar_restricciones_rol()

    def _crear_pagina_scrollable(self, padre):
        contenedor = tk.Frame(padre, bg=COLORES["fondo"])
        contenedor.pack(fill="both", expand=True)

        canvas = tk.Canvas(
            contenedor,
            bg=COLORES["fondo"],
            highlightthickness=0,
            bd=0,
        )
        scroll_y = ttk.Scrollbar(
            contenedor,
            orient="vertical",
            command=canvas.yview,
            style="Custom.Vertical.TScrollbar",
        )
        canvas.configure(yscrollcommand=scroll_y.set)
        canvas.pack(side="left", fill="both", expand=True)
        scroll_y.pack(side="right", fill="y")

        interior = tk.Frame(canvas, bg=COLORES["fondo"])
        ventana = canvas.create_window((0, 0), window=interior, anchor="nw")

        def _ajustar_region(_evento=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _ajustar_ancho(evento):
            canvas.itemconfigure(ventana, width=evento.width)

        interior.bind("<Configure>", _ajustar_region)
        canvas.bind("<Configure>", _ajustar_ancho)

        def _rueda(evento):
            if evento.delta:
                canvas.yview_scroll(int(-1 * (evento.delta / 120)), "units")
            elif getattr(evento, "num", None) == 4:
                canvas.yview_scroll(-3, "units")
            elif getattr(evento, "num", None) == 5:
                canvas.yview_scroll(3, "units")

        for widget in (canvas, interior):
            widget.bind("<Enter>", lambda _evento, c=canvas: c.bind_all("<MouseWheel>", _rueda))
            widget.bind("<Leave>", lambda _evento, c=canvas: c.unbind_all("<MouseWheel>"))

        return interior

    def _cabecera(self, padre):
        frame = tk.Frame(padre, bg=COLORES["fondo"])
        frame.pack(fill="x")

        izquierda = tk.Frame(frame, bg=COLORES["fondo"])
        izquierda.pack(side="left")

        tk.Label(
            izquierda,
            text="Sistema de Asistencia",
            font=FUENTES["titulo"],
            bg=COLORES["fondo"],
            fg=COLORES["texto_primario"],
        ).pack(anchor="w")

        tk.Label(
            izquierda,
            text="Control de ingreso y salida con estudiantes, secciones y estadísticas",
            font=FUENTES["subtitulo"],
            bg=COLORES["fondo"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w")

        rol_texto = "Administrador" if self._rol_actual == "ADMIN" else "Profesor / Coordinador"
        tk.Label(
            izquierda,
            text=f"Sesión: {self._nombre_usuario_actual}  •  Rol: {rol_texto}",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["fondo"],
            fg=COLORES["resalte"],
        ).pack(anchor="w", pady=(2, 0))

        derecha = tk.Frame(frame, bg=COLORES["fondo"])
        derecha.pack(side="right", anchor="ne")

        self._lbl_fecha = tk.Label(
            derecha,
            text="",
            font=("Segoe UI", 9),
            bg=COLORES["fondo"],
            fg=COLORES["texto_secundario"],
        )
        self._lbl_fecha.pack(anchor="e")

        self._lbl_hora = tk.Label(
            derecha,
            text="",
            font=FUENTES["hora"],
            bg=COLORES["fondo"],
            fg=COLORES["acento"],
        )
        self._lbl_hora.pack(anchor="e")

        tk.Button(
            derecha,
            text="Configurar correo",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["acento"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["acento"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=self._abrir_configuracion_correo,
        ).pack(anchor="e", pady=(4, 0))

        tk.Frame(padre, bg=COLORES["borde"], height=1).pack(fill="x", pady=(8, 0))

    def _construir_tab_asistencia(self):
        cuerpo = tk.Frame(self._contenido_asistencia, bg=COLORES["fondo"])
        cuerpo.pack(fill="both", expand=True)
        cuerpo.columnconfigure(0, weight=0)
        cuerpo.columnconfigure(1, weight=1)
        cuerpo.rowconfigure(0, weight=1)

        self._panel_registro(cuerpo)
        self._panel_tabla(cuerpo)

    def _panel_registro(self, padre):
        frame = tk.Frame(
            padre,
            bg=COLORES["panel"],
            bd=0,
            relief="flat",
            width=390,
        )
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        frame.pack_propagate(False)

        inner = tk.Frame(frame, bg=COLORES["panel"])
        inner.pack(fill="both", expand=True, padx=20, pady=18)

        tk.Label(
            inner,
            text="REGISTRAR MOVIMIENTO",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w", pady=(0, 14))

        tk.Label(
            inner,
            text="Código numérico del estudiante",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w")

        entrada_frame = tk.Frame(inner, bg=COLORES["acento"], bd=1)
        entrada_frame.pack(fill="x", pady=(4, 0))

        self._var_id = tk.StringVar()
        vcmd_codigo = (self.register(self._validar_numerico), "%P")
        self._entry_id = tk.Entry(
            entrada_frame,
            textvariable=self._var_id,
            font=FUENTES["entrada"],
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=8,
            justify="center",
            validate="key",
            validatecommand=vcmd_codigo,
        )
        self._entry_id.pack(fill="x")
        self._entry_id.bind("<Return>", self._procesar_registro)
        self._entry_id.bind("<KP_Enter>", self._procesar_registro)
        self._entry_id.focus_set()

        tk.Label(
            inner,
            text="Presiona Enter para registrar",
            font=("Segoe UI", 8),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="e", pady=(3, 0))

        self._btn_registrar = tk.Button(
            inner,
            text="REGISTRAR",
            font=FUENTES["boton"],
            bg=COLORES["acento"],
            fg="#FFFFFF",
            activebackground=COLORES["acento_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=10,
            cursor="hand2",
            command=self._procesar_registro,
        )
        self._btn_registrar.pack(fill="x", pady=(14, 0))

        acciones = tk.Frame(inner, bg=COLORES["panel"])
        acciones.pack(fill="x", pady=(8, 0))

        tk.Button(
            acciones,
            text="ESCANEAR QR",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["acento"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["acento"],
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            command=self._iniciar_escaneo_qr_embebido,
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            acciones,
            text="LIMPIAR",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["texto_primario"],
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            command=self._limpiar_registro,
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        tk.Frame(inner, bg=COLORES["borde"], height=1).pack(fill="x", pady=18)

        tk.Label(
            inner,
            text="ESCANEO QR USB",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w", pady=(0, 8))

        self._var_indice_camara = tk.StringVar(value="1")
        fila_camara = tk.Frame(inner, bg=COLORES["panel"])
        fila_camara.pack(fill="x")

        tk.Label(
            fila_camara,
            text="Cámara (1 = PC)",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(side="left")

        self._entry_indice_camara = tk.Entry(
            fila_camara,
            textvariable=self._var_indice_camara,
            font=("Segoe UI", 10),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=8,
            width=6,
            justify="center",
        )
        self._entry_indice_camara.pack(side="left", padx=(8, 0))

        tk.Button(
            fila_camara,
            text="INICIAR",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["acento"],
            fg="#FFFFFF",
            activebackground=COLORES["acento_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=7,
            cursor="hand2",
            command=self._iniciar_escaneo_qr_embebido,
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            fila_camara,
            text="DETENER",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["texto_primario"],
            relief="flat",
            bd=0,
            padx=10,
            pady=7,
            cursor="hand2",
            command=self._detener_escaneo_qr_embebido,
        ).pack(side="left", padx=(8, 0))

        self._lbl_qr_estado = tk.Label(
            inner,
            text="El escaneo automático se iniciará al abrir la aplicación.",
            font=("Segoe UI", 8),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
            wraplength=270,
            justify="left",
        )
        self._lbl_qr_estado.pack(anchor="w", pady=(8, 0))

        self._qr_preview_frame = tk.Frame(
            inner,
            bg=COLORES["entrada_fondo"],
            highlightthickness=1,
            highlightbackground=COLORES["borde"],
            width=330,
            height=210,
        )
        self._qr_preview_frame.pack(fill="x", pady=(10, 0))
        self._qr_preview_frame.pack_propagate(False)

        self._lbl_qr_preview = tk.Label(
            self._qr_preview_frame,
            text="Vista de cámara\nesperando conexión",
            font=("Segoe UI", 9),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_secundario"],
            justify="center",
        )
        self._lbl_qr_preview.pack(fill="both", expand=True)

        tk.Frame(inner, bg=COLORES["borde"], height=1).pack(fill="x", pady=18)

        tk.Label(
            inner,
            text="HOY",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w", pady=(0, 10))

        stats_frame = tk.Frame(inner, bg=COLORES["panel"])
        stats_frame.pack(fill="x")

        self._stat_ingresos = self._crear_stat(stats_frame, "INGRESOS", "0", COLORES["exito"])
        self._stat_salidas = self._crear_stat(stats_frame, "SALIDAS", "0", COLORES["advertencia"])
        self._stat_presentes = self._crear_stat(stats_frame, "PRESENTES", "0", COLORES["resalte"])

        self._lbl_resumen_hoy = tk.Label(
            inner,
            text="Entradas: 0  |  Salidas: 0  |  Presentes: 0",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
            wraplength=280,
            justify="left",
        )
        self._lbl_resumen_hoy.pack(anchor="w", pady=(8, 0))

        tk.Frame(inner, bg=COLORES["borde"], height=1).pack(fill="x", pady=18)

        tk.Label(
            inner,
            text="ÚLTIMO REGISTRO",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w", pady=(0, 8))

        self._resultado_frame = tk.Frame(inner, bg=COLORES["tarjeta"], relief="flat", bd=0)
        self._resultado_frame.pack(fill="x")

        self._lbl_resultado = tk.Label(
            self._resultado_frame,
            text="Esperando primer registro...",
            font=("Segoe UI", 9),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            wraplength=260,
            justify="left",
            pady=12,
            padx=12,
        )
        self._lbl_resultado.pack(fill="x")

        self._lbl_conexion = tk.Label(
            inner,
            text="",
            font=("Segoe UI", 10),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        )
        self._lbl_conexion.pack(side="bottom", anchor="w", pady=(12, 0))
        self._actualizar_indicador_conexion()

    def _crear_stat(self, padre, etiqueta, valor_inicial, color):
        tarjeta = tk.Frame(padre, bg=COLORES["tarjeta"], relief="flat")
        tarjeta.pack(fill="x", pady=3)

        tk.Label(
            tarjeta,
            text=etiqueta,
            font=FUENTES["stat_label"],
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            pady=4,
            padx=10,
        ).pack(side="left")

        lbl = tk.Label(
            tarjeta,
            text=valor_inicial,
            font=("Segoe UI", 16, "bold"),
            bg=COLORES["tarjeta"],
            fg=color,
            padx=10,
        )
        lbl.pack(side="right")
        return lbl

    def _panel_tabla(self, padre):
        frame = tk.Frame(padre, bg=COLORES["panel"])
        frame.grid(row=0, column=1, sticky="nsew")

        inner = tk.Frame(frame, bg=COLORES["panel"])
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        cabecera = tk.Frame(inner, bg=COLORES["panel"])
        cabecera.pack(fill="x", pady=(0, 10))

        tk.Label(
            cabecera,
            text="MOVIMIENTOS DE HOY",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(side="left")

        tk.Button(
            cabecera,
            text="Actualizar",
            font=("Segoe UI", 8),
            bg=COLORES["tarjeta"],
            fg=COLORES["acento"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["acento"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=self._actualizar_tabla_movimientos,
        ).pack(side="right")

        columnas = ("id", "nombre", "seccion", "hora", "tipo", "estado", "permiso", "alerta")
        self._tabla = ttk.Treeview(
            inner,
            columns=columnas,
            show="headings",
            style="Custom.Treeview",
            selectmode="browse",
        )
        self._tabla.heading("id", text="#")
        self._tabla.heading("nombre", text="Nombre Completo")
        self._tabla.heading("seccion", text="Sección")
        self._tabla.heading("hora", text="Hora")
        self._tabla.heading("tipo", text="Tipo")
        self._tabla.heading("estado", text="Estado")
        self._tabla.heading("permiso", text="Permiso")
        self._tabla.heading("alerta", text="Alerta")

        self._tabla.column("id", width=50, anchor="center", stretch=False)
        self._tabla.column("nombre", width=220, anchor="w")
        self._tabla.column("seccion", width=90, anchor="center", stretch=False)
        self._tabla.column("hora", width=90, anchor="center", stretch=False)
        self._tabla.column("tipo", width=100, anchor="center", stretch=False)
        self._tabla.column("estado", width=90, anchor="center", stretch=False)
        self._tabla.column("permiso", width=120, anchor="center", stretch=False)
        self._tabla.column("alerta", width=170, anchor="center", stretch=False)

        self._tabla.tag_configure("INGRESO", background="#183328", foreground=COLORES["exito"])
        self._tabla.tag_configure("SALIDA", background="#2E1A1A", foreground=COLORES["advertencia"])
        self._tabla.tag_configure("ALERTA", background="#3A2E18", foreground=COLORES["resalte"])

        panel_rapido = tk.Frame(inner, bg=COLORES["tarjeta"], padx=12, pady=12)
        panel_rapido.pack(fill="x", pady=(0, 12))

        cab_rapido = tk.Frame(panel_rapido, bg=COLORES["tarjeta"])
        cab_rapido.pack(fill="x", pady=(0, 8))

        tk.Label(
            cab_rapido,
            text="PERMISOS PENDIENTES / APROBACIÓN RÁPIDA",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["resalte"],
        ).pack(side="left")

        tk.Button(
            cab_rapido,
            text="Actualizar",
            font=("Segoe UI", 8),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["acento"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=self._actualizar_permisos_rapidos,
        ).pack(side="right")

        cuerpo_rapido = tk.Frame(panel_rapido, bg=COLORES["tarjeta"])
        cuerpo_rapido.pack(fill="x")
        cuerpo_rapido.columnconfigure(0, weight=1)
        cuerpo_rapido.columnconfigure(1, weight=0)

        columnas_p = ("id", "codigo", "nombre", "seccion", "tipo", "hora", "detalle")
        self._tabla_permisos_rapidos = ttk.Treeview(
            cuerpo_rapido,
            columns=columnas_p,
            show="headings",
            style="Custom.Treeview",
            height=4,
            selectmode="browse",
        )
        encabezados_p = {
            "id": "ID",
            "codigo": "Código",
            "nombre": "Estudiante",
            "seccion": "Sección",
            "tipo": "Movimiento",
            "hora": "Hora",
            "detalle": "Motivo",
        }
        anchos_p = {"id": 50, "codigo": 95, "nombre": 170, "seccion": 75, "tipo": 100, "hora": 75, "detalle": 220}
        for col in columnas_p:
            self._tabla_permisos_rapidos.heading(col, text=encabezados_p[col])
            self._tabla_permisos_rapidos.column(
                col,
                width=anchos_p[col],
                anchor="center" if col not in {"nombre", "detalle"} else "w",
                stretch=col == "detalle",
            )
        self._tabla_permisos_rapidos.grid(row=0, column=0, sticky="nsew")
        self._tabla_permisos_rapidos.bind("<<TreeviewSelect>>", self._seleccionar_permiso_rapido)

        panel_accion = tk.Frame(cuerpo_rapido, bg=COLORES["tarjeta"])
        panel_accion.grid(row=0, column=1, sticky="ns", padx=(10, 0))

        self._var_hora_permiso_rapido = tk.StringVar(value=self._hora_actual_texto())
        tk.Label(
            panel_accion,
            text="Hora asignada",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w")
        selector_rapido, _ = self._crear_selector_hora(panel_accion, self._var_hora_permiso_rapido, ancho=12)
        selector_rapido.pack(fill="x", pady=(4, 8))

        tk.Label(
            panel_accion,
            text="Comentario opcional",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w")

        self._var_comentario_permiso_rapido = tk.StringVar()
        tk.Entry(
            panel_accion,
            textvariable=self._var_comentario_permiso_rapido,
            font=("Segoe UI", 10),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=7,
            width=34,
        ).pack(fill="x", pady=(4, 8))

        tk.Button(
            panel_accion,
            text="ACEPTAR PERMISO",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["exito"],
            fg="#FFFFFF",
            activebackground="#00A87D",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            cursor="hand2",
            command=lambda: self._resolver_permiso_rapido("APROBADO"),
        ).pack(fill="x", pady=(0, 6))

        tk.Button(
            panel_accion,
            text="RECHAZAR",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["advertencia"],
            fg="#FFFFFF",
            activebackground="#CC5555",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            cursor="hand2",
            command=lambda: self._resolver_permiso_rapido("RECHAZADO"),
        ).pack(fill="x")

        self._lbl_permiso_rapido = tk.Label(
            panel_accion,
            text="Selecciona una solicitud pendiente.",
            font=("Segoe UI", 8),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            wraplength=250,
            justify="left",
        )
        self._lbl_permiso_rapido.pack(anchor="w", pady=(8, 0))

        panel_tabla = tk.Frame(inner, bg=COLORES["panel"])
        panel_tabla.pack(fill="both", expand=True)

        scroll = ttk.Scrollbar(
            panel_tabla,
            orient="vertical",
            command=self._tabla.yview,
            style="Custom.Vertical.TScrollbar",
        )
        self._tabla.configure(yscrollcommand=scroll.set)

        self._tabla.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _construir_tab_estudiantes(self):
        cont = tk.Frame(self._contenido_estudiantes, bg=COLORES["fondo"])
        cont.pack(fill="both", expand=True)
        cont.columnconfigure(0, weight=0)
        cont.columnconfigure(1, weight=1)
        cont.rowconfigure(0, weight=1)

        self._panel_form_estudiantes(cont)
        self._panel_lista_estudiantes(cont)

    def _panel_form_estudiantes(self, padre):
        frame = tk.Frame(padre, bg=COLORES["panel"], width=360)
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        frame.pack_propagate(False)

        inner = tk.Frame(frame, bg=COLORES["panel"])
        inner.pack(fill="both", expand=True, padx=20, pady=18)

        tk.Label(
            inner,
            text="AGREGAR ESTUDIANTE",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w", pady=(0, 14))

        self._var_codigo_estudiante = tk.StringVar()
        self._var_nombre = tk.StringVar()
        self._var_apellido = tk.StringVar()
        self._var_correo_encargado = tk.StringVar()
        self._var_seccion = tk.StringVar(value=SECCIONES[0])
        vcmd_codigo = (self.register(self._validar_numerico), "%P")

        self._entradas_estudiante = [
            self._crear_campo_texto(inner, "Código numérico", self._var_codigo_estudiante, validatecommand=vcmd_codigo),
            self._crear_campo_texto(inner, "Nombre", self._var_nombre),
            self._crear_campo_texto(inner, "Apellido", self._var_apellido),
            self._crear_campo_texto(inner, "Correo del encargado", self._var_correo_encargado),
        ]

        tk.Label(
            inner,
            text="Sección / grado",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w", pady=(8, 0))
        self._combo_seccion = ttk.Combobox(
            inner,
            textvariable=self._var_seccion,
            values=SECCIONES,
            state="readonly",
            font=("Segoe UI", 10),
        )
        self._combo_seccion.pack(fill="x", pady=(4, 0))

        self._btn_agregar_estudiante = tk.Button(
            inner,
            text="AGREGAR ESTUDIANTE",
            font=FUENTES["boton"],
            bg=COLORES["acento"],
            fg="#FFFFFF",
            activebackground=COLORES["acento_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=10,
            cursor="hand2",
            command=self._procesar_nuevo_estudiante,
        )
        self._btn_agregar_estudiante.pack(fill="x", pady=(14, 0))

        botones_edicion = tk.Frame(inner, bg=COLORES["panel"])
        botones_edicion.pack(fill="x", pady=(8, 0))

        self._btn_cancelar_edicion = tk.Button(
            botones_edicion,
            text="CANCELAR EDICIÓN",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["texto_primario"],
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            command=self._cancelar_edicion_estudiante,
        )
        self._btn_cancelar_edicion.pack(side="left", fill="x", expand=True)
        self._btn_cancelar_edicion.config(state="disabled")

        self._btn_eliminar_estudiante = tk.Button(
            botones_edicion,
            text="ELIMINAR",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["advertencia"],
            fg="#FFFFFF",
            activebackground="#CC5555",
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            command=self._eliminar_estudiante_seleccionado,
        )
        self._btn_eliminar_estudiante.pack(side="left", fill="x", expand=True, padx=(8, 0))
        self._btn_eliminar_estudiante.config(state="disabled")

        self._lbl_estado_estudiantes = tk.Label(
            inner,
            text="Usa un código numérico, por ejemplo 6052414.",
            font=("Segoe UI", 8),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
            wraplength=300,
            justify="left",
        )
        self._lbl_estado_estudiantes.pack(anchor="w", pady=(10, 0))

    def _crear_campo_texto(self, padre, etiqueta, variable, validatecommand=None):
        tk.Label(
            padre,
            text=etiqueta,
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w", pady=(8, 0))

        entrada = tk.Entry(
            padre,
            textvariable=variable,
            font=("Segoe UI", 11),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=8,
        )
        if validatecommand:
            entrada.configure(validate="key", validatecommand=validatecommand)
        entrada.pack(fill="x", pady=(4, 0))
        return entrada

    def _panel_lista_estudiantes(self, padre):
        frame = tk.Frame(padre, bg=COLORES["panel"])
        frame.grid(row=0, column=1, sticky="nsew")

        inner = tk.Frame(frame, bg=COLORES["panel"])
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        cabecera = tk.Frame(inner, bg=COLORES["panel"])
        cabecera.pack(fill="x", pady=(0, 10))

        tk.Label(
            cabecera,
            text="ESTUDIANTES REGISTRADOS",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(side="left")

        busqueda_frame = tk.Frame(inner, bg=COLORES["panel"])
        busqueda_frame.pack(fill="x", pady=(0, 10))

        tk.Label(
            busqueda_frame,
            text="Buscar",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(side="left")

        entrada_busqueda = tk.Entry(
            busqueda_frame,
            textvariable=self._busqueda_estudiantes,
            font=("Segoe UI", 10),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=8,
        )
        entrada_busqueda.pack(side="left", fill="x", expand=True, padx=(8, 8))
        entrada_busqueda.bind("<KeyRelease>", lambda _evento: self._actualizar_lista_estudiantes())

        tk.Button(
            busqueda_frame,
            text="Limpiar",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["texto_primario"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=lambda: (self._busqueda_estudiantes.set(""), self._actualizar_lista_estudiantes()),
        ).pack(side="right")

        self._filtro_seccion = tk.StringVar(value=TODAS)
        filtro = ttk.Combobox(
            cabecera,
            textvariable=self._filtro_seccion,
            values=(TODAS, *SECCIONES),
            state="readonly",
            width=14,
        )
        filtro.pack(side="right")
        filtro.bind("<<ComboboxSelected>>", lambda _evento: self._actualizar_lista_estudiantes())

        tk.Button(
            cabecera,
            text="Actualizar",
            font=("Segoe UI", 8),
            bg=COLORES["tarjeta"],
            fg=COLORES["acento"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["acento"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=self._actualizar_lista_estudiantes,
        ).pack(side="right", padx=(0, 10))

        columnas = ("codigo", "nombre", "seccion", "ubicacion", "estado", "registro")
        self._tabla_estudiantes = ttk.Treeview(
            inner,
            columns=columnas,
            show="headings",
            style="Custom.Treeview",
            selectmode="browse",
        )
        encabezados = {
            "codigo": "#",
            "nombre": "Nombre completo",
            "seccion": "Sección",
            "ubicacion": "Ubicación",
            "estado": "Estado",
            "registro": "Registro",
        }
        anchos = {
            "codigo": 110,
            "nombre": 270,
            "seccion": 90,
            "ubicacion": 95,
            "estado": 80,
            "registro": 120,
        }
        for columna in columnas:
            self._tabla_estudiantes.heading(columna, text=encabezados[columna])
            self._tabla_estudiantes.column(columna, width=anchos[columna], anchor="center" if columna in {"codigo", "seccion", "ubicacion", "estado", "registro"} else "w", stretch=columna == "nombre")

        self._tabla_estudiantes.tag_configure("activo", background="#182940")
        self._tabla_estudiantes.tag_configure("inactivo", background="#3A2424")
        self._tabla_estudiantes.tag_configure("dentro", background="#183328", foreground=COLORES["exito"])
        self._tabla_estudiantes.tag_configure("fuera", background="#182940", foreground=COLORES["texto_primario"])
        self._tabla_estudiantes.bind("<<TreeviewSelect>>", self._cargar_estudiante_seleccionado)
        self._tabla_estudiantes.bind("<Double-1>", self._cargar_estudiante_seleccionado)

        scroll = ttk.Scrollbar(
            inner,
            orient="vertical",
            command=self._tabla_estudiantes.yview,
            style="Custom.Vertical.TScrollbar",
        )
        self._tabla_estudiantes.configure(yscrollcommand=scroll.set)

        self._tabla_estudiantes.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def _construir_tab_estadisticas(self):
        cont = tk.Frame(self._contenido_estadisticas, bg=COLORES["fondo"])
        cont.pack(fill="x", expand=False)
        cont.columnconfigure(0, weight=1)
        cont.rowconfigure(1, weight=1)

        encabezado = tk.Frame(cont, bg=COLORES["fondo"])
        encabezado.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        tk.Label(
            encabezado,
            text="PANEL DE REPORTES E HISTORIAL",
            font=("Segoe UI", 13, "bold"),
            bg=COLORES["fondo"],
            fg=COLORES["acento"],
        ).pack(anchor="w")

        tk.Label(
            encabezado,
            text="Resumen operativo, filtros por sección y historial unificado para consultar, exportar o imprimir.",
            font=("Segoe UI", 9),
            bg=COLORES["fondo"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w", pady=(2, 0))

        self._panel_stats = tk.Frame(cont, bg=COLORES["fondo"])
        self._panel_stats.grid(row=1, column=0, sticky="nsew")
        cont.rowconfigure(2, weight=1)
        cont.rowconfigure(3, weight=1)
        self._panel_stats.columnconfigure(0, weight=1)
        self._panel_stats.columnconfigure(1, weight=1)
        self._panel_stats.columnconfigure(2, weight=1)
        self._panel_stats.columnconfigure(3, weight=1)

        self._stat_total_estudiantes = self._crear_stat_card(self._panel_stats, 0, "Estudiantes", "0", "Registrados")
        self._stat_activos = self._crear_stat_card(self._panel_stats, 1, "Activos", "0", "Estudiantes habilitados")
        self._stat_mov_hoy = self._crear_stat_card(self._panel_stats, 2, "Movimientos", "0", "Hoy")
        self._stat_presentes_hoy = self._crear_stat_card(self._panel_stats, 3, "Presentes", "0", "Estado actual")

        segunda_fila = tk.Frame(cont, bg=COLORES["fondo"])
        segunda_fila.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        segunda_fila.columnconfigure(0, weight=1)
        segunda_fila.columnconfigure(1, weight=1)
        segunda_fila.rowconfigure(0, weight=1)

        self._panel_detalle_secciones(segunda_fila)
        self._panel_asistencia_por_seccion(segunda_fila)

        tercera_fila = tk.Frame(cont, bg=COLORES["fondo"])
        tercera_fila.grid(row=3, column=0, sticky="nsew", pady=(12, 0))
        tercera_fila.columnconfigure(0, weight=1)
        self._panel_reporte_movimientos(tercera_fila)

    def _crear_stat_card(self, padre, columna, titulo, valor_inicial, subtitulo):
        tarjeta = tk.Frame(padre, bg=COLORES["tarjeta"], padx=18, pady=14)
        tarjeta.grid(row=0, column=columna, sticky="nsew", padx=6)

        tk.Label(
            tarjeta,
            text=titulo.upper(),
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w")

        lbl = tk.Label(
            tarjeta,
            text=valor_inicial,
            font=("Segoe UI", 24, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["resalte"],
        )
        lbl.pack(anchor="w", pady=(4, 0))

        tk.Label(
            tarjeta,
            text=subtitulo,
            font=("Segoe UI", 9),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w", pady=(2, 0))

        return lbl

    def _panel_detalle_secciones(self, padre):
        frame = tk.Frame(padre, bg=COLORES["panel"])
        frame.grid(row=0, column=0, sticky="nsew", padx=(0, 6))

        inner = tk.Frame(frame, bg=COLORES["panel"])
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            inner,
            text="RESUMEN POR SECCIÓN",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w", pady=(0, 10))

        columnas = ("seccion", "estudiantes", "activos")
        self._tabla_secciones = ttk.Treeview(
            inner,
            columns=columnas,
            show="headings",
            style="Custom.Treeview",
            height=8,
        )
        self._tabla_secciones.heading("seccion", text="Sección")
        self._tabla_secciones.heading("estudiantes", text="Estudiantes")
        self._tabla_secciones.heading("activos", text="Activos")
        self._tabla_secciones.column("seccion", width=90, anchor="center", stretch=False)
        self._tabla_secciones.column("estudiantes", width=120, anchor="center", stretch=False)
        self._tabla_secciones.column("activos", width=100, anchor="center", stretch=False)

        self._tabla_secciones.pack(fill="both", expand=True)

    def _panel_asistencia_por_seccion(self, padre):
        frame = tk.Frame(padre, bg=COLORES["panel"])
        frame.grid(row=0, column=1, sticky="nsew", padx=(6, 0))

        inner = tk.Frame(frame, bg=COLORES["panel"])
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            inner,
            text="ASISTENCIA DE HOY POR SECCIÓN",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w", pady=(0, 10))

        columnas = ("seccion", "ingresos", "salidas")
        self._tabla_asistencia_seccion = ttk.Treeview(
            inner,
            columns=columnas,
            show="headings",
            style="Custom.Treeview",
            height=8,
        )
        self._tabla_asistencia_seccion.heading("seccion", text="Sección")
        self._tabla_asistencia_seccion.heading("ingresos", text="Ingresos")
        self._tabla_asistencia_seccion.heading("salidas", text="Salidas")
        self._tabla_asistencia_seccion.column("seccion", width=90, anchor="center", stretch=False)
        self._tabla_asistencia_seccion.column("ingresos", width=100, anchor="center", stretch=False)
        self._tabla_asistencia_seccion.column("salidas", width=100, anchor="center", stretch=False)

        self._tabla_asistencia_seccion.pack(fill="both", expand=True)

    def _panel_reporte_movimientos(self, padre):
        frame = tk.Frame(padre, bg=COLORES["panel"])
        frame.grid(row=0, column=0, sticky="nsew")

        inner = tk.Frame(frame, bg=COLORES["panel"])
        inner.pack(fill="both", expand=True, padx=16, pady=16)

        barra_superior = tk.Frame(inner, bg=COLORES["panel"])
        barra_superior.pack(fill="x", pady=(0, 10))

        cabecera_reporte = tk.Frame(barra_superior, bg=COLORES["panel"])
        cabecera_reporte.pack(side="left", fill="y")

        tk.Label(
            cabecera_reporte,
            text="REPORTE COMPLETO DE ENTRADAS Y SALIDAS",
            font=("Segoe UI", 11, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w")

        self._lbl_reporte_seccion = tk.Label(
            cabecera_reporte,
            text="Filtro: TODAS LAS SECCIONES",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["resalte"],
        )
        self._lbl_reporte_seccion.pack(anchor="w", pady=(2, 0))

        resumen_superior = tk.Frame(barra_superior, bg=COLORES["panel"])
        resumen_superior.pack(side="right", fill="y")

        self._lbl_reporte_total = self._crear_chip_resumen(resumen_superior, "Total", "0", COLORES["acento"])
        self._lbl_reporte_ingresos = self._crear_chip_resumen(resumen_superior, "Entradas", "0", COLORES["exito"])
        self._lbl_reporte_salidas = self._crear_chip_resumen(resumen_superior, "Salidas", "0", COLORES["advertencia"])
        self._lbl_reporte_alertas = self._crear_chip_resumen(resumen_superior, "Alertas", "0", COLORES["resalte"])

        barra_filtros = tk.Frame(inner, bg=COLORES["panel"])
        barra_filtros.pack(fill="x", pady=(0, 10))

        filtros_seccion = tk.Frame(barra_filtros, bg=COLORES["panel"])
        filtros_seccion.pack(side="left", fill="x", expand=True)

        tk.Label(
            filtros_seccion,
            text="Sección",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(side="left", padx=(0, 8))

        self._botones_reporte_seccion = {}
        for seccion in (TODAS, *SECCIONES):
            texto = "TODAS" if seccion == TODAS else seccion
            boton = tk.Button(
                filtros_seccion,
                text=texto,
                font=("Segoe UI", 8, "bold"),
                bg=COLORES["acento"] if seccion == TODAS else COLORES["tarjeta"],
                fg="#FFFFFF" if seccion == TODAS else COLORES["texto_secundario"],
                activebackground=COLORES["acento_hover"],
                activeforeground="#FFFFFF",
                relief="flat",
                bd=0,
                padx=10,
                pady=5,
                cursor="hand2",
                command=lambda s=seccion: self._seleccionar_reporte_seccion(s),
            )
            boton.pack(side="left", padx=(0, 6))
            self._botones_reporte_seccion[seccion] = boton

        busqueda_frame = tk.Frame(inner, bg=COLORES["panel"])
        busqueda_frame.pack(fill="x", pady=(0, 10))

        tk.Label(
            busqueda_frame,
            text="Buscar",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(side="left")

        entrada_busqueda = tk.Entry(
            busqueda_frame,
            textvariable=self._busqueda_estadisticas,
            font=("Segoe UI", 10),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=8,
        )
        entrada_busqueda.pack(side="left", fill="x", expand=True, padx=(8, 8))
        entrada_busqueda.bind("<KeyRelease>", lambda _evento: self._actualizar_tabla_estadisticas())

        tk.Button(
            busqueda_frame,
            text="Limpiar",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["texto_primario"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=lambda: (self._busqueda_estadisticas.set(""), self._actualizar_tabla_estadisticas()),
        ).pack(side="right")

        tk.Button(
            busqueda_frame,
            text="Vista previa",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["texto_primario"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=self._previsualizar_reporte_actual,
        ).pack(side="right", padx=(0, 8))

        tk.Button(
            busqueda_frame,
            text="Exportar Excel",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["acento"],
            fg="#FFFFFF",
            activebackground=COLORES["acento_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=self._exportar_reporte_estadisticas,
        ).pack(side="right", padx=(0, 8))

        tk.Button(
            busqueda_frame,
            text="Exportar PDF",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["resalte"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["resalte"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=self._exportar_reporte_pdf,
        ).pack(side="right", padx=(0, 8))

        columnas = ("fecha", "hora", "codigo", "nombre", "seccion", "tipo", "permiso", "alerta")
        self._tabla_reporte_movimientos = ttk.Treeview(
            inner,
            columns=columnas,
            show="headings",
            style="Custom.Treeview",
            height=10,
        )
        self._tabla_reporte_movimientos.heading("fecha", text="Fecha")
        self._tabla_reporte_movimientos.heading("hora", text="Hora")
        self._tabla_reporte_movimientos.heading("codigo", text="Código")
        self._tabla_reporte_movimientos.heading("nombre", text="Estudiante")
        self._tabla_reporte_movimientos.heading("seccion", text="Sección")
        self._tabla_reporte_movimientos.heading("tipo", text="Movimiento")
        self._tabla_reporte_movimientos.heading("permiso", text="Permiso")
        self._tabla_reporte_movimientos.heading("alerta", text="Alerta")
        self._tabla_reporte_movimientos.column("fecha", width=100, anchor="center", stretch=False)
        self._tabla_reporte_movimientos.column("hora", width=90, anchor="center", stretch=False)
        self._tabla_reporte_movimientos.column("codigo", width=120, anchor="center", stretch=False)
        self._tabla_reporte_movimientos.column("nombre", width=320, anchor="w")
        self._tabla_reporte_movimientos.column("seccion", width=90, anchor="center", stretch=False)
        self._tabla_reporte_movimientos.column("tipo", width=120, anchor="center", stretch=False)
        self._tabla_reporte_movimientos.column("permiso", width=120, anchor="center", stretch=False)
        self._tabla_reporte_movimientos.column("alerta", width=170, anchor="center", stretch=False)
        self._tabla_reporte_movimientos.tag_configure("INGRESO", foreground=COLORES["exito"])
        self._tabla_reporte_movimientos.tag_configure("SALIDA", foreground=COLORES["advertencia"])
        self._tabla_reporte_movimientos.tag_configure("ALERTA", foreground=COLORES["resalte"])

        scroll_y = ttk.Scrollbar(
            inner,
            orient="vertical",
            command=self._tabla_reporte_movimientos.yview,
            style="Custom.Vertical.TScrollbar",
        )
        scroll_x = ttk.Scrollbar(
            inner,
            orient="horizontal",
            command=self._tabla_reporte_movimientos.xview,
        )
        self._tabla_reporte_movimientos.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        self._tabla_reporte_movimientos.pack(side="left", fill="both", expand=True)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")

    def _crear_chip_resumen(self, padre, etiqueta: str, valor_inicial: str, color: str):
        chip = tk.Frame(padre, bg=COLORES["tarjeta"], padx=14, pady=10)
        chip.pack(side="left", padx=(0, 10))

        tk.Label(
            chip,
            text=etiqueta.upper(),
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w")

        lbl = tk.Label(
            chip,
            text=valor_inicial,
            font=("Segoe UI", 18, "bold"),
            bg=COLORES["tarjeta"],
            fg=color,
        )
        lbl.pack(anchor="w")
        return lbl

    def _obtener_texto_permiso(self, detalle_alerta: str, estado_alerta: str = "") -> str:
        detalle = str(detalle_alerta or "").upper()
        if "CON PERMISO" in detalle:
            return "CON PERMISO"
        if "SIN PERMISO" in detalle:
            return "SIN PERMISO"
        if str(estado_alerta or "").upper() == "NORMAL":
            return "NO APLICA"
        return "NO APLICA"

    def _hora_actual_texto(self) -> str:
        return datetime.now().strftime("%H:%M")

    def _opciones_hora(self, paso_minutos: int = 5) -> list[str]:
        ahora = datetime.now().replace(second=0, microsecond=0)
        inicio = ahora.replace(hour=0, minute=0)
        opciones = [
            (inicio + timedelta(minutes=minuto)).strftime("%H:%M")
            for minuto in range(0, 24 * 60, paso_minutos)
        ]
        actual = self._hora_actual_texto()
        if actual not in opciones:
            opciones.insert(0, actual)
        return opciones

    def _crear_selector_hora(self, padre, variable: tk.StringVar, ancho: int = 8):
        cont = tk.Frame(padre, bg=padre.cget("bg"))
        selector = ttk.Combobox(
            cont,
            textvariable=variable,
            values=self._opciones_hora(),
            state="readonly",
            width=ancho,
        )
        selector.pack(side="left", fill="x", expand=True)
        tk.Button(
            cont,
            text="Ahora",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["acento"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["acento"],
            relief="flat",
            bd=0,
            padx=8,
            pady=4,
            cursor="hand2",
            command=lambda: variable.set(self._hora_actual_texto()),
        ).pack(side="left", padx=(8, 0))
        return cont, selector

    def _construir_tab_registros(self):
        cont = tk.Frame(self._tab_registros, bg=COLORES["fondo"])
        cont.pack(fill="both", expand=True)
        cont.columnconfigure(0, weight=1)
        cont.rowconfigure(2, weight=1)

        encabezado = tk.Frame(cont, bg=COLORES["fondo"])
        encabezado.grid(row=0, column=0, sticky="ew", pady=(0, 10))

        tk.Label(
            encabezado,
            text="REGISTROS POR ESTUDIANTE",
            font=("Segoe UI", 13, "bold"),
            bg=COLORES["fondo"],
            fg=COLORES["acento"],
        ).pack(anchor="w")

        tk.Label(
            encabezado,
            text="Busca un estudiante por código, nombre, apellido o sección para consultar e imprimir solo su historial.",
            font=("Segoe UI", 9),
            bg=COLORES["fondo"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w", pady=(2, 0))

        barra = tk.Frame(cont, bg=COLORES["panel"])
        barra.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        barra.columnconfigure(1, weight=1)

        tk.Label(
            barra,
            text="Buscar estudiante",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).grid(row=0, column=0, padx=(14, 8), pady=12, sticky="w")

        entrada = tk.Entry(
            barra,
            textvariable=self._busqueda_registros,
            font=("Segoe UI", 10),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=8,
        )
        entrada.grid(row=0, column=1, sticky="ew", pady=12)
        entrada.bind("<KeyRelease>", lambda _evento: self._actualizar_tabla_registros())

        tk.Button(
            barra,
            text="Limpiar",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["texto_primario"],
            relief="flat",
            bd=0,
            padx=8,
            pady=5,
            cursor="hand2",
            command=lambda: (self._busqueda_registros.set(""), self._actualizar_tabla_registros()),
        ).grid(row=0, column=2, padx=(8, 6), pady=12)

        tk.Button(
            barra,
            text="Exportar hoja",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["acento"],
            fg="#FFFFFF",
            activebackground=COLORES["acento_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=8,
            pady=5,
            cursor="hand2",
            command=self._exportar_registros_estudiante_csv,
        ).grid(row=0, column=3, padx=(0, 6), pady=12)

        tk.Button(
            barra,
            text="Imprimir PDF",
            font=("Segoe UI", 8, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["resalte"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["resalte"],
            relief="flat",
            bd=0,
            padx=8,
            pady=5,
            cursor="hand2",
            command=self._exportar_registros_estudiante_pdf,
        ).grid(row=0, column=4, padx=(0, 14), pady=12)

        cuerpo = tk.Frame(cont, bg=COLORES["fondo"])
        cuerpo.grid(row=2, column=0, sticky="nsew")
        cuerpo.columnconfigure(0, weight=0)
        cuerpo.columnconfigure(1, weight=1)
        cuerpo.rowconfigure(0, weight=1)

        panel_estudiantes = tk.Frame(cuerpo, bg=COLORES["panel"], width=390)
        panel_estudiantes.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        panel_estudiantes.pack_propagate(False)

        tk.Label(
            panel_estudiantes,
            text="ESTUDIANTES ENCONTRADOS",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w", padx=14, pady=(14, 8))

        columnas_lista = ("codigo", "nombre", "seccion", "ubicacion")
        self._tabla_registros_estudiantes = ttk.Treeview(
            panel_estudiantes,
            columns=columnas_lista,
            show="headings",
            style="Custom.Treeview",
            height=12,
            selectmode="browse",
        )
        self._tabla_registros_estudiantes.heading("codigo", text="Código")
        self._tabla_registros_estudiantes.heading("nombre", text="Nombre")
        self._tabla_registros_estudiantes.heading("seccion", text="Sección")
        self._tabla_registros_estudiantes.heading("ubicacion", text="Ubicación")
        self._tabla_registros_estudiantes.column("codigo", width=95, anchor="center", stretch=False)
        self._tabla_registros_estudiantes.column("nombre", width=170, anchor="w")
        self._tabla_registros_estudiantes.column("seccion", width=70, anchor="center", stretch=False)
        self._tabla_registros_estudiantes.column("ubicacion", width=80, anchor="center", stretch=False)
        self._tabla_registros_estudiantes.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._tabla_registros_estudiantes.bind("<<TreeviewSelect>>", self._seleccionar_estudiante_registros)

        panel_historial = tk.Frame(cuerpo, bg=COLORES["panel"])
        panel_historial.grid(row=0, column=1, sticky="nsew")
        panel_historial.columnconfigure(0, weight=1)
        panel_historial.rowconfigure(1, weight=1)

        self._lbl_registros_estudiante = tk.Label(
            panel_historial,
            text="Selecciona un estudiante para ver sus registros.",
            font=("Segoe UI", 10, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["resalte"],
            anchor="w",
        )
        self._lbl_registros_estudiante.grid(row=0, column=0, sticky="ew", padx=14, pady=(14, 8))

        columnas_hist = ("fecha", "hora", "movimiento", "estado", "turno", "permiso", "alerta", "detalle")
        self._tabla_registros_historial = ttk.Treeview(
            panel_historial,
            columns=columnas_hist,
            show="headings",
            style="Custom.Treeview",
        )
        encabezados_hist = {
            "fecha": "Fecha",
            "hora": "Hora",
            "movimiento": "Movimiento",
            "estado": "Estado",
            "turno": "Turno",
            "permiso": "Permiso",
            "alerta": "Alerta",
            "detalle": "Detalle",
        }
        anchos_hist = {
            "fecha": 100,
            "hora": 80,
            "movimiento": 110,
            "estado": 90,
            "turno": 100,
            "permiso": 110,
            "alerta": 135,
            "detalle": 220,
        }
        for columna in columnas_hist:
            self._tabla_registros_historial.heading(columna, text=encabezados_hist[columna])
            self._tabla_registros_historial.column(columna, width=anchos_hist[columna], anchor="center" if columna != "detalle" else "w", stretch=columna == "detalle")
        self._tabla_registros_historial.tag_configure("INGRESO", foreground=COLORES["exito"])
        self._tabla_registros_historial.tag_configure("SALIDA", foreground=COLORES["advertencia"])
        self._tabla_registros_historial.tag_configure("ALERTA", foreground=COLORES["resalte"])

        scroll = ttk.Scrollbar(
            panel_historial,
            orient="vertical",
            command=self._tabla_registros_historial.yview,
            style="Custom.Vertical.TScrollbar",
        )
        self._tabla_registros_historial.configure(yscrollcommand=scroll.set)
        self._tabla_registros_historial.grid(row=1, column=0, sticky="nsew", padx=(14, 0), pady=(0, 14))
        scroll.grid(row=1, column=1, sticky="ns", padx=(0, 14), pady=(0, 14))
        self._codigo_registros_seleccionado = None

    # ------------------------------------------------------------------
    # Permisos (entrada tardía / salida antes de horario) y roles
    # ------------------------------------------------------------------
    def _construir_tab_permisos(self):
        cont = tk.Frame(self._contenido_permisos, bg=COLORES["fondo"])
        cont.pack(fill="both", expand=True)
        cont.columnconfigure(0, weight=1)
        cont.rowconfigure(3, weight=1)
        cont.rowconfigure(5, weight=1)

        tk.Label(
            cont,
            text="VALIDACIÓN Y SEGUIMIENTO DE PERMISOS",
            font=("Segoe UI", 13, "bold"),
            bg=COLORES["fondo"],
            fg=COLORES["acento"],
        ).grid(row=0, column=0, sticky="w", pady=(0, 2))

        tk.Label(
            cont,
            text=(
                "Cuando un estudiante registra una entrada tardía o una salida antes de "
                "horario, el sistema guarda el movimiento de todas formas y deja aquí una "
                "solicitud para seguimiento. Si el permiso fue aprobado, la asistencia "
                "queda evidenciada como con permiso; si no, queda marcada como sin permiso."
            ),
            font=("Segoe UI", 9),
            bg=COLORES["fondo"],
            fg=COLORES["texto_secundario"],
            wraplength=1000,
            justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(0, 10))

        panel_seccion = tk.Frame(cont, bg=COLORES["panel"])
        panel_seccion.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        panel_seccion.columnconfigure(1, weight=1)

        tk.Label(
            panel_seccion,
            text="PERMISO PARA UNA SECCIÓN",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["resalte"],
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=14, pady=(12, 8))

        self._var_permiso_seccion = tk.StringVar(value=SECCIONES[0])
        self._var_permiso_tipo = tk.StringVar(value="SALIDA")
        self._var_permiso_hora_seccion = tk.StringVar(value=self._hora_actual_texto())
        self._var_permiso_motivo_seccion = tk.StringVar()

        tk.Label(
            panel_seccion,
            text="Sección",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).grid(row=1, column=0, padx=(14, 8), pady=(0, 10), sticky="w")
        ttk.Combobox(
            panel_seccion,
            textvariable=self._var_permiso_seccion,
            values=SECCIONES,
            state="readonly",
            width=14,
        ).grid(row=1, column=1, padx=(0, 10), pady=(0, 10), sticky="w")

        tk.Label(
            panel_seccion,
            text="Tipo",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).grid(row=1, column=2, padx=(0, 8), pady=(0, 10), sticky="w")
        ttk.Combobox(
            panel_seccion,
            textvariable=self._var_permiso_tipo,
            values=("INGRESO", "SALIDA"),
            state="readonly",
            width=14,
        ).grid(row=1, column=3, padx=(0, 14), pady=(0, 10), sticky="w")

        tk.Label(
            panel_seccion,
            text="Hora asignada",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).grid(row=2, column=0, padx=(14, 8), pady=(0, 12), sticky="w")
        selector_seccion, _ = self._crear_selector_hora(panel_seccion, self._var_permiso_hora_seccion, ancho=10)
        selector_seccion.grid(row=2, column=1, sticky="w", pady=(0, 12))

        tk.Label(
            panel_seccion,
            text="Comentario opcional",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).grid(row=2, column=2, padx=(0, 8), pady=(0, 12), sticky="w")
        tk.Entry(
            panel_seccion,
            textvariable=self._var_permiso_motivo_seccion,
            font=("Segoe UI", 10),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=7,
        ).grid(row=2, column=3, padx=(0, 14), pady=(0, 12), sticky="ew")

        tk.Button(
            panel_seccion,
            text="OTORGAR A LA SECCIÓN",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["acento"],
            fg="#FFFFFF",
            activebackground=COLORES["acento_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=12,
            pady=7,
            cursor="hand2",
            command=self._otorgar_permiso_seccion,
        ).grid(row=3, column=0, columnspan=4, padx=14, pady=(0, 12), sticky="ew")

        panel_pend = tk.Frame(cont, bg=COLORES["panel"])
        panel_pend.grid(row=3, column=0, sticky="nsew", pady=(0, 12))
        panel_pend.columnconfigure(0, weight=1)
        panel_pend.rowconfigure(1, weight=1)

        cab_pend = tk.Frame(panel_pend, bg=COLORES["panel"])
        cab_pend.grid(row=0, column=0, sticky="ew", padx=14, pady=(12, 8))
        tk.Label(
            cab_pend, text="SOLICITUDES PENDIENTES", font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"], fg=COLORES["resalte"],
        ).pack(side="left")
        tk.Button(
            cab_pend, text="Actualizar", font=("Segoe UI", 8), bg=COLORES["tarjeta"],
            fg=COLORES["acento"], activebackground=COLORES["borde"], activeforeground=COLORES["acento"],
            relief="flat", bd=0, padx=8, pady=4, cursor="hand2",
            command=self._actualizar_tabla_permisos,
        ).pack(side="right")

        columnas_p = ("id", "codigo", "nombre", "seccion", "fecha", "tipo", "hora", "detalle", "solicitado")
        self._tabla_permisos_pendientes = ttk.Treeview(
            panel_pend, columns=columnas_p, show="headings", style="Custom.Treeview", height=8, selectmode="browse",
        )
        encabezados_p = {
            "id": "ID", "codigo": "Código", "nombre": "Estudiante", "seccion": "Sección",
            "fecha": "Fecha", "tipo": "Movimiento", "hora": "Hora", "detalle": "Motivo", "solicitado": "Solicitado",
        }
        anchos_p = {"id": 50, "codigo": 90, "nombre": 220, "seccion": 80, "fecha": 90, "tipo": 100, "hora": 75, "detalle": 260, "solicitado": 140}
        for col in columnas_p:
            self._tabla_permisos_pendientes.heading(col, text=encabezados_p[col])
            self._tabla_permisos_pendientes.column(col, width=anchos_p[col], anchor="center" if col not in {"nombre", "detalle"} else "w", stretch=col == "detalle")
        self._tabla_permisos_pendientes.grid(row=1, column=0, sticky="nsew", padx=14, pady=(0, 10))
        self._tabla_permisos_pendientes.bind("<<TreeviewSelect>>", self._seleccionar_permiso_pendiente)

        scroll_pend_x = ttk.Scrollbar(
            panel_pend,
            orient="horizontal",
            command=self._tabla_permisos_pendientes.xview,
        )
        self._tabla_permisos_pendientes.configure(xscrollcommand=scroll_pend_x.set)
        scroll_pend_x.grid(row=2, column=0, sticky="ew", padx=14, pady=(0, 10))

        botones_p = tk.Frame(panel_pend, bg=COLORES["panel"])
        botones_p.grid(row=3, column=0, sticky="ew", padx=14, pady=(0, 14))

        self._var_hora_permiso = tk.StringVar(value=self._hora_actual_texto())
        tk.Label(
            botones_p, text="Hora:", font=("Segoe UI", 9),
            bg=COLORES["panel"], fg=COLORES["texto_secundario"],
        ).pack(side="left", padx=(0, 8))
        selector_permiso, _ = self._crear_selector_hora(botones_p, self._var_hora_permiso, ancho=9)
        selector_permiso.pack(side="left", padx=(0, 10))

        self._var_motivo_permiso = tk.StringVar()
        tk.Label(
            botones_p, text="Comentario opcional:", font=("Segoe UI", 9),
            bg=COLORES["panel"], fg=COLORES["texto_secundario"],
        ).pack(side="left", padx=(0, 8))
        tk.Entry(
            botones_p, textvariable=self._var_motivo_permiso, font=("Segoe UI", 10),
            bg=COLORES["entrada_fondo"], fg=COLORES["texto_primario"], insertbackground=COLORES["acento"],
            relief="flat", bd=7,
        ).pack(side="left", fill="x", expand=True, padx=(0, 10))

        tk.Button(
            botones_p, text="ACEPTAR PERMISO", font=("Segoe UI", 9, "bold"), bg=COLORES["exito"], fg="#FFFFFF",
            activebackground="#00A87D", activeforeground="#FFFFFF", relief="flat", bd=0, padx=12, pady=7,
            cursor="hand2", command=lambda: self._resolver_permiso_seleccionado("APROBADO"),
        ).pack(side="left", padx=(0, 8))

        tk.Button(
            botones_p, text="RECHAZAR", font=("Segoe UI", 9, "bold"), bg=COLORES["advertencia"], fg="#FFFFFF",
            activebackground="#CC5555", activeforeground="#FFFFFF", relief="flat", bd=0, padx=12, pady=7,
            cursor="hand2", command=lambda: self._resolver_permiso_seleccionado("RECHAZADO"),
        ).pack(side="left")

        tk.Label(
            cont, text="HISTORIAL DE PERMISOS", font=("Segoe UI", 11, "bold"),
            bg=COLORES["fondo"], fg=COLORES["acento"],
        ).grid(row=4, column=0, sticky="w", pady=(4, 6))

        panel_hist = tk.Frame(cont, bg=COLORES["panel"])
        panel_hist.grid(row=5, column=0, sticky="nsew")
        panel_hist.columnconfigure(0, weight=1)
        panel_hist.rowconfigure(0, weight=1)

        columnas_h = ("codigo", "nombre", "fecha", "tipo", "hora", "estado", "autorizado", "resolucion", "comentario")
        self._tabla_permisos_historial = ttk.Treeview(
            panel_hist, columns=columnas_h, show="headings", style="Custom.Treeview",
        )
        encabezados_h = {
            "codigo": "Código", "nombre": "Estudiante", "fecha": "Fecha", "tipo": "Movimiento",
            "hora": "Hora", "estado": "Estado", "autorizado": "Autorizado por", "resolucion": "Resuelto", "comentario": "Comentario",
        }
        anchos_h = {"codigo": 90, "nombre": 220, "fecha": 90, "tipo": 100, "hora": 75, "estado": 100, "autorizado": 150, "resolucion": 160, "comentario": 240}
        for col in columnas_h:
            self._tabla_permisos_historial.heading(col, text=encabezados_h[col])
            self._tabla_permisos_historial.column(col, width=anchos_h[col], anchor="center" if col not in {"nombre", "comentario"} else "w", stretch=col in {"nombre", "comentario"})
        self._tabla_permisos_historial.tag_configure("APROBADO", foreground=COLORES["exito"])
        self._tabla_permisos_historial.tag_configure("RECHAZADO", foreground=COLORES["advertencia"])
        self._tabla_permisos_historial.tag_configure("PENDIENTE", foreground=COLORES["resalte"])
        self._tabla_permisos_historial.grid(row=0, column=0, sticky="nsew", padx=14, pady=14)

        scroll_hist_x = ttk.Scrollbar(
            panel_hist,
            orient="horizontal",
            command=self._tabla_permisos_historial.xview,
        )
        self._tabla_permisos_historial.configure(xscrollcommand=scroll_hist_x.set)
        scroll_hist_x.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))

        self._actualizar_tabla_permisos()

    def _actualizar_tabla_permisos(self):
        for fila in self._tabla_permisos_pendientes.get_children():
            self._tabla_permisos_pendientes.delete(fila)
        pendientes = self._repo.obtener_permisos_pendientes()
        for permiso in pendientes:
            self._tabla_permisos_pendientes.insert(
                "", "end", iid=str(permiso["id_permiso"]),
                values=(
                    permiso["id_permiso"],
                    permiso["id_estudiante"],
                    permiso["nombre_completo"],
                    permiso["codigo_seccion"],
                    self._repo._formatear_fecha(permiso["fecha"]),
                    "ENTRADA" if permiso["tipo_evento"] == "INGRESO" else "SALIDA",
                    permiso.get("hora_permiso", "") or "—",
                    permiso.get("motivo", ""),
                    permiso.get("fecha_solicitud", ""),
                ),
            )

        for fila in self._tabla_permisos_historial.get_children():
            self._tabla_permisos_historial.delete(fila)
        historial = self._repo.obtener_historial_permisos(100)
        for permiso in historial:
            self._tabla_permisos_historial.insert(
                "", "end",
                values=(
                    permiso["id_estudiante"],
                    permiso["nombre_completo"],
                    self._repo._formatear_fecha(permiso["fecha"]),
                    "ENTRADA" if permiso["tipo_evento"] == "INGRESO" else "SALIDA",
                    permiso.get("hora_permiso", "") or "—",
                    permiso["estado"],
                    permiso.get("autorizado_por", "") or "—",
                    permiso.get("fecha_resolucion", "") or "—",
                    permiso.get("observacion", "") or "—",
                ),
                tags=(permiso["estado"],),
            )

        if hasattr(self, "_actualizar_permisos_rapidos"):
            self._actualizar_permisos_rapidos()

    def _resolver_permiso_seleccionado(self, estado: str):
        seleccion = self._tabla_permisos_pendientes.selection()
        if not seleccion:
            self._aviso_temporal("Permisos", "Selecciona una solicitud pendiente de la lista.", COLORES["advertencia"])
            return

        id_permiso = int(seleccion[0])
        autorizado_por = self._nombre_usuario_actual or self._usuario_actual or "sistema"
        comentario = self._var_motivo_permiso.get().strip()
        hora_permiso = self._var_hora_permiso.get().strip() if hasattr(self, "_var_hora_permiso") else ""
        exito = self._repo.resolver_permiso(id_permiso, estado, autorizado_por, comentario, hora_permiso)
        if not exito:
            self._aviso_temporal("Permisos", "No se pudo actualizar la solicitud.", COLORES["advertencia"])
            return

        self._var_motivo_permiso.set("")
        if hasattr(self, "_var_hora_permiso"):
            self._var_hora_permiso.set(hora_permiso or self._hora_actual_texto())
        self._actualizar_tabla_permisos()
        texto = "aprobado" if estado == "APROBADO" else "rechazado"
        self._aviso_temporal("Permiso resuelto", f"La solicitud #{id_permiso} fue {texto}.", COLORES["exito"] if estado == "APROBADO" else COLORES["advertencia"])

    def _seleccionar_permiso_pendiente(self, evento=None):
        seleccion = self._tabla_permisos_pendientes.selection()
        if not seleccion:
            return

        valores = self._tabla_permisos_pendientes.item(seleccion[0]).get("values", [])
        if not valores:
            return

        if hasattr(self, "_var_hora_permiso") and len(valores) > 6:
            hora = str(valores[6]).strip()
            self._var_hora_permiso.set(hora if hora and hora != "—" else self._hora_actual_texto())
        if hasattr(self, "_var_motivo_permiso") and len(valores) > 7:
            motivo = str(valores[7]).strip()
            self._var_motivo_permiso.set("" if motivo == "—" else motivo)

    def _seleccionar_permiso_rapido(self, evento=None):
        seleccion = self._tabla_permisos_rapidos.selection()
        if not seleccion:
            if hasattr(self, "_lbl_permiso_rapido"):
                self._lbl_permiso_rapido.config(text="Selecciona una solicitud pendiente.")
            return

        valores = self._tabla_permisos_rapidos.item(seleccion[0]).get("values", [])
        if not valores:
            return

        detalle = (
            f"{valores[1]} - {valores[2]} | Sección: {valores[3]} | "
            f"{valores[4]} | Hora: {valores[5]} | {valores[6]}"
        )
        if hasattr(self, "_var_hora_permiso_rapido"):
            self._var_hora_permiso_rapido.set(str(valores[5]) if str(valores[5]).strip() else self._hora_actual_texto())
        if hasattr(self, "_lbl_permiso_rapido"):
            self._lbl_permiso_rapido.config(text=detalle)

    def _resolver_permiso_rapido(self, estado: str):
        seleccion = self._tabla_permisos_rapidos.selection()
        if not seleccion:
            self._aviso_temporal("Permisos", "Selecciona una solicitud pendiente de la lista.", COLORES["advertencia"])
            return

        id_permiso = int(seleccion[0])
        autorizado_por = self._nombre_usuario_actual or self._usuario_actual or "sistema"
        comentario = self._var_comentario_permiso_rapido.get().strip()
        hora_permiso = self._var_hora_permiso_rapido.get().strip() if hasattr(self, "_var_hora_permiso_rapido") else ""
        exito = self._repo.resolver_permiso(id_permiso, estado, autorizado_por, comentario, hora_permiso)
        if not exito:
            self._aviso_temporal("Permisos", "No se pudo actualizar la solicitud.", COLORES["advertencia"])
            return

        self._var_comentario_permiso_rapido.set("")
        self._actualizar_permisos_rapidos()
        self._actualizar_tabla_permisos()
        texto = "aprobado" if estado == "APROBADO" else "rechazado"
        self._aviso_temporal("Permiso resuelto", f"La solicitud #{id_permiso} fue {texto}.", COLORES["exito"] if estado == "APROBADO" else COLORES["advertencia"])

    def _actualizar_permisos_rapidos(self):
        if not hasattr(self, "_tabla_permisos_rapidos"):
            return

        for item in self._tabla_permisos_rapidos.get_children():
            self._tabla_permisos_rapidos.delete(item)

        pendientes = self._repo.obtener_permisos_pendientes()
        for permiso in pendientes:
            self._tabla_permisos_rapidos.insert(
                "",
                "end",
                iid=str(permiso["id_permiso"]),
                values=(
                    permiso["id_permiso"],
                    permiso["id_estudiante"],
                    permiso["nombre_completo"],
                    permiso["codigo_seccion"],
                    "ENTRADA" if permiso["tipo_evento"] == "INGRESO" else "SALIDA",
                    permiso.get("hora_permiso", "") or self._var_hora_permiso_rapido.get(),
                    permiso.get("motivo", ""),
                ),
            )

        if pendientes:
            first = self._tabla_permisos_rapidos.get_children()[0]
            self._tabla_permisos_rapidos.selection_set(first)
            self._tabla_permisos_rapidos.focus(first)
            self._seleccionar_permiso_rapido()
        elif hasattr(self, "_lbl_permiso_rapido"):
            self._lbl_permiso_rapido.config(text="No hay solicitudes pendientes.")

    def _otorgar_permiso_seccion(self):
        seccion = self._var_permiso_seccion.get().strip().upper()
        tipo = self._var_permiso_tipo.get().strip().upper()
        hora_permiso = self._var_permiso_hora_seccion.get().strip() if hasattr(self, "_var_permiso_hora_seccion") else ""
        motivo = self._var_permiso_motivo_seccion.get().strip()

        if seccion not in SECCIONES or tipo not in {"INGRESO", "SALIDA"}:
            self._aviso_temporal("Permisos", "Selecciona una sección y un tipo válido.", COLORES["advertencia"])
            return

        creados = self._repo.otorgar_permiso_seccion(
            seccion,
            datetime.now().date().isoformat(),
            tipo,
            motivo,
            self._nombre_usuario_actual or self._usuario_actual or "sistema",
            hora_permiso,
        )

        if creados <= 0:
            self._aviso_temporal(
                "Permisos",
                "No se generaron permisos nuevos. Puede que ya existan solicitudes pendientes para esa sección.",
                COLORES["advertencia"],
            )
            return

        self._var_permiso_motivo_seccion.set("")
        if hasattr(self, "_var_permiso_hora_seccion"):
            self._var_permiso_hora_seccion.set(self._hora_actual_texto())
        self._actualizar_tabla_permisos()
        self._actualizar_permisos_rapidos()
        self._aviso_temporal(
            "Permisos",
            f"Se generaron {creados} permisos para la sección {seccion}.",
            COLORES["exito"],
        )

    def _aplicar_restricciones_rol(self):
        """El rol PROFESOR/COORDINADOR solo puede imprimir/consultar reportes y validar
        permisos; no puede crear, editar ni eliminar estudiantes."""
        if self._rol_actual == "ADMIN":
            return

        for widget in (
            self._btn_agregar_estudiante,
            self._btn_eliminar_estudiante,
            self._btn_cancelar_edicion,
        ):
            widget.config(state="disabled")

        for entrada in getattr(self, "_entradas_estudiante", []):
            entrada.config(state="disabled")
        self._combo_seccion.config(state="disabled")

        aviso = tk.Label(
            self._tab_estudiantes,
            text="Modo consulta: tu rol (Profesor/Coordinador) puede ver estudiantes, pero no agregar, editar ni eliminar.",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["fondo"],
            fg=COLORES["resalte"],
        )
        aviso.pack(before=self._tab_estudiantes.winfo_children()[0], anchor="w", padx=4, pady=(0, 6))

    # ------------------------------------------------------------------
    # Validación y lógica de registro
    # ------------------------------------------------------------------
    def _validar_numerico(self, texto: str) -> bool:
        return texto.isdigit() or texto == ""

    def _validar_correo_basico(self, correo: str) -> bool:
        correo = correo.strip()
        if not correo:
            return True
        if "@" not in correo:
            return False
        local, dominio = correo.rsplit("@", 1)
        return bool(local) and "." in dominio and not dominio.startswith(".")

    def _leer_config_correo_local(self) -> dict:
        if not CORREO_CONFIG_PATH.exists():
            return {}

        valores = {}
        try:
            for linea in CORREO_CONFIG_PATH.read_text(encoding="utf-8").splitlines():
                limpia = linea.strip()
                if not limpia or limpia.startswith("#") or "=" not in limpia:
                    continue
                clave, valor = limpia.split("=", 1)
                valores[clave.strip()] = valor.strip().strip('"').strip("'")
        except OSError:
            return {}
        return valores

    def _cargar_config_correo(self) -> dict:
        archivo = self._leer_config_correo_local()
        host = os.getenv("ASISTENCIA_SMTP_HOST", archivo.get("ASISTENCIA_SMTP_HOST", "")).strip()
        usuario = os.getenv("ASISTENCIA_SMTP_USER", archivo.get("ASISTENCIA_SMTP_USER", "")).strip()
        contrasena = os.getenv("ASISTENCIA_SMTP_PASSWORD", archivo.get("ASISTENCIA_SMTP_PASSWORD", "")).strip()
        puerto = os.getenv("ASISTENCIA_SMTP_PORT", archivo.get("ASISTENCIA_SMTP_PORT", "587")).strip()
        correo_origen = os.getenv("ASISTENCIA_SMTP_FROM", archivo.get("ASISTENCIA_SMTP_FROM", usuario)).strip()
        tls = os.getenv("ASISTENCIA_SMTP_TLS", archivo.get("ASISTENCIA_SMTP_TLS", "1")).strip().lower() not in {"0", "false", "no"}

        try:
            puerto_num = int(puerto)
        except ValueError:
            puerto_num = 587

        return {
            "host": host,
            "port": puerto_num,
            "username": usuario,
            "password": contrasena,
            "from": correo_origen or usuario,
            "tls": tls,
        }

    def _guardar_config_correo(self, valores: dict) -> bool:
        lineas = [
            "# Configuracion de correo para Island (generado desde la app).",
            f"ASISTENCIA_SMTP_HOST={valores.get('host', '')}",
            f"ASISTENCIA_SMTP_PORT={valores.get('port', '587')}",
            f"ASISTENCIA_SMTP_TLS={'1' if valores.get('tls', True) else '0'}",
            f"ASISTENCIA_SMTP_USER={valores.get('username', '')}",
            f"ASISTENCIA_SMTP_PASSWORD={valores.get('password', '')}",
            f"ASISTENCIA_SMTP_FROM={valores.get('from', valores.get('username', ''))}",
            "",
        ]
        try:
            CORREO_CONFIG_PATH.write_text("\n".join(lineas), encoding="utf-8")
        except OSError as exc:
            logger.error("No se pudo guardar correo_island.env: %s", exc)
            return False
        self._config_correo = self._cargar_config_correo()
        return True

    def _abrir_configuracion_correo(self):
        actual = self._cargar_config_correo()

        ventana = tk.Toplevel(self)
        ventana.title("Configurar correo (alertas por Gmail)")
        ventana.configure(bg=COLORES["panel"])
        ventana.geometry("500x560")
        ventana.transient(self)
        ventana.grab_set()

        cont = tk.Frame(ventana, bg=COLORES["panel"])
        cont.pack(fill="both", expand=True)

        tk.Label(
            cont,
            text="CONFIGURAR ENVÍO DE ALERTAS POR CORREO",
            font=("Segoe UI", 11, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(18, 4))

        tk.Label(
            cont,
            text=(
                "Para Gmail: activa la verificación en dos pasos en tu cuenta y genera una "
                "'contraseña de aplicación' en myaccount.google.com/apppasswords. Usa esa "
                "contraseña aquí, no la de tu cuenta normal."
            ),
            font=("Segoe UI", 8),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(0, 14))

        variables = {
            "host": tk.StringVar(value=actual.get("host") or "smtp.gmail.com"),
            "port": tk.StringVar(value=str(actual.get("port") or 587)),
            "username": tk.StringVar(value=actual.get("username") or ""),
            "password": tk.StringVar(value=actual.get("password") or ""),
            "from": tk.StringVar(value=actual.get("from") or ""),
        }
        var_tls = tk.BooleanVar(value=bool(actual.get("tls", True)))

        def campo(etiqueta, variable, mostrar=None):
            tk.Label(
                cont, text=etiqueta, font=("Segoe UI", 9), bg=COLORES["panel"], fg=COLORES["texto_secundario"],
            ).pack(anchor="w", padx=20)
            entrada = tk.Entry(
                cont, textvariable=variable, show=mostrar, font=("Segoe UI", 10),
                bg=COLORES["entrada_fondo"], fg=COLORES["texto_primario"],
                insertbackground=COLORES["acento"], relief="flat", bd=7,
            )
            entrada.pack(fill="x", padx=20, pady=(2, 10))
            return entrada

        campo("Servidor SMTP", variables["host"])
        campo("Puerto (587 = STARTTLS, 465 = SSL)", variables["port"])
        campo("Correo Gmail (usuario)", variables["username"])
        campo("Contraseña de aplicación", variables["password"], mostrar="*")
        campo("Correo remitente (From)", variables["from"])

        tk.Checkbutton(
            cont,
            text="Usar STARTTLS (recomendado para el puerto 587)",
            variable=var_tls,
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
            selectcolor=COLORES["entrada_fondo"],
            activebackground=COLORES["panel"],
        ).pack(anchor="w", padx=20, pady=(0, 10))

        lbl_estado = tk.Label(
            cont, text="", font=("Segoe UI", 9), bg=COLORES["panel"],
            fg=COLORES["texto_secundario"], wraplength=420, justify="left",
        )
        lbl_estado.pack(anchor="w", padx=20, pady=(0, 6))

        def recolectar() -> dict:
            try:
                puerto = int(variables["port"].get().strip() or "587")
            except ValueError:
                puerto = 587
            return {
                "host": variables["host"].get().strip(),
                "port": puerto,
                "username": variables["username"].get().strip(),
                "password": variables["password"].get().strip(),
                "from": variables["from"].get().strip() or variables["username"].get().strip(),
                "tls": var_tls.get(),
            }

        def guardar():
            valores = recolectar()
            if not valores["host"] or not valores["username"] or not valores["password"]:
                lbl_estado.config(text="Completa servidor, usuario y contraseña.", fg=COLORES["advertencia"])
                return
            if self._guardar_config_correo(valores):
                lbl_estado.config(text="Configuración guardada correctamente.", fg=COLORES["exito"])
            else:
                lbl_estado.config(text="No se pudo guardar el archivo de configuración.", fg=COLORES["advertencia"])

        def probar_en_hilo():
            valores = recolectar()
            mensaje = EmailMessage()
            mensaje["Subject"] = f"{NOMBRE_SISTEMA} - Correo de prueba"
            mensaje["From"] = f"{NOMBRE_SISTEMA} <{valores['from']}>"
            mensaje["To"] = valores["from"]
            mensaje.set_content(f"Este es un correo de prueba de {NOMBRE_SISTEMA}. Si lo recibes, la configuración SMTP funciona correctamente.")
            try:
                self._enviar_correo_smtp(valores, mensaje)
                self.after(0, lambda: lbl_estado.config(text=f"Correo de prueba enviado a {valores['from']}.", fg=COLORES["exito"]))
            except Exception as exc:
                error = str(exc) or exc.__class__.__name__
                logger.error("Fallo la prueba de correo: %s", error, exc_info=True)
                self.after(0, lambda: lbl_estado.config(text=f"Error al enviar: {error}", fg=COLORES["advertencia"]))

        def probar():
            valores = recolectar()
            if not valores["host"] or not valores["username"] or not valores["password"]:
                lbl_estado.config(text="Completa servidor, usuario y contraseña antes de probar.", fg=COLORES["advertencia"])
                return
            lbl_estado.config(text="Enviando correo de prueba...", fg=COLORES["texto_secundario"])
            threading.Thread(target=probar_en_hilo, daemon=True).start()

        botones = tk.Frame(cont, bg=COLORES["panel"])
        botones.pack(fill="x", padx=20, pady=(10, 18))

        tk.Button(
            botones, text="Guardar configuración", font=FUENTES["boton"], bg=COLORES["acento"], fg="#FFFFFF",
            activebackground=COLORES["acento_hover"], activeforeground="#FFFFFF", relief="flat",
            bd=0, padx=10, pady=10, cursor="hand2", command=guardar,
        ).pack(side="left", fill="x", expand=True, padx=(0, 6))

        tk.Button(
            botones, text="Enviar prueba", font=("Segoe UI", 9, "bold"), bg=COLORES["tarjeta"],
            fg=COLORES["resalte"], activebackground=COLORES["borde"], activeforeground=COLORES["resalte"],
            relief="flat", bd=0, padx=10, pady=10, cursor="hand2", command=probar,
        ).pack(side="left", fill="x", expand=True, padx=(6, 0))

    def _formatear_nombre_estudiante(self, estudiante: dict) -> str:
        return f"{estudiante.get('nombre', '')} {estudiante.get('apellido', '')}".strip()

    def _obtener_carpeta_reportes(self) -> Path:
        REPORTES_DIR.mkdir(parents=True, exist_ok=True)
        return REPORTES_DIR

    def _ruta_reporte(self, nombre_archivo: str) -> Path:
        return self._obtener_carpeta_reportes() / nombre_archivo

    def _coincide_texto(self, consulta: str, *campos: object) -> bool:
        consulta = consulta.strip().lower()
        if not consulta:
            return True
        texto = " ".join(str(campo) for campo in campos).lower()
        return consulta in texto

    def _procesar_registro(self, evento=None):
        id_estudiante = self._var_id.get().strip()

        if not id_estudiante:
            self._mostrar_resultado("Ingresa un código numérico válido.", COLORES["resalte"])
            return

        if not id_estudiante.isdigit():
            self._mostrar_resultado("El código debe contener solo números.", COLORES["advertencia"])
            return

        self._btn_registrar.config(state="disabled", text="Procesando...")
        self._entry_id.config(state="disabled")

        threading.Thread(
            target=self._registrar_en_hilo,
            args=(id_estudiante,),
            daemon=True,
        ).start()

    def _registrar_en_hilo(self, id_estudiante: str):
        try:
            estudiante = self._repo.buscar_estudiante(id_estudiante)

            if estudiante is None:
                self.after(
                    0,
                    lambda c=id_estudiante: self._on_no_registrado(c),
                )
                return

            registro = self._repo.registrar_movimiento(id_estudiante, self._usuario_actual or "")

            if registro is None:
                self.after(0, lambda: self._on_error_registro("No se pudo guardar el movimiento."))
                return

            if registro.get("bloqueado"):
                self.after(0, lambda r=registro: self._on_registro_bloqueado(estudiante, r))
                return

            self.after(0, lambda: self._on_registro_exitoso(estudiante, registro))
        except Exception as exc:
            self.after(0, lambda: self._on_error_registro(f"Error inesperado: {exc}"))

    def _on_registro_exitoso(self, estudiante: dict, registro: dict):
        tipo = registro["tipo_evento"]
        alerta = registro.get("estado_alerta") or "NORMAL"
        color = COLORES["resalte"] if alerta != "NORMAL" else COLORES["exito"] if tipo == "INGRESO" else COLORES["advertencia"]
        icono = "●" if tipo == "INGRESO" else "■"
        self._qr_registration_busy = False
        nombre = self._formatear_nombre_estudiante(estudiante)
        seccion = estudiante["codigo_seccion"]
        correo_encargado = str(estudiante.get("correo_encargado", "")).strip()
        permiso_evidencia = str(registro.get("permiso_evidencia") or "NO APLICA")

        texto = (
            f"{icono} {tipo}\n"
            f"{nombre}\n"
            f"Sección: {seccion}  •  {registro['hora']}\n"
            f"Turno: {registro.get('turno', '')}  •  {alerta}\n"
            f"Permiso: {permiso_evidencia}\n"
            f"Estado actual: {registro.get('estado_actual', '')}\n"
            f"Encargado: {correo_encargado or 'sin correo'}"
        )
        self._mostrar_resultado(texto, color)
        if alerta != "NORMAL":
            self._aviso_temporal(
                "Alerta de asistencia",
                (
                    f"{alerta}\n\n"
                    f"Estudiante: {nombre}\n"
                    f"Sección: {seccion}\n"
                    f"Hora: {registro['hora']}\n"
                    f"Turno: {registro.get('turno', '')}\n"
                    f"Detalle: {registro.get('detalle_alerta', '')}"
                ),
                COLORES["resalte"],
            )
            if correo_encargado:
                threading.Thread(
                    target=self._enviar_alerta_correo_en_hilo,
                    args=(estudiante, registro),
                    daemon=True,
                ).start()
            if hasattr(self, "_actualizar_tabla_permisos"):
                self._actualizar_tabla_permisos()
            if hasattr(self, "_actualizar_permisos_rapidos"):
                self._actualizar_permisos_rapidos()

        self._limpiar_registro()
        self._actualizar_tabla_movimientos()
        self._actualizar_estadisticas_basicas()
        self._actualizar_tabla_estadisticas()
        self._actualizar_tabla_registros()
        self._actualizar_indicador_conexion()

    def _on_registro_bloqueado(self, estudiante: dict, registro: dict):
        self._qr_registration_busy = False
        nombre = f"{estudiante['nombre']} {estudiante['apellido']}"
        requiere_permiso = registro.get("requiere_permiso")
        titulo = "Requiere permiso" if requiere_permiso else "Registro no procesado"
        texto = (
            f"{titulo}\n"
            f"{nombre}\n"
            f"Estado actual: {registro.get('estado_actual', 'FUERA')}\n"
            f"{registro.get('mensaje', '')}"
        )
        self._mostrar_resultado(texto, COLORES["resalte"])
        self._aviso_temporal(titulo, texto, COLORES["resalte"], duracion_ms=5000)
        self._limpiar_registro()
        self._actualizar_tabla_movimientos()
        self._actualizar_estadisticas_basicas()
        self._actualizar_tabla_estadisticas()
        self._actualizar_tabla_registros()
        if requiere_permiso and hasattr(self, "_actualizar_tabla_permisos"):
            self._actualizar_tabla_permisos()
        if hasattr(self, "_actualizar_permisos_rapidos"):
            self._actualizar_permisos_rapidos()

    def _on_error_registro(self, mensaje: str):
        self._qr_registration_busy = False
        self._mostrar_resultado(mensaje, COLORES["advertencia"])
        self._limpiar_registro()

    def _enviar_alerta_correo_en_hilo(self, estudiante: dict, registro: dict):
        correo_destino = str(estudiante.get("correo_encargado", "")).strip()
        if not correo_destino:
            logger.info("Alerta sin envío: el estudiante %s no tiene correo de encargado.", estudiante.get("id_estudiante"))
            return

        # Se relee la config cada vez por si se guardó desde el diálogo de Configurar correo.
        config = self._cargar_config_correo()
        self._config_correo = config

        if not config["host"] or not config["username"] or not config["password"]:
            logger.warning(
                "Correo SMTP no configurado (host=%r, usuario=%r). No se notificó a %s.",
                config["host"], config["username"], correo_destino,
            )
            self.after(
                0,
                lambda: self._aviso_temporal(
                    "Correo no configurado",
                    (
                        f"{NOMBRE_SISTEMA} generó la alerta, pero falta configurar el correo SMTP "
                        f"para notificar a {correo_destino}.\n\n"
                        "Ve a 'Configurar correo' en la parte superior para conectar tu cuenta de Gmail."
                    ),
                    COLORES["texto_secundario"],
                    duracion_ms=5000,
                ),
            )
            return

        mensaje = EmailMessage()
        nombre = self._formatear_nombre_estudiante(estudiante)
        mensaje["Subject"] = f"{NOMBRE_SISTEMA} - Alerta de asistencia"
        mensaje["From"] = f"{NOMBRE_SISTEMA} <{config['from']}>"
        mensaje["To"] = correo_destino
        mensaje.set_content(
            "\n".join(
                [
                    f"{NOMBRE_SISTEMA}",
                    "Alerta de asistencia",
                    "",
                    f"Estudiante: {nombre}",
                    f"Código: {estudiante.get('id_estudiante', '')}",
                    f"Sección: {estudiante.get('codigo_seccion', '')}",
                    f"Fecha: {registro.get('fecha', '')}",
                    f"Hora: {registro.get('hora', '')}",
                    f"Movimiento: {registro.get('tipo_evento', '')}",
                    f"Alerta: {registro.get('estado_alerta', '')}",
                    f"Detalle: {registro.get('detalle_alerta', '')}",
                ]
            )
        )

        try:
            self._enviar_correo_smtp(config, mensaje)
            logger.info("Correo de alerta enviado a %s (estudiante %s).", correo_destino, estudiante.get("id_estudiante"))
            self.after(
                0,
                lambda: self._aviso_temporal(
                    "Correo enviado",
                    f"{NOMBRE_SISTEMA} notificó a {correo_destino} sobre la alerta de {nombre}.",
                    COLORES["exito"],
                    duracion_ms=3500,
                ),
            )
        except Exception as exc:
            error = str(exc) or exc.__class__.__name__
            logger.error("No se pudo enviar el correo a %s: %s", correo_destino, error, exc_info=True)
            self.after(
                0,
                lambda: self._aviso_temporal(
                    "Correo no enviado",
                    f"No se pudo notificar a {correo_destino}:\n{error}",
                    COLORES["advertencia"],
                    duracion_ms=5000,
                ),
            )

    def _enviar_correo_smtp(self, config: dict, mensaje: EmailMessage):
        """Envía un mensaje ya construido usando la configuración SMTP dada.

        Soporta el puerto 587 (STARTTLS, usado por Gmail/Outlook) y el 465
        (SSL directo), y siempre valida el certificado con un contexto TLS.
        """
        contexto = ssl.create_default_context()
        if int(config.get("port") or 0) == 465:
            with smtplib.SMTP_SSL(config["host"], config["port"], timeout=15, context=contexto) as servidor:
                if config["username"]:
                    servidor.login(config["username"], config["password"])
                servidor.send_message(mensaje)
            return

        with smtplib.SMTP(config["host"], config["port"], timeout=15) as servidor:
            servidor.ehlo()
            if config["tls"]:
                servidor.starttls(context=contexto)
                servidor.ehlo()
            if config["username"]:
                servidor.login(config["username"], config["password"])
            servidor.send_message(mensaje)

    def _on_no_registrado(self, codigo: str):
        self._qr_registration_busy = False
        mensaje = (
            "NIE no registrado\n"
            f"Código/NIE: {codigo}\n"
            "No existe un estudiante activo con este identificador."
        )
        self._mostrar_resultado(mensaje, COLORES["advertencia"])
        self._aviso_temporal("NIE no registrado", mensaje, COLORES["advertencia"], duracion_ms=4500)
        self._limpiar_registro()

    def _limpiar_registro(self):
        self._var_id.set("")
        self._entry_id.config(state="normal")
        self._btn_registrar.config(state="normal", text="REGISTRAR")
        self._entry_id.focus_set()

    def _abrir_lector_qr(self):
        ventana = tk.Toplevel(self)
        ventana.title("Leer código QR")
        ventana.configure(bg=COLORES["fondo"])
        ventana.geometry("900x620")
        ventana.resizable(True, True)
        self._maximizar_ventana(ventana)
        ventana.transient(self)
        ventana.grab_set()

        cont = tk.Frame(ventana, bg=COLORES["panel"])
        cont.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            cont,
            text="LECTOR QR",
            font=("Segoe UI", 11, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w")

        tk.Label(
            cont,
            text="Pega el contenido del QR o selecciona una imagen con el código.",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
            wraplength=360,
            justify="left",
        ).pack(anchor="w", pady=(6, 12))

        var_qr = tk.StringVar()
        entry = tk.Entry(
            cont,
            textvariable=var_qr,
            font=("Segoe UI", 11),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=8,
        )
        entry.pack(fill="x")
        entry.focus_set()

        mensaje = tk.Label(
            cont,
            text="",
            font=("Segoe UI", 8),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
            wraplength=360,
            justify="left",
        )
        mensaje.pack(anchor="w", pady=(8, 0))

        def usar_codigo():
            codigo = var_qr.get().strip()
            if not codigo:
                mensaje.config(text="Ingresa un código antes de continuar.", fg=COLORES["advertencia"])
                return
            if not codigo.isdigit():
                mensaje.config(text="El contenido del QR debe ser un código numérico.", fg=COLORES["advertencia"])
                return
            self._var_id.set(codigo)
            ventana.destroy()
            self.after(50, self._procesar_registro)

        def cargar_imagen():
            ruta = filedialog.askopenfilename(
                parent=ventana,
                title="Selecciona una imagen QR",
                filetypes=[
                    ("Imágenes", "*.png *.jpg *.jpeg *.bmp *.gif"),
                    ("Todos los archivos", "*.*"),
                ],
            )
            if not ruta:
                return

            codigo, error = self._decodificar_qr_desde_imagen(ruta)
            if codigo:
                var_qr.set(codigo)
                mensaje.config(text=f"Código detectado: {codigo}", fg=COLORES["exito"])
                return

            mensaje.config(
                text=error or "No se pudo leer el QR de la imagen.",
                fg=COLORES["advertencia"],
            )

        botones = tk.Frame(cont, bg=COLORES["panel"])
        botones.pack(fill="x", pady=(14, 0))

        tk.Button(
            botones,
            text="CARGAR IMAGEN",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["acento"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["acento"],
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            command=cargar_imagen,
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            botones,
            text="USAR CÁMARA",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["acento"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["acento"],
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            command=self._iniciar_escaneo_qr_embebido,
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        tk.Button(
            botones,
            text="USAR CÓDIGO",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["acento"],
            fg="#FFFFFF",
            activebackground=COLORES["acento_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            command=usar_codigo,
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        if self._decodificar_qr_disponible() is None:
            mensaje.config(
                text="Para leer imágenes QR automáticamente falta instalar 'pyzbar'. Puedes pegar el código manualmente.",
                fg=COLORES["texto_secundario"],
            )

    def _decodificar_qr_disponible(self):
        try:
            import pyzbar  # noqa: F401
            return True
        except Exception:
            return None

    def _decodificar_qr_desde_imagen(self, ruta: str):
        try:
            from PIL import Image
        except Exception:
            return None, "PIL no está disponible para abrir imágenes."

        try:
            from pyzbar.pyzbar import decode
        except Exception:
            return None, "Falta instalar 'pyzbar' para decodificar imágenes QR."

        try:
            imagen = Image.open(ruta)
            resultados = decode(imagen)
            if not resultados:
                return None, "No se detectó ningún QR en la imagen."

            contenido = resultados[0].data.decode("utf-8").strip()
            return contenido, None
        except Exception as exc:
            return None, f"No se pudo leer la imagen: {exc}"

    def _set_estado_qr(self, texto: str, color: str):
        if hasattr(self, "_lbl_qr_estado"):
            self._lbl_qr_estado.config(text=texto, fg=color)

    def _set_preview_qr_texto(self, texto: str, color: str | None = None):
        if not hasattr(self, "_lbl_qr_preview"):
            return
        self._qr_preview_image = None
        self._lbl_qr_preview.config(
            image="",
            text=texto,
            fg=color or COLORES["texto_secundario"],
            bg=COLORES["entrada_fondo"],
        )

    def _mostrar_frame_qr(self, frame):
        if not hasattr(self, "_lbl_qr_preview") or not self._qr_scan_active:
            return

        try:
            import cv2
            from PIL import Image, ImageTk
        except Exception:
            if not self._qr_preview_error:
                self._qr_preview_error = True
                self._set_preview_qr_texto(
                    "Instala Pillow para ver\nla cámara en este cuadro.",
                    COLORES["advertencia"],
                )
            return

        try:
            ancho = max(self._lbl_qr_preview.winfo_width(), 320)
            alto = max(self._lbl_qr_preview.winfo_height(), 200)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            imagen = Image.fromarray(frame_rgb)
            imagen.thumbnail((ancho, alto))

            lienzo = Image.new("RGB", (ancho, alto), COLORES["entrada_fondo"])
            x = (ancho - imagen.width) // 2
            y = (alto - imagen.height) // 2
            lienzo.paste(imagen, (x, y))

            self._qr_preview_image = ImageTk.PhotoImage(lienzo)
            self._lbl_qr_preview.config(image=self._qr_preview_image, text="")
        except Exception:
            self._set_preview_qr_texto("No se pudo mostrar\nla cámara.", COLORES["advertencia"])

    def _iniciar_escaneo_qr_embebido(self, evento=None):
        if self._qr_scan_active:
            self._set_estado_qr("El escaneo ya está activo.", COLORES["texto_secundario"])
            return

        try:
            indice = int(self._var_indice_camara.get().strip())
        except Exception:
            self._set_estado_qr("El índice de cámara debe ser un número.", COLORES["advertencia"])
            return

        self._qr_scan_active = True
        self._qr_preview_error = False
        self._set_preview_qr_texto("Conectando cámara...")
        self._set_estado_qr(f"Iniciando cámara {indice}...", COLORES["texto_secundario"])

        self._qr_scan_thread = threading.Thread(
            target=self._escaneo_qr_usb_embebido,
            args=(indice,),
            daemon=True,
        )
        self._qr_scan_thread.start()

    def _detener_escaneo_qr_embebido(self):
        self._qr_scan_active = False
        self._set_preview_qr_texto("Vista de cámara\ndetenida")
        self._set_estado_qr("Escaneo detenido.", COLORES["texto_secundario"])

    def _escaneo_qr_usb_embebido(self, indice: int):
        try:
            import cv2
        except Exception:
            self.after(
                0,
                lambda: self._set_estado_qr(
                    "Falta instalar 'opencv-python' para usar la cámara USB.",
                    COLORES["advertencia"],
                ),
            )
            self._qr_scan_active = False
            self.after(0, lambda: self._set_preview_qr_texto("opencv-python no está\ninstalado.", COLORES["advertencia"]))
            return

        try:
            from pyzbar.pyzbar import decode
        except Exception:
            self.after(
                0,
                lambda: self._set_estado_qr(
                    "Falta instalar 'pyzbar' para leer el QR desde la cámara.",
                    COLORES["advertencia"],
                ),
            )
            self._qr_scan_active = False
            self.after(0, lambda: self._set_preview_qr_texto("pyzbar no está\ninstalado.", COLORES["advertencia"]))
            return

        cap = cv2.VideoCapture(indice)
        camara_usada = indice
        if not cap.isOpened():
            cap.release()
            cap = None
            for candidato in range(6):
                if candidato == indice:
                    continue
                prueba = cv2.VideoCapture(candidato)
                if prueba.isOpened():
                    cap = prueba
                    camara_usada = candidato
                    break
                prueba.release()

            if cap is None:
                self.after(
                    0,
                    lambda: self._set_estado_qr(
                        "No se pudo abrir la cámara. Prueba con el índice 1 para la PC o cambia a una USB disponible.",
                        COLORES["advertencia"],
                    ),
                )
                self._qr_scan_active = False
                self.after(0, lambda: self._set_preview_qr_texto("No se encontró\nuna cámara disponible.", COLORES["advertencia"]))
                return

            self.after(
                0,
                lambda: self._set_estado_qr(
                    f"Cámara encontrada en el índice {camara_usada}. Escaneando...",
                    COLORES["exito"],
                ),
            )

        import time
        ultimo_codigo = None
        ultimo_ts = 0.0

        try:
            while self._qr_scan_active:
                ok, frame = cap.read()
                if not ok:
                    self.after(
                        0,
                        lambda: self._set_estado_qr(
                            "No se pudo leer video de la cámara USB.",
                            COLORES["advertencia"],
                        ),
                    )
                    time.sleep(0.1)
                    continue

                self.after(0, lambda f=frame.copy(): self._mostrar_frame_qr(f))

                resultados = decode(frame)
                if resultados:
                    codigo = resultados[0].data.decode("utf-8").strip()
                    ahora = time.monotonic()
                    if codigo.isdigit():
                        if self._qr_registration_busy or (codigo == ultimo_codigo and (ahora - ultimo_ts) < 2.0):
                            time.sleep(0.1)
                            continue

                        ultimo_codigo = codigo
                        ultimo_ts = ahora
                        self._qr_registration_busy = True
                        self.after(0, lambda c=codigo, i=camara_usada: self._aplicar_qr_detectado(c, i))
                        time.sleep(1.5)
                        continue

                    self.after(
                        0,
                        lambda: self._set_estado_qr(
                            "Se leyó un QR, pero su contenido no es numérico.",
                            COLORES["advertencia"],
                        ),
                    )
                    time.sleep(0.5)
                    continue

                self.after(
                    0,
                    lambda: self._set_estado_qr(
                        f"Escaneando con cámara {camara_usada}... coloca el QR frente al lente.",
                        COLORES["texto_secundario"],
                    ),
                )
                time.sleep(0.03)
        finally:
            try:
                cap.release()
            except Exception:
                pass
            self._qr_scan_active = False
            self._qr_registration_busy = False
            self.after(
                0,
                lambda: (
                    self._set_estado_qr("Escaneo detenido.", COLORES["texto_secundario"]),
                    self._set_preview_qr_texto("Vista de cámara\ndetenida"),
                ),
            )

    def _aplicar_qr_detectado(self, codigo: str, indice_camara: int):
        self._var_id.set(codigo)
        self._set_estado_qr(
            f"Código detectado en cámara {indice_camara}: {codigo}. Registrando...",
            COLORES["exito"],
        )
        self._procesar_registro()

    def _abrir_lector_camara(self, padre=None):
        self._iniciar_escaneo_qr_embebido()

    def _abrir_pantalla_inicio_qr_auto(self):
        if self._escaneo_inicial_completado:
            self.deiconify()
            return

        ventana = tk.Toplevel(self)
        ventana.title("Inicio automático por QR")
        ventana.configure(bg=COLORES["fondo"])
        ventana.geometry("900x620")
        ventana.resizable(True, True)
        self._maximizar_ventana(ventana)
        ventana.transient(self)
        ventana.grab_set()
        ventana.lift()
        ventana.attributes("-topmost", True)
        ventana.after(200, lambda: ventana.attributes("-topmost", False))

        cont = tk.Frame(ventana, bg=COLORES["panel"])
        cont.pack(fill="both", expand=True, padx=16, pady=16)

        tk.Label(
            cont,
            text="ESCANEO AUTOMÁTICO",
            font=("Segoe UI", 12, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w")

        tk.Label(
            cont,
            text=(
                "Esta pantalla usa la cámara USB para leer un QR una sola vez.\n"
                "Cuando detecte un código numérico, registrará la asistencia automáticamente."
            ),
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
            wraplength=500,
            justify="left",
        ).pack(anchor="w", pady=(6, 12))

        fila = tk.Frame(cont, bg=COLORES["panel"])
        fila.pack(fill="x")

        tk.Label(
            fila,
            text="Índice de cámara (1 = PC)",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(side="left")

        var_indice = tk.StringVar(value="1")
        entrada_indice = tk.Entry(
            fila,
            textvariable=var_indice,
            font=("Segoe UI", 11),
            bg=COLORES["entrada_fondo"],
            fg=COLORES["texto_primario"],
            insertbackground=COLORES["acento"],
            relief="flat",
            bd=8,
            width=8,
            justify="center",
        )
        entrada_indice.pack(side="left", padx=(8, 0))

        lbl_estado = tk.Label(
            cont,
            text="Preparando escaneo...",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
            wraplength=500,
            justify="left",
        )
        lbl_estado.pack(anchor="w", pady=(12, 0))

        botones = tk.Frame(cont, bg=COLORES["panel"])
        botones.pack(fill="x", pady=(18, 0))

        control = {"activa": False}

        def continuar_sistema():
            control["activa"] = False
            if ventana.winfo_exists():
                ventana.destroy()
            self.deiconify()
            self._escaneo_inicial_completado = True

        def iniciar():
            if control["activa"]:
                return

            try:
                indice = int(var_indice.get().strip())
            except ValueError:
                lbl_estado.config(text="El índice debe ser un número.", fg=COLORES["advertencia"])
                return

            control["activa"] = True
            lbl_estado.config(text="Abriendo cámara USB...", fg=COLORES["texto_secundario"])

            threading.Thread(
                target=self._escaneo_qr_usb_una_vez,
                args=(indice, ventana, lbl_estado, control),
                daemon=True,
            ).start()

        tk.Button(
            botones,
            text="INICIAR ESCANEO",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["acento"],
            fg="#FFFFFF",
            activebackground=COLORES["acento_hover"],
            activeforeground="#FFFFFF",
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            command=iniciar,
        ).pack(side="left", fill="x", expand=True)

        tk.Button(
            botones,
            text="CONTINUAR SIN QR",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"],
            activebackground=COLORES["borde"],
            activeforeground=COLORES["texto_primario"],
            relief="flat",
            bd=0,
            padx=10,
            pady=8,
            cursor="hand2",
            command=continuar_sistema,
        ).pack(side="left", fill="x", expand=True, padx=(8, 0))

        ventana.protocol("WM_DELETE_WINDOW", continuar_sistema)
        self.after(300, iniciar)

    def _escaneo_qr_usb_una_vez(self, indice: int, ventana, lbl_estado, control: dict):
        try:
            import cv2
        except Exception:
            self.after(
                0,
                lambda: lbl_estado.config(
                    text="Falta instalar 'opencv-python' para usar la cámara USB.",
                    fg=COLORES["advertencia"],
                ),
            )
            control["activa"] = False
            return

        try:
            from pyzbar.pyzbar import decode
        except Exception:
            self.after(
                0,
                lambda: lbl_estado.config(
                    text="Falta instalar 'pyzbar' para leer el QR desde la cámara.",
                    fg=COLORES["advertencia"],
                ),
            )
            control["activa"] = False
            return

        cap = cv2.VideoCapture(indice)
        if not cap.isOpened():
            self.after(
                0,
                lambda: lbl_estado.config(
                    text=f"No se pudo abrir la cámara USB en el índice {indice}. Prueba 0, 1 o 2.",
                    fg=COLORES["advertencia"],
                ),
            )
            control["activa"] = False
            return

        import time

        while control["activa"] and ventana.winfo_exists():
            ok, frame = cap.read()
            if not ok:
                self.after(
                    0,
                    lambda: lbl_estado.config(
                        text="No se pudo leer video de la cámara USB.",
                        fg=COLORES["advertencia"],
                    ),
                )
                break

            resultados = decode(frame)
            if resultados:
                codigo = resultados[0].data.decode("utf-8").strip()
                if codigo.isdigit():
                    control["activa"] = False
                    try:
                        cap.release()
                    except Exception:
                        pass
                    self.after(0, lambda: self._confirmar_qr_inicial(codigo, ventana))
                    return

                self.after(
                    0,
                    lambda: lbl_estado.config(
                        text="Se leyó un QR, pero su contenido no es numérico.",
                        fg=COLORES["advertencia"],
                    ),
                )
                break

            self.after(
                0,
                lambda: lbl_estado.config(
                    text=f"Escaneando con cámara USB {indice}... coloca el QR frente al lente.",
                    fg=COLORES["texto_secundario"],
                ),
            )
            time.sleep(0.03)

        try:
            cap.release()
        except Exception:
            pass

    def _confirmar_qr_inicial(self, codigo: str, ventana):
        self._escaneo_inicial_completado = True
        if ventana.winfo_exists():
            ventana.destroy()
        self.deiconify()
        self._var_id.set(codigo)
        self.after(150, self._procesar_registro)

    # ------------------------------------------------------------------
    # Alta de estudiantes
    # ------------------------------------------------------------------
    def _procesar_nuevo_estudiante(self):
        codigo = self._var_codigo_estudiante.get().strip()
        nombre = self._var_nombre.get().strip()
        apellido = self._var_apellido.get().strip()
        correo_encargado = self._var_correo_encargado.get().strip()
        seccion = self._var_seccion.get().strip().upper()

        if not codigo or not nombre or not apellido or seccion not in SECCIONES:
            self._lbl_estado_estudiantes.config(
                text="Completa código, nombre, apellido y sección.",
                fg=COLORES["advertencia"],
            )
            return

        if not self._validar_correo_basico(correo_encargado):
            self._lbl_estado_estudiantes.config(
                text="El correo del encargado no parece válido.",
                fg=COLORES["advertencia"],
            )
            return

        if not codigo.isdigit():
            self._lbl_estado_estudiantes.config(
                text="El código del estudiante debe ser numérico.",
                fg=COLORES["advertencia"],
            )
            return

        self._btn_agregar_estudiante.config(state="disabled", text="Guardando...")

        threading.Thread(
            target=self._guardar_estudiante_en_hilo,
            args=(
                codigo,
                nombre,
                apellido,
                correo_encargado,
                seccion,
                self._modo_estudiante,
                self._codigo_estudiante_original,
            ),
            daemon=True,
        ).start()

    def _guardar_estudiante_en_hilo(
        self,
        codigo: str,
        nombre: str,
        apellido: str,
        correo_encargado: str,
        seccion: str,
        modo: str,
        codigo_original: str | None,
    ):
        try:
            if modo == "editar":
                if codigo_original is None:
                    self.after(0, lambda: self._on_error_estudiante("No hay un estudiante seleccionado para editar."))
                    return

                if codigo != codigo_original:
                    existente = self._repo.buscar_estudiante_por_id(codigo)
                    if existente is not None:
                        self.after(
                            0,
                            lambda: self._on_error_estudiante(
                                f"El código {codigo} ya existe para {existente['nombre']} {existente['apellido']}."
                            ),
                        )
                        return

                exito = self._repo.actualizar_estudiante(
                    codigo_original,
                    codigo,
                    nombre,
                    apellido,
                    seccion,
                    correo_encargado,
                    activo=True,
                )
                if not exito:
                    self.after(0, lambda: self._on_error_estudiante("No se pudo actualizar el estudiante."))
                    return

                self.after(0, lambda: self._on_estudiante_actualizado(codigo_original, codigo, nombre, apellido, seccion))
                return

            existente = self._repo.buscar_estudiante_por_id(codigo)
            if existente is not None:
                self.after(
                    0,
                    lambda: self._on_error_estudiante(
                        f"El código {codigo} ya existe para {existente['nombre']} {existente['apellido']}."
                    ),
                )
                return

            exito = self._repo.registrar_estudiante(codigo, nombre, apellido, seccion, correo_encargado)
            if not exito:
                self.after(0, lambda: self._on_error_estudiante("No se pudo guardar el estudiante."))
                return

            self.after(0, lambda: self._on_estudiante_exitoso(codigo, nombre, apellido, seccion))
        except Exception as exc:
            self.after(0, lambda: self._on_error_estudiante(f"Error inesperado: {exc}"))

    def _on_estudiante_exitoso(self, codigo: str, nombre: str, apellido: str, seccion: str):
        self._lbl_estado_estudiantes.config(
            text=f"Estudiante agregado: {codigo} - {nombre} {apellido} ({seccion}).",
            fg=COLORES["exito"],
        )
        self._aviso_temporal("Estudiante agregado", f"{nombre} {apellido} fue registrado correctamente.", COLORES["exito"])

        self._var_codigo_estudiante.set("")
        self._var_nombre.set("")
        self._var_apellido.set("")
        self._var_correo_encargado.set("")
        self._var_seccion.set(SECCIONES[0])
        self._salir_modo_edicion()
        self._actualizar_lista_estudiantes()
        self._actualizar_estadisticas_basicas()
        self._actualizar_tabla_estadisticas()
        self._actualizar_tabla_registros()

    def _on_estudiante_actualizado(self, codigo_original: str, codigo: str, nombre: str, apellido: str, seccion: str):
        self._lbl_estado_estudiantes.config(
            text=f"Estudiante actualizado: {codigo_original} -> {codigo} | {nombre} {apellido} ({seccion}).",
            fg=COLORES["exito"],
        )
        self._aviso_temporal("Estudiante actualizado", f"{nombre} {apellido} fue actualizado correctamente.", COLORES["exito"])
        self._var_codigo_estudiante.set("")
        self._var_nombre.set("")
        self._var_apellido.set("")
        self._var_correo_encargado.set("")
        self._var_seccion.set(SECCIONES[0])
        self._salir_modo_edicion()
        self._actualizar_lista_estudiantes()
        self._actualizar_estadisticas_basicas()
        self._actualizar_tabla_estadisticas()
        self._actualizar_tabla_registros()

    def _on_error_estudiante(self, mensaje: str):
        self._lbl_estado_estudiantes.config(text=mensaje, fg=COLORES["advertencia"])
        if self._modo_estudiante == "editar":
            self._btn_agregar_estudiante.config(state="normal", text="ACTUALIZAR ESTUDIANTE")
            self._btn_cancelar_edicion.config(state="normal")
        else:
            self._btn_agregar_estudiante.config(state="normal", text="AGREGAR ESTUDIANTE")
            self._btn_cancelar_edicion.config(state="disabled")

    def _salir_modo_edicion(self):
        self._modo_estudiante = "crear"
        self._codigo_estudiante_original = None
        self._btn_agregar_estudiante.config(state="normal", text="AGREGAR ESTUDIANTE")
        self._btn_cancelar_edicion.config(state="disabled")
        self._btn_eliminar_estudiante.config(state="disabled")
        self._lbl_estado_estudiantes.config(
            text="Usa un código numérico, por ejemplo 6052414.",
            fg=COLORES["texto_secundario"],
        )

    def _entrar_modo_edicion(self, codigo_original: str):
        self._modo_estudiante = "editar"
        self._codigo_estudiante_original = codigo_original
        self._btn_agregar_estudiante.config(text="ACTUALIZAR ESTUDIANTE")
        self._btn_cancelar_edicion.config(state="normal")
        self._btn_eliminar_estudiante.config(state="normal")
        correo = self._var_correo_encargado.get().strip() or "Sin correo"
        self._lbl_estado_estudiantes.config(
            text=f"Editando estudiante {codigo_original}. Encargado: {correo}. Cambia los campos y presiona actualizar.",
            fg=COLORES["resalte"],
        )

    def _cancelar_edicion_estudiante(self):
        self._var_codigo_estudiante.set("")
        self._var_nombre.set("")
        self._var_apellido.set("")
        self._var_correo_encargado.set("")
        self._var_seccion.set(SECCIONES[0])
        self._salir_modo_edicion()

    def _eliminar_estudiante_seleccionado(self):
        codigo = self._codigo_estudiante_original
        if not codigo:
            self._lbl_estado_estudiantes.config(
                text="Selecciona un estudiante para eliminar.",
                fg=COLORES["advertencia"],
            )
            return

        estudiante = self._repo.buscar_estudiante_por_id(codigo)
        if estudiante is None:
            self._lbl_estado_estudiantes.config(
                text="No se encontró el estudiante seleccionado.",
                fg=COLORES["advertencia"],
            )
            return

        nombre = f"{estudiante['nombre']} {estudiante['apellido']}"
        exito = self._repo.eliminar_estudiante(codigo)
        if not exito:
            self._lbl_estado_estudiantes.config(
                text="No se pudo eliminar el estudiante.",
                fg=COLORES["advertencia"],
            )
            return

        self._lbl_estado_estudiantes.config(
            text=f"Estudiante eliminado: {codigo} - {nombre}.",
            fg=COLORES["exito"],
        )
        self._aviso_temporal("Estudiante eliminado", f"{nombre} quedó inactivo en el sistema.", COLORES["advertencia"])
        self._cancelar_edicion_estudiante()
        self._actualizar_lista_estudiantes()
        self._actualizar_estadisticas_basicas()
        self._actualizar_tabla_estadisticas()
        self._actualizar_tabla_registros()

    def _cargar_estudiante_seleccionado(self, evento=None):
        seleccion = self._tabla_estudiantes.selection()
        if not seleccion:
            return

        item = self._tabla_estudiantes.item(seleccion[0])
        valores = item.get("values", [])
        if len(valores) < 6:
            return

        codigo = str(valores[0])
        estudiante = self._repo.buscar_estudiante_por_id(codigo)
        if estudiante is None:
            return

        nombre = str(estudiante["nombre"])
        apellido = str(estudiante["apellido"])
        seccion = str(estudiante["codigo_seccion"])
        correo = str(estudiante.get("correo_encargado", ""))

        self._var_codigo_estudiante.set(codigo)
        self._var_nombre.set(nombre)
        self._var_apellido.set(apellido)
        self._var_correo_encargado.set(correo)
        self._var_seccion.set(seccion if seccion in SECCIONES else SECCIONES[0])
        self._entrar_modo_edicion(codigo)

    # ------------------------------------------------------------------
    # Actualización de vistas
    # ------------------------------------------------------------------
    def _actualizar_tabla_movimientos(self):
        movimientos = self._repo.obtener_ultimos_movimientos(limite=100)

        for item in self._tabla.get_children():
            self._tabla.delete(item)

        if not movimientos:
            self._tabla.insert(
                "",
                "end",
                values=(
                    "",
                    "Sin registros de entrada o salida hoy",
                    "",
                    "",
                    "",
                    "",
                    "",
                    "",
                ),
                tags=("ALERTA",),
            )
            return

        for mov in movimientos:
            tipo = mov["tipo_evento"]
            alerta = mov.get("estado_alerta") or "NORMAL"
            estado_actual = "DENTRO" if tipo == "INGRESO" else "FUERA"
            permiso = self._obtener_texto_permiso(mov.get("detalle_alerta", ""), alerta)
            self._tabla.insert(
                "",
                "end",
                values=(
                    mov.get("id_asistencia", ""),
                    mov["nombre_completo"],
                    mov["codigo_seccion"],
                    str(mov["hora"])[:8],
                    tipo,
                    estado_actual,
                    permiso,
                    alerta,
                ),
                tags=("ALERTA",) if alerta != "NORMAL" else (tipo,),
            )

    def _actualizar_lista_estudiantes(self):
        for item in self._tabla_estudiantes.get_children():
            self._tabla_estudiantes.delete(item)

        seccion = self._filtro_seccion.get()
        consulta = self._busqueda_estudiantes.get()
        estudiantes = self._repo.obtener_estudiantes(
            codigo_seccion=seccion,
            incluir_inactivos=True,
        )

        for estudiante in estudiantes:
            activo = "ACTIVO" if int(estudiante["activo"]) == 1 else "INACTIVO"
            ubicacion = self._repo.obtener_estado_estudiante_hoy(estudiante["id_estudiante"])
            tag = "inactivo" if activo == "INACTIVO" else "dentro" if ubicacion == "DENTRO" else "fuera"
            nombre = estudiante["nombre"]
            apellido = estudiante["apellido"]
            if not self._coincide_texto(
                consulta,
                estudiante["id_estudiante"],
                nombre,
                apellido,
                estudiante["codigo_seccion"],
                estudiante.get("correo_encargado", ""),
                activo,
            ):
                continue
            self._tabla_estudiantes.insert(
                "",
                "end",
                values=(
                    estudiante["id_estudiante"],
                    f"{nombre} {apellido}",
                    estudiante["codigo_seccion"],
                    ubicacion,
                    activo,
                    estudiante["fecha_registro"],
                ),
                tags=(tag,),
            )

        if hasattr(self, "_lbl_estado_estudiantes") and seccion != TODAS:
            self._lbl_estado_estudiantes.config(
                text=f"Mostrando estudiantes de {seccion}.",
                fg=COLORES["texto_secundario"],
            )

    def _actualizar_estadisticas_basicas(self):
        resumen = self._repo.obtener_resumen_hoy()
        self._stat_ingresos.config(text=str(resumen["ingresos"]))
        self._stat_salidas.config(text=str(resumen["salidas"]))
        self._stat_presentes.config(text=str(resumen["presentes"]))
        if hasattr(self, "_lbl_resumen_hoy"):
            self._lbl_resumen_hoy.config(
                text=(
                    f"Entradas: {resumen['ingresos']}  |  "
                    f"Salidas: {resumen['salidas']}  |  "
                    f"Presentes: {resumen['presentes']}"
                )
            )

    def _actualizar_tabla_estadisticas(self):
        resumen = self._repo.obtener_estadisticas_generales()

        self._stat_total_estudiantes.config(text=str(resumen["total_estudiantes"]))
        self._stat_activos.config(text=str(resumen["activos"]))
        self._stat_mov_hoy.config(text=str(resumen["ingresos_hoy"] + resumen["salidas_hoy"]))
        self._stat_presentes_hoy.config(text=str(resumen["presentes_hoy"]))

        for item in self._tabla_secciones.get_children():
            self._tabla_secciones.delete(item)
        for fila in resumen["secciones"]:
            self._tabla_secciones.insert(
                "",
                "end",
                values=(
                    fila["codigo_seccion"],
                    fila["total_estudiantes"],
                    fila["activos"],
                ),
            )

        for item in self._tabla_asistencia_seccion.get_children():
            self._tabla_asistencia_seccion.delete(item)
        for fila in resumen["asistencia_por_seccion"]:
            self._tabla_asistencia_seccion.insert(
                "",
                "end",
                values=(
                    fila["codigo_seccion"],
                    fila["ingresos"],
                    fila["salidas"],
                ),
            )

        movimientos = self._obtener_reporte_filtrado() if hasattr(self, "_tabla_reporte_movimientos") else []
        if hasattr(self, "_lbl_reporte_total"):
            ingresos = sum(1 for mov in movimientos if mov["tipo_evento"] == "INGRESO")
            salidas = sum(1 for mov in movimientos if mov["tipo_evento"] == "SALIDA")
            alertas = sum(1 for mov in movimientos if (mov.get("estado_alerta") or "NORMAL") != "NORMAL")
            self._lbl_reporte_total.config(text=str(len(movimientos)))
            self._lbl_reporte_ingresos.config(text=str(ingresos))
            self._lbl_reporte_salidas.config(text=str(salidas))
            self._lbl_reporte_alertas.config(text=str(alertas))

        if hasattr(self, "_tabla_reporte_movimientos"):
            self._actualizar_estudiantes_reporte_seccion()
            for item in self._tabla_reporte_movimientos.get_children():
                self._tabla_reporte_movimientos.delete(item)
            if not movimientos:
                self._tabla_reporte_movimientos.insert(
                    "",
                    "end",
                    values=(
                        "",
                        "",
                        "",
                        "Sin movimientos para mostrar",
                        "",
                        "",
                        "",
                        "",
                    ),
                    tags=("ALERTA",),
                )
                return

            for mov in movimientos:
                tipo = mov["tipo_evento"]
                alerta = mov.get("estado_alerta") or "NORMAL"
                permiso = self._obtener_texto_permiso(mov.get("detalle_alerta", ""), alerta)
                self._tabla_reporte_movimientos.insert(
                    "",
                    "end",
                values=(
                    mov["fecha"],
                    str(mov["hora"])[:8],
                    mov["id_estudiante"],
                    mov["nombre_completo"],
                    mov["codigo_seccion"],
                    "ENTRO" if tipo == "INGRESO" else "SALIO",
                    permiso,
                    alerta,
                ),
                tags=("ALERTA",) if alerta != "NORMAL" else (tipo,),
            )

    def _seleccionar_reporte_seccion(self, seccion: str):
        self._filtro_reporte_seccion.set(seccion)
        for codigo, boton in self._botones_reporte_seccion.items():
            activo = codigo == seccion
            boton.config(
                bg=COLORES["acento"] if activo else COLORES["tarjeta"],
                fg="#FFFFFF" if activo else COLORES["texto_secundario"],
            )
        texto = "TODAS LAS SECCIONES" if seccion == TODAS else seccion
        self._lbl_reporte_seccion.config(text=f"Filtro: {texto}")
        self._actualizar_tabla_estadisticas()

    def _previsualizar_reporte_actual(self):
        movimientos = self._obtener_reporte_filtrado()
        if not movimientos:
            self._aviso_temporal("Vista previa", "No hay registros para previsualizar.", COLORES["advertencia"])
            return

        encabezados = ["Fecha", "Hora", "Código", "Nombre", "Sección", "Movimiento", "Permiso", "Alerta"]
        filas = []
        for mov in movimientos:
            tipo = mov["tipo_evento"]
            permiso = self._obtener_texto_permiso(mov.get("detalle_alerta", ""), mov.get("estado_alerta", ""))
            filas.append(
                [
                    mov["fecha"],
                    str(mov["hora"])[:5],
                    mov["id_estudiante"],
                    mov["nombre_completo"],
                    mov["codigo_seccion"],
                    "ENTRO" if tipo == "INGRESO" else "SALIO",
                    permiso,
                    mov.get("estado_alerta") or "NORMAL",
                ]
            )

        titulo = f"{NOMBRE_SISTEMA} - Vista previa de entradas y salidas"
        self._previsualizar_reporte(titulo, encabezados, filas, lambda: None)

    def _actualizar_estudiantes_reporte_seccion(self):
        if not hasattr(self, "_tabla_reporte_estudiantes_seccion"):
            return

        for item in self._tabla_reporte_estudiantes_seccion.get_children():
            self._tabla_reporte_estudiantes_seccion.delete(item)

        seccion = self._filtro_reporte_seccion.get()
        estudiantes = self._repo.obtener_estudiantes(
            codigo_seccion=seccion,
            incluir_inactivos=True,
        )
        for estudiante in estudiantes:
            activo = "ACTIVO" if int(estudiante["activo"]) == 1 else "INACTIVO"
            ubicacion = self._repo.obtener_estado_estudiante_hoy(estudiante["id_estudiante"])
            self._tabla_reporte_estudiantes_seccion.insert(
                "",
                "end",
                values=(
                    estudiante["id_estudiante"],
                    f"{estudiante['nombre']} {estudiante['apellido']}",
                    ubicacion,
                    activo,
                ),
            )

    def _obtener_reporte_filtrado(self) -> list[dict]:
        consulta = self._busqueda_estadisticas.get()
        seccion = self._filtro_reporte_seccion.get()
        movimientos = self._repo.obtener_reporte_movimientos()
        filtrados = []
        for mov in movimientos:
            if seccion != TODAS and mov["codigo_seccion"] != seccion:
                continue
            if self._coincide_texto(
                consulta,
                mov["fecha"],
                mov["hora"],
                mov["id_estudiante"],
                mov["nombre_completo"],
                mov["codigo_seccion"],
                mov["tipo_evento"],
                mov.get("turno", ""),
                mov.get("estado_alerta", ""),
                mov.get("detalle_alerta", ""),
            ):
                filtrados.append(mov)
        return filtrados

    def _actualizar_tabla_registros(self):
        if not hasattr(self, "_tabla_registros_estudiantes"):
            return

        for item in self._tabla_registros_estudiantes.get_children():
            self._tabla_registros_estudiantes.delete(item)

        consulta = self._busqueda_registros.get()
        estudiantes = self._repo.obtener_estudiantes(incluir_inactivos=True)
        primero = None
        for estudiante in estudiantes:
            activo = "ACTIVO" if int(estudiante["activo"]) == 1 else "INACTIVO"
            nombre_completo = f"{estudiante['nombre']} {estudiante['apellido']}"
            ubicacion = self._repo.obtener_estado_estudiante_hoy(estudiante["id_estudiante"])
            if not self._coincide_texto(
                consulta,
                estudiante["id_estudiante"],
                nombre_completo,
                estudiante["codigo_seccion"],
                estudiante.get("correo_encargado", ""),
                activo,
                ubicacion,
            ):
                continue
            item = self._tabla_registros_estudiantes.insert(
                "",
                "end",
                values=(
                    estudiante["id_estudiante"],
                    nombre_completo,
                    estudiante["codigo_seccion"],
                    ubicacion,
                ),
            )
            if primero is None:
                primero = item

        if primero is not None:
            self._tabla_registros_estudiantes.selection_set(primero)
            self._tabla_registros_estudiantes.focus(primero)
            self._seleccionar_estudiante_registros()
        else:
            self._codigo_registros_seleccionado = None
            self._lbl_registros_estudiante.config(text="No hay estudiantes que coincidan con la búsqueda.")
            for item in self._tabla_registros_historial.get_children():
                self._tabla_registros_historial.delete(item)

    def _seleccionar_estudiante_registros(self, evento=None):
        seleccion = self._tabla_registros_estudiantes.selection()
        if not seleccion:
            return

        valores = self._tabla_registros_estudiantes.item(seleccion[0]).get("values", [])
        if not valores:
            return

        codigo = str(valores[0])
        self._codigo_registros_seleccionado = codigo
        estudiante = self._repo.buscar_estudiante_por_id(codigo)
        nombre = str(valores[1])
        seccion = str(valores[2])
        ubicacion = str(valores[3])
        correo = ""
        if estudiante:
            nombre = f"{estudiante['nombre']} {estudiante['apellido']}"
            seccion = estudiante["codigo_seccion"]
            correo = str(estudiante.get("correo_encargado", "")).strip()
        self._lbl_registros_estudiante.config(
            text=(
                f"{codigo} - {nombre} | Sección: {seccion} | Estado actual: {ubicacion}"
                + (f" | Encargado: {correo}" if correo else " | Encargado: sin correo")
            )
        )

        for item in self._tabla_registros_historial.get_children():
            self._tabla_registros_historial.delete(item)

        for mov in self._obtener_registros_estudiante_filtrados():
            tipo = mov["tipo_evento"]
            alerta = mov.get("estado_alerta") or "NORMAL"
            permiso = self._obtener_texto_permiso(mov.get("detalle_alerta", ""), alerta)
            self._tabla_registros_historial.insert(
                "",
                "end",
                values=(
                    mov["fecha"],
                    str(mov["hora"])[:8],
                    "ENTRO" if tipo == "INGRESO" else "SALIO",
                    "DENTRO" if tipo == "INGRESO" else "FUERA",
                    mov.get("turno", ""),
                    permiso,
                    alerta,
                    mov.get("detalle_alerta", ""),
                ),
                tags=("ALERTA",) if alerta != "NORMAL" else (tipo,),
            )

    def _obtener_registros_estudiante_filtrados(self) -> list[dict]:
        codigo = getattr(self, "_codigo_registros_seleccionado", None)
        if not codigo:
            return []
        return [
            mov
            for mov in self._repo.obtener_reporte_movimientos()
            if str(mov["id_estudiante"]) == str(codigo)
        ]

    def _exportar_reporte_estadisticas(self):
        movimientos = self._obtener_reporte_filtrado()
        if not movimientos:
            self._aviso_temporal("Exportar reporte", "No hay registros para exportar.", COLORES["advertencia"])
            return

        nombre_archivo = f"reporte_asistencia_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ruta = self._ruta_reporte(nombre_archivo)

        encabezados = [
            "Fecha",
            "Hora",
            "Codigo",
            "Nombre completo",
            "Seccion",
            "Correo encargado",
            "Turno",
            "Movimiento",
            "Estado",
            "Permiso",
            "Alerta",
            "Detalle",
        ]

        try:
            with open(ruta, "w", newline="", encoding="utf-8-sig") as archivo:
                escritor = csv.writer(archivo)
                escritor.writerow(encabezados)
                for mov in movimientos:
                    tipo = mov["tipo_evento"]
                    permiso = self._obtener_texto_permiso(mov.get("detalle_alerta", ""), mov.get("estado_alerta", ""))
                    escritor.writerow(
                        [
                            mov["fecha"],
                            str(mov["hora"])[:8],
                            mov["id_estudiante"],
                            mov["nombre_completo"],
                            mov["codigo_seccion"],
                            mov.get("correo_encargado", ""),
                            mov.get("turno", ""),
                            "ENTRO" if tipo == "INGRESO" else "SALIO",
                            "DENTRO" if tipo == "INGRESO" else "FUERA",
                            permiso,
                            mov.get("estado_alerta") or "NORMAL",
                            mov.get("detalle_alerta", ""),
                        ]
                    )
        except OSError as exc:
            self._aviso_temporal("Exportar reporte", f"No se pudo guardar el archivo:\n{exc}", COLORES["advertencia"])
            return

        self._aviso_temporal(
            "Exportar Excel",
            f"Hoja CSV para Excel generada en reportes.\n\nRegistros: {len(movimientos)}\nArchivo: {ruta}",
            COLORES["exito"],
        )

    def _exportar_reporte_pdf(self):
        movimientos = self._obtener_reporte_filtrado()
        if not movimientos:
            self._aviso_temporal("Imprimir PDF", "No hay registros para imprimir.", COLORES["advertencia"])
            return

        encabezados = ["Fecha", "Hora", "Codigo", "Nombre", "Secc.", "Correo", "Mov.", "Estado", "Permiso", "Alerta"]
        filas = []
        for mov in movimientos:
            tipo = mov["tipo_evento"]
            permiso = self._obtener_texto_permiso(mov.get("detalle_alerta", ""), mov.get("estado_alerta", ""))
            filas.append(
                [
                    mov["fecha"],
                    str(mov["hora"])[:5],
                    mov["id_estudiante"],
                    mov["nombre_completo"],
                    mov["codigo_seccion"],
                    mov.get("correo_encargado", ""),
                    "ENTRO" if tipo == "INGRESO" else "SALIO",
                    "DENTRO" if tipo == "INGRESO" else "FUERA",
                    permiso,
                    mov.get("estado_alerta") or "NORMAL",
                ]
            )

        titulo = f"{NOMBRE_SISTEMA} - Reporte completo de asistencia"

        def confirmar_impresion():
            nombre_archivo = f"reporte_asistencia_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            ruta = self._ruta_reporte(nombre_archivo)
            try:
                self._crear_pdf_reporte(ruta, titulo, encabezados, filas)
            except OSError as exc:
                self._aviso_temporal("Imprimir PDF", f"No se pudo guardar el PDF:\n{exc}", COLORES["advertencia"])
                return
            self._aviso_temporal(
                "Exportar PDF",
                f"PDF generado en reportes.\n\nRegistros: {len(movimientos)}\nArchivo: {ruta}",
                COLORES["exito"],
            )

        self._previsualizar_reporte(titulo, encabezados, filas, confirmar_impresion)

    def _exportar_registros_estudiante_csv(self):
        movimientos = self._obtener_registros_estudiante_filtrados()
        if not movimientos:
            self._aviso_temporal("Registros", "Selecciona un estudiante con registros para exportar.", COLORES["advertencia"])
            return

        codigo = str(movimientos[0]["id_estudiante"])
        nombre_archivo = f"registros_estudiante_{codigo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        ruta = self._ruta_reporte(nombre_archivo)

        try:
            with open(ruta, "w", newline="", encoding="utf-8-sig") as archivo:
                escritor = csv.writer(archivo)
                escritor.writerow(["Fecha", "Hora", "Codigo", "Nombre completo", "Seccion", "Correo encargado", "Movimiento", "Estado", "Turno", "Permiso", "Alerta", "Detalle"])
                for mov in movimientos:
                    tipo = mov["tipo_evento"]
                    permiso = self._obtener_texto_permiso(mov.get("detalle_alerta", ""), mov.get("estado_alerta", ""))
                    escritor.writerow(
                        [
                            mov["fecha"],
                            str(mov["hora"])[:8],
                            mov["id_estudiante"],
                            mov["nombre_completo"],
                            mov["codigo_seccion"],
                            mov.get("correo_encargado", ""),
                            "ENTRO" if tipo == "INGRESO" else "SALIO",
                            "DENTRO" if tipo == "INGRESO" else "FUERA",
                            mov.get("turno", ""),
                            permiso,
                            mov.get("estado_alerta") or "NORMAL",
                            mov.get("detalle_alerta", ""),
                        ]
                    )
        except OSError as exc:
            self._aviso_temporal("Registros", f"No se pudo guardar el archivo:\n{exc}", COLORES["advertencia"])
            return

        self._aviso_temporal("Registros", f"Hoja CSV para Excel generada en reportes.\nArchivo: {ruta}", COLORES["exito"])

    def _exportar_registros_estudiante_pdf(self):
        movimientos = self._obtener_registros_estudiante_filtrados()
        if not movimientos:
            self._aviso_temporal("Registros", "Selecciona un estudiante con registros para imprimir.", COLORES["advertencia"])
            return

        codigo = str(movimientos[0]["id_estudiante"])
        nombre = movimientos[0]["nombre_completo"]
        encabezados = ["Fecha", "Hora", "Codigo", "Nombre", "Secc.", "Correo", "Mov.", "Estado", "Permiso", "Alerta"]

        filas = []
        for mov in movimientos:
            tipo = mov["tipo_evento"]
            permiso = self._obtener_texto_permiso(mov.get("detalle_alerta", ""), mov.get("estado_alerta", ""))
            filas.append(
                [
                    mov["fecha"],
                    str(mov["hora"])[:5],
                    mov["id_estudiante"],
                    mov["nombre_completo"],
                    mov["codigo_seccion"],
                    mov.get("correo_encargado", ""),
                    "ENTRO" if tipo == "INGRESO" else "SALIO",
                    "DENTRO" if tipo == "INGRESO" else "FUERA",
                    permiso,
                    mov.get("estado_alerta") or "NORMAL",
                ]
            )

        titulo = f"{NOMBRE_SISTEMA} - Registros de {codigo} - {nombre}"

        def confirmar_impresion():
            nombre_archivo = f"registros_estudiante_{codigo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
            ruta = self._ruta_reporte(nombre_archivo)
            try:
                self._crear_pdf_reporte(ruta, titulo, encabezados, filas)
            except OSError as exc:
                self._aviso_temporal("Registros", f"No se pudo guardar el PDF:\n{exc}", COLORES["advertencia"])
                return
            self._aviso_temporal("Registros", f"PDF generado en reportes.\nArchivo: {ruta}", COLORES["exito"])

        self._previsualizar_reporte(titulo, encabezados, filas, confirmar_impresion)

    def _previsualizar_reporte(self, titulo: str, encabezados: list[str], filas: list[list[object]], on_confirmar):
        """Muestra una previsualización del reporte antes de generarlo/imprimirlo en PDF."""
        ventana = tk.Toplevel(self)
        ventana.title(f"Previsualización - {titulo}")
        ventana.configure(bg=COLORES["panel"])
        ventana.geometry("960x560")
        ventana.transient(self)
        ventana.grab_set()

        cabecera = tk.Frame(ventana, bg=COLORES["panel"])
        cabecera.pack(fill="x", padx=18, pady=(16, 8))

        tk.Label(
            cabecera,
            text="VISTA PREVIA DE IMPRESIÓN",
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["acento"],
        ).pack(anchor="w")

        tk.Label(
            cabecera,
            text=titulo,
            font=("Segoe UI", 13, "bold"),
            bg=COLORES["panel"],
            fg=COLORES["texto_primario"],
            wraplength=900,
            justify="left",
        ).pack(anchor="w", pady=(4, 2))

        resumen = tk.Frame(ventana, bg=COLORES["panel"])
        resumen.pack(fill="x", padx=18, pady=(0, 12))

        total = len(filas)
        ingresos = sum(1 for fila in filas if len(fila) > 5 and str(fila[5]) == "ENTRO")
        salidas = sum(1 for fila in filas if len(fila) > 5 and str(fila[5]) == "SALIO")
        alertas = sum(1 for fila in filas if len(fila) > 6 and str(fila[6]) != "NORMAL")

        self._crear_chip_resumen(resumen, "Registros", str(total), COLORES["acento"])
        self._crear_chip_resumen(resumen, "Entradas", str(ingresos), COLORES["exito"])
        self._crear_chip_resumen(resumen, "Salidas", str(salidas), COLORES["advertencia"])
        self._crear_chip_resumen(resumen, "Alertas", str(alertas), COLORES["resalte"])

        tk.Label(
            ventana,
            text=f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_secundario"],
        ).pack(anchor="w", padx=18, pady=(0, 10))

        contenedor = tk.Frame(ventana, bg=COLORES["panel"])
        contenedor.pack(fill="both", expand=True, padx=18)

        columnas = tuple(f"c{idx}" for idx in range(len(encabezados)))
        tabla = ttk.Treeview(contenedor, columns=columnas, show="headings", style="Custom.Treeview")
        for idx, encabezado in enumerate(encabezados):
            tabla.heading(columnas[idx], text=encabezado)
            tabla.column(columnas[idx], width=max(72, 860 // max(1, len(encabezados))), anchor="center" if idx not in (3,) else "w")

        for fila in filas:
            tabla.insert("", "end", values=fila)

        scroll_y = ttk.Scrollbar(contenedor, orient="vertical", command=tabla.yview, style="Custom.Vertical.TScrollbar")
        scroll_x = ttk.Scrollbar(contenedor, orient="horizontal", command=tabla.xview)
        tabla.configure(yscrollcommand=scroll_y.set, xscrollcommand=scroll_x.set)
        tabla.pack(side="top", fill="both", expand=True)
        scroll_y.pack(side="right", fill="y")
        scroll_x.pack(side="bottom", fill="x")

        botones = tk.Frame(ventana, bg=COLORES["panel"])
        botones.pack(fill="x", padx=18, pady=14)

        accion_principal = "IMPRIMIR / GUARDAR PDF" if on_confirmar is not None else "CERRAR"

        def confirmar():
            if on_confirmar is None:
                ventana.destroy()
                return
            ventana.destroy()
            on_confirmar()

        tk.Button(
            botones, text="CANCELAR", font=("Segoe UI", 9, "bold"), bg=COLORES["tarjeta"],
            fg=COLORES["texto_secundario"], activebackground=COLORES["borde"], activeforeground=COLORES["texto_primario"],
            relief="flat", bd=0, padx=14, pady=9, cursor="hand2", command=ventana.destroy,
        ).pack(side="right", padx=(8, 0))

        tk.Button(
            botones, text=accion_principal, font=FUENTES["boton"], bg=COLORES["acento"], fg="#FFFFFF",
            activebackground=COLORES["acento_hover"], activeforeground="#FFFFFF", relief="flat", bd=0,
            padx=14, pady=9, cursor="hand2", command=confirmar,
        ).pack(side="right")

    def _crear_pdf_reporte(self, ruta: str, titulo: str, encabezados: list[str], filas: list[list[object]]):
        ancho_pagina = 842
        alto_pagina = 595
        margen_x = 34
        y_inicio = 540
        alto_linea = 16
        filas_por_pagina = 27
        anchos = [56, 38, 56, 150, 44, 150, 48, 54, 130]
        if len(encabezados) != len(anchos):
            ancho_util = ancho_pagina - (margen_x * 2)
            anchos = [max(42, ancho_util // max(1, len(encabezados)))] * len(encabezados)
        paginas = max(1, math.ceil(len(filas) / filas_por_pagina))

        def escapar_pdf(texto: object) -> str:
            valor = str(texto).replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            return valor[:42]

        def linea_texto(x: int, y: int, texto: object, tam: int = 8, negrita: bool = False) -> str:
            fuente = "F2" if negrita else "F1"
            return f"BT /{fuente} {tam} Tf {x} {y} Td ({escapar_pdf(texto)}) Tj ET\n"

        base_objetos = [
            b"<< /Type /Catalog /Pages 4 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
            b"<< /Type /Pages /Kids [] /Count 0 >>",
        ]

        todos = base_objetos
        paginas_ids = []
        paginas_objetos = []
        for pagina in range(paginas):
            inicio = pagina * filas_por_pagina
            bloque = filas[inicio : inicio + filas_por_pagina]
            contenido = []
            contenido.append(linea_texto(margen_x, 565, titulo, 14, True))
            contenido.append(linea_texto(margen_x, 548, f"{NOMBRE_SISTEMA} | Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}    Pagina {pagina + 1} de {paginas}", 8))
            x = margen_x
            for idx, encabezado in enumerate(encabezados):
                contenido.append(linea_texto(x, y_inicio - 24, encabezado, 8, True))
                x += anchos[idx]
            y = y_inicio - 42
            for fila in bloque:
                x = margen_x
                for idx, valor in enumerate(fila):
                    limite = 24 if idx in {3, 5} else 18
                    contenido.append(linea_texto(x, y, str(valor)[:limite], 7))
                    x += anchos[idx]
                y -= alto_linea

            stream = "".join(contenido).encode("latin-1", errors="replace")
            contenido_id = 5 + len(paginas_objetos)
            pagina_id = contenido_id + 1
            paginas_ids.append(pagina_id)
            paginas_objetos.append(b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"endstream")
            paginas_objetos.append(
                f"<< /Type /Page /Parent 4 0 R /MediaBox [0 0 {ancho_pagina} {alto_pagina}] "
                f"/Resources << /Font << /F1 2 0 R /F2 3 0 R >> >> /Contents {contenido_id} 0 R >>".encode("ascii")
            )

        todos[3] = f"<< /Type /Pages /Kids [{' '.join(f'{pid} 0 R' for pid in paginas_ids)}] /Count {len(paginas_ids)} >>".encode("ascii")
        todos.extend(paginas_objetos)

        salida = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for idx, obj in enumerate(todos, start=1):
            offsets.append(len(salida))
            salida.extend(f"{idx} 0 obj\n".encode("ascii"))
            salida.extend(obj)
            salida.extend(b"\nendobj\n")

        xref_pos = len(salida)
        salida.extend(f"xref\n0 {len(todos) + 1}\n".encode("ascii"))
        salida.extend(b"0000000000 65535 f \n")
        for offset in offsets[1:]:
            salida.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        salida.extend(
            f"trailer\n<< /Size {len(todos) + 1} /Root 1 0 R >>\nstartxref\n{xref_pos}\n%%EOF".encode("ascii")
        )

        with open(ruta, "wb") as archivo:
            archivo.write(salida)

    def _aviso_temporal(self, titulo: str, mensaje: str, color: str | None = None, duracion_ms: int = 3500):
        aviso = tk.Toplevel(self)
        aviso.title(titulo)
        aviso.configure(bg=COLORES["panel"])
        aviso.resizable(False, False)
        aviso.transient(self)
        aviso.attributes("-topmost", True)

        ancho = 390
        alto = 150
        x = self.winfo_x() + self.winfo_width() - ancho - 28
        y = self.winfo_y() + 72
        aviso.geometry(f"{ancho}x{alto}+{max(x, 0)}+{max(y, 0)}")

        barra = tk.Frame(aviso, bg=color or COLORES["acento"], height=5)
        barra.pack(fill="x")

        cont = tk.Frame(aviso, bg=COLORES["panel"], padx=16, pady=14)
        cont.pack(fill="both", expand=True)

        tk.Label(
            cont,
            text=titulo.upper(),
            font=("Segoe UI", 9, "bold"),
            bg=COLORES["panel"],
            fg=color or COLORES["acento"],
        ).pack(anchor="w")

        tk.Label(
            cont,
            text=mensaje,
            font=("Segoe UI", 9),
            bg=COLORES["panel"],
            fg=COLORES["texto_primario"],
            wraplength=350,
            justify="left",
        ).pack(anchor="w", pady=(8, 0))

        aviso.after(duracion_ms, aviso.destroy)

    def _mostrar_resultado(self, texto: str, color: str):
        self._lbl_resultado.config(text=texto, fg=color)

    def _actualizar_indicador_conexion(self):
        if self._db.esta_conectado():
            self._lbl_conexion.config(text="● BD conectada", fg=COLORES["exito"])
        else:
            self._lbl_conexion.config(text="● BD desconectada", fg=COLORES["advertencia"])

    # ------------------------------------------------------------------
    # Reloj y cierre
    # ------------------------------------------------------------------
    def _tick_reloj(self):
        ahora = datetime.now()
        self._lbl_hora.config(text=ahora.strftime("%H:%M:%S"))
        self._lbl_fecha.config(text=ahora.strftime("%A, %d de %B de %Y").capitalize())
        self.after(1000, self._tick_reloj)

    def _al_cerrar(self):
        self._qr_scan_active = False
        if self._db is not None:
            self._db.cerrar()
        self.destroy()


if __name__ == "__main__":
    app = ControlAsistenciaApp()
    app.mainloop()
