# Pokémon Z — antitrampas (fase 1: auditoría)

Esta rama incluye un prototipo de auditoría, no un anti-cheat completo ni un servidor autoritativo. La conexión cooperativa TCP/WebSocket y el protocolo Marshal no cambian. Los participantes todavía tienen el juego instalado.

## Implementado

- Inscripción por el administrador de Pokémon de referencia: sala, rol, UID, especie, habilidad, naturaleza, IV, EV, nivel y muerte.
- Recepción de observaciones NO confiables del Jugador y Coach con su token de sala.
- Alertas persistentes SQLite para UNKNOWN_POKEMON, WRONG_OWNER, IMMUTABLE_CHANGED (especie, habilidad, naturaleza, IV), LEVEL_REGRESSION y UNAUTHORIZED_REVIVAL.
- Un gimnasio confirmado por el administrador concede un crédito de resurrección. Repetir el mismo gimnasio no permite farmear créditos.
- Consulta de alertas con token de administrador.
- Validación de campos y límites de las peticiones.

El motor del juego todavía no envía observaciones automáticamente. Un cliente modificado puede falsificar u omitir observaciones. La auditoría no bloquea cambios ni constituye prueba concluyente de trampa.

## Arranque local (Windows PowerShell)

Desde la raíz del repositorio, con Python 3.10 o superior:

~~~powershell
$env:PZ_ROOMS_JSON = Get-Content .\data\rooms.json -Raw
$env:PZ_ADMIN_TOKEN = python -c "import secrets; print(secrets.token_hex(32))"
$env:PZ_ANTICHEAT_DB = "data/anticheat.sqlite3"
$env:PZ_ANTICHEAT_HOST = "127.0.0.1"
$env:PZ_ANTICHEAT_PORT = "27018"
python anticheat_service.py
~~~

Guardar el token de administrador para ejecuciones posteriores: el comando genera uno nuevo cada vez. No guardarlo en Git ni entregarlo a los jugadores.

El servicio HTTP es independiente del relay de WebSocket porque su biblioteca no acepta peticiones POST con cuerpo. Por defecto escucha solo en localhost:27018. Para acceso remoto se necesita un proxy HTTPS, autenticación, almacenamiento persistente y pruebas adicionales. No exponer HTTP sin TLS a internet.

El almacenamiento local de la modalidad gratuita de Render es efímero; una base SQLite en ese disco puede perderse tras un reinicio o despliegue. No utilizarlo para partidas oficiales sin almacenamiento persistente.

## API experimental

Autenticación en cabecera Authorization: Bearer TOKEN; tipo Content-Type: application/json.

| Método | Ruta | Autorización | Función |
| --- | --- | --- | --- |
| POST | /anticheat/enroll | Admin | Inscribir Pokémon revisado |
| POST | /anticheat/observe | Token de rol | Enviar lista de Pokémon observados |
| POST | /anticheat/gym | Admin | Registrar gimnasio y crédito |
| POST | /anticheat/revive | Admin | Consumir crédito y autorizar resurrección |
| GET | /anticheat/alerts?room=PRUEBA01 | Admin | Consultar incidencias |

Ejemplo para enroll:

~~~json
{
  "room": "PRUEBA01",
  "role": "player",
  "pokemon": {
    "uid": "captura_0001",
    "species": "Gengar",
    "ability": "Levitate",
    "nature": "Modest",
    "ivs": {"hp":12,"attack":12,"defense":12,"sp_attack":12,"sp_defense":12,"speed":12},
    "evs": {"hp":0,"attack":0,"defense":0,"sp_attack":0,"sp_defense":0,"speed":0},
    "level": 30,
    "dead": false
  }
}
~~~

Observe utiliza la misma estructura, pero pokemon contiene una lista. Gym recibe room y gym_id; revive recibe room y uid.

El UID debe ser estable y provenir de una captura verificada. Nunca inscribir automáticamente un Pokémon a partir de una petición de cliente. En esta fase el organizador valida manualmente inscripciones y gimnasios.

## Pruebas

~~~powershell
python -m unittest discover -s tests -v
~~~

Los tests cubren cambios de IV/habilidad, roles, Pokémon desconocidos, regresiones de nivel, resurrecciones, repetición de gimnasios, persistencia y flujo HTTP autenticado.

## Pendiente antes del torneo

1. Integrar exportación de estado desde el motor Pokémon Z, incluyendo cajas del PC, con UID inmutable.
2. Pasar al servidor la autorización de capturas, regalos, aleatorización y reglas de ruta.
3. Validar resultados de combate, muertes y victorias a partir de estado autoritativo; no confiar en resultados enviados por el cliente.
4. Detectar informes ausentes, desconexiones e inconsistencias entre Jugador y Coach.
5. Añadir almacenamiento persistente, copias de seguridad y un panel de incidencias.
6. Probar el juego completo y corregir falsos positivos antes de activar sanciones.

No sancionar automáticamente: una alerta requiere revisión humana.
