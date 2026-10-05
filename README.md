# Secretario

Un bot de Telegram que hace de secretario personal. Le mandas una nota de voz, la
transcribe, la ordena y la guarda. Le preguntas por algo que dijiste hace tres meses
y lo encuentra. Le cuentas que el martes tienes dentista y te avisa el martes.

Todo corre en casa. Lo único que sale a internet es la API de Telegram, el modelo
que razona y tu Google Calendar, que es donde viven las citas.

## Arranque rápido

Necesitas un contenedor LXC o una VM en Proxmox con Debian, **3 GB de RAM** y 4
vCPU, y Docker instalado. Con 3 GB cabe, pero sin holgura: mira
[Cuánto cabe en 3 GB](#cuánto-cabe-en-3-gb) antes de cambiar ningún modelo.

```bash
git clone <este-repo> secretario
cd secretario

cp .env.example .env
openssl rand -hex 32          # copia el resultado a N8N_ENCRYPTION_KEY en .env
# y rellena tambien TELEGRAM_BOT_TOKEN y TELEGRAM_ALLOWED_USER_ID

mkdir -p vault
docker compose up -d

# Modelo de embeddings (una sola vez, tarda un par de minutos)
docker compose exec ollama ollama pull embeddinggemma
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

Si usas [Memos](#memos), hay una cuarta, esta sí con secreto: una **Header Auth**
llamada `Memos`, con *Name* `Authorization` y *Value* `Bearer <token>`. El token se
saca en Memos, en *Settings > My Account > Access Tokens*. Asígnala a los nodos
`buscar_memos` y `leer_memo` de `02b`.

Y una quinta, para que el "escribiendo…" no se apague mientras el agente piensa (ver
[El latido](#el-latido)): una **n8n API** llamada `n8n API`, con *Base URL*
`http://localhost:5678/api/v1` y como *API Key* la que generas en n8n, en *Settings >
n8n API*. Va en el nodo *Mirar la pregunta* de `02b`. Sin ella, `02b` no se deja
publicar.

Y una sexta, para el calendario: una **Google Calendar OAuth2 API** llamada `Google
Calendar account`. Va en todos los nodos *Leer el calendario*, *Crear en Google* y
*Borrar de Google*. Hay que crearla con un poco de cuidado, y una sola vez:

1. En Google Cloud, un proyecto con la **Google Calendar API** activada.
2. En *Google Auth Platform*: público **Externo**, y en *Desarrollo de la marca* una
   página principal y una política de privacidad (vale la URL del repo). Sin eso no
   deja pulsar **Publicar app**, y hay que pulsarlo: en modo *Prueba* el token caduca
   a los 7 días y el calendario deja de funcionar sin avisar.
3. Un cliente OAuth de tipo *Aplicación web* con la redirección
   `http://localhost:5678/rest/oauth2-credential/callback`.
4. La credencial se conecta desde `http://localhost:5678`, no desde la IP: Google no
   acepta una IP privada como vuelta. Desde tu PC, `ssh -L 5678:localhost:5678
   <servidor>` y abres n8n por localhost. Al conectar sale "Google no ha verificado
   esta aplicación": *Configuración avanzada → Ir a Alfred*. La app es tuya.

Se puede revocar en cualquier momento desde
[myaccount.google.com/permissions](https://myaccount.google.com/permissions).

Los system prompts viven en `prompts/`, montado en el contenedor como `/prompts`
en solo lectura. Los workflows los leen en ejecución, así que para cambiar un
prompt basta con editar el fichero: no hay que tocar ni reimportar el JSON.

## Qué hay dentro

| Servicio | Para qué | Puerto |
|---|---|---|
| n8n | Orquesta todo. Es donde vive la lógica. | 5678 (LAN) |
| whisper | Transcribe las notas de voz. faster-whisper, modelo `small`, int8. | interno |
| qdrant | Memoria vectorial, para poder preguntarle a las notas. | interno |
| ollama | Genera los embeddings con `embeddinggemma`. | interno |

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
        ├── borrar   → busca en el vault → botones → marca cancelado
        │
        ├── nota  ─┬→ .md en vault/  +  embedding en qdrant
        ├── tarea ─┘
        └── con fecha → botones → Google Calendar
        │
        ▼
   confirmación por Telegram
```

Y en paralelo, cada 15 minutos un workflow mira los eventos próximos y avisa, y
a las 8:00 otro te manda el parte del día.

Da igual dictar que escribir: el mensaje escrito se salta Whisper y entra en el
mismo sitio, solo que el prompt sabe que ese texto no trae ruido de transcripción
y no hay que guardar el original aparte.

Cuando el mensaje es una pregunta en vez de un dictado, entra un **AI Agent** con sus
herramientas: buscar en Qdrant, leer la agenda de Google Calendar y, si lo tienes, buscar y
leer en [Memos](#memos). De distinguir pregunta de
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

<!-- y si la cancelas, se le añaden:  cancelado: true  y  cancelado_el: ... -->

Dentista el miércoles a las seis, en la clínica de la calle Mayor.

<!-- transcripción cruda -->
> pues eh el miércoles a las seis tengo dentista en la de calle mayor
```

Eso vale para notas y tareas. **Lo que tiene fecha no va al vault: va a tu Google
Calendar**, al principal. Ahí lo puedes ver, mover o borrar desde el móvil o la web,
y la agenda, los avisos y el resumen de las 8:00 leen de ahí, así que lo que cambies
a mano en Google lo ve Alfred y lo que apuntes a mano también.

Un evento dictado se crea con:

- el título como título y empieza en `cuando`. Si dijiste hasta cuándo dura ("de
  10 a 14"), acaba ahí; si ocupa días enteros ("resérvame el finde", "del lunes al
  miércoles estoy fuera"), es un evento de todo el día de uno o varios días; y si
  no dijiste nada, dura una hora, que es lo que pide Google, marcada como supuesta
  (sin `finConocido` en sus propiedades privadas) para que la agenda no la cuente
  como un dato;
- el texto limpio en la descripción y, si fue por voz, la transcripción cruda debajo;
- **sin recordatorios de Google**, porque ya avisa Telegram;
- `alfred: true` en sus propiedades privadas, para distinguirlo de los tuyos.

Una tarea con día (*"recuérdame mañana comprar pan"*) también es algo con fecha, así
que va al calendario y pasa por los mismos botones que un evento.

Un mensaje con varias citas (el calendario de partidos que te pasan por WhatsApp, las
sesiones de un curso) son varios eventos. El clasificador las devuelve en `eventos`,
una por cita y con su lugar, en la misma petición de siempre. Te enseña la lista
entera con un solo botón de guardar, y si alguna no se puede crear te dice cuál. La
que venga sin fecha clara se cae de la lista avisando, sin tumbar las demás.

Antes los eventos eran notas con `cuando` relleno. Los que quedaban pendientes se
pasaron a Google con `05 - Migrar eventos a Google` y en el vault llevan
`migrado: gcal` y el `gcal_id` del evento. Se quedan ahí como recuerdo, pero ya no
avisan, no salen en la agenda y no se proponen al cancelar.

La transcripción cruda se guarda junto a la versión limpia siempre que la haya. El
día que el modelo interprete mal algo importante, querrás ver qué dijiste de verdad.
Si el mensaje lo escribiste tú, `origen: texto` y ese bloque no aparece: no hay
original que contrastar.

## La memoria

Cada nota que se guarda se indexa también en Qdrant, en la colección `notas`. El
embedding lo hace `embeddinggemma` en Ollama, en local, y en el payload van el
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

## Memos

Si ya tienes notas en una instancia de [Memos](https://usememos.com), el agente
también puede consultarlas. No está en el compose: es un servicio aparte en la LAN,
y el bot solo lo **lee**. Nada de lo que dictas va a Memos, y nada de Memos entra en
el vault ni en Qdrant.

Son tres herramientas del agente en `02b`, las tres nodos HTTP Request Tool:

| Herramienta | Qué hace |
|---|---|
| `buscar_memos` | Lista o filtra notas con la API de Memos (`GET /api/v1/memos`), con filtros CEL como `content.contains("receta")`. Diez por página. |
| `leer_memo` | Lee una nota concreta por su `name` (`memos/abc123`). |
| `avisar_busqueda` | Te manda por Telegram un *"🔎 Voy a buscar en Memos…"* silencioso antes de cada consulta, para que la espera no parezca un bot colgado. |

`avisar_busqueda` no es solo de Memos: el agente lo usa antes de cualquier fuente,
también Qdrant y la agenda. Por eso cuelga del agente aunque no uses Memos, y
funciona sin configurar nada.

Si no usas Memos, borra `buscar_memos` y `leer_memo` y quita las menciones de las
descripciones de `avisar_busqueda`. Si los dejas sin credencial, el agente los
seguirá intentando y fallarán en cada pregunta.

## El latido

Telegram quita el "escribiendo…" a los cinco segundos, o en cuanto el bot manda
cualquier mensaje, avisos de búsqueda incluidos. Una pregunta tarda más que eso, y un
chat mudo no se distingue de un bot caído.

Mandarlo cada pocos segundos desde la propia pregunta no se puede: mientras el nodo
*Agente* piensa, esa ejecución está esperándole y no corre nada más. Así que `02b` se
**llama a sí mismo** sin esperar, con `latido: true`, y esa segunda ejecución solo
hace una cosa: cada 4 segundos pregunta a n8n cómo va la primera y, si sigue en
marcha, manda otro "escribiendo…".

- Si la pregunta termina bien, el latido se calla. Mira antes de mandar, así que no
  deja un "escribiendo…" colgado después de la respuesta.
- Si la pregunta termina con error, te llega un *"⚠️ Algo ha fallado con tu
  pregunta"*. Es lo que el silencio no te dejaba saber.
- A los tres minutos se rinde, pase lo que pase.

Solo se lanza para preguntas, que es donde se espera. Dictar una nota tarda poco, y
el "escribiendo…" de siempre llega.

## Cancelar y olvidar

*"Cancela el dentista del jueves"*, *"olvida lo del pan"*. El clasificador lo marca
como `borrar`, el bot busca qué puede ser en el vault y en tu Google Calendar (de un
mes atrás a un año adelante) y te enseña **hasta tres candidatos** con su fecha para
que elijas con un botón. Igual que al guardar un evento, pero al revés.

Si eliges un evento de Google, se borra de Google. Va a la papelera del calendario y
ahí se queda 30 días, por si te arrepientes. Si Google no responde, la búsqueda
sigue solo con el vault y te lo dice debajo de los candidatos.

Si eliges una nota del vault, nada se borra del disco. La nota se queda donde está
con dos líneas más:

```yaml
cancelado: true
cancelado_el: 2026-09-22T11:04:00
```

A partir de ahí desaparece de la agenda, de los avisos, del resumen de las 8:00 y
del índice de Qdrant, y el punto correspondiente se borra por la API de Qdrant. A
efectos de uso está borrada. A efectos de recuperarla, sigue ahí:

```bash
grep -rl 'cancelado: true' vault/
```

Es un borrado blando por dos razones. La primera es que el nodo de ficheros de n8n
no sabe borrar: un `rm` de verdad obliga a meter el nodo Execute Command, que ejecuta
shell arbitrario dentro del contenedor, y no compensa pagar eso por una papelera. La
segunda es que el borrado es el único sitio donde equivocarse cuesta, y aquí el que
decide qué borrar es un modelo de lenguaje.

**La búsqueda es por palabras, no por significado**, y eso también es deliberado
aunque tengamos Qdrant al lado. Que no encuentre *"lo del médico"* cuando la nota
dice *"dentista"* se arregla repitiéndolo con otras palabras; borrar la nota
equivocada, no. En un borrado interesa acertar poco antes que acertar de más. De
paso, lee el vault directamente, así que funciona aunque el índice esté desfasado.

A igualdad de palabras gana la nota con la fecha más cercana a hoy: si tienes dos
citas con el dentista, la que cancelas casi siempre es la que viene.

## Los avisos

Dos workflows, los dos con Schedule Trigger, los dos hay que **activarlos a mano**
después de importarlos o no se disparan nunca.

**04a - Avisos**, cada 15 minutos. Lee de Google Calendar los eventos que empiezan en
una ventana que va de 2 horas antes de ahora a 1 hora después y te manda el aviso. Lo
avisado se apunta en el `staticData` del workflow, con el id del evento y su hora: así
no se toca nada de tu calendario y, si mueves un evento, te vuelve a avisar a la hora
nueva. Los eventos de todo el día no avisan: salen en el resumen de las 8:00.

Si Google no responde, te lo dice por Telegram, como mucho una vez cada 6 horas. Un
calendario que no se puede leer es un bot que no avisa, y eso no se nota hasta que te
pierdes algo.

La ventana hacia atrás no es un descuido. Si el bot ha estado parado media hora, los
eventos que cayeron en ese hueco te llegan tarde en vez de no llegar; te lo dice con
un *"se te ha pasado hace 40 min"* en vez de fingir que es un aviso normal. Las dos
constantes están arriba del nodo *Buscar eventos que tocan* y se tocan ahí.

Se apunta **después** de que Telegram acepte el mensaje, no antes. Si el envío
falla, no se apunta y te vuelve a avisar dentro de 15 minutos. Es el fallo que
quieres: el contrario, marcar y no avisar, te deja sin enterarte y sin rastro.

**04b - Resumen diario**, a las 8:00, también desde Google. Los eventos de hoy y,
debajo, los de los próximos siete días. Solo llega si hoy hay algo: un "hoy no tienes
nada" cada mañana acaba siendo ruido que dejas de leer. El precio es que un día sin
mensaje no te dice si estás libre o si el workflow está parado; para eso, pregúntale.
Lo que sí rompe el silencio es no poder leer el calendario: eso te lo dice.

No lleva tareas sin fecha. Podría, pero no hay forma de marcar una tarea como hecha,
así que la lista solo crecería hasta volverse ruido. Eso pide un botón de "hecho", y
eso es otra fase.

## Cuánto cabe en 3 GB

Esta es la restricción que manda en el proyecto, así que conviene tenerla delante
antes de cambiar nada. Uso real en reposo, con todo levantado:

| | |
|---|---|
| n8n | ~625 MB |
| whisper (`small`, int8) | ~1.000 MB |
| ollama (con el modelo cargado) | ~325 MB |
| qdrant | ~22 MB |
| **total** | **~2,0 GB de 3,0** |

Queda un giga, y ahí es donde caben los picos. No es mucho: hay una ejecución muerta
con `possible out-of-memory issue` en el historial para demostrarlo.

De ahí salen dos ajustes que parecen raros y no lo son. **`OLLAMA_KEEP_ALIVE=5m`**, en
vez de las 24 horas que se suelen poner: el modelo de embeddings se usa unas pocas
veces al día y no tiene sentido que ocupe memoria el resto del tiempo; recargarlo
cuesta un segundo. Y **`embeddinggemma` en vez de `bge-m3`**, que es mejor modelo: son
622 MB contra 1,2 GB, y buscando entre unos cientos de notas la diferencia entre los
dos no se nota. La que sí se notaría es la de quedarse sin RAM.

Si algún día le añades memoria, el primer sitio donde se nota no son los embeddings:
es subir Whisper de `small` a `medium`. `small` se come palabras en español —en el
vault hay un *"Cuérdame mañana comprar pan"* por *"Recuérdame"*— y eso pasa en cada
nota que dictas.

### Si corre en LXC

`docker stats` miente dentro de un LXC: lee los cgroups del host y te enseña un
límite que no existe, con contenedores al 200% de un tope que nadie aplica. Fíate del
uso absoluto y de `free`, no del porcentaje.

Y la swap del contenedor no se toca desde dentro: un swapfile no funciona en LXC
porque no hay loop device. Se define en el host, con `pct set <vmid> -swap 2048` y un
reinicio del contenedor.

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
Gemini las notas recuperadas, esas también salen. Y cuando mira la agenda, salen los
títulos de tu calendario, también los que apuntaste a mano y los de las invitaciones.
Si te incomoda, cambia el nodo Google Gemini Chat Model por Ollama Chat Model y no se
toca nada más del flujo. El resto del sistema ya es local, salvo el propio calendario.

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
4. **Los avisos.** ✅ Recordatorios de los eventos que se acercan, con repesca de
   los que se escaparon si el bot estuvo parado, y el parte de las 8:00.
5. **Cancelar y olvidar.** ✅ Anular una cita o tirar una nota desde el chat, con
   confirmación y sin perder nada. Hasta aquí, el bot solo sabía añadir.

6. **El calendario.** ✅ Lo que tiene fecha pasa a Google Calendar: lo ves y lo
   cambias desde cualquier sitio, y Alfred lee de ahí para la agenda, los avisos y el
   resumen. El vault se queda con notas y tareas.

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
- El latido lee el estado de la pregunta por la API de n8n, con la credencial
  `n8n API`. Si esa key caduca o la borras, el latido se calla en la primera vuelta:
  el "escribiendo…" vuelve a durar cinco segundos y los fallos vuelven a ser
  silenciosos, sin ningún error a la vista.
- Por la misma razón, cada pregunta deja **dos** ejecuciones de `02b` en el
  historial: la que contesta y su latido. Es normal. El latido no gasta peticiones a
  Gemini.
- `latido: true` en la entrada de `02b` está reservado. Si algún día otro workflow
  le pasa ese campo, `02b` lo tomará por un latido y no procesará el mensaje.
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
- **No leas el binario a mano.** n8n puede guardar el contenido de un fichero en
  disco en vez de dentro del item, y lo decide él (`binaryMode: "separate"` aparece
  solo en los ajustes del workflow). Cuando lo hace, `item.binary.data.data` no es
  el fichero en base64: es la cadena literal `filesystem-v2`, y el contenido vive en
  `binary_data/` bajo un id. Un `Buffer.from(..., 'base64')` sobre eso no falla, que
  es lo peor: devuelve basura en silencio. Por eso los workflows que leen el vault
  pasan por un nodo **Extract From File**, que resuelve los dos modos. Costó una
  agenda que decía "no hay ningún evento" con el evento guardado al lado.
- Y su gemela: **Extract From File se queda solo con la clave que le pides y tira el
  resto del json**, el `fileName` incluido. Si necesitas saber de qué fichero venía
  cada texto —y lo necesitas en cuanto quieras escribir en él— hay que ir a buscarlo
  al nodo de lectura y emparejar por posición, que el orden de los items se respeta.
  Sin eso, `avisado: true` acaba en un `/vault/sin-nombre.md` y el aviso se repite
  cada quince minutos para siempre.
- Los mensajes escritos entran por la rama **falsa** de *Es nota de voz*, que hasta
  la fase 3 no iba a ningún sitio. Si la desconectas, el bot se queda mudo ante todo
  lo que no sea audio, y sin error: el mensaje simplemente se evapora.

- Los dos workflows de la fase 4 llevan **Schedule Trigger**, así que no hacen nada
  hasta que los activas con el toggle. Importarlos no basta, y no avisan de que no
  están avisando.
- El `chat_id` de los avisos sale de `TELEGRAM_ALLOWED_USER_ID`, porque en un chat
  privado el chat id y tu user id son el mismo número. Si algún día hablas con el bot
  desde un grupo, los avisos seguirán llegando a tu chat privado.
- El campo `avisado` de las notas antiguas ya no lo mira nadie. Lo avisado vive en el
  `staticData` de `04a`, que solo se guarda en ejecuciones de producción: si lanzas
  `04a` a mano para probarlo, te avisará cada vez de lo mismo.

- El calendario se pide por la API de Google con nodos **HTTP Request**, no con el
  nodo de Google Calendar. El nodo exige el id del calendario, que es tu correo, y no
  acepta el alias `primary`; con HTTP se usa `primary` y el correo no acaba en un
  repo público. La credencial es la misma (*predefined credential type*).
- Al crear un nodo HTTP por MCP, n8n avisa de que se salta la asignación automática
  de credenciales. Por si acaso, se la pone después un `setNodeCredential`. Si un nodo
  se queda sin credencial, como va con `onError` en continuar, lo único que verías es
  "no he podido leer el calendario".
- `timeMin` en la API de Google filtra por el **fin** del evento, no por el inicio.
  Los nodos Code vuelven a filtrar por inicio; no te fíes solo de la petición.
- Google devuelve los eventos de todo el día con `start.date` y sin hora, y su
  `end.date` es **exclusivo**: un evento del sábado al domingo acaba el lunes. Al
  crear uno hay que sumar un día al último; al leerlo, restarlo. Los nodos Code los
  marcan como `todoElDia`: en la agenda salen como "del sábado al domingo, todo el
  día", el resumen los enseña cada día que siguen en marcha y los avisos los saltan.
- "Este finde" sale de la tabla de anclas, no del modelo: si ya es sábado o domingo
  es el que está en curso, y si no el siguiente. Sin esa línea, un domingo el
  modelo apuntaba el finde de la semana que viene.
- Los eventos de Google tienen dueño fuera de Alfred: los que creas a mano conservan
  sus recordatorios, así que de esos te avisan Google y Telegram. Los que crea Alfred
  van sin recordatorios a propósito.
- Una invitación que te mandan entra en tu calendario con el título que quiera quien
  la manda, y ese título llega a Gemini cuando preguntas por la agenda. La agenda solo
  pasa título y hora, nunca la descripción, y el agente solo lee: no tiene ninguna
  herramienta que cree o borre en el calendario.

- Cambiar de modelo de embeddings **obliga a reindexar**, aunque el número de
  dimensiones coincida: los vectores de dos modelos distintos no son comparables y
  Qdrant no tiene forma de saberlo. Se buscaría igual, pero devolvería cualquier
  cosa. `03b - Reindexar` tira la colección y la rehace, que es justo lo que hace
  falta. Y acuérdate de `ollama pull` del modelo nuevo antes, o el reindexado falla
  entero.

- Solo hay **un pendiente a la vez** en `staticData`, y ahora lo comparten las dos
  preguntas con botones: guardar un evento y cancelar algo. Si dictas un evento y sin
  contestar pides cancelar otra cosa, los botones del primero quedan caducados. Por
  eso el pendiente lleva un campo `tipo`: sin él, un "sí" de una pregunta resolvería
  la otra.
- Una búsqueda de borrado que no encuentra nada **no toca el pendiente** que hubiera.
  Es a propósito: pedir que cancele algo que no existe no debería cargarse la
  confirmación de un evento que estabas a medias de guardar.
- Cuidado con el pasado al dictar. *"Ayer cancelé el dentista"* es una nota; *"cancela
  el dentista"* es una orden. El prompt lo explica y ante la duda se queda en `nota`,
  pero es la frontera más fina de las cuatro que distingue.
- Si Qdrant no responde al cancelar, el `.md` queda marcado igual y el punto se queda
  en el índice: la nota estaría cancelada pero el agente aún podría encontrarla al
  buscar. Lo arregla `03b - Reindexar`, que ya salta las canceladas.

- La dirección de Memos, `http://192.168.1.219:5230`, va **escrita en tres sitios**
  de `02b`: la URL de `buscar_memos`, la de `leer_memo` y la descripción de
  `buscar_memos`, que es de donde saca el agente cómo montar los enlaces que te da.
  Si Memos cambia de IP, cambia las tres o te pasará enlaces a una dirección vieja.
- Con Memos las preguntas salen **más caras todavía**. Cada llamada a una
  herramienta es una vuelta más al modelo, y `avisar_busqueda` va antes de cada
  búsqueda y exige esperar su respuesta. Una pregunta que mira en Memos cuesta así
  cuatro peticiones: clasificar, avisar, buscar y contestar. Si el tope diario te
  aprieta, `avisar_busqueda` es lo primero que sobra.
- Las notas de Memos que encuentra el agente **se mandan a Gemini**, igual que lo
  que recupera de Qdrant. Las privadas también: el token ve todo lo que ve tu cuenta.
  Si hay algo en Memos que no quieres fuera de casa, usa un token de una cuenta que
  no lo vea.
- Las descripciones de `buscar_memos` y `leer_memo` le dicen al modelo que el texto
  de las notas es un dato y no una orden. Eso reduce el riesgo de que una nota con
  instrucciones dentro le haga caso, pero no lo elimina. Es otra razón para que el
  acceso sea solo de lectura.

## Estructura

```
secretario/
├─ docker-compose.yml
├─ .env.example
├─ workflows/     # los JSON exportados de n8n
│  ├─ 01-libreta.json       # fase 1, polling simple
│  ├─ 02a-escucha.json      # el bucle de long polling
│  ├─ 02b-secretario.json   # transcribir, clasificar, guardar, contestar
│  ├─ 03a-agenda.json       # herramienta del agente: los eventos de Google Calendar
│  ├─ 03b-reindexar.json    # rehace la colección de qdrant desde el vault
│  ├─ 04a-avisos.json       # cada 15 min, avisa de lo que se acerca
│  ├─ 04b-resumen.json      # el parte de las 8:00
│  └─ 05-migrar-eventos-a-google.json  # una vez: los eventos del vault a Google
├─ prompts/       # system prompts en ficheros aparte, para versionarlos
│  ├─ 01-limpiar-transcripcion.md
│  ├─ 02-clasificar.md
│  └─ 03-agente.md
├─ scripts/       # exportar-workflows.py baja n8n al repo; limpiar-workflow.py, los exports a mano
├─ docs/
└─ vault/         # tus notas (en .gitignore)
```
