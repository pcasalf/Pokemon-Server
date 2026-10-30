# Carga la red real y su adaptador con sockets simulados. No necesita el motor.
module CoopConfig
 VERSION='test';PORT=27015;PING_FRAMES=120;TIMEOUT_FRAMES=1800
end
module ModLoader
 def self.log(*);end
end
load_path=File.expand_path('fixtures/010_Coop_Net.rb',File.dirname(__FILE__))
eval(File.read(load_path).split("\nmodule Graphics\n",2)[0],TOPLEVEL_BINDING)
module CoopNet
 class << self
  attr_accessor :sent_bytes
  def close_socket(*);end
  def flush;@sent_bytes||='';@sent_bytes<<@outbuf;@outbuf='';end
  def start_guest(ip,port)
   disconnect(false);@sock=9;@role=:guest;@state=:connecting
   @inbuf='';@outbuf='';@sent_bytes='';@last_ping=@tick
  end
 end
end
load File.expand_path('../client/015_Coop_Relay.rb',File.dirname(__FILE__))
def assert(x);raise 'FAIL' unless x;end
def start(role)
 CoopNet.start_relay('127.0.0.1','PRUEBA01',role,'a'*48,'QA')
 CoopNet.instance_variable_set(:@state,:handshake)
 assert(CoopNet.send_msg(:hello,{}))
 assert(CoopNet.sent_bytes.start_with?('PZRELAY 1 PRUEBA01 '+role+' test 5141 '))
end
def receive(s)
 CoopNet.instance_variable_set(:@inbuf,CoopNet.instance_variable_get(:@inbuf)+s)
 CoopNet.process_inbuf
end
start('player');assert(CoopNet.host?);assert(!CoopNet.send_msg(:pos,{}))
receive("WA");assert(!CoopNet.connected?)
receive("IT\nREADY\n");assert(CoopNet.state==:handshake)
hello=Marshal.dump([:hello,{:version=>'test',:name=>'Coach'}])
receive([hello.length].pack('N')+hello);assert(CoopNet.connected? && CoopNet.host?)
assert(CoopNet.peer_name=='Coach')
CoopNet.disconnect(false);assert(!CoopNet.relay? && CoopNet.tournament_role.nil?)
start('coach');receive("WAIT\nREADY\n")
assert(CoopNet.sent_bytes.include?(Marshal.dump([:hello,{:version=>'test',:name=>'Jugador'}])))
welcome=Marshal.dump([:welcome,{:version=>'test',:name=>'Jugador'}])
receive([welcome.length].pack('N')+welcome);assert(CoopNet.connected? && CoopNet.guest?)
start('player');receive("ERROR ACCESS\n");assert(!CoopNet.active?)
start('player');receive('X'*1025);assert(!CoopNet.active?)
CoopNet.start_guest('127.0.0.1',27015);CoopNet.instance_variable_set(:@state,:handshake)
CoopNet.send_msg(:hello,{:version=>'test'})
assert(CoopNet.sent_bytes.include?(Marshal.dump([:hello,{:version=>'test'}])))
puts 'PASS: login, roles, gating, fragmented WAIT, READY, host/guest handshake, cleanup, rejection, bounds, direct mode'
module Kernel
 class << self
  attr_accessor :relay_test_choices
  def pbMessage(*);(@relay_test_choices||[]).shift;end
 end
end
def _INTL(text,*);text;end
module CoopSession
 class << self;attr_accessor :pending;end
end
module CoopWindowTitle
 def self.set(*);end
end
class CoopLobby
 def self.run_inner;:direct;end
 def initialize(name);@was_host=CoopNet.host?;end
 def on_disconnected(*);@restart_host=@was_host;end
 def main;:start;end
 def seed;123;end
 def peer_name;'Coach';end
 def exit_message;nil;end
end
module CoopMenu
 def self.open;:direct;end
 def self.wait_for_connection;:wait;end
end
load File.expand_path('../client/045_Coop_Relay_Menu.rb',File.dirname(__FILE__))
module CoopRelay
 def self.connect_menu;'QA';end
end
Kernel.relay_test_choices=[1];assert(CoopLobby.run_inner==:direct)
start('player');Kernel.relay_test_choices=[0]
assert(CoopLobby.run_inner==true)
assert(CoopSession.pending[:tournament_role]=='player')
assert(CoopSession.pending[:relay_room]=='PRUEBA01' && CoopSession.pending[:seed]==123)
lobby=CoopLobby.new('QA');lobby.on_disconnected('salida')
assert(lobby.instance_variable_get(:@restart_host)==false)
CoopNet.disconnect(false);Kernel.relay_test_choices=[1];assert(CoopMenu.open==:direct)
puts 'PASS: lobby/direct selection, pending session, room/role, relay disconnect does not open host socket'
