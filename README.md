# Island — Sistema de Control de Asistencia (versión web con NiceGUI + MySQL)

Esta es la migración de la app de escritorio (Tkinter + SQLite) a una
**interfaz web** que puedes compartir con un link, conectada a **MySQL**
(para administrarla con phpMyAdmin) y con avisos por **correo y WhatsApp**
(WhatsApp vía CallMeBot).

**La lógica y las reglas de negocio no cambiaron**: horarios, cálculo de
alertas (entrada/salida temprana o tardía), permisos, roles de usuario,
etc. siguen siendo exactamente las mismas que ya tenías en `repository.py`.
Solo cambiaron:
1. La interfaz (de Tkinter/escritorio a NiceGUI/web, para poder compartirla).
2. El motor de base de datos (de SQLite a MySQL, para usar phpMyAdmin).
3. Se agregó el envío de WhatsApp (CallMeBot) además del correo que ya existía.

## Archivos nuevos / modificados

| Archivo | Qué es |
|---|---|
| `main.py` | **Nuevo.** Interfaz web con NiceGUI (reemplaza `app.py`). |
| `db_connection.py` | Reescrito para conectarse a MySQL en vez de SQLite. Misma API pública. |
| `repository.py` | Igual que antes, solo se agregó el campo `telefono_encargado` (necesario para WhatsApp). |
| `schema_mysql.sql` | **Nuevo.** Igual que `schema.sql` pero en sintaxis MySQL, para importar en phpMyAdmin. |
| `config_notificaciones.py` | **Nuevo.** Lee/guarda `correo_island.env` (ahora con datos de MySQL y CallMeBot además del correo). |
| `correo_notificador.py` | Misma lógica de envío SMTP que tenía `app.py`, movida a su propio archivo. |
| `whatsapp_notificador.py` | **Nuevo.** Envío de WhatsApp usando CallMeBot. |
| `schema.sql`, `app.py` | Se dejan sin usar, solo como referencia de la versión anterior. |

## 1. Base de datos (MySQL / phpMyAdmin)

1. Crea una base de datos vacía, por ejemplo `control_asistencia`, desde phpMyAdmin.
2. Ve a la pestaña **Importar** de esa base y sube el archivo `schema_mysql.sql`
   (crea las tablas, vistas y los usuarios/estudiantes de ejemplo).
   - Si prefieres que la app la cree sola, no es necesario importar nada:
     `main.py` detecta si la tabla `estudiantes` no existe y crea el esquema
     automáticamente la primera vez que se conecta.
3. Anota host, usuario, contraseña, puerto y nombre de la base (te los da tu
   proveedor de hosting o tu XAMPP/WAMP/phpMyAdmin local).

## 2. Configuración (`correo_island.env`)

Ya te dejé un `correo_island.env` con tu configuración de correo anterior
conservada. Solo edítalo (o hazlo desde la pestaña **Configuración** dentro
de la app, como ADMIN) para completar:

```
ASISTENCIA_DB_HOST=...
ASISTENCIA_DB_PORT=3306
ASISTENCIA_DB_USER=...
ASISTENCIA_DB_PASSWORD=...
ASISTENCIA_DB_NAME=control_asistencia

ASISTENCIA_WHATSAPP_APIKEY=...
```

Puedes ver todos los campos disponibles en `correo_island_env.example`.

### WhatsApp con CallMeBot (gratis)

1. En el WhatsApp del **encargado** que recibirá los avisos, agregar el número
   de CallMeBot como contacto: **+34 644 66 34 43**.
2. Enviarle el mensaje exacto: `I allow callmebot to send me messages`.
3. CallMeBot responde con una **apikey** personal. Esa apikey se pone en
   `ASISTENCIA_WHATSAPP_APIKEY` (o en la pestaña Configuración de la app).
4. En la ficha de cada estudiante, registra el número de WhatsApp del
   encargado en el campo **"WhatsApp del encargado"** (con código de país,
   ej. `+50370000000`).

> Nota: CallMeBot con la apikey gratuita solo puede enviar mensajes al mismo
> número que autorizó esa apikey. Si necesitas notificar a muchos encargados
> distintos, cada uno debe generar su propia apikey (CallMeBot lo permite
> gratis); si en el futuro quieres usar una sola apikey para todos, se
> necesitaría contratar el plan de WhatsApp Business API de CallMeBot.

## 3. Instalar y ejecutar

```bash
pip install -r requirements.txt
python main.py
```

Al iniciar, verás en la consola algo como:

```
NiceGUI ready to go on http://localhost:8080, and http://<tu-ip-en-la-red>:8080
```

- Abre `http://localhost:8080` en tu propia máquina, o
- Comparte `http://<tu-ip-en-la-red>:8080` con quien esté en la misma red
  (colegio/oficina), o
- Si quieres compartirlo por internet (fuera de tu red), tienes 3 opciones
  comunes:
  1. **Túnel rápido** (para pruebas): `ngrok http 8080` te da un link público
     temporal.
  2. **Desplegarlo en un servidor/VPS** (o en un hosting con Python, ej.
     Railway, Render, PythonAnywhere) y dejarlo corriendo ahí con su propio
     dominio/link permanente.
  3. **Reverse proxy con dominio propio** (Nginx/Caddy) apuntando al puerto 8080.

Usuarios por defecto (igual que antes):
- `admin` / `admin123` (rol ADMIN)
- `profesor` / `profesor123` (rol PROFESOR)

**Recuerda cambiar `storage_secret` dentro de `main.py`** (línea final,
`ui.run(...)`) por una clave propia antes de compartir el link públicamente.

## 4. Qué cambia para quien usaba la app de escritorio

- El lector de QR con cámara USB de escritorio (OpenCV) se reemplazó por un
  lector de QR que usa la **cámara del navegador** (funciona en celular,
  tablet o laptop con cámara, botón "Iniciar cámara" en la pestaña
  "Marcar asistencia"). También puedes seguir digitando el código a mano,
  igual que antes.
- Los reportes en PDF hechos a mano se reemplazaron por exportación a **CSV**
  desde la pestaña "Registros" (se abre perfecto en Excel/Google Sheets).
- Todo lo demás (reglas de horario, alertas, permisos, roles, correo) es
  igual que en la versión de escritorio.
