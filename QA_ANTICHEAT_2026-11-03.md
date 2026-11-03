# QA de seguridad — Pokémon-Server (03/11/2026)

**Alcance:** PR #1 (rama feature/anticheat-audit-mvp), API de auditoría y transporte cooperativo existente, mediante revisión del código y GitHub Actions. Sin prueba visual dentro del juego real ni pruebas de red sobre Render desplegado.

## Verificación automática

- CI más reciente verificado: 36 pruebas en Python, 34 correctas, 2 omitidas por no estar configurado RUBY_QA.
- Los tests abarcan relay TCP, puente WSS, autenticación, restricciones de tamaño, auditoría SQLite, evolución autorizada, revivir por créditos, historial e HTTP.
- Omitidas: prueba de dos clientes Ruby reales en TCP y prueba de adaptadores Ruby por WebSocket. La ausencia de fallos de CI no demuestra que una partida completa funcione.

## Fallos corregidos durante este QA

| ID | Prioridad | Estado | Problema y corrección |
|---|---|---|---|
| QA-01 | Alta | Corregido en rama | Evolución legítima cambiaba especie y se marcaba como modificación inmutable. Ahora se registra UNVERIFIED_EVOLUTION y el administrador puede validar una evolución; queda histórico de cambios. No se valida aún el árbol evolutivo. |
| QA-02 | Media | Corregido en rama | API permitía inscripciones administrativas en salas inexistentes; ahora las rechaza. |
| QA-03 | Alta | Mitigado | API HTTP sin cifrado podía configurarse para escuchar públicamente; ahora solo admite localhost y requiere proxy HTTPS para acceso remoto. |
| QA-04 | Media | Mitigado | Peticiones HTTP incompletas podían bloquear indefinidamente la API monohilo; ahora hay timeout de 5 segundos por lectura. No hay todavía protección completa frente a denegación de servicio. |
| QA-05 | Media | Corregido en rama | Los reportes almacenaban cantidad y alertas, pero no las instantáneas declaradas de cada Pokémon. Se añadió tabla de observations para reconstrucción retrospectiva. Son datos suministrados por clientes, no prueba independiente. |
| QA-06 | Media | Corregido en rama | Endpoint de evolución no permite autorizar cambio aislado de habilidad sin cambio de especie. |

## Problemas aún abiertos: impedirían certificar el sistema antitrampas

| ID | Prioridad | Hallazgo | Impacto |
|---|---|---|---|
| QA-P0-01 | Bloqueante | Pokémon Z todavía no envía informes automáticos al servidor de auditoría. | No hay vigilancia real sin integración del juego. |
| QA-P0-02 | Bloqueante | El cliente decide estado de Pokémon, capturas, RNG y combate; servidor relay retransmite mensajes sin comprobar semántica. | Un cliente manipulado puede enviar eventos falsos, estados ilegales u omitir informes. |
| QA-P0-03 | Bloqueante | Protocolo del juego intercambia objetos Ruby Marshal entre pares. La deserialización de datos recibidos necesita análisis de seguridad y sustitución/control. | Riesgo de procesamiento inseguro de datos no confiables, además de falsificación de acciones. No se confirma explotación; requiere revisión específica del motor. |
| QA-P1-01 | Alta | EV dentro de límites (252 por estadística, 510 total) pueden alterarse sin alerta de evolución de EV. | Trampas de EV pueden pasar desapercibidas. Para distinguir entrenamiento/vitaminas de hacks deben verificarse eventos legítimos. |
| QA-P1-02 | Alta | Informes que omiten Pokémon no generan alerta; tampoco hay cadencia obligatoria ni detección de ausencia de reportes. | Un jugador puede esconder criaturas o dejar de informar. |
| QA-P1-03 | Alta | Solo se comprueba nivel 1–100, no los topes específicos del torneo por ruta/gimnasio. | Un Pokémon ilegalmente sobreleveado puede pasar por válido. |
| QA-P1-04 | Alta | Se permite aprobar manualmente cualquier especie en una evolución; no hay validación automática de cadena evolutiva ni reglas del randomizador. | Un error administrativo puede legalizar un cambio ilegal. |
| QA-P1-05 | Alta | El almacenamiento previsto en disco efímero de Render Free no garantiza persistencia; la API de auditoría tampoco está desplegada. | Pérdida de registros/progreso ante reinicios o despliegues si no se usa DB persistente. |
| QA-P1-06 | Alta | API monohilo y sin límites por origen ni contadores de intentos; tokens de rol estables para reportar. | Denegación de servicio o falsificación/replay de observaciones por alguien con token. |
| QA-P2-01 | Media | Almacenamiento continuo de observaciones sin retención ni copias de seguridad automáticas. | La base de datos puede crecer sin límite. |
| QA-P2-02 | Media | GitHub Actions omite dos pruebas de integración Ruby y no prueba juego visual ni conexión remota real. | Riesgo de bugs de integración aún no detectados. |
| QA-P2-03 | Baja | Prueba del relay sin claves deja un aviso/traceback de cierre WebSocket en logs, aunque el test pasa. | Ruido operativo y posible confusión de diagnóstico. |

## Orden recomendado antes de publicar el torneo

1. Conectar el motor de Pokémon Z y hacer que genere IDs únicos permanentes; reportar equipo y cajas con secuencias verificadas y límites de frecuencia.
2. Convertir la generación de capturas/regalos/evoluciones, semillas RNG y principales cambios de estado en **operaciones autorizadas por el servidor**, no meras declaraciones del cliente.
3. Verificar consistencia de combates, muertes, PP, movimientos, EV y límites de nivel; auditar las reglas específicas del Randomlocke.
4. Migrar a almacenamiento persistente y HTTPS, añadir alertas al organizador, backups, bloqueo de sesiones y rotación de claves.
5. Hacer pruebas adversariales con **dos clientes reales**, guardados manipulados y pérdida de red, no solo tests unitarios.

**Veredicto:** base de auditoría funcional para pruebas controladas; NO APTO todavía como protección antitrampas de un torneo abierto a participantes no confiables.
