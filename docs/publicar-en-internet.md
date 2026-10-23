# Publicar el cotizador en internet

Se usa lo mismo que el sistema de repuestos: **GitHub** (guarda el código), **Supabase** (base de datos) y
**Render** (la página web). Todo gratis para este uso.

## 1. Subir el código a GitHub
Crear un repositorio **privado** nuevo (por ejemplo `turismo-servinorte`) y subir esta carpeta.

## 2. Base de datos en Supabase
1. Entrar a supabase.com y crear un **proyecto nuevo** (no usar el de repuestos ni el de colaciones).
2. Anotar la contraseña de la base que se elige al crearlo.
3. En *Connect* → *Connection string* → *Transaction pooler*, copiar la dirección (empieza con
   `postgresql://`) y reemplazar `[YOUR-PASSWORD]` por la contraseña.

## 3. Página en Render
1. Entrar a render.com → *New* → *Blueprint* → elegir el repositorio. Render lee `render.yaml`.
2. Completar las variables que pide:
   - `DATABASE_URL`: la dirección de Supabase del paso 2.
   - `DJANGO_SUPERUSER_USERNAME`, `DJANGO_SUPERUSER_PASSWORD`, `DJANGO_SUPERUSER_EMAIL`: el usuario
     administrador para entrar la primera vez.
3. Esperar a que termine (unos minutos). La dirección queda tipo `https://servinorte-turismo.onrender.com`.

## Notas
- En el plan gratis, si nadie entra por un rato la página "se duerme" y la primera vez tarda ~1 minuto en abrir.
- Para agregar otros usuarios: entrar a `/admin/` → Usuarios. Para que puedan cambiar parámetros, darles el
  permiso "Can change parámetros de precio" (o hacerlos superusuarios).
