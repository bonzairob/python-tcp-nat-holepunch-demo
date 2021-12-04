#!/usr/bin/env python
import sys
import time
import traceback
import socket
import os
import json
import threading
from queue import Queue



STOP = threading.Event()

HOST_DOMAIN = "yoursite.net"

DEFAULT_NAME = "TestUser"

DEFAULT_GAME = "yourgame"


class ServerConnection(threading.Thread):
    """ Manage a connection to the matchmaking server """

    def __init__(self, queue, host='127.0.0.1', port=3333, connected=None):
        threading.Thread.__init__(self)

        self.queue = queue
        self.host = host
        self.port = port


        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        self.sock.connect((self.host, self.port))
        self.priv_addr = self.sock.getsockname()

        # tell the main thread we connected
        queue.put({'mtype':"connected", 'priv_address':self.priv_addr})

        self.closed = False


    def run(self):

        print("Connecting from", self.priv_addr)
        self.sock.settimeout(2)

        packet_buffer = b""
        size = 1024
        while not STOP.is_set() and not self.closed:
            try:
                data = self.sock.recv(size)


                if data and len(data):

                    if chr(data[-1]) != "\n":
                        packet_buffer += data

                    else:
                        data = packet_buffer + data
                        packet_buffer = b""

                        # what has it got in its packetses?
                        packetses = data.strip().split(b"\n")

                        for p in packetses:
                            self.processServerPacket(p)

                else:
                    print("Disconnected!", data)
                    STOP.set()


            except socket.timeout:
                pass

            except IOError as e:
                print("self.sock.recv fail, disconnecting from server")
                #  [Errno 9] Bad file descriptor in self.sock.recv(size)
                self.sock.close()
                return False

            except Exception as e:
                print("ServerConnection Exception:", e)

                ex_type, ex, tb = sys.exc_info()
                traceback.print_tb(tb)


                self.sock.close()
                return False

        self.sock.close()

        return



    def processServerPacket(self, packet):
        # print("processServerPacket:", packet)
        try:
            packet = json.loads(packet)

        except json.JSONDecodeError as e:
            print("JSON decode error", packet)
            print(e)

            ex_type, ex, tb = sys.exc_info()
            traceback.print_tb(tb)

            return


        # Print packets to console
        if packet['ptype'] != "ping":
            print("processServerPacket:", packet)


        if packet['ptype'] == "pub_address":
            # Receive my own public address back
            self.queue.put({
                'mtype':'pub_address',
                'pub_address':packet['pub_address'],
            })


        elif packet['ptype'] == "ping":
            # Recive a ping, respond wih a pong
            self.send({
                'ptype':'pong',
                'sent_at':packet['sent_at'],
                'received_at':time.time()
            })


        elif packet['ptype'] == "peer_connection":
            # Server is giving me a peer's details
            self.queue.put({
                'mtype':'peer_connection',
                'authority':packet['authority'],
                'to':packet['to'],
            })


        elif packet['ptype'] == "user_join":
            # A peer joined the matchmaking server

            #AUTO REQUEST
            time.sleep(0.2)
            self.queue.put({
                'mtype': 'packet_relay',
                'ptype':'connection_request',
                'key': packet['key']
            })


        elif packet['ptype'] == "connection_requested":
            # A peer is requesting a connection with me

            #AUTO ACCEPT
            self.queue.put({
                'mtype': 'packet_relay',
                'ptype':'connection_accept',
                'key': packet['from_client']
            })



    def send(self, message):
        self.sock.send(bytes(json.dumps(message)+"\n", "utf8"))


    def close(self):
        self.closed = True
        self.sock.close()

        self.queue.put({
            'mtype': 'disconnected'
        })









class HoleHolder(threading.Thread):
    """ Bind the socket, hold it open between disconnecting from the matchmaker and receiving a peer's connection """

    def __init__(self, port):
        threading.Thread.__init__(self)

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

        pub_address = ''
        print("HoleHolder Binding", (pub_address, port))
        self.sock.bind((pub_address, port))


    def run(self):
        # This doesnt need to stay open long as PeerConnection takes over almost immediately

        self.sock.listen(1)
        self.sock.settimeout(2)

        time.sleep(0.5)

        print("Closting HoleHolder!")
        self.sock.close()

        return






