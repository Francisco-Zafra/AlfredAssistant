# Secretario

Un bot de Telegram que hace de secretario personal. Le mandas una nota de voz, la
transcribe, la ordena y la guarda. Le preguntas por algo que dijiste hace tres meses
y lo encuentra. Le cuentas que el martes tienes dentista y te avisa el martes.

Todo corre en casa. Lo único que sale a internet es la API de Telegram y el modelo
que razona.

## Arranque rápido

Necesitas una VM en Proxmox con Debian, unos 6 GB de RAM y 4 vCPU, y Docker instalado.

```bash
git clone <este-repo> secretario
cd secretario

cp .env.example .env
openssl rand -hex 32          # copia el resultado a N8N_ENCRYPTION_KEY en .env
# y rellena tambien TELEGRAM_BOT_TOKEN y TELEGRAM_ALLOWED_USER_ID

mkdir -p vault
docker compose up -d

# Modelo de embeddings (una sola vez, tarda un par de minutos)
docker compose exec ollama ollama pull nomic-embed-text
```

n8n queda en `http://<ip-de-la-vm>:5678`, accesible solo desde la LAN o la VPN. La
primera vez te pide crear el usuario propietario.

Luego importa los workflows de `workflows/` desde la interfaz, y conecta las
credenciales a mano: las exportaciones de n8n no las incluyen, a propósito. En la
fase 1 la única credencial que hay que crear es la de Gemini. En la fase 3 entran
dos más, y estas no llevan secreto porque los servicios son tuyos y viven en la
red interna de Docker:

| Credencial | Campo | Valor |
|---|---|---|
| Qdrant | URL | `http://qdrant:6333` (API key en blanco) |
| Ollama | Base URL | `http://ollama:11434` |

Los system prompts viven en `prompts/`, montado en el contenedor como `/prompts`
en solo lectura. Los workflows los leen en ejecución, así que para cambiar un
prompt basta con editar el fichero: no hay que tocar ni reimportar el JSON.

## Qué hay dentro

| Servicio | Para qué | Puerto |
|---|---|---|
| n8n | Orquesta todo. Es donde vive la lógica. | 5678 (LAN) |
| whisper | Transcribe las notas de voz. faster-whisper, modelo `small`, int8. | interno |
| qdrant | Memoria vectorial, para poder preguntarle a las notas. | interno |
| ollama | Genera los embeddings con `nomic-embed-text`. | interno |

Solo n8n publica puerto. Los demás hablan entre ellos por la red interna de Docker
y no son alcanzables desde fuera del host.

## Cómo fluye

```
Telegram (long polling, llega al instante)
        │
        ├── nota de voz → getFile → whisper:9000/asr → texto crudo
        └── texto → tal cual
        │
        ▼
   Gemini limpia y clasifica
        │
        ├── pregunta → AI Agent → respuesta por Telegram
        │
        ├── nota  ─┐
        ├── tarea ─┼→ .md en vault/  +  embedding en qdrant
        └── evento ┘   (el evento pregunta con botones antes de guardar)
        │
        ▼
   confirmación por Telegram
```

Y en paralelo, cada 15 minutos, un workflow mira los eventos próximos y avisa.

Da igual dictar que escribir: el mensaje escrito se salta Whisper y entra en el
mismo sitio, solo que el prompt sabe que ese texto no trae ruido de transcripción
y no hay que guardar el original aparte.

Cuando el mensaje es una pregunta en vez de un dictado, entra un **AI Agent** con dos
herramientas: buscar en Qdrant y leer la agenda del vault. De distinguir pregunta de
dictado se encarga el mismo prompt que ya clasificaba, que devuelve `tipo:
"pregunta"`. Un router aparte habría sido más limpio, pero son dos peticiones al
modelo en vez de una y el tope diario de Gemini se cuenta por peticiones.

## El almacén

Todo son ficheros markdown en `vault/`. Sin base de datos, sin formato propietario.
Si mañana quieres abrirlo con Obsidian, funciona sin migrar nada.

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

Dentista el miércoles a las seis, en la clínica de la calle Mayor.

