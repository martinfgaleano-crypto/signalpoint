# Signal Point — guía de trabajo para Claude

Signal Point es un briefing de eventos de mercado y economía en palabras simples. Cada brief dice qué pasó, quién está expuesto, qué mirar después y qué no se sabe, con la fuente a un clic y un grado de solidez. **No es tiempo real. No es asesoría de inversión.**

## Antes de empezar (siempre)
1. Lee el tablero `~/LeadLensVault/SignalPoint/ESTADO.md` y la ruta `~/LeadLensVault/SignalPoint/RUTA.md`. Di en una línea en qué tarea (S1, S2…) trabajas.
2. Una tarea = una sesión = un PR. Lo que aparezca de más se anota en el tablero.
3. Al cerrar: actualiza la ruta y el tablero, y anota lo no verificado.

## Cómo está armado
- **Sitio:** HTML/JS estático, sin paso de build. GitHub Pages publica la rama `main` desde la raíz: **todo lo que entra a `main` queda público al instante.**
- `index.html` (página principal, datos de la edición embebidos), `nuevo/` (portada alterna), `glosario/`, `herramientas/` (calculadoras), `aprende/` (cursos).
- **Robots (GitHub Actions):**
  - `.github/workflows/news-drafts.yml` — lunes a viernes: `tools/news_drafts.py` redacta briefs con IA, revisa cifras, pasa un editor (otro modelo) y publica en la rama `drafts` (`live/briefs-live.json`).
  - `.github/workflows/fetch-history.yml` — datos de mercado y estudios de eventos a la rama `data`.
  - Las ramas `data` y `drafts` las escribe el robot con push forzado. No trabajes sobre ellas.
- **Backend:** Supabase (inicio de sesión por código, `profiles`, `portfolios`, `digest_subs`, `premium_content`; funciones `ask` y `digest` en `supabase/functions/`; SQL en `backend/sql/`).
- **Comandos:** `python3 tools/news_drafts.py <dir>` (necesita `ANTHROPIC_API_KEY`); `node tools/quality.cjs` para la revisión de calidad.

## Reglas que no se rompen
- **Nunca directo a `main`.** Rama → PR → revisar → merge. `main` es producción.
- **Verdad primero:** cada cifra con su fuente y fecha; lo que no se sabe se dice; nada de pronósticos ni recomendaciones de compra o venta. Un error publicado se corrige con retractación visible, no en silencio.
- **Secretos:** solo en los secretos de GitHub Actions o de Supabase. Nunca en el código ni en un commit; este repositorio es público.
- **Datos de personas** (correos, portafolios): no se copian, no se imprimen, no salen de Supabase.
- **Gasto:** cualquier cambio que aumente las llamadas a modelos de IA lleva su estimación de costo en el PR.
- No se cambian precios, no se activa el cobro y no se envían correos a lectores sin que el fundador lo pida.
- Las migraciones de base de datos las aplica el fundador.

## Con el fundador
No es técnico. Español, lenguaje simple, resultado primero, hechos con evidencia (PR, archivo, cifra) y "no verificado" cuando aplique.