class PeerConnection(threading.Thread):
    """ Accept a connection with a peer, and report what happens via a queue """

    def __init__(self, queue, peer_host, peer_port, priv_addr, pub_address):
        threading.Thread.__init__(self)

        self.queue = queue
        self.peer_host = peer_host
        self.peer_port = peer_port

        self.priv_addr = priv_addr
        self.pub_address = pub_address


        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

        bind = '', self.priv_addr[1]
        print("PeerConnection binding", (bind))
        self.sock.bind( tuple(bind) )

        print("PeerConnection connecting to", self.peer_host, self.peer_port)
        self.sock.connect((self.peer_host, self.peer_port))


        print("PeerConnection connected!")
        self.send({'ptype':'handshake'})


    def run(self):    # change here
        self.sock.settimeout(2)

        packet_buffer = b""
        size = 1024
        while not STOP.is_set():
            try:
                data = self.sock.recv(size)


                if data and len(data):

                    if chr(data[-1]) != "\n":
                        packet_buffer += data

                    else:
                        data = packet_buffer + data
                        packet_buffer = b""
                        packetses = str(data, "utf8").strip().split("\n")

                        for packet in packetses:
                            self.processPacket(packet)

                else:
                    print("Data?", data)
                    print("Disconnected!")
                    STOP.set()


            except socket.timeout:
                pass

            except Exception as e:
                print("listenToClient other exception", e)

                ex_type, ex, tb = sys.exc_info()
                traceback.print_tb(tb)

                break

        self.sock.close()

        return



    def processPacket(self, packet):
        # print("processPacket:", packet)
        try:
            packet = json.loads(packet)

        except json.JSONDecodeError as e:
            print("JSON decode error:", packet)
            print(e)

            ex_type, ex, tb = sys.exc_info()
            traceback.print_tb(tb)

            return

        print( packet )

        if packet['ptype'] == "handshake":
            self.queue.put({'mtype':"handshake"})

        else:
            #pass the packet along to the main thread
            packet['mtype'] = 'relay'
            self.queue.put(packet)



    def send(self, message):
        self.sock.send(bytes(json.dumps(message)+"\n", "utf8"))
















class MatchmakerConnection:
    """ Connect to a matchmaking srver, until we get matched to a peer. """
    def __init__(self, host='127.0.0.1', port=3333, name=DEFAULT_NAME):
        self.server_host = host
        self.server_port = port

        self.name = name
        self.priv_address = None
        self.pub_address = None

        #set true when attached to a client
        self.matched = False


        self.connectToServer()


        self.peer_conn_queue = None
        self.hole_holder = None
        self.peer_connection = None



    def connectToServer(self):
        # Start a queue thread for retrieving server data
        self.server_conn_queue =  Queue()
        self.server_conn_queue_thread = threading.Thread(
            target = self.serverConnectionQueueChecker,
            args = ()
        )
        self.server_conn_queue_thread.start()

        # and then start the server connection
        self.server_conn = ServerConnection(self.server_conn_queue, self.server_host, self.server_port, self.name)
        self.server_conn.start()



    def serverConnectionQueueChecker(self):
        """ Check for data received from the server. """

        while not STOP.is_set() and not self.matched:
            msg = self.server_conn_queue.get()
            print("serverConnectionQueueChecker", msg)

            mtype = msg['mtype']

            if mtype == "connected":
                # We connected to the server successfuly, send back some data.

                self.priv_address = msg['priv_address']

                self.server_conn.send({
                    "ptype":"intro",
                    "name":self.name,
                    "game":DEFAULT_GAME,
                    "priv_address": self.priv_address
                })


            elif mtype == "disconnected":
                # Got disconnected, don't need the queue any more
                break


            elif mtype == 'pub_address':
                # Receive my public address
                self.pub_address = msg['pub_address']


            elif mtype == "peer_connection":
                # Make a connection with the given peer
                self.makeConnection(msg['to'], msg['authority'])


            elif mtype == "packet_relay":
                # Relay this packet on to the server
                del(msg['mtype'])
                self.send(msg)

        return



    def say(self, msg):
        self.send({'ptype':"message", 'message':msg})



    def send(self, packet):
        if self.matched:
            self.peer_connection.send(packet)
        else:
            self.server_conn.send(packet)



    def stop(self):
        STOP.set()






    def peerConnectionQueueChecker(self):
        """ Receive messages from my peer connection """
        print("start")

        while not STOP.is_set() and self.matched:
            msg = self.peer_conn_queue.get()
            print("peerConnectionQueueChecker", msg)

            mtype = msg['mtype']

            if mtype == "handshake":
                print("handshaken!")


            elif mtype == "relay":
                # Received a relayed packet

                ptype = msg['ptype']

                if ptype == "disconnect":
                    # Got disconnected, don't need the queue any more
                    break

                elif ptype == 'message':
                    print("message recieved:", msg['message'])

        print("peerConnectionQueueChecker ending")
        return







    def makeConnection(self, peer_address, authority):
        """ Disconnect from the server and connect to a peer. """

        # Listen on the outgoing port that I connected to the server with
        # And send to the peer doing the same thing
        # If we bind the ports quick enough, the router will leave the NAT routing intact and the peer takes over the connection

        peer_host, peer_port = peer_address

        print("Close server connection")
        self.server_conn.close()

        print("Start peer connections")
        self.matched = True

        print("hold open the hole")
        #this seems to hold the connection open by binding faster
        self.hole_holder = HoleHolder(self.pub_address[1])
        self.hole_holder.start()

        #give the peer the chance to do the same
        time.sleep(0.01)

        print("connector")
        #get messages from the peer into the main(ish) thread
        self.peer_conn_queue = Queue()
        self.peer_conn_queue_thread = threading.Thread(
            target = self.peerConnectionQueueChecker,
            args = ()
        )
        self.peer_conn_queue_thread.start()


        #then if we make this after a moment, we can connect to our peer
        self.peer_connection = PeerConnection(
            self.peer_conn_queue,
            peer_host,
            peer_port,
            self.priv_address,
            self.pub_address
        )
        self.peer_connection.start()

        self.hole_holder.join() #then this closes itself












