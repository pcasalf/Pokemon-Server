#==============================================================================
# Pokemon Z Cooperativo - Red (TCP no bloqueante sobre Winsock)
#------------------------------------------------------------------------------
# Un jugador es ANFITRION (abre el puerto y espera) y el otro INVITADO (se
# conecta a la IP del anfitrion). Los mensajes son [tipo, datos] serializados
# con Marshal y precedidos de su longitud (4 bytes).
#
# Uso desde otros mods:
#   CoopNet.on(:tipo) { |datos| ... }   -> registrar receptor
#   CoopNet.send_msg(:tipo, datos)      -> enviar al otro jugador
#   CoopNet.connected?  CoopNet.host?  CoopNet.guest?
#
# La red se atiende sola en cada Graphics.update, en cualquier pantalla.
#==============================================================================
module CoopNet
  AF_INET        = 2
  SOCK_STREAM    = 1
  IPPROTO_TCP    = 6
  SOL_SOCKET     = 0xFFFF
  SO_REUSEADDR   = 4
  TCP_NODELAY    = 1
  FIONBIO        = 0x8004667E - 0x100000000   # como entero con signo
  WSAEWOULDBLOCK = 10035
  WSAEINPROGRESS = 10036
  WSAEALREADY    = 10037
  WSAEISCONN     = 10056
  INVALID        = -1

  @api = {}
  def self.api(name, args, ret)
    @api[name] ||= Win32API.new("ws2_32", name, args, ret)
    return @api[name]
  end

  # Llama a una funcion de Winsock y devuelve el resultado como entero con
  # signo de 32 bits: el motor devuelve -1 como 4294967295.
  def self.ccall(name, args, ret, *params)
    v = api(name, args, ret).call(*params)
    v = v.to_i
    v -= 0x100000000 if v >= 0x80000000
    return v
  end

  #--------------------------------------------------------------------------
  # Estado
  #--------------------------------------------------------------------------
  @role       = nil     # :host / :guest / nil
  @listen     = INVALID
  @sock       = INVALID
  MAX_MESSAGE = 8 * 1024 * 1024   # ningun mensaje normal se acerca a esto
  @state      = :off    # :off :listening :connecting :handshake :online
  @inbuf      = ""
  @outbuf     = ""
  @handlers   = {}
  @last_recv  = 0
  @last_ping  = 0
  @peer_name  = nil
  @status_msg = ""
  @wsa_ready  = false
  @in_poll    = false
  @tick       = 0       # reloj propio: Graphics.frame_count se reinicia
                        # al empezar partida nueva o cargar

  class << self
    attr_reader :role, :state, :peer_name, :tick
    attr_accessor :status_msg
  end

  def self.host?;      return @role == :host;  end
  def self.guest?;     return @role == :guest; end
  def self.active?;    return @state != :off;  end
  def self.connected?; return @state == :online; end

  #--------------------------------------------------------------------------
  # Receptores de mensajes
  #--------------------------------------------------------------------------
  def self.on(type, &block)
    (@handlers[type] ||= []).push(block)
  end

  def self.dispatch(type, data)
    list = @handlers[type]
    return if !list
    for h in list
      begin
        h.call(data)
      rescue StandardError => e
        ModLoader.log("Coop: error en receptor #{type}: #{e.class} #{e.message}\n" +
                      (e.backtrace || [])[0, 4].join("\n"))
      end
    end
  end

  #--------------------------------------------------------------------------
  # Utilidades Winsock
  #--------------------------------------------------------------------------
  def self.wsa_init
    return if @wsa_ready
    data = "\0" * 512
    ccall("WSAStartup", "ip", "i", 0x0202, data)
    @wsa_ready = true
  end

  def self.last_error
    return api("WSAGetLastError", "", "i").call
  end

  def self.sockaddr(ip, port)
    parts = ip.to_s.strip.split(".")
    raise ArgumentError, "IP no valida: #{ip}" if parts.length != 4
    bytes = []
    for p in parts
      n = p.to_i
      raise ArgumentError, "IP no valida: #{ip}" if n < 0 || n > 255 || p !~ /^\d+$/
      bytes.push(n)
    end
    return [AF_INET, port].pack("vn") + bytes.pack("C4") + ("\0" * 8)
  end

  def self.new_socket
    s = ccall("socket", "iii", "l", AF_INET, SOCK_STREAM, IPPROTO_TCP)
    raise "No se pudo crear el socket (#{last_error})" if s == INVALID
    one = [1].pack("l")
    ccall("setsockopt", "liipi", "i", s, IPPROTO_TCP, TCP_NODELAY, one, 4)
    return s
  end

  def self.set_nonblocking(s)
    arg = [1].pack("L")
    ccall("ioctlsocket", "llp", "i", s, FIONBIO, arg)
  end

  def self.close_socket(s)
    ccall("closesocket", "l", "i", s) if s != INVALID
  end

  #--------------------------------------------------------------------------
  # Arranque
  #--------------------------------------------------------------------------
  def self.start_host(port = CoopConfig::PORT)
    disconnect(false)
    wsa_init
    s = new_socket
    one = [1].pack("l")
    ccall("setsockopt", "liipi", "i", s, SOL_SOCKET, SO_REUSEADDR, one, 4)
    addr = [AF_INET, port].pack("vn") + "\0\0\0\0" + ("\0" * 8)  # 0.0.0.0
    if ccall("bind", "lpi", "i", s, addr, 16) != 0
      err = last_error
      close_socket(s)
      raise "No se pudo abrir el puerto #{port} (error #{err}). " +
            "Quiza ya hay otra partida abierta como anfitrion."
    end
    ccall("listen", "li", "i", s, 1)
    set_nonblocking(s)
    @listen = s
    @role   = :host
    @state  = :listening
    @status_msg = "Esperando al invitado en el puerto #{port}..."
  end

  def self.start_guest(ip, port = CoopConfig::PORT)
    disconnect(false)
    wsa_init
    addr = sockaddr(ip, port)
    s = new_socket
    set_nonblocking(s)
    r = ccall("connect", "lpi", "i", s, addr, 16)
    if r != 0
      err = last_error
      if err != WSAEWOULDBLOCK && err != WSAEINPROGRESS && err != WSAEALREADY
        close_socket(s)
        raise "No se pudo conectar a #{ip}:#{port} (error #{err})"
      end
    end
    @sock  = s
    @role  = :guest
    @state = :connecting
    @connect_started = @tick
    @status_msg = "Conectando con #{ip}:#{port}..."
  end

  def self.disconnect(notify = true, reason = nil)
    if notify && @sock != INVALID && @state == :online
      begin
        send_msg(:bye, reason)
        flush
      rescue
      end
    end
    close_socket(@sock)   if @sock != INVALID
    close_socket(@listen) if @listen != INVALID
    was_online = (@state == :online)
    @sock = INVALID; @listen = INVALID
    @inbuf = ""; @outbuf = ""
    @state = :off
    @role = nil
    @peer_name = nil
    @status_msg = reason ? reason.to_s : "Desconectado"
    dispatch(:disconnected, reason) if was_online
  end

  #--------------------------------------------------------------------------
  # Envio
  #--------------------------------------------------------------------------
  def self.send_msg(type, data = nil)
    return false if @sock == INVALID
    return false if @state != :online && @state != :handshake
    payload = Marshal.dump([type, data])
    @outbuf << [payload.length].pack("N") << payload
    flush
    return true
  end

  def self.flush
    return if @sock == INVALID || @outbuf.length == 0
    loop do
      break if @outbuf.length == 0
      chunk = @outbuf[0, 8192]
      n = ccall("send", "lpii", "i", @sock, chunk, chunk.length, 0)
      if n > 0
        @outbuf = @outbuf[n, @outbuf.length - n] || ""
      else
        err = last_error
        lost("Error al enviar (#{err})") if err != WSAEWOULDBLOCK
        break
      end
    end
  end

  #--------------------------------------------------------------------------
  # Bucle (se llama en cada fotograma)
  #--------------------------------------------------------------------------
  def self.poll
    @tick += 1
    return if @state == :off || @in_poll
    @in_poll = true
    begin
      case @state
      when :listening  then poll_accept
      when :connecting then poll_connect
      end
      if @state == :handshake || @state == :online
        flush
        poll_recv
        poll_keepalive
      end
    rescue Exception => e
      raise if e.is_a?(SystemExit)
      ModLoader.log("Coop: error de red #{e.class} #{e.message}\n" +
                    (e.backtrace || [])[0, 4].join("\n"))
      # cortar la conexion para no repetir el mismo error cada fotograma
      @in_poll = false
      lost("Error interno de red: #{e.message}")
    ensure
      @in_poll = false
    end
  end

  def self.poll_accept
    s = ccall("accept", "lll", "l", @listen, 0, 0)
    return if s == INVALID
    set_nonblocking(s)
    one = [1].pack("l")
    ccall("setsockopt", "liipi", "i", s, IPPROTO_TCP, TCP_NODELAY, one, 4)
    @sock = s
    close_socket(@listen)
    @listen = INVALID
    @state = :handshake
    @last_recv = @tick
    @status_msg = "Invitado conectado, comprobando version..."
  end

  def self.poll_connect
    # select() con espera 0 para ver si el connect ha terminado
    fdset_w = [1, @sock].pack("LL") + ("\0" * 4 * 63)
    fdset_e = [1, @sock].pack("LL") + ("\0" * 4 * 63)
    fdset_r = [0].pack("L") + ("\0" * 4 * 64)
    tv = [0, 0].pack("ll")
    r = ccall("select", "ipppp", "i", 0, fdset_r, fdset_w, fdset_e, tv)
    if r > 0
      if fdset_e.unpack("L")[0] > 0
        lost("El anfitrion no responde (conexion rechazada)")
        return
      end
      if fdset_w.unpack("L")[0] > 0
        @state = :handshake
        @last_recv = @tick
        @status_msg = "Conectado, comprobando version..."
        send_msg(:hello, { :version => CoopConfig::VERSION, :name => local_name })
      end
    elsif @tick - @connect_started > 60 * 10
      lost("Tiempo de conexion agotado (10 s)")
    end
  end

  def self.poll_recv
    buf = "\0" * 16384
    closed = nil
    6.times do
      n = ccall("recv", "lpii", "i", @sock, buf, buf.length, 0)
      if n > 0
        @inbuf << buf[0, n]
        @last_recv = @tick
      elsif n == 0
        closed = "El otro jugador ha cerrado la conexion"
        break
      else
        err = last_error
        closed = "Conexion perdida (#{err})" if err != WSAEWOULDBLOCK
        break
      end
    end
    # Procesar lo recibido antes de dar por cerrada la conexion, para no
    # perder el ultimo mensaje (por ejemplo el motivo de la desconexion)
    sock_before = @sock
    process_inbuf
    # (si un receptor ha cerrado o reabierto la conexion, no tocarla)
    lost(closed) if closed && @state != :off && @sock == sock_before
  end

  def self.process_inbuf
    # Extraer mensajes completos
    while @inbuf.length >= 4
      len = @inbuf[0, 4].unpack("N")[0]
      if len > MAX_MESSAGE
        lost("Mensaje demasiado grande (#{len} bytes): conexion cortada")
        return
      end
      break if @inbuf.length < 4 + len
      payload = @inbuf[4, len]
      @inbuf = @inbuf[4 + len, @inbuf.length - 4 - len] || ""
      begin
        msg = Marshal.load(payload)
      rescue StandardError => e
        ModLoader.log("Coop: mensaje corrupto #{e.message}")
        next
      end
      if !msg.is_a?(Array) || !msg[0].is_a?(Symbol)
        ModLoader.log("Coop: mensaje con formato raro, se ignora")
        next
      end
      handle_message(msg[0], msg[1])
      return if @state == :off
    end
  end

  def self.poll_keepalive
    now = @tick
    if now - @last_ping > CoopConfig::PING_FRAMES
      @last_ping = now
      send_msg(:ping) if @state == :online
    end
    if now - @last_recv > CoopConfig::TIMEOUT_FRAMES
      lost("El otro jugador no responde")
    end
  end

  def self.lost(reason)
    disconnect(false, reason)
  end

  #--------------------------------------------------------------------------
  # Saludo inicial y mensajes de sistema
  #--------------------------------------------------------------------------
  def self.local_name
    return ($Trainer && $Trainer.name) ? $Trainer.name : "Jugador"
  end

  def self.handle_message(type, data)
    # Hasta completar el saludo solo valen los mensajes del saludo
    if @state != :online && ![:hello, :welcome, :reject, :bye, :ping].include?(type)
      return
    end
    case type
    when :hello   # (anfitrion) llega el invitado
      return if !host? || @state != :handshake || !data.is_a?(Hash)
      if data[:version] != CoopConfig::VERSION
        send_msg(:reject, "Version distinta: anfitrion #{CoopConfig::VERSION}, " +
                          "invitado #{data[:version]}")
        flush
        lost("El invitado tiene otra version (#{data[:version]})")
        return
      end
      @peer_name = data[:name].to_s[0, 24]
      send_msg(:welcome, { :version => CoopConfig::VERSION, :name => local_name })
      go_online
    when :welcome # (invitado) el anfitrion acepta
      return if host? || @state != :handshake || !data.is_a?(Hash)
      if data[:version] != CoopConfig::VERSION
        send_msg(:reject, "Version distinta: invitado #{CoopConfig::VERSION}, " +
                          "anfitrion #{data[:version]}")
        flush
        lost("El anfitrion tiene otra version (#{data[:version]})")
        return
      end
      @peer_name = data[:name].to_s[0, 24]
      go_online
    when :reject
      lost(data.to_s)
    when :bye
      lost(data ? data.to_s : "El otro jugador se ha desconectado")
    when :ping
      # nada, solo mantiene viva la conexion
    else
      dispatch(type, data)
    end
  end

  def self.go_online
    @state = :online
    @status_msg = "Conectado con #{@peer_name}"
    dispatch(:connected, @peer_name)
  end
end

#------------------------------------------------------------------------------
# Atender la red en cada fotograma, este donde este el juego
#------------------------------------------------------------------------------
module Graphics
  class << self
    if !method_defined?(:coop_net_update)
      alias coop_net_update update
    end
    def update(*args)
      coop_net_update(*args)
      CoopNet.poll
    end
  end
end
