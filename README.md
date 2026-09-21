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
fase 1 la única credencial que hay que crear es la de Gemini.

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
        ├── nota  ─┐
        ├── tarea ─┼→ .md en vault/  +  embedding en qdrant
        └── evento ┘
        │
        ▼
   confirmación por Telegram
```

Y en paralelo, cada 15 minutos, un workflow mira los eventos próximos y avisa.

Cuando el mensaje es una pregunta en vez de un dictado, entra un **AI Agent** con dos
herramientas: buscar en Qdrant y leer la agenda del vault.

## El almacén

Todo son ficheros markdown en `vault/`. Sin base de datos, sin formato propietario.
Si mañana quieres abrirlo con Obsidian, funciona sin migrar nada.

```markdown
---
tipo: evento
creado: 2026-09-21T18:40:00
cuando: 2026-09-23T18:00:00
avisado: false
tags: [dentista, salud]
---

Dentista el miércoles a las seis, en la clínica de la calle Mayor.

<!-- transcripción cruda -->
> pues eh el miércoles a las seis tengo dentista en la de calle mayor
```

Los eventos no necesitan calendario aparte: son notas con `cuando` relleno. El
workflow de avisos los busca por ahí y marca `avisado: true` al notificar.

La transcripción cruda se guarda siempre junto a la versión limpia. El día que el
modelo interprete mal algo importante, querrás ver qué dijiste de verdad.

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

1. **La libreta.** Polling → Whisper → limpiar con Gemini → guardar `.md` → responder
   "apuntado". Con esto solo, ya estás usando el bot todos los días.
2. **El clasificador.** Distingue nota de tarea de evento, resuelve fechas
   relativas ("mañana", "en tres días", "en 1h") y confirma con botones antes de
   guardar un evento: Whisper se come fechas. Sin AI Agent todavía, es la misma
   llamada al modelo con un prompt más rico; las herramientas hacen falta en la
   fase 3, no aquí.
3. **La memoria.** Qdrant, indexación y la herramienta de búsqueda. Aquí es cuando
   deja de ser una libreta y pasa a ser un secretario.
4. **Los avisos.** Recordatorios y resumen diario de las 8:00.

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

## Estructura

```
secretario/
├─ docker-compose.yml
├─ .env.example
├─ workflows/     # los JSON exportados de n8n
│  ├─ 01-libreta.json       # fase 1, polling simple
│  ├─ 02a-escucha.json      # el bucle de long polling
│  └─ 02b-secretario.json   # transcribir, clasificar, guardar
├─ prompts/       # system prompts en ficheros aparte, para versionarlos
├─ scripts/       # reindexar el vault en qdrant, backups
├─ docs/
└─ vault/         # tus notas (en .gitignore)
```
