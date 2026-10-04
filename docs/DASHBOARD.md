# PLAN — Alfred Dashboard

## 0. Objetivo

Construir una **interfaz web visual para Alfred** sin sustituir ni duplicar el sistema actual.

Alfred ya funciona como secretario personal por Telegram. El dashboard debe convertirse en una **segunda interfaz del mismo asistente**:

- **Telegram** seguirá siendo la interfaz rápida y conversacional: texto, voz, avisos y respuestas.
- **Alfred Dashboard** será la interfaz visual: ver agenda, tareas y notas; buscar; consultar a Alfred; y, más adelante, organizar información y añadir módulos personales.
- **n8n** seguirá siendo el orquestador y la capa lógica de Alfred.
- **`vault/` seguirá siendo la fuente de verdad** para notas, tareas y eventos.
- **Qdrant seguirá siendo un índice derivado y reconstruible**, no una base de datos primaria.
- **Gemini seguirá siendo el modelo principal** y OpenRouter seguirá siendo el fallback donde ya existe.
- No introducir una base de datos nueva para duplicar información que ya vive en el vault.

El resultado esperado no es un dashboard genérico de métricas, sino una **aplicación web de Alfred**.

---

# 1. Antes de tocar nada

## 1.1. Leer primero

Antes de implementar cambios, leer completos:

1. `CLAUDE.md`
2. `README.md`
3. `docker-compose.yml`
4. `prompts/02-clasificar.md`
5. `prompts/03-agente.md`
6. `workflows/02a-escucha.json`
7. `workflows/02b-secretario.json`
8. `workflows/03a-agenda.json`
9. `workflows/03b-reindexar.json`
10. `workflows/04a-avisos.json`
11. `workflows/04b-resumen.json`

`workflows/01-libreta.json` es histórico y no debe usarse como base para nuevas funciones.

## 1.2. Reglas que no deben romperse

Mantener estas decisiones del proyecto salvo que una fase de este plan indique expresamente lo contrario:

- Todo el código, comentarios, prompts, documentación y commits en español.
- El vault es la fuente de verdad.
- Qdrant es solo un índice derivado.
- No guardar secretos en código, JSON versionado, prompts ni frontend.
- No leer ni versionar el contenido real de `vault/` salvo petición expresa del usuario.
- No ejecutar manualmente `02a - Escucha`.
- No modificar workflows en producción sin exportar antes el estado actual y tener un punto de rollback.
- No añadir llamadas a Gemini innecesarias: existe un límite diario.
- Mantener el consumo de RAM bajo control: la máquina actual tiene 3 GB.
- No cambiar el modelo de embeddings sin reindexar Qdrant.
- No asumir que `item.binary.data.data` contiene base64: respetar el patrón existente `Read/Write Files -> Extract From File`.
- Recordar que `Extract From File` pierde `fileName`; si hay que escribir de vuelta, recuperar el nombre del nodo de lectura y emparejar por posición.
- Un nodo HTTP Request puede reemplazar el JSON del item: no depender del item actual después de una petición si los datos originales se necesitan más adelante.

## 1.3. Cambio de alcance deliberado

El proyecto actual dice:

- sin webhooks;
- sin puertos nuevos;
- nada expuesto a Internet.

Un dashboard web real necesita una interfaz HTTP accesible desde el navegador. Por tanto, este proyecto introduce **una excepción controlada**:

- el dashboard será accesible **solo desde LAN/VPN**;
- no se hará port-forwarding en el router;
- no se expondrá públicamente a Internet;
- cualquier API usada por el dashboard deberá quedar igualmente limitada a LAN/VPN;
- no abrir puertos de Qdrant, Ollama o Whisper;
- documentar el cambio en `CLAUDE.md` y `README.md` solo cuando se implemente la integración real.

No hacer este cambio durante la fase puramente visual/mock.

---

# 2. Arquitectura actual que debe preservarse

La arquitectura real del proyecto es, conceptualmente:

```text
Telegram
   │
   ▼
02a - Escucha
   │
   ├─ long polling getUpdates
   ├─ filtra por TELEGRAM_ALLOWED_USER_ID
   └─ normaliza texto / callback
   │
   ▼
02b - Secretario
   │
   ├─ texto ────────────────────────────────┐
   │                                       │
   ├─ voz -> Telegram getFile -> Whisper ──┤
   │                                       ▼
   │                               preparar contexto
   │                                       │
   │                                       ▼
   │                               clasificar con Gemini
   │                              (OpenRouter fallback)
   │                                       │
   ├───────────────┬──────────────┬────────┴─────────┬─────────────┐
   ▼               ▼              ▼                  ▼             ▼
 nota            tarea          evento            pregunta       borrar
   │               │              │                  │             │
   └──────┬────────┘          confirmación           │        candidatos
          │                  por botones             │        + botones
          ▼                       │                  │             │
      /vault/*.md                 ▼                  ▼             ▼
          │                   /vault/*.md        AI Agent      cancelación
          │                       │                  │             │
          └──────────┬────────────┘                  │             │
                     ▼                               │             │
                  Qdrant <──── embeddings Ollama ───┘             │
                                                     │             │
                                              agenda / notas /     │
                                              Memos (lectura)      │
                                                     │             │
                                                     ▼             │
                                                  Telegram <───────┘
```

