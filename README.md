# Servidor local de Pokémon Z — primera fase

**Actualización:** preparada la variante HTTP/WebSocket para Render. Consulta
`RENDER.md`. El servidor TCP local sigue disponible.

Conecta a dos jugadores por sala a través de un servidor central. El Jugador
conserva el papel interno de anfitrión y el Coach el de invitado, para mantener
compatibilidad con el cooperativo. Cada rol tiene una clave de acceso distinta.

Esta entrega autentica acceso a salas, retransmite mensajes y registra conexiones.
**No valida Pokémon, inventarios, guardados ni resultados. No es todavía el sistema
antitrampas del torneo.** El motor sigue resolviendo el combate en los dos clientes.

## Arrancar

Necesitas Python 3.10 o superior, sin instalar paquetes adicionales.

1. Abre `INICIAR-SERVIDOR.cmd`. El primer arranque crea `PRUEBA01` y sus claves.
2. Mantén esa consola abierta. El servidor escucha en `127.0.0.1:27016`.
3. Cierra el juego antes de instalar los dos scripts de `client/` en `Mods/`.
   Para la copia del workspace puedes ejecutar `INSTALAR-EN-PRUEBAS.ps1`.
4. Cada copia del juego recibe únicamente su propio `Mods/torneo_relay.cfg`:
   - Jugador: `data/profiles/PRUEBA01/player/Mods/torneo_relay.cfg`.
   - Coach: `data/profiles/PRUEBA01/coach/Mods/torneo_relay.cfg`.
5. En ambas copias: **Multijugador → Servidor del torneo**. El perfil rellena
   servidor, sala y clave; confirma tu rol y tu nombre. Ambos pulsan Listo en la sala.

Para dos clientes en el mismo ordenador, abre dos carpetas separadas del juego y
coloca el perfil correspondiente en cada una. No copies el perfil de Jugador al Coach.
Si usas dos ordenadores, `127.0.0.1` solo sirve para el del servidor. La conexión por
LAN requiere escuchar en la IP LAN y poner esa IP en los dos perfiles.

La conexión directa anterior sigue en **Multijugador → Conexión directa**.
Durante una partida guardada, el menú cooperativo también ofrece el servidor.
Al reconectar se vuelve a identificar sala/rol; no se recuperan turnos perdidos.

## Otras salas y parámetros

Desde esta carpeta:

```powershell
python server.py init-room --code PAREJA02 --ip 127.0.0.1 --port 27016
python server.py serve --host 127.0.0.1 --port 27016
```

Reinicia el servidor después de crear salas: carga sus claves al arrancar.
Crear una sala existente se rechaza para evitar cambiar sus accesos por accidente.
El archivo `data/rooms.json` contiene todas las claves: se queda en el servidor.
Entrega a cada participante únicamente el perfil de su rol y sala.

## Registro y límites

`data/audit.jsonl` registra entradas, salidas, emparejamientos, rechazos y tamaño/hash
de cada trama por sala y rol. No registra claves ni contenido de Pokémon.
Rota a partir de 10 MiB y conserva dos archivos anteriores. Esto permite investigar
el transporte, pero no reconstruir decisiones ni detectar Pokémon ilegales.

Se permiten 64 conexiones, dos roles por sala, tramas de hasta 8 MiB, 240 tramas/s
y 16 MiB/s por cliente. Se limita la espera de acceso, pareja y tramas incompletas.
Al salir uno, se cierra también la conexión del compañero para no mezclar sesiones.

Esta versión está preparada para pruebas locales. El acceso TCP no lleva cifrado.
Antes de publicarla en Internet faltan el transporte cifrado y la validación del
estado del torneo. El relay no deserializa Marshal; los clientes siguen usando el
protocolo antiguo, por lo que solo deben conectarse participantes de confianza.

## Comprobaciones

```powershell
python -m unittest discover -s tests -v
ruby --disable-gems tests/test_client.rb
```

Las pruebas Python abren sockets TCP reales en loopback. La prueba Ruby carga la
red del juego y el adaptador con sockets simulados: comprueba acceso, roles, saludo,
respuestas fragmentadas, rechazo, limpieza y compatibilidad con conexión directa.
No equivale a completar una partida con dos ventanas del juego.

Validación realizada: 14 pruebas TCP correctas, incluida una con dos procesos Ruby
que cargan el adaptador y se intercambian mensajes Marshal reales. Para repetir ese
caso, define `RUBY_QA` con la ruta del ejecutable Ruby antes de ejecutar unittest;
si no está definido, ese caso se omite explícitamente. La prueba Ruby adicional
también comprueba las rutas del menú y el reinicio de sesión con la interfaz simulada.

## Siguiente fase

Guardar identidades y equipos, y definir eventos de captura/regalo/experiencia para
que el servidor autorice los cambios. Para impedir trampas, las decisiones importantes
deben pasar a una autoridad del servidor; no basta con comprobar datos enviados por
un cliente que el participante puede modificar.
