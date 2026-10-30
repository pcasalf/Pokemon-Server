# Entrada al servidor desde Multijugador y desde el menu cooperativo del mapa.
module CoopRelay
  def self.connect_menu
    cfg = profile
    name = CoopLobby.ask_name
    return nil if !name
    ip = pbEnterText(_INTL("IP del servidor del torneo"), 0, 15, cfg["ip"] || "127.0.0.1")
    return nil if !ip || ip.strip == ""
    room = pbEnterText(_INTL("Codigo de sala"), 0, 16, cfg["room"] || "PRUEBA01")
    return nil if !room || room.strip == ""
    choices = cfg["role"] == "coach" ? ["Coach", "Jugador", "Volver"] : ["Jugador", "Coach", "Volver"]
    selected = Kernel.pbMessage(_INTL("Tu papel en esta pareja"), choices, 3)
    return nil if selected != 0 && selected != 1
    role = choices[selected] == "Coach" ? "coach" : "player"
    # No ofrecer la clave de otro rol como si correspondiese al elegido.
    saved = cfg["role"] == role ? cfg["token"] : nil
    token = pbEnterText(_INTL("Clave de acceso de {1}", choices[selected]), 0, 48, saved || "")
    return nil if !token || token.strip == ""
    CoopNet.start_relay(ip.strip, room.strip.upcase, role, token.strip.downcase,
                        name, (cfg["port"] || PORT).to_i)
    return name
  end
end

class CoopLobby
  class << self
    alias relay_direct_run_inner run_inner
  end
  alias relay_direct_initialize initialize
  alias relay_direct_on_disconnected on_disconnected

  def initialize(name)
    @relay_lobby = CoopNet.relay?
    relay_direct_initialize(name)
  end

  def on_disconnected(reason)
    relay_direct_on_disconnected(reason)
    @restart_host = false if @relay_lobby
  end

  def self.run_inner
    mode = Kernel.pbMessage(_INTL("Multijugador"),
      [_INTL("Servidor del torneo"), _INTL("Conexion directa"), _INTL("Volver")], 3)
    return relay_direct_run_inner if mode == 1
    return false if mode != 0
    name = CoopRelay.connect_menu
    return false if !name
    lobby = CoopLobby.new(name)
    @@current = lobby
    begin
      result = lobby.main
      if result == :start
        CoopSession.pending = { :role => CoopNet.role, :seed => lobby.seed,
          :partner => lobby.peer_name, :my_name => name,
          :relay_room => CoopNet.relay_room, :tournament_role => CoopNet.tournament_role }
        srand(lobby.seed)
        CoopWindowTitle.set("Pokemon Z - Torneo (" + name + ")")
        return true
      end
    ensure
      @@current = nil
    end
    CoopNet.disconnect(true, "Ha salido de la sala") if CoopNet.active?
    Kernel.pbMessage(lobby.exit_message) if lobby.exit_message
    return false
  end
end

module CoopMenu
  class << self
    alias relay_direct_open open
  end
  def self.open
    return relay_direct_open if CoopNet.active?
    mode = Kernel.pbMessage(_INTL("Conectar cooperativo"),
      [_INTL("Servidor del torneo"), _INTL("Conexion directa"), _INTL("Volver")], 3)
    return relay_direct_open if mode == 1
    return if mode != 0
    begin
      name = CoopRelay.connect_menu
      wait_for_connection if name
    rescue StandardError => e
      CoopNet.disconnect(false)
      Kernel.pbMessage(_INTL("No se pudo conectar:\n{1}", e.message))
    end
  end
end