Procesos paralelos:

```text
04a - Avisos
cada 15 min -> vault -> eventos próximos -> Telegram -> avisado:true

04b - Resumen diario
08:00 -> vault -> hoy + próximos 7 días -> Telegram

03b - Reindexar
manual -> borra colección Qdrant -> lee vault -> recrea índice
```

El dashboard debe colocarse **encima** de esta arquitectura, no sustituirla.

---

# 3. Principio de diseño

## 3.1. Alfred es el producto; el dashboard es una interfaz

No crear un “Life OS” independiente.

Nombre de trabajo del producto:

**Alfred**

Nombre técnico de esta ampliación:

**Alfred Dashboard**

La aplicación debe dar la sensación de que Telegram y la web son dos ventanas al mismo asistente.

## 3.2. Responsabilidad de cada interfaz

### Telegram

Optimizado para:

- dictar notas rápidamente;
- mandar mensajes escritos;
- preguntar algo a Alfred;
- recibir avisos;
- recibir resumen diario;
- confirmar eventos;
- confirmar cancelaciones;
- uso móvil con mínima fricción.

### Dashboard

Optimizado para:

- ver información de un vistazo;
- navegar por agenda;
- navegar y filtrar notas;
- ver tareas;
- hacer búsquedas;
- conversar con Alfred desde una interfaz grande;
- revisar y organizar información;
- en fases posteriores, proyectos, fitness, homelab, pádel, finanzas, etc.

---

# 4. Alcance del MVP

El MVP debe tener solo estas áreas:

1. **Inicio**
2. **Agenda**
3. **Notas y tareas**
4. **Buscar**
5. **Alfred**
6. **Ajustes/estado**, muy básico

No implementar todavía:

- Fitness
- Finanzas
- Home Assistant
- Homelab avanzado
- Pádel
- Trading
- Proyectos complejos
- Hábitos
- Integraciones bancarias
- autenticación multiusuario
- sincronización cloud
- una nueva base de datos

Esos módulos pueden aparecer visualmente como ideas futuras, pero no deben formar parte funcional del MVP.

---

# 5. Diseño visual

## 5.1. Estilo

Diseño de escritorio moderno, sobrio y denso sin parecer un panel empresarial genérico.

Referencias conceptuales:

- Linear: jerarquía, densidad, navegación lateral.
- Raycast: rapidez y acciones.
- Notion: lectura cómoda de contenido.
- Apple: espacios, tipografía y limpieza.

No copiar ninguna interfaz literalmente.

## 5.2. Tema

Primera versión:

- dark mode como tema principal;
- posibilidad de preparar variables para light mode, pero no dedicar tiempo al selector si retrasa el MVP;
- diseño responsive, usable en escritorio y tablet;
- móvil funcional, aunque Telegram seguirá siendo la interfaz móvil preferida.

