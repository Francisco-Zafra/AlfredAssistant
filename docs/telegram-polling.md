# Telegram sin abrir puertos

El nodo **Telegram Trigger** de n8n funciona por webhook: Telegram llama a una URL
pública tuya con HTTPS y certificado válido. Como todo esto vive detrás de la VPN y
no hay nada expuesto, ese camino está cerrado.

La alternativa es **long polling**: n8n abre una petición a Telegram y la deja
colgada hasta 50 segundos; Telegram responde en el instante en que llega un mensaje.
Solo hay tráfico saliente, así que no hace falta dominio, ni certificado, ni reenviar
puertos, ni que tu IP pública sea estable, y la latencia es prácticamente cero.

Se descartó el webhook porque obliga a que algo tuyo sea alcanzable desde internet
(puerto abierto o túnel), y esto es la única forma de tener entrega inmediata sin eso.

## Antes de empezar

Si en algún momento llegaste a registrar un webhook para este bot, hay que quitarlo,
porque `getUpdates` y los webhooks son excluyentes. Una sola vez, desde cualquier sitio:

```
curl "https://api.telegram.org/bot<TU_TOKEN>/deleteWebhook"
```

## Cómo se mantiene viva la petición

El Schedule Trigger de n8n no sirve para long polling: dispara por reloj sin esperar a
que termine la ejecución anterior, así que a 50 segundos de espera tendrías dos
`getUpdates` solapados y Telegram devuelve 409.

La solución es **encadenar el workflow consigo mismo**. `02a - Escucha` termina
llamándose a sí mismo con *Execute Workflow*, sin esperar respuesta: en cuanto un poll
acaba, arranca el siguiente. Sin huecos.

```
Arranque en cadena ─┐
                    ├─> Leer offset -> getUpdates (timeout=50) -> Avanzar offset ─┬─> Volver a escuchar ──┐
Rescate 1 min ──────┘                                                             │                       │
  └─ ¿Se ha parado? ─┘                                                            └─> Repartir -> Encolar │
                                                                                                          │
   └──────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### El offset NO puede salir del almacén estático

n8n guarda `staticData` **al terminar** la ejecución. El siguiente eslabón de la
cadena arranca antes de eso, así que si leyera el offset de ahí se encontraría el
valor viejo y volvería a procesar los mismos mensajes.

Por eso `Avanzar offset` mete el offset nuevo en su salida y la rellamada se lo pasa
como dato de entrada. `Leer offset` usa lo que le llega y solo cae al almacén estático
cuando no le llega nada, que es el caso del rescate.

### El Schedule de rescate

Si la cadena se rompe —un fallo no capturado, un reinicio a destiempo— el bot se queda
mudo para siempre. Un Schedule cada minuto la revive, pero solo si hace falta:
`Avanzar offset` deja un `ultimoLatido` en el almacén estático y el nodo de rescate no
hace nada si el latido tiene menos de dos minutos. Sin esa guarda arrancarías una
segunda cadena y volveríamos al 409.

Si por lo que sea acabaran corriendo dos cadenas, Telegram devuelve 409 en una de
ellas, esa ejecución muere y el sistema se queda con una sola. Se arregla solo, pero
lo verás en el historial de errores.

### Los dos workflows

`02a - Escucha` solo lee y reparte. `02b - Secretario` hace el trabajo pesado
(descargar, transcribir, clasificar, guardar) y se llama con *Execute Workflow* sin
esperar respuesta, así que una nota de un minuto transcribiéndose no bloquea la
escucha.

Al importarlos hay que rellenar a mano dos campos `workflowId`, porque los ids los
genera n8n al importar: la rellamada de `02a` apunta a sí mismo y el nodo de encolar
apunta a `02b`. Vienen con `PEGA_AQUI_EL_ID_...` para que no se te pasen.

## El compromiso a tener en cuenta

El offset se avanza nada más recibir los mensajes, no al terminar de procesarlos.

El precio es que si n8n se cae entre el reparto y el guardado, ese mensaje se pierde
sin quedar registrado. Para uso personal es asumible, y el propio Telegram te sirve
de copia: el audio sigue en el chat.

Ojo con una consecuencia del acuse de recibo: cuando pides `offset=N`, Telegram borra
de su cola todos los updates con id menor que N. Una vez confirmados desaparecen de su
lado, así que reimportar el workflow y empezar con el offset a cero no revive nada.

## Descargar una nota de voz

Telegram no da la URL directa, hay dos pasos:

1. `GET https://api.telegram.org/bot<TOKEN>/getFile?file_id={{ $json.voice_file_id }}`
   devuelve un `result.file_path`.
2. `GET https://api.telegram.org/file/bot<TOKEN>/{{ $json.result.file_path }}`
   con *Response Format* puesto a **File**, que es lo que luego se le pasa a Whisper.
