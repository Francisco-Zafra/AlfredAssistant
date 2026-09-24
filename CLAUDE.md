# CLAUDE.md

Secretario personal por Telegram montado sobre n8n: notas de voz → Whisper → Gemini
clasifica → markdown en `vault/` + índice en Qdrant, con un AI Agent para preguntas y
avisos programados. El README es la documentación completa; esto es lo que hace falta
para trabajar aquí sin romper nada.

Todo, código, comentarios, prompts y commits, en **español**. Los comentarios
explican el *por qué*, no el qué: sigue el tono de los que ya hay.

## Dónde vive cada cosa

- **La lógica está en n8n, no en el repo.** `workflows/*.json` es una copia versionada.
  La fuente de verdad es la instancia (`http://192.168.1.212:5678`).
- `prompts/` sí manda desde el repo: se monta en n8n como `/prompts` (solo lectura) y
  los workflows lo leen en cada ejecución. Editar un prompt no requiere tocar el JSON.
- `vault/` son las notas reales del usuario. **No leer, no commitear, no citar** salvo
  que lo pida.
- `docker-compose.yml` levanta n8n, whisper, qdrant y ollama. Solo n8n publica puerto.

## Control de versiones de los workflows

Se editan en n8n (interfaz o MCP) y se bajan al repo con el script:

```bash
python scripts/exportar-workflows.py   # lee N8N_API_URL / N8N_API_KEY del .env
git diff workflows/
```

- Si vas a modificar un workflow por MCP, **exporta y commitea antes**, para tener un
  punto al que volver y un diff limpio de lo que has cambiado.
- El export normaliza: quita ids, credenciales, `staticData` y `availableInMCP`;
  ordena nodos, conexiones y parámetros; y vuelve a poner `PEGA_AQUI_EL_ID_DE_...` en
  los Execute Workflow. Es idempotente: si no has cambiado nada en n8n, no hay diff.
- Aborta sin escribir si encuentra pinData o algo con pinta de secreto. No lo
  esquives: arregla el workflow en n8n.
- Un export hecho a mano desde la interfaz se pasa por `scripts/limpiar-workflow.py`,
  que deja el mismo formato.
- `01-libreta.json` ya no existe en n8n (fase 1, sustituida por 02a/02b). Se conserva.

## MCP de n8n

`.mcp.json` apunta al MCP oficial de la instancia y lleva el token en claro: está en
`.gitignore`, la plantilla es `.mcp.json.example`. Ojo:

- Solo ve los workflows con el acceso MCP activado (ahora mismo 02a y 02b). El script
  de export usa la API pública y los ve todos.
- **Cambiar un workflow por MCP cambia el bot real, en producción.** No actives,
  publiques, ejecutes ni borres workflows sin que el usuario lo pida. `02a` está en
  bucle de long polling permanente: no lo ejecutes a mano.
- Sigue los pasos que da el propio servidor (SDK reference, `get_node_types`, validar)
  en vez de adivinar parámetros.

## Restricciones que mandan

- **3 GB de RAM** para todo el stack, con ~1 GB de holgura. Nada de modelos más
  grandes ni servicios nuevos sin mirar la tabla "Cuánto cabe en 3 GB" del README.
- Nada expuesto a internet: sin webhooks, sin puertos nuevos, sin túneles.
- Tier gratuito de Gemini con tope **diario de peticiones**: no añadas llamadas al
  modelo por mensaje sin necesidad.
- Secretos solo en `.env` (leídos con `$env` en n8n) o en credenciales de n8n.
  Nunca en un nodo, un prompt o un fichero versionado.

## Antes de tocar un workflow

La sección "Trampas conocidas" del README es obligatoria: recoge fallos que ya
costaron horas (HTTP Request que pisa el json del item, `binaryMode: separate` y
`filesystem-v2`, Extract From File que tira el `fileName`, `staticData` que solo se
guarda en producción, un único pendiente compartido...). Si descubres una trampa
nueva, añádela ahí con el mismo estilo.

Los Execute Workflow llevan ids que n8n genera al importar; en el repo van como
`PEGA_AQUI_EL_ID_DE_<prefijo>_<NOMBRE>`. Son tres: dos en `02a` y *Consultar la
agenda* en `02b`.

`02b` se llama a sí mismo con `latido: true` para mantener el "escribiendo…" mientras
el agente piensa (sección "El latido" del README). Si ves una ejecución de 02b que
solo espera y consulta a n8n, es eso. No es un bucle roto.