## 5.3. Layout principal

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Alfred                                               estado / hora   │
├────────────────┬─────────────────────────────────────────────────────┤
│                │                                                     │
│  Inicio        │                  CONTENIDO                          │
│  Agenda        │                                                     │
│  Notas         │                                                     │
│  Tareas        │                                                     │
│  Buscar        │                                                     │
│                │                                                     │
│  Alfred        │                                                     │
│                │                                                     │
│  ───────────   │                                                     │
│  Sistema       │                                                     │
│                │                                                     │
└────────────────┴─────────────────────────────────────────────────────┘
```

Barra lateral fija en escritorio.

En tablet/móvil puede convertirse en drawer o navegación inferior.

---

# 6. Pantallas del MVP

## 6.1. Inicio

Objetivo: responder en menos de cinco segundos a:

> “¿Qué tengo hoy y qué está pasando en Alfred?”

Componentes:

### Cabecera

- saludo según hora;
- fecha completa;
- estado de Alfred (`Online`, `Degradado`, `Sin conexión`) si existe endpoint de salud;
- caja rápida “Preguntar a Alfred”.

### Hoy

Mostrar eventos del día ordenados por hora.

Ejemplo:

```text
HOY
18:30  Dentista
21:00  Gimnasio
```

Si no hay eventos:

```text
Hoy no tienes nada apuntado.
```

### Próximos eventos

Mostrar entre 3 y 6 próximos eventos.

### Tareas pendientes

Mostrar tareas no canceladas.

En el MVP no inventar estados que el vault no tiene. Si las tareas actuales no tienen `completada`, mostrarlas como “tareas registradas” y no como checklist real hasta que se diseñe ese metadato.

### Notas recientes

Últimas notas no canceladas por campo `creado`.

### Actividad de Alfred

Inicialmente puede mostrar datos simples y reales, por ejemplo:

- número de notas activas;
- número de eventos próximos;
- última nota creada;
- salud de Qdrant / n8n si es barato obtenerla.

No convertirlo en un dashboard de métricas arbitrarias.

---

## 6.2. Agenda

Vista principal de eventos del vault.

Primera versión:

- vista lista agrupada por día;
- selector de rango:
  - Hoy
  - 7 días
  - 30 días
  - 60 días
- eventos pasados recientes opcionales;
- eventos cancelados ocultos por defecto;
- búsqueda por texto.

Cada evento muestra:

- título;
- fecha;
- hora;
- tags;
- origen (`voz` / `texto`) solo en detalle, no como ruido visual en la lista;
- estado avisado si resulta útil.

Detalle de evento:

- título;
- cuerpo limpio;
- fecha/hora;
- tags;
- fecha de creación;
- origen;
- transcripción cruda, colapsada y solo si existe;
- estado cancelado, si procede.

No implementar un calendario mensual complejo en el primer corte. Primero conseguir una lista excelente y fiable.

---

## 6.3. Notas

Vista para explorar el vault.

Filtros:

- todas;
- notas;
- tareas;
- eventos;
- tags;
- fecha de creación;
- activas / canceladas.

Cada tarjeta/fila:

- icono por tipo;
- título;
- extracto corto del cuerpo;
- tags;
- fecha de creación;
- `cuando` si existe.

Detalle:

- mostrar el Markdown renderizado de forma segura;
- mostrar metadatos de frontmatter de forma legible;
- transcripción cruda colapsable;
- no ejecutar HTML arbitrario del Markdown.

---

## 6.4. Tareas

En la arquitectura actual una tarea es una nota con `tipo: tarea`.

Primera versión:

- lista todas las tareas activas;
- filtros por tags y antigüedad;
- búsqueda;
- acceso al detalle.

IMPORTANTE:

No añadir todavía un sistema falso de tareas completadas si el modelo actual no lo soporta.

Una fase posterior podrá añadir al frontmatter:

```yaml
completada: true
completada_el: 2026-10-04T19:30:00
```

pero eso requiere modificar:

- clasificador/agente si Alfred va a marcarlas por conversación;
- API del dashboard;
- búsquedas;
- resumen diario si se desea;
- reindexado si el contenido indexado cambia.

No hacerlo silenciosamente dentro del MVP.

---

## 6.5. Buscar

Debe haber dos tipos de búsqueda claramente diferenciados.

### A. Búsqueda estructurada/local

Para navegar visualmente por el vault:

- título;
- cuerpo;
- tags;
- tipo;
- fechas.

Debe ser barata y no gastar Gemini.

### B. Preguntar a Alfred

Para preguntas semánticas o conversacionales:

> “¿Qué dije sobre el seguro del coche?”

> “¿Cuándo era lo del dentista?”

Aquí sí se usa el flujo del agente existente.

No usar Gemini para cada pulsación del buscador visual.

---

## 6.6. Alfred

Pantalla de chat con el asistente.

Primera versión:

- historial de la sesión actual del navegador;
- campo de texto;
- envío con Enter;
- indicador de procesamiento;
- respuestas en texto plano con soporte básico de saltos de línea;
- posibilidad futura de voz, pero no necesaria en MVP.

La lógica de respuesta debe reutilizar el núcleo de Alfred.

No duplicar en frontend la clasificación ni prompts.

Idealmente el frontend manda una entrada neutral:

```json
{
  "texto": "¿Qué tengo mañana?",
  "origen": "dashboard"
}
```

Y n8n decide qué hacer.

### Diferencia respecto a Telegram

El dashboard no necesita enviar mensajes de “escribiendo…” por Telegram ni lanzar el latido visual de Telegram.

El navegador ya puede mantener un spinner/estado `Procesando…` mientras espera.

Por ello, al reutilizar `02b`, separar la lógica de canal de la lógica de negocio antes de reutilizar ciegamente el flujo completo.

---

# 7. Arquitectura objetivo

```text
                              ┌──────────────────────┐
                              │       Gemini         │
                              └──────────┬───────────┘
                                         │
                                         ▼