<!-- transcripción cruda -->
> pues eh el miércoles a las seis tengo dentista en la de calle mayor
```

Los eventos no necesitan calendario aparte: son notas con `cuando` relleno. El
workflow de avisos los busca por ahí y marca `avisado: true` al notificar.

La transcripción cruda se guarda junto a la versión limpia siempre que la haya. El
día que el modelo interprete mal algo importante, querrás ver qué dijiste de verdad.
Si el mensaje lo escribiste tú, `origen: texto` y ese bloque no aparece: no hay
original que contrastar.

## La memoria

Cada nota que se guarda se indexa también en Qdrant, en la colección `notas`. El
embedding lo hace `nomic-embed-text` en Ollama, en local, y en el payload van el
título, el tipo, la fecha y el fichero, para que el agente pueda decirte *cuándo*
apuntaste algo y no solo *qué*.

El vault es la fuente de verdad y Qdrant es un índice desechable. Se reconstruye
entero con el workflow **03b - Reindexar**, que tira la colección y la rehace leyendo
`/vault/*.md`. Hay que pasar por ahí en tres casos: la primera vez, si vienes de la
fase 2 con notas ya guardadas; cuando editas o borras notas a mano; y cuando el
indexado en caliente ha fallado.

Ese indexado cuelga en paralelo del guardado, no en cadena, y con el error
silenciado. Es a propósito: si Ollama está ocupado o Qdrant no arranca, prefieres
que la nota llegue al disco y que la respuesta salga, aunque se quede sin indexar.
El precio es que no te enteras. Si el bot dice que no encuentra algo que juras haber
apuntado, reindexa antes de dar por rota la memoria.

## Decisiones y por qué

**Long polling en vez de webhooks.** Nada abierto al exterior, nada de dominio ni
certificados, y aun así el mensaje se procesa en cuanto lo mandas: la petición a
Telegram se queda esperando hasta 50 segundos y vuelve en el instante en que llega
algo. El workflow se encadena consigo mismo para que no haya huecos, con un Schedule
de rescate por si la cadena se rompe. Detalles en
[docs/telegram-polling.md](docs/telegram-polling.md).

El webhook se descartó porque exige que algo tuyo sea alcanzable desde internet, por
puerto abierto o por túnel, y eso choca con la premisa de no exponer nada.

**Gemini para razonar, el resto local.** Los modelos pequeños en CPU fallan al elegir
herramienta lo suficiente como para que acabes desconfiando del bot, y este Xeon no
tiene GPU. Con eso en la mano, el tier gratuito de Gemini es la opción práctica.

Ojo con la letra pequeña: en el tier gratuito, Google puede usar tus prompts y
respuestas para mejorar sus productos, y hay revisión humana de por medio. Existe un
matiz para clientes del EEE que podría no aplicarte esa cláusula, pero las fuentes se
contradicen, así que compruébalo en los términos antes de volcar ahí tu vida personal.

La fuga no es solo la nota que dictas: cuando el agente busca en Qdrant y le pasa a
Gemini las notas recuperadas, esas también salen. Si te incomoda, cambia el nodo
Google Gemini Chat Model por Ollama Chat Model y no se toca nada más del flujo. El
resto del sistema ya es local.

**Todo en un compose.** Levantas o tiras el stack entero de una vez, y el backup es
copiar `vault/` y los volúmenes.

## Por fases

No intentes montarlo entero de golpe. Cada fase funciona sola y ya es útil.

1. **La libreta.** ✅ Polling → Whisper → limpiar con Gemini → guardar `.md` →
   responder "apuntado". Con esto solo, ya estás usando el bot todos los días.
2. **El clasificador.** ✅ Distingue nota de tarea de evento, resuelve fechas
   relativas ("mañana", "en tres días", "en 1h") y confirma con botones antes de
   guardar un evento: Whisper se come fechas. Sin AI Agent todavía, es la misma
   llamada al modelo con un prompt más rico; las herramientas hacen falta en la
   fase 3, no aquí.
3. **La memoria.** ✅ Qdrant, indexación y la herramienta de búsqueda, más el AI
   Agent que las usa. Aquí es cuando deja de ser una libreta y pasa a ser un
   secretario: ya puedes preguntarle. Entra también la entrada por texto, que hasta
   ahora se perdía por una rama sin conectar.
4. **Los avisos.** Recordatorios y resumen diario de las 8:00.

Google Calendar no está en ninguna fase todavía. Es una decisión aplazada, no un
olvido: los eventos son notas con `cuando` relleno y de momento eso basta.

## Trampas conocidas

- `N8N_ENCRYPTION_KEY` se fija en el primer arranque. Si se regenera, pierdes todas
  las credenciales guardadas. Haz copia de `.env` en tu gestor de contraseñas.
- Sin `N8N_SECURE_COOKIE=false` no puedes iniciar sesión por `http://IP:5678`.
  n8n exige HTTPS para la cookie salvo en localhost.
- Sin `N8N_BLOCK_ENV_ACCESS_IN_NODE=false`, cualquier expresión o nodo Code que use
  `$env` falla con *access to env vars denied*. El token de Telegram se lee así, o
  sea que sin esa variable no arranca ni el primer nodo.
- Los nodos de fichero de n8n solo ven `/vault`, por `N8N_RESTRICT_FILE_ACCESS_TO`.
  Si añades otra ruta, amplía esa variable o fallarán en silencio.
- Filtra por tu user id de Telegram desde el primer día. Los bots se encuentran, y
  no quieres la libreta llena de mensajes ajenos.
- El webservice de Whisper puede devolver el JSON marcado como `text/plain`. n8n
  entonces no lo parsea y te deja la respuesta entera como cadena en `json.data`, no
  en `json.text`. El nodo *Normalizar transcripcion* cubre las dos formas y el
  `output=txt`; si lo tocas, no des por hecha ninguna.
- `$getWorkflowStaticData` solo se guarda en ejecuciones de producción. Si pruebas el
  polling con *Execute Workflow*, el offset nunca avanza y cada ejecución reprocesa
  todo el backlog. Actívalo con el toggle para probarlo de verdad.
- El tier gratuito de Gemini tiene tope **diario** por modelo y cada nota gasta una
  petición. Cuando se agota, el workflow tira de OpenRouter; si ese también falla,
  guarda la transcripción cruda con `revisar: true` en el frontmatter y te avisa por
  Telegram con la hora a la que vuelve la cuota. Para repescarlas:
  `grep -rl 'revisar: true' vault/`.
- Un nodo **HTTP Request reemplaza el json del item** con la respuesta del servidor.
  Si un nodo posterior necesita un campo que venía de antes, o lo lees con
  `$('Nodo anterior').item.json.campo`, o sacas el HTTP de la ruta principal y lo
  cuelgas como rama lateral. Los nodos que leen un campo del item actual, como
  *Convert to File*, no tienen la primera salida: esos exigen lo segundo.
- Los dos nodos *Execute Workflow* de `02a` llevan el id del workflow destino, y ese
  id lo genera n8n al importar. Vienen con `PEGA_AQUI_EL_ID_...`: si no los rellenas,
  la cadena no arranca y el bot no contesta.
- Si la cadena de long polling se corta, el Schedule de rescate tarda entre dos y tres
  minutos en revivirla. Es el precio de no arrancar dos cadenas a la vez.
- Solo hay **una** confirmación pendiente a la vez, guardada en `staticData`. Si
  dictas dos eventos seguidos sin contestar al primero, los botones del primero
  quedan caducados y te lo dice al pulsarlos. Caducan también a los 30 minutos.
- Whisper `small` con int8 se come sobre 2 GB mientras transcribe. Es el pico de RAM
  del stack.
- Al meter fechas relativas, pásale al prompt la fecha y hora actuales. Si no, el
  modelo no sabe qué significa "mañana".

- Los ids de workflow a rellenar a mano son **tres**, no dos: los dos *Execute
  Workflow* de `02a` y el nodo *Consultar la agenda* de `02b`, que apunta a
  `03a - Agenda`. Todos vienen con `PEGA_AQUI_EL_ID_...`. Si te dejas el de la
  agenda, el bot contesta igual pero se inventa la agenda o dice que no la ve.
- La colección `notas` de Qdrant la crea el nodo de inserción la primera vez que
  guardas algo. Si preguntas antes de tener ni una nota indexada, la búsqueda falla
  y el agente contesta a ciegas. Corre `03b - Reindexar` una vez y ya está.
- `03b - Reindexar` **borra la colección** antes de rehacerla. Tiene que hacerlo: el
  nodo de inserción genera un id nuevo por cada trozo, así que reindexar sin borrar
  duplicaría el vault entero en el índice.
- La memoria de conversación del agente es la *Simple Memory* de n8n, que vive en la
  RAM del proceso. Al reiniciar el contenedor se pierde el hilo. Para preguntas
  sueltas da igual; para "¿y el martes?" justo después de reiniciar, no.
- Una pregunta gasta **dos** peticiones al modelo, la de clasificar y la del agente,
  y el agente puede gastar más si encadena herramientas. Con el tope diario del tier
  gratuito, preguntar sale bastante más caro que dictar.
- Si el clasificador se equivoca y toma tu pregunta por un dictado, la pregunta
  acaba guardada como nota en el vault. Se borra y ya, pero conviene saberlo antes
  de encontrarte "¿qué tengo mañana?" convertido en una nota.
- El nodo de lectura de ficheros con comodín no devuelve lo mismo en todas las
  versiones de n8n: unas sacan un item por fichero con la propiedad binaria `data`,
  otras un solo item con `data0`, `data1`... Los nodos que leen el vault cubren las
  dos formas a propósito; si los tocas, no des por hecha ninguna.
- Los mensajes escritos entran por la rama **falsa** de *Es nota de voz*, que hasta
  la fase 3 no iba a ningún sitio. Si la desconectas, el bot se queda mudo ante todo
  lo que no sea audio, y sin error: el mensaje simplemente se evapora.

## Estructura

```
secretario/
├─ docker-compose.yml
├─ .env.example
├─ workflows/     # los JSON exportados de n8n
│  ├─ 01-libreta.json       # fase 1, polling simple
│  ├─ 02a-escucha.json      # el bucle de long polling
│  ├─ 02b-secretario.json   # transcribir, clasificar, guardar, contestar
│  ├─ 03a-agenda.json       # herramienta del agente: los eventos del vault
│  └─ 03b-reindexar.json    # rehace la colección de qdrant desde el vault
├─ prompts/       # system prompts en ficheros aparte, para versionarlos
│  ├─ 01-limpiar-transcripcion.md
│  ├─ 02-clasificar.md
│  └─ 03-agente.md
├─ scripts/       # limpiar los exports de n8n antes de subirlos
├─ docs/
└─ vault/         # tus notas (en .gitignore)
```