if __name__ == '__main__':
    # logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')
    # startHosting()

    print ('Use --host=x --port=y if you want something other than '+HOST_DOMAIN+':3333' )

    kwargs = {
        'host': HOST_DOMAIN,
        'port': 3333
    }
    for arg in sys.argv:
        if '=' in arg:
            k,v = arg.split('=')
            if "--" in k:
                k = k.strip('-')
            kwargs[k] = v

    if 'port' in kwargs and type(kwargs['port']) != int:
        kwargs['port'] = int(kwargs['port'])


    name = input("Your Name ["+DEFAULT_NAME+"]> ")
    if name == "":
        name = DEFAULT_NAME
    kwargs['name'] = name



    matchmaker_conn = MatchmakerConnection(**kwargs)


    try:
        while True:
            command = input("> ")

            if command == "exit":
                matchmaker_conn.stop()
                break

            elif command == "":
                continue

            elif command.startswith("connect"):
                # "connect 123abc"
                who = command.split(' ')[1]
                matchmaker_conn.send({
                    'ptype':'connection_request',
                    'key': who
                })

            elif command.startswith("accept"):
                # "accept 123abc"
                who = command.split(' ')[1]
                matchmaker_conn.send({
                    'ptype':'connection_accept',
                    'key': who
                })

            elif command.startswith("cancel"):
                # "cancel 123abc"
                who = command.split(' ')[1]
                matchmaker_conn.send({
                    'ptype':'connection_cancel',
                    'key': who
                })

            elif command.startswith("reject"):
                # "reject 123abc"
                who = command.split(' ')[1]
                matchmaker_conn.send({
                    'ptype':'connection_reject',
                    'key': who
                })



            elif command.startswith("say"):
                matchmaker_conn.say(' '.join(command.split(' ')[1:]))



            elif command == "help":
                print("\thelp - this")
                print("\texit - clean shutdown (ctrl+c also fine)")
                print("\tconnect [user key] - ask to connect to this user")
                print("\taccept [user key] - accept a connection request from this user")
                print("\tcancel [user key] - cancel a previous connection request to this user")
                print("\treject [user key] - reject a connection request from this user")

            else:
                print("\tCMD \""+command+"\" not recognised!")


    except KeyboardInterrupt:
        print("^C, stop")
        matchmaker_conn.stop()

    print( "done!")
    os._exit(0)