# Despliegue gratuito en Render

El código preparado añade HTTP `/health` y WebSocket binario `/relay` al relay.
El juego mantiene el adaptador TCP y se conecta a un puente local en 127.0.0.1:27017.
El puente usa WSS con verificación de certificados para llegar a Render; no necesita
desactivar TLS ni añadir bibliotecas al motor Ruby antiguo.

## Servicio

- Nombre propuesto: `pokemon-z-torneo`.
- Repositorio: privado, únicamente esta carpeta de código, sin `data/` ni el juego.
- Runtime: Python.
- Plan: **Free**.
- Región: Frankfurt.
- Build: `pip install -r requirements.txt`.
- Start: `python web_server.py`.
- Puerto: el código usa la variable `PORT` de Render y escucha en 0.0.0.0.
- Health check: `/health`.
- Variable `PYTHON_VERSION`: `3.12.10`.
- Variable privada `PZ_ROOMS_JSON`: contenido del archivo local `data/rooms.json`.

Sin claves, el servicio arranca en modo de preparación: `/health` devuelve
`setup_required` y `/relay` rechaza conexiones con HTTP 503. No genera claves al reiniciar.
No publicar las claves en Git ni incluirlas en capturas. `render.yaml` es una
plantilla alternativa; el despliegue previsto usa creación directa del servicio.

## Después del despliegue

1. Verificar `https://<servicio>.onrender.com/health`: debe devolver `ok`.
2. Ejecutar `python configure_render.py --url https://<servicio>.onrender.com`.
3. En cada copia del juego, poner el perfil correspondiente de
   `data/render-profiles/PRUEBA01/player/Mods/` o `coach/Mods/`.
4. En cada ordenador abrir `INICIAR-PUENTE-RENDER.cmd` y dejarlo funcionando.
5. En el juego: Multijugador → Servidor del torneo; confirmar los datos del perfil.

No usar `INICIAR-SERVIDOR.cmd` para conectarse a Render: ese ejecuta el servidor TCP
local anterior. La opción local sigue funcionando como antes.

## Qué está probado

22 pruebas automatizadas pasan con la dependencia fijada: 14 del relay TCP y 8 de la
entrada WebSocket/puente. Incluyen `/health`, binarios, tramas de 256 KiB repartidas
entre mensajes WebSocket, autenticación, cierre de pareja y dos procesos Ruby con
el adaptador real a través del puente. El transporte de esas pruebas es loopback
sin TLS; el certificado público y el despliegue Render se verifican después de publicarlo.
No se ha probado una partida visual con dos ventanas.

## Límites

El plan gratuito puede dormir y reiniciarse. Las salas activas se pierden al reiniciar
y el juego tiene que reconectar; no se reanudan turnos automáticamente. Los registros
locales de Render son efímeros. Esta entrega no guarda progreso en la nube ni valida
Pokémon: esas funciones requieren el siguiente trabajo de cuentas y persistencia.

## Estado de preparación

Código y pruebas preparados localmente. El acceso a Render está verificado; no hay
servicio creado todavía. Falta un repositorio Git remoto dedicado para subir el código
y que Render pueda construirlo. La integración GitHub disponible no permite crear
repositorios nuevos; la sesión local de GitHub CLI tampoco está autenticada válidamente.
