# Telegram sin abrir puertos

El nodo **Telegram Trigger** de n8n funciona por webhook: Telegram llama a una URL
pública tuya con HTTPS y certificado válido. Como todo esto vive detrás de la VPN y
no hay nada expuesto, ese camino está cerrado.

La alternativa es **polling**: n8n le pregunta a Telegram cada pocos segundos si hay
mensajes nuevos. Solo hay tráfico saliente, así que no hace falta dominio, ni
certificado, ni reenviar puertos, ni que tu IP pública sea estable.

## Antes de empezar

Si en algún momento llegaste a registrar un webhook para este bot, hay que quitarlo,
porque `getUpdates` y los webhooks son excluyentes. Una sola vez, desde cualquier sitio:

```
curl "https://api.telegram.org/bot<TU_TOKEN>/deleteWebhook"
```

## Los nodos

### 1. Schedule Trigger

Intervalo: cada **5 segundos**. Son unas 17.000 peticiones al día, que a Telegram le
dan igual en un bot personal. Lo que sí cuesta es el historial de ejecuciones de n8n:
ver la poda en `docker-compose.yml`.

Lo técnicamente mejor sería *long polling* (`timeout=25`, la petición se queda
esperando y vuelve en cuanto hay mensaje). No se usa aquí porque el Schedule Trigger
de n8n no espera a que termine la ejecución anterior: dos `getUpdates` solapados
sobre el mismo bot hacen que Telegram devuelva 409 y se corte uno de los dos.

### 2. Code — "leer offset"

Modo: *Run Once for All Items*.

```js
// El offset marca el último update ya procesado. Vive en el almacén
// estático del workflow, así que sobrevive a reinicios de n8n.
const estado = $getWorkflowStaticData('global');
return [{ json: { offset: estado.telegramOffset ?? 0 } }];
```

### 3. HTTP Request — "getUpdates"

- Método: `GET`
- URL: `https://api.telegram.org/bot<TU_TOKEN>/getUpdates`
  (mejor: guarda el token como credencial o variable y usa una expresión)
- Query parameters:
  - `offset` → `={{ $json.offset }}`
  - `timeout` → `0`
  - `allowed_updates` → `["message"]`

### 4. Code — "procesar updates"

Modo: *Run Once for All Items*.

```js
const ALLOWED_USER_ID = 0; // <-- pon aquí tu id numérico de Telegram

const estado = $getWorkflowStaticData('global');
const respuesta = $input.first().json;

if (!respuesta.ok || !respuesta.result || respuesta.result.length === 0) {
  return [];
}

const updates = respuesta.result;

// Avanzamos el offset ANTES de procesar. Ver la nota de abajo sobre el
// compromiso que esto implica.
estado.telegramOffset = Math.max(...updates.map(u => u.update_id)) + 1;

const salida = [];

for (const u of updates) {
  const msg = u.message;
  if (!msg) continue;

  // Puerta de entrada: cualquier otro que encuentre el bot se queda fuera.
  if (msg.from?.id !== ALLOWED_USER_ID) continue;

  salida.push({
    json: {
      update_id: u.update_id,
      chat_id: msg.chat.id,
      message_id: msg.message_id,
      fecha: new Date(msg.date * 1000).toISOString(),
      tipo: msg.voice ? 'voz' : (msg.text ? 'texto' : 'otro'),
      texto: msg.text ?? null,
      // file_id se usa después con getFile para descargar el audio
      voice_file_id: msg.voice?.file_id ?? null,
      voice_duracion: msg.voice?.duration ?? null,
    },
  });
}

return salida;
```

## El compromiso a tener en cuenta

El offset se avanza nada más recibir los mensajes, no al terminar de procesarlos. Es
lo que evita que un poll que llega mientras se transcribe un audio largo vuelva a
coger el mismo mensaje y lo guarde dos veces.

El precio es que si n8n se cae a mitad de procesar una nota, ese mensaje se pierde
sin quedar registrado. Para uso personal es asumible, y el propio Telegram te sirve
de copia: el audio sigue en el chat.

Si algún día te molesta, la solución limpia es partirlo en dos workflows. El de
polling solo lee y encola; un segundo workflow, llamado con **Execute Workflow**,
hace el trabajo pesado y puede reintentar por su cuenta.

## Descargar una nota de voz

Telegram no da la URL directa, hay dos pasos:

1. `GET https://api.telegram.org/bot<TOKEN>/getFile?file_id={{ $json.voice_file_id }}`
   devuelve un `result.file_path`.
2. `GET https://api.telegram.org/file/bot<TOKEN>/{{ $json.result.file_path }}`
   con *Response Format* puesto a **File**, que es lo que luego se le pasa a Whisper.
