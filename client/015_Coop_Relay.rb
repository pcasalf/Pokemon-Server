# Servidor central de salas. Conserva el protocolo Marshal entre los dos juegos.
# El servidor solo autentica la sala/rol y retransmite tramas; no valida Pokemon.
module CoopRelay
  PORT = 27016
  PROFILE = "Mods/torneo_relay.cfg"
  def self.profile
    ret = {}
    if File.exist?(PROFILE)
      File.open(PROFILE, "rb") do |f|
        f.each_line do |line|
          k, v = line.strip.split("=", 2)
          ret[k] = v if k && v
        end
      end
    end
    return ret
  rescue StandardError
    return {}
  end

  def self.error(code)
    return {
      "ACCESS" => "La sala o la clave de acceso no son correctas.",
      "ROLE_BUSY" => "Ese rol ya esta conectado en esta sala.",
      "VERSION" => "Los dos jugadores necesitan la misma version del juego.",
      "PAIR_TIMEOUT" => "Se agoto la espera del otro jugador.",
      "FULL" => "El servidor esta lleno. Intentalo mas tarde."
    }[code] || "El servidor ha rechazado la conexion (#{code})."
  end
end

module CoopNet
  class << self
    alias relay_direct_send_msg send_msg
    alias relay_direct_process_inbuf process_inbuf
    alias relay_direct_poll_keepalive poll_keepalive
    alias relay_direct_disconnect disconnect
    attr_reader :tournament_role, :relay_room
  end

  def self.relay?; return @relay_mode ? true : false; end

  def self.start_relay(ip, room, role, token, name, port = CoopRelay::PORT)
    raise "Codigo de sala no valido" if room !~ /\A[A-Z0-9]{6,16}\z/
    raise "Rol no valido" if !["player", "coach"].include?(role)
    raise "Clave de acceso no valida" if token !~ /\A[0-9a-f]{48}\z/
    raise "Puerto no valido" if port.to_i < 1 || port.to_i > 65535
    raise "Nombre no valido" if !name || name.length == 0 || name.length > 96
    version = CoopConfig::VERSION.to_s
    raise "Version no valida" if version !~ /\A[A-Za-z0-9_.-]{1,32}\z/
    start_guest(ip, port.to_i)
    @role = role == "player" ? :host : :guest
    @relay_mode = true
    @relay_ready = false
    @relay_room = room
    @tournament_role = role
    @relay_started = @tick
    @relay_login = ["PZRELAY", "1", room, role, version,
                    name.unpack("H*")[0], token, "END"].join(" ") + "\n"
    @status_msg = "Conectando al servidor del torneo..."
  end

  def self.disconnect(notify = true, reason = nil)
    relay_direct_disconnect(notify, reason)
  ensure
    @relay_mode = false
    @relay_ready = false
    @relay_login = nil
    @relay_room = nil
    @tournament_role = nil
  end

  def self.send_msg(type, data = nil)
    if @relay_mode && !@relay_ready
      # poll_connect manda hello al terminar TCP; lo sustituimos por acceso al relay.
      if type == :hello && @state == :handshake && @relay_login
        @outbuf << @relay_login
        @relay_login = nil
        flush
        @status_msg = "Esperando pareja en sala #{@relay_room}..."
        return true
      end
      return false
    end
    return relay_direct_send_msg(type, data)
  end

  def self.process_inbuf
    if @relay_mode && !@relay_ready
      loop do
        i = @inbuf.index("\n")
        if !i
          lost("Respuesta del servidor demasiado larga") if @inbuf.length > 1024
          return
        end
        if i > 1024
          lost("Respuesta del servidor demasiado larga")
          return
        end
        line = @inbuf[0, i]
        @inbuf = @inbuf[i + 1, @inbuf.length - i - 1] || ""
        if line == "WAIT"
          @status_msg = "Esperando pareja en sala #{@relay_room}..."
        elsif line == "READY"
          @relay_ready = true
          @last_recv = @tick
          @status_msg = "Pareja encontrada; comprobando version..."
          # Jugador conserva :host y Coach :guest para los mods existentes.
          relay_direct_send_msg(:hello, { :version => CoopConfig::VERSION,
                                         :name => local_name }) if guest?
          break
        elsif line[0, 6] == "ERROR "
          lost(CoopRelay.error(line[6, line.length - 6]))
          return
        else
          lost("Respuesta del servidor no valida")
          return
        end
      end
    end
    relay_direct_process_inbuf
  end

  def self.poll_keepalive
    if @relay_mode && !@relay_ready
      lost("Tiempo de espera de la pareja agotado") if @tick - @relay_started > 60 * 185
      return
    end
    relay_direct_poll_keepalive
  end
end
