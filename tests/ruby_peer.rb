# Prueba de transporte: cliente Ruby real + adaptador, sockets Ruby en vez de Winsock.
require 'socket'
module CoopConfig
 VERSION='integration';PORT=27015;PING_FRAMES=120;TIMEOUT_FRAMES=1800
end
module ModLoader
 def self.log(*);end
end
eval(File.read(File.join(File.dirname(__FILE__),'fixtures/010_Coop_Net.rb')).split("\nmodule Graphics\n",2)[0],TOPLEVEL_BINDING)
module CoopNet
 def self.start_guest(ip,port)
  disconnect(false);@socket=TCPSocket.new(ip,port);@sock=@socket.fileno
  @role=:guest;@state=:connecting;@inbuf='';@outbuf='';@last_recv=@tick
 end
 def self.close_socket(*)
  @socket.close if @socket && !@socket.closed?
 end
 def self.flush
  return if @outbuf.empty?
  @socket.write(@outbuf);@outbuf=''
 end
 def self.socket_tick
  @tick+=1
  begin
   loop do
    data=@socket.read_nonblock(16384)
    @inbuf << data
    @last_recv=@tick
   end
  rescue IO::WaitReadable
  rescue EOFError
   process_inbuf
   return false
  end
  process_inbuf
  return true
 end
end
load File.expand_path('../client/015_Coop_Relay.rb',File.dirname(__FILE__))
role,port,token=ARGV
CoopNet.start_relay('127.0.0.1','PRUEBA01',role,token,role,port.to_i)
CoopNet.instance_variable_set(:@state,:handshake)
CoopNet.send_msg(:hello,{})
done=false;sent=false
CoopNet.on(:qa_probe) do |value|
 raise 'Payload modificado' unless value=={:move=>7,:target=>3}
 CoopNet.send_msg(:qa_ack,value)
 done=true
end
CoopNet.on(:qa_ack) do |value|
 raise 'Respuesta modificada' unless value=={:move=>7,:target=>3}
 done=true
end
limit=Time.now+5
until done
 raise 'Timeout' if Time.now>limit
 alive=CoopNet.socket_tick
 if CoopNet.connected? && role=='player' && !sent
  CoopNet.send_msg(:qa_probe,{:move=>7,:target=>3});sent=true
 end
 raise 'Conexion cerrada antes de recibir respuesta' if !alive && !done
 sleep 0.005
end
CoopNet.disconnect(false)
puts "PASS #{role}: saludo y mensajes Marshal a traves del servidor"