┌──────────────┐             ┌──────────────────────┐
│   Telegram   │────────────▶│      Alfred Core     │
└──────────────┘             │         n8n          │
                             └──────────┬───────────┘
                                        │
                  ┌─────────────────────┼─────────────────────┐
                  ▼                     ▼                     ▼
              /vault/*.md            Qdrant                 Memos
           fuente de verdad          índice             solo lectura
                  ▲
                  │
                             ┌──────────────────────┐
                             │   API Dashboard n8n  │
                             └──────────┬───────────┘
                                        │
                                        ▼
                             ┌──────────────────────┐
                             │   Alfred Dashboard   │
                             │ React + TypeScript   │
                             └──────────────────────┘
```

---

# 8. Frontend

## 8.1. Stack propuesto

Crear una carpeta nueva:

```text
dashboard/
```

Stack:

- React
- TypeScript
- Vite
- React Router
- CSS moderno

Preferencia: evitar dependencias grandes si no aportan valor.

Para iconos se puede usar una librería pequeña y estándar.

No introducir un framework full-stack como Next.js en el MVP: no necesitamos SSR ni backend Node y aumentaría complejidad y consumo.

## 8.2. Estructura sugerida

```text
dashboard/
├── src/
│   ├── api/
│   │   ├── client.ts
│   │   ├── dashboard.ts
│   │   ├── agenda.ts
│   │   ├── notas.ts
│   │   └── alfred.ts
│   ├── components/
│   │   ├── layout/
│   │   ├── notes/
│   │   ├── agenda/
│   │   └── common/
│   ├── pages/
│   │   ├── Home.tsx
│   │   ├── Agenda.tsx
│   │   ├── Notas.tsx
│   │   ├── Tareas.tsx
│   │   ├── Buscar.tsx
│   │   ├── Alfred.tsx
│   │   └── Sistema.tsx
│   ├── types/
│   │   └── alfred.ts
│   ├── mocks/
│   │   └── ...
│   ├── App.tsx
│   └── main.tsx
├── public/
├── .env.example
├── package.json
└── vite.config.ts
```

## 8.3. Configuración

El frontend solo podrá contener configuración pública, por ejemplo:

```env
VITE_ALFRED_API_BASE_URL=http://192.168.x.x:5678/...
```

Nunca:

- token de Telegram;
- API key de Gemini;
- token de Memos;
- N8N API key;
- N8N encryption key.

---

# 9. Modelo de datos del frontend

Crear tipos explícitos.

Ejemplo conceptual:

```ts
export type TipoNota = 'nota' | 'tarea' | 'evento';

export interface NotaAlfred {
  id: string;
  fichero: string;
  tipo: TipoNota;
  titulo: string;
  cuerpo: string;
  creado: string | null;
  cuando: string | null;
  avisado: boolean;
  cancelado: boolean;
  canceladoEl: string | null;
  origen: 'voz' | 'texto' | 'dashboard' | string | null;
  tags: string[];
  transcripcion: string | null;
}
```

No usar el nombre del fichero como único identificador lógico si en el futuro existe riesgo de renombrado. Para el MVP puede ser el identificador de transporte porque el sistema actual ya se apoya en él, pero encapsularlo detrás de `id`.

Respuesta de dashboard:

```ts
export interface ResumenDashboard {
  ahora: string;
  hoy: NotaAlfred[];
  proximos: NotaAlfred[];
  tareas: NotaAlfred[];
  notasRecientes: NotaAlfred[];
  estadisticas: {
    notasActivas: number;
    tareasActivas: number;
    eventosProximos: number;
  };
}
```

---

# 10. API de Alfred para el dashboard

## 10.1. Regla principal

No permitir que el frontend lea `/vault` directamente.

El navegador debe hablar con una capa API de n8n.

## 10.2. Endpoints mínimos

Diseñar conceptualmente:

```text
GET  /alfred/api/v1/dashboard
GET  /alfred/api/v1/notas
GET  /alfred/api/v1/notas/:id
GET  /alfred/api/v1/agenda
POST /alfred/api/v1/mensaje
GET  /alfred/api/v1/health
```

Los paths exactos dependerán de cómo se implementen los Webhook nodes de n8n.

### `GET dashboard`

Devuelve todo lo necesario para Home en una sola llamada para evitar hacer seis requests.

### `GET notas`

Query params posibles:

```text
?tipo=nota
?tipo=tarea
?tipo=evento
?tag=casa
?q=seguro
?canceladas=false
?limit=50
?offset=0
```

La búsqueda `q` de este endpoint debe ser local/simple, no semántica con Gemini.

### `GET notas/:id`

Devuelve nota completa incluyendo transcripción cruda si existe.

### `GET agenda`

Parámetros:

```text
?desde=2026-10-04
?hasta=2026-12-04
?canceladas=false
```

Debe leer el mismo vault que `03a - Agenda`.

### `POST mensaje`

Entrada:

```json
{
  "texto": "¿Qué tengo mañana?"
}
```

Salida:

```json
{
  "tipo": "respuesta",
  "texto": "Mañana tienes..."
}
```

En fases posteriores puede admitir también una acción de creación.

### `GET health`

Debe ser barato.

Respuesta conceptual:

```json
{
  "status": "ok",
  "services": {
    "n8n": "ok",
    "qdrant": "ok"
  }
}
```

No consultar Gemini para health.

---

# 11. Cómo reutilizar n8n sin duplicar lógica

## 11.1. No copiar `02b` entero

`02b - Secretario` mezcla actualmente varias responsabilidades:

- lógica de negocio;
- Telegram;
- descarga de voz;
- transcripción;
- botones;
- latido de “escribiendo…”;
- clasificación;
- guardado;
- consultas;
- respuesta.

Copiarlo para el dashboard generaría divergencia.

## 11.2. Refactor deseado, pero no en el primer commit

Después de tener el frontend mock y definir contratos API, extraer de forma incremental subworkflows reutilizables.

Posible estructura futura:

```text
02a - Escucha Telegram
02b - Secretario Telegram

05a - API Dashboard
05b - API Notas
05c - API Agenda
05d - API Mensaje

06a - Core - Leer vault
06b - Core - Procesar mensaje
06c - Core - Buscar notas
06d - Core - Guardar nota
```

No es obligatorio usar exactamente esos números/nombres. Mantener la convención existente.

## 11.3. Primera reutilización sencilla

No refactorizar `03a - Agenda` si basta con reutilizar su algoritmo en un nuevo workflow de API inicialmente.

Pero si se copia lógica, marcar explícitamente la deuda técnica y luego moverla a un subworkflow común.

Prioridad:

1. no romper Alfred;
2. validar el dashboard;
3. reducir duplicación cuando el contrato esté claro.

---

# 12. Lectura del vault desde n8n

Crear una utilidad/patrón común para parsear Markdown.

Debe respetar el formato actual:

```markdown
---
tipo: evento
titulo: "Dentista el miércoles"
creado: 2026-09-21T18:40:00
cuando: 2026-09-23T18:00:00
avisado: false
origen: voz
tags: [dentista, salud]
---

Texto limpio...

<!-- transcripción cruda -->
> texto original...
```

El parser debe devolver por separado:

- frontmatter;
- cuerpo limpio;
- transcripción cruda;
- nombre de fichero.

No introducir por ahora una dependencia YAML externa dentro de los nodos Code si el parser plano actual cubre el formato generado por Alfred.

Centralizarlo en cuanto haya más de dos workflows API que lo necesiten.

---

# 13. Escritura desde el dashboard

## Fase MVP

El dashboard será primero **read-heavy**.

Permitido en la primera integración:

- consultar;
- buscar;
- preguntar a Alfred.

No permitir todavía edición libre de Markdown desde la web.

Razón:

- editar archivos obliga a mantener consistencia con Qdrant;
- cancelar tiene lógica de borrado blando;
- los eventos usan confirmación;
- cualquier cambio manual puede quedar sin indexar.

## Segunda iteración

Añadir creación a través de Alfred:

```text
Dashboard -> POST mensaje -> Core Alfred -> clasificación -> guardado -> Qdrant
```

Es decir, el usuario puede escribir:

> “Mañana a las seis tengo dentista”

pero no es el frontend quien fabrica directamente el Markdown.

Alfred sigue decidiendo:

- tipo;
- título;
- fecha;
- tags;
- contenido limpio.

## Tercera iteración

Edición estructurada manual de una nota.

Solo cuando exista un flujo transaccional claro:

1. leer nota;
2. modificar;
3. escribir;
4. eliminar/reemplazar punto anterior en Qdrant o reindexar esa nota;
5. confirmar éxito.

---

# 14. Seguridad

## 14.1. Red

El dashboard es personal y de un solo usuario.

No diseñar inicialmente un sistema multiusuario.

Acceso:

- LAN;
- VPN/Tailscale si ya existe en la infraestructura del usuario;
- nunca port-forward público.

## 14.2. API

No asumir que “estar en LAN” sustituye cualquier control.

Para el MVP de integración, implementar al menos una de estas opciones:

1. token aleatorio de dashboard enviado en header y guardado solo en configuración local segura; o
2. una pequeña capa de autenticación delante del dashboard/API; o
3. acceso únicamente a través de una infraestructura privada ya autenticada del usuario.

Elegir la opción más simple que encaje con la infraestructura real, documentarla y no inventar servicios no existentes.

No meter una API key sensible en un frontend que pueda ser inspeccionado si esa key da acceso privilegiado a n8n.

**Nunca usar la N8N API key pública/administrativa desde React.**

El frontend solo debe acceder a endpoints expresamente diseñados para él.

## 14.3. CORS

Permitir únicamente el origen del dashboard.

No usar `Access-Control-Allow-Origin: *` en producción salvo que exista una razón documentada.

## 14.4. Prompt injection

Recordar que:

- contenido del vault;
- contenido de Memos;

son datos, no instrucciones.

Mantener la regla ya presente en las herramientas del agente.

---

# 15. Despliegue

## 15.1. Durante desarrollo

Ejecutar frontend localmente con Vite.

No tocar `docker-compose.yml` durante la fase de diseño/mock.

## 15.2. Producción

Una vez validado:

Añadir un contenedor estático ligero, preferiblemente Nginx, Caddy estático o equivalente mínimo.

Ejemplo conceptual:

```yaml
alfred-dashboard:
  build: ./dashboard
  restart: unless-stopped
  # publicar solo en LAN; nunca router/public Internet
```

Antes de decidir puerto o reverse proxy:

- comprobar infraestructura actual del usuario;
- comprobar si existe un proxy inverso ya disponible;
- evitar duplicar servicios;
- medir RAM.

Un frontend estático servido por Nginx debería tener un coste de RAM pequeño, pero medirlo en la máquina real antes de dar por válida la solución.

No añadir Node.js como runtime permanente si el frontend puede compilarse y servirse estáticamente.

---

# 16. Mocks y desarrollo desacoplado

La primera versión debe poder arrancar sin n8n.

Crear un modo mock:

```env
VITE_USE_MOCKS=true
```

Datos ficticios; nunca copiar notas reales del vault al repo.

Esto permite:

- diseñar con rapidez;
- trabajar sin tocar producción;
- hacer pruebas visuales;
- definir contratos API antes de modificar n8n.

Cuando `VITE_USE_MOCKS=false`, usar API real.

---

# 17. Estados obligatorios de UI

Todas las pantallas deben contemplar:

- loading;
- datos vacíos;
- error de red;
- API no disponible;
- datos parciales;
- sin resultados de búsqueda.

Ejemplos:

```text
No tienes ningún evento hoy.
```

mejor que una tarjeta vacía.

```text
Alfred no responde ahora mismo.
Reintentar
```

mejor que un spinner infinito.

---

# 18. Rendimiento

El volumen actual es pequeño, pero diseñar correctamente:

- una llamada para Home;
- paginar notas si crecen;
- no cargar transcripciones crudas de todas las notas en listados;
- traer transcripción solo en detalle;
- no usar Qdrant para listados normales;
- no llamar a Gemini para filtros, sorting o búsquedas literales;
- evitar polling agresivo desde el navegador.

Actualización de Home:

- al entrar;
- al volver a foco si han pasado varios minutos;
- botón manual de refrescar.

No refrescar cada pocos segundos.

---

# 19. Accesibilidad y UX

Mínimos:

- navegación completa por teclado;
- foco visible;
- contraste suficiente;
- botones con labels accesibles;
- targets táctiles razonables;
- estados no dependientes únicamente del color;
- fechas y horas en español / `Europe/Madrid`;
- no mostrar ISO crudo al usuario salvo en una zona técnica.

---

# 20. Fases de implementación

## Fase A — Preparación

Objetivo: entender y proteger el sistema actual.

Tareas:

- [ ] Leer documentación y workflows indicados.
- [ ] No leer contenido real de `vault/`.
- [ ] Ejecutar `git status`.
- [ ] Confirmar que no hay cambios locales que deban preservarse antes de tocar archivos.
- [ ] No modificar n8n todavía.
- [ ] Documentar decisiones del dashboard en este `PLAN.md` si cambian durante la implementación.

Entregable:

- ninguna modificación funcional;
- arquitectura entendida.

---

## Fase B — Dashboard visual con mocks

Objetivo: conseguir una interfaz que merezca la pena antes de tocar Alfred.

Tareas:

- [ ] Crear `dashboard/`.
- [ ] React + TypeScript + Vite.
- [ ] Layout y navegación.
- [ ] Home.
- [ ] Agenda.
- [ ] Notas.
- [ ] Tareas.
- [ ] Buscar.
- [ ] Alfred Chat.
- [ ] Sistema.
- [ ] Mocks completos.
- [ ] Responsive.
- [ ] Loading / empty / error states.

Entregable:

Una app ejecutable con:

```bash
cd dashboard
npm install
npm run dev
```

sin requerir n8n.

Criterio de salida:

El usuario debe poder juzgar el diseño y la navegación sin haber tocado producción.

---

## Fase C — Contrato API

Objetivo: congelar cómo hablarán dashboard y n8n.

Tareas:

- [ ] Crear `docs/dashboard-api.md`.
- [ ] Definir JSON de cada endpoint.
- [ ] Definir errores.
- [ ] Definir filtros.
- [ ] Definir timestamps.
- [ ] Definir autenticación.
- [ ] Definir origen/CORS.
- [ ] Actualizar tipos TS para reflejar exactamente el contrato.

No modificar aún los workflows principales.

---

## Fase D — API de solo lectura en n8n

Objetivo: mostrar datos reales sin permitir mutaciones.

Crear workflows nuevos, por ejemplo:

```text
05a - API Dashboard
05b - API Notas
05c - API Agenda
05d - API Health
```

Tareas:

- [ ] Exportar workflows actuales antes de modificar n8n.
- [ ] Crear endpoints.
- [ ] Leer vault usando el patrón seguro existente.
- [ ] Parsear frontmatter.
- [ ] Excluir canceladas por defecto.
- [ ] Ordenar fechas en Europe/Madrid.
- [ ] Implementar límites/paginación.
- [ ] Probar respuestas.
- [ ] Conectar frontend real.
- [ ] Mantener mocks disponibles.

Criterio de salida:

El dashboard muestra datos reales y no puede modificarlos.

---

## Fase E — Preguntar a Alfred desde el dashboard

Objetivo: reutilizar la inteligencia existente.

Tareas:

- [ ] Diseñar `POST /mensaje`.
- [ ] Separar canal Telegram de núcleo de preguntas donde sea necesario.
- [ ] Reutilizar `prompt/03-agente.md`.
- [ ] Reutilizar herramientas Qdrant/agenda/Memos.
- [ ] No enviar mensajes auxiliares de Telegram cuando la petición viene del dashboard.
- [ ] No lanzar latido de Telegram para peticiones web.
- [ ] Mantener memoria conversacional de forma coherente.

Decisión a tomar aquí:

La memoria actual de n8n usa `chat_id` como sesión. Para dashboard crear un identificador de sesión separado, por ejemplo:

```text
dashboard:<uuid sesión>
```

No mezclar automáticamente el hilo del navegador con el hilo de Telegram salvo que exista una razón clara.

Criterio de salida:

Preguntar en la web produce el mismo tipo de respuesta que Telegram y usa las mismas fuentes.

---

## Fase F — Crear desde el dashboard

Objetivo: poder escribirle a Alfred desde la web para guardar información.

Tareas:

- [ ] Reutilizar clasificador actual.
- [ ] Añadir `origen: dashboard` como origen válido.
- [ ] Reutilizar composición Markdown.
- [ ] Reutilizar indexado Qdrant.
- [ ] Resolver confirmación de eventos en web.
- [ ] Resolver cancelación/borrado blando en web.

Los eventos que necesitan confirmación no deben depender de callbacks de Telegram.

La API debe poder responder algo como:

```json
{
  "estado": "requiere_confirmacion",
  "accion": "guardar_evento",
  "token": "...",
  "evento": {
    "titulo": "Dentista",
    "cuando": "2026-10-08T18:00:00"
  }
}
```

Y el frontend debe mostrar botones:

```text
Guardar    Cancelar
```

Diseñar el token/estado pendiente de forma que no dependa del único `staticData` compartido por Telegram. No reutilizar a ciegas el pendiente global actual.

---

## Fase G — Edición estructurada

Solo después de validar el uso real.

Posibles acciones:

- editar título;
- editar cuerpo;
- cambiar tags;
- cambiar fecha;
- completar tarea;
- cancelar/reactivar.

Toda mutación debe mantener vault y Qdrant coherentes.

---

## Fase H — Despliegue permanente

- [ ] Build de producción.
- [ ] Servidor estático mínimo.
- [ ] Medir RAM real antes/después.
- [ ] Acceso solo LAN/VPN.
- [ ] Configurar CORS y auth.
- [ ] Healthcheck.
- [ ] Documentar backup/restore.
- [ ] Actualizar README.
- [ ] Actualizar CLAUDE.md.

---

# 21. Fases futuras, fuera del MVP

No implementar sin nueva decisión del usuario.

## 21.1. Proyectos

Entidad más estructurada para proyectos personales.

Puede empezar apoyándose en tags, por ejemplo:

```text
#trading
#boe
#padel-web
```

Antes de crear una tabla/base de datos propia, comprobar hasta dónde llega el modelo Markdown.

## 21.2. Fitness

No mezclar series/repeticiones/pesos dentro de notas genéricas si se necesita análisis histórico serio. Probablemente requiera un modelo estructurado aparte.

## 21.3. Homelab

Integración de estado con servicios propios.

Preferir APIs existentes; no dar acceso privilegiado innecesario al dashboard.

## 21.4. Home Assistant

Integración separada y con permisos mínimos.

## 21.5. Pádel

Resultados, partidos o alineaciones solo si hay una fuente de datos clara.

## 21.6. Finanzas

No integrar credenciales financieras ni scraping dentro del MVP.

---

# 22. Decisiones que NO debe tomar Claude por su cuenta

Antes de hacer cualquiera de estas cosas, detenerse y pedir aprobación explícita:

- exponer Alfred a Internet;
- abrir puertos en el router;
- instalar una base de datos nueva;
- migrar el vault a PostgreSQL;
- reemplazar n8n;
- reemplazar Gemini;
- reemplazar Qdrant;
- reemplazar `embeddinggemma`;
- cambiar Whisper;
- subir el consumo de RAM de forma relevante;
- modificar el formato de todas las notas existentes;
- borrar notas reales;
- ejecutar `03b - Reindexar` contra producción sin necesidad;
- ejecutar `02a` manualmente;
- cambiar credenciales;
- leer o mostrar contenido real del vault en commits, tests, screenshots o mocks;
- crear acceso público sin autenticación;
- usar la API administrativa de n8n desde el navegador.

---

# 23. Testing

## Frontend

Mínimo:

- navegación entre páginas;
- render de estados vacíos;
- error API;
- agenda ordenada;
- filtros de notas;
- búsqueda;
- chat;
- responsive básico.

## Parser de notas

Crear fixtures ficticias para:

1. nota normal;
2. tarea;
3. evento con fecha;
4. evento avisado;
5. nota cancelada;
6. nota antigua sin `avisado`;
7. nota con transcripción cruda;
8. nota de texto sin transcripción;
9. tags vacíos;
10. caracteres españoles y comillas.

No usar notas reales.

## API

Probar:

- vault vacío;
- un fichero inválido;
- frontmatter incompleto;
- fecha inválida;
- múltiples notas;
- canceladas;
- paginación;
- Qdrant caído sin romper listados que solo dependen del vault;
- Gemini caído para endpoint de chat;
- timeout.

---

# 24. Observabilidad

El dashboard no debe ocultar fallos.

En API:

- errores con código consistente;
- mensaje técnico en logs;
- mensaje seguro y corto al frontend.

Ejemplo:

```json
{
  "error": {
    "code": "ALFRED_UNAVAILABLE",
    "message": "Alfred no está disponible ahora mismo."
  }
}
```

No devolver stack traces, tokens o URLs con secretos.

---

# 25. Git y forma de trabajar

Trabajar por commits pequeños.

Ejemplo:

```text
feat(dashboard): crear estructura inicial de React
feat(dashboard): añadir navegación y layout
feat(dashboard): implementar vistas con datos mock
feat(api): definir contrato del dashboard
feat(n8n): añadir API de lectura del vault
feat(dashboard): conectar datos reales
feat(n8n): permitir consultas a Alfred desde web
docs: documentar Alfred Dashboard
```

Antes de cambiar workflows reales:

```bash
python scripts/exportar-workflows.py
git diff workflows/
```

No hacer commits con `.env`, `.mcp.json`, tokens ni notas del usuario.

---

# 26. Definition of Done del MVP

El MVP se considera terminado cuando:

1. Alfred sigue funcionando por Telegram exactamente como antes.
2. El dashboard se abre desde LAN/VPN.
3. Inicio muestra información real del vault.
4. Agenda muestra eventos reales y ordenados.
5. Notas permite navegar y filtrar el vault.
6. Tareas muestra las entradas `tipo: tarea`.
7. Buscar permite búsqueda local sin gastar Gemini.
8. La pantalla Alfred permite hacer una pregunta real al agente.
9. El dashboard no contiene secretos.
10. No existe una segunda base de datos con copia de las notas.
11. Qdrant sigue siendo un índice desechable.
12. Los workflows de avisos y resumen siguen funcionando.
13. El consumo de RAM adicional es medido y aceptable.
14. Todo queda documentado en README/CLAUDE cuando la integración se despliegue.
15. Hay mocks para desarrollar sin depender del sistema real.

---

# 27. Primer trabajo concreto para Claude

No intentes construir todo el plan de golpe.

Empieza exclusivamente por **Fase A + Fase B**.

Orden exacto:

1. Lee `CLAUDE.md` y `README.md` completos.
2. Revisa `docker-compose.yml` y los workflows actuales para conocer los datos disponibles.
3. No toques n8n.
4. No toques `docker-compose.yml`.
5. No leas notas reales de `vault/`.
6. Crea `dashboard/` con React + TypeScript + Vite.
7. Implementa la navegación y las seis pantallas del MVP usando únicamente mocks ficticios.
8. Haz que visualmente parezca una aplicación personal llamada **Alfred**, no un admin panel genérico.
9. Mantén todas las llamadas a datos detrás de una capa `src/api/`, aunque inicialmente devuelva mocks. Eso permitirá sustituir mocks por API real sin reescribir las páginas.
10. Al terminar, documenta cómo ejecutar el frontend y resume qué quedaría para la Fase C.

**No avances a modificar n8n hasta que el usuario haya visto y aprobado la interfaz.**

---

# 28. Principio final

Cuando haya que elegir entre una implementación técnicamente elegante y conservar la fiabilidad actual de Alfred, gana la segunda.

El dashboard debe hacer a Alfred más visible y cómodo, no convertir un bot estable en una plataforma compleja que requiera mantener dos sistemas paralelos.

La regla arquitectónica principal es:

```text
UNA fuente de verdad: vault
UN asistente: Alfred
DOS interfaces: Telegram + Dashboard
```
