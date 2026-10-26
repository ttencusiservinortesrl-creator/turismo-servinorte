# Conectar el diagrama de unidades (Drive)

La app lee y escribe **PL - DIAGRAMA DE VEHICULOS 2026.xlsx** con una "cuenta de servicio" de Google:
un usuario técnico que solo puede abrir los archivos que se le compartan. Se configura una sola vez.

## 1. Crear la cuenta de servicio (Google Cloud)
1. Entrar a https://console.cloud.google.com con la cuenta de Google de la empresa.
2. Arriba, en el selector de proyectos: **Nuevo proyecto** → nombre `servinorte-turismo` → Crear.
3. Menú ☰ → **APIs y servicios** → **Biblioteca** → buscar **Google Drive API** → **Habilitar**.
4. Menú ☰ → **IAM y administración** → **Cuentas de servicio** → **Crear cuenta de servicio**.
   - Nombre: `cotizador`. Tocar **Crear y continuar** y después **Listo** (no hace falta darle roles).
5. Entrar a la cuenta creada → pestaña **Claves** → **Agregar clave** → **Crear clave nueva** → **JSON** → Crear.
   Se descarga un archivo `.json`. **Es una contraseña: no mandarlo por mail ni chat, ni subirlo a GitHub.**
6. Copiar el mail de la cuenta (termina en `@servinorte-turismo.iam.gserviceaccount.com`).

## 2. Compartir el diagrama con esa cuenta
En Drive, sobre **PL - DIAGRAMA DE VEHICULOS 2026.xlsx** → Compartir → pegar el mail de la cuenta → **Editor**
→ Enviar (destildar "Notificar"). Si no aparece la opción, lo tiene que compartir el dueño (Sergio García).

## 3. Cargar la clave en Render
Render → servicio `servinorte-turismo` → **Environment** → **Add Environment Variable**:
- Key: `GOOGLE_SERVICE_ACCOUNT_JSON`
- Value: abrir el `.json` con el Bloc de notas, copiar **todo** el contenido y pegarlo.
Guardar (**Save Changes**). Render reinicia solo.

## 4. Probar
En la app → **Unidades**: tiene que aparecer la grilla con las unidades de turismo.

## Cada año
Cuando arranque el diagrama del año nuevo (2027): compartirlo también con la cuenta de servicio y cambiar
el **Código del diagrama en Drive** en Parámetros (es lo que va después de `/d/` en el link del archivo).

## Cómo escribe la app en el diagrama
- Solo en ventas **aceptadas** y solo cuando alguien toca **Anotar en el diagrama** (antes pregunta).
- Baja la última versión, verifica que la unidad siga libre esos días, escribe 3 renglones (cliente /
  recorrido / COT y días) combinando las celdas de los días del viaje, y sube el archivo. Si alguien modificó
  la planilla en ese momento, no sube nada y pide reintentar.
- No usa librerías que reescriben el Excel entero: cambia solo esas celdas (no se pierden comentarios ni formatos).
- Drive guarda el historial de versiones: si algo sale mal, Archivo → Historial de versiones.
- La app no borra del diagrama: si se cancela un viaje, se borra a mano en el Excel.
