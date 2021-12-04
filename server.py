#!/usr/bin/env python
import sys
import time
import traceback
import itertools
import socket
import os
import json
import threading
from queue import Queue
import random


def randString(length=6):
    st = ""
    for i in range(length):
        st += random.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789")
    return st



# Threads should run until told otherwise
STOP = threading.Event()


HOST_DOMAIN = "yoursite.net"



class Listener(threading.Thread):
    """ Create a server to listen for and manage client connections. """

    def __init__(self, queue, host='0.0.0.0', port=3333):
        threading.Thread.__init__(self)

        self.queue = queue
        self.host = host
        self.port = port

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((host, port))

        self.clients = {}

        # Ping clients regularly and disconnect any who don't respond
        self.ping_thread = threading.Thread(
            target = self.pingThread,
            args = ()
        )
        self.ping_thread.start()



    def pingThread(self):
        """ Every 5 seconds, ping all clients, and disconnect anyone who hasn't responded for 2 pings. """
        ping_interval = 5

        while not STOP.is_set():
            time.sleep(ping_interval)

            for client in self.clients.values():
                now = time.time()

                if client['lastping'] and client['lastping'] < now - ping_interval*2:
                    self.queue.put({'mtype':'pingout', 'client': client['key']})

                else:
                    self.queue.put({'mtype':'sendping','client': client['key']})



    def run(self):
        """ Indefinitely listen for client connections and manage them. """
        self.sock.listen(1)
        self.sock.settimeout(2.)

        print("[Info]: Listening for connections on {0}, port {1}".format(self.host,self.port))

        while not STOP.is_set():
            try:
                client, address = self.sock.accept()

                # Give everyone a unique key.
                client_key = randString()

                # Store the client's info.
                self.clients[client_key] = {
                    'key':client_key,
                    'client': client,
                    'pub_address': address,
                    'listener': threading.Thread(
                        target = self.listenToClient,
                        args = (client,client_key,address)
                    ),
                    'lastping': None,
                    'disconnected': False
                }
                print("New client detected:", client_key, address)

                # Start the client's own listener thread so we can go back to waiting for new connections.
                self.clients[client_key]['listener'].start()

                # Tell the client their own public address.

                client.send(
                    bytes(
                        json.dumps({'ptype':'pub_address', 'pub_address':address})
                        +"\n",
                        "utf8"
                    )
                )

                #Let the matchmaker know there's a new client.
                self.queue.put({
                    'mtype': 'new_client',
                    'client': client_key,
                    'pub_address': address
                })

            except socket.timeout:
                pass


        self.joinClientThreads()

        print("Listener.run() ending")
        return



    def joinClientThreads(self):
        """ Clean up any remaining threads. """

        for client in self.clients.values():
            client['client'].close()





    def listenToClient(self, client, client_key, pub_address):
        """ Listen to the given client and deal with their packets. """
        client.settimeout(2)

        # Receive this many bytes at a time
        size = 1024

        # Store partial packets
        packet_buffer = b""

        #Reason for disconnect, if needed
        dc_reason = None

        while not STOP.is_set() and not self.clients[client_key]['disconnected']:

            if self.clients[client_key]['disconnected']:
                #This client was marked disconnected, so finish up.
                print("Disconnecting client", client_key)

                dc_reason = "Disconnected"

                break

            try:
                data = client.recv(size)

                if data and len(data):
                    print("listenToClient", client_key, "Recv:", data)

                    if chr(data[-1]) != "\n":
                        # Buffer partial packets
                        packet_buffer += data

                    else:
                        # Join all received data and split by \n
                        data = packet_buffer + data
                        packet_buffer = b""
                        packets = data.strip().split(b"\n")

                        for packet in packets:
                            self.processClientPacket(client_key, packet)

                else:
                    # data = None indicates they disconnected themselves
                    print("listenToClient", client_key, "disconnected")

                    dc_reason = "Disconnected"

                    break


            except socket.timeout:
                pass


            except IOError as e:
                # socket is gone, disconnect
                #  [Errno 9] Bad file descriptor
                #  data = self.sock.recv(size)
                dc_reason="Disconnected"
                break

            except Exception as e:
                # Catch any other kinds of errors

                print("listenToClient Exception", e)

                dc_reason = "Connection lost"

                ex_type, ex, tb = sys.exc_info()
                traceback.print_tb(tb)

                break


        # Let the matchmaker know this client is gone
        self.queue.put({'mtype':'disconnect', 'client':client_key, 'reason':dc_reason})

        del(self.clients[client_key])

        client.close()

        print('listenToCient', client_key, 'done')

        return




    def processClientPacket(self, client_key, packet):
        """ Deal with a single packet from a client connection. JSON with ptype key expected. """
        packet = json.loads(packet)
        print("processClientPacket", packet)
        ptype = packet['ptype']

        if ptype == "intro":
            # Client is a valid connection, let the matchmaker know.
            self.queue.put({
                'mtype': 'client_intro',
                'client': self.clients[client_key],
                'name': packet['name'],
                'game': packet['game'],
                'priv_address': packet['priv_address']
            })


        elif ptype == "pong":
            # Received a response to a ping.

            self.clients[client_key]['lastping'] = time.time()

            #time to send, time to get back, avg
            self.clients[client_key]['latency'] = [
                packet['received_at'] - packet['sent_at'],
                time.time() - packet['sent_at']
            ]
            self.clients[client_key]['latency'].append(
                sum(self.clients[client_key]['latency']) / 2
            )
            print("latency", client_key, self.clients[client_key]['latency'][2])


        elif ptype == "connection_request":
            # Alice requests connection with the Bob. store this on the user!
            self.queue.put({
                'mtype': 'connection_request',
                'client': client_key,
                'to_client': packet['key']
            })

        elif ptype == "connection_accept":
            # Bob accepts Alice's previous request. ignore if not requested
            self.queue.put({
                'mtype': 'connection_accept',
                'client': client_key,
                'from_client': packet['key']
            })

        elif ptype == "connection_cancel":
            # Alice cancels her request to Bob, subsequent accepts do nothing
            self.queue.put({
                'mtype': 'connection_cancel',
                'client': client_key,
                'to_client': packet['key']
            })


        elif ptype == "connection_reject":
            # Bob wants to dismiss Alice's request
            self.queue.put({
                'mtype': 'connection_reject',
                'client': client_key,
                'to_client': packet['key']
            })


    def markDisconnected(self, client_key):
        # Discard this client asap
        if client_key in self.clients:
            self.clients[client_key]['disconnected'] = True











class Matchmaker:
    """ A class to track and connect users. """

    def __init__(self, host='0.0.0.0', port=3333):

        self.host = host

        #Create a listener for new connections, and a queue so it can pass data back.
        self.conn_listener_queue =  Queue()
        self.conn_listener_queue_thread = threading.Thread(
            target = self.listenerQueueChecker,
            args = ()
        )
        self.conn_listener_queue_thread.start()

        self.conn_listener = Listener(self.conn_listener_queue, host, port)
        self.conn_listener.start()

        #real users
        self.users = {}
        self.client_count = 0



    def listenerQueueChecker(self):
        """ Check messages from the Listener server"""

        while not STOP.is_set():

            msg = self.conn_listener_queue.get()
            print("listenerQueueChecker!", msg)

            mtype = msg['mtype']

            if mtype == 'new_client':
                # A new cient has joined, don't know if they're a real user yet though
                self.client_count += 1


            elif mtype == "disconnect":
                # A client has disconnected for some reason.
                # if this client had been introduced, ping other people for user list

                self.client_count -= 1

                if msg['client'] in self.users:
                    self.deleteUserAndAnnounce(
                        msg['client'],
                        msg['reason'] if 'reason' in msg else None
                    )


            elif mtype == "sendping":
                # Time to send a ping to this guy
                try:
                    self.send(msg['client'], {'ptype':"ping", 'sent_at':time.time()})
                except KeyError:
                    pass


            elif mtype == "pingout":
                #the client hasnt responded to a ping for a while
                self.conn_listener.markDisconnected(msg['client'])

                self.client_count -= 1

                if msg['client'] in self.users:
                    self.deleteUserAndAnnounce(msg['client'], "Ping timeout")


            elif mtype == 'client_intro':
                #NOW WE MAKE A USER

                #send all - someone joined
                #send everyone else a join message. send this user the list of users, including themselves


                #in case of testing clients on the actual server
                client_pub_address =  msg['client']['pub_address']
                print("CLIENT PUB ADDR", client_pub_address)
                if client_pub_address[0] == '127.0.0.1':
                    client_pub_address =  (HOST_DOMAIN, client_pub_address[1])

                #set up the new user
                self.users[msg['client']['key']] = {
                    'key': msg['client']['key'],
                    'pub_address': client_pub_address,
                    'priv_address': msg['priv_address'],
                    'client': msg['client']['client'],
                    'name': msg['name'],
                    'game': msg['game'],
                    'current_request': None
                }

                users_same_game_not_new_guy = {
                    k: v
                    for k, v in self.users.items()
                    if v['game'].startswith(msg['game'])
                    and v['key'] != msg['client']['key']
                }

                #send the new client the list of people (not including themselves)
                self.send(msg['client']['key'], {
                    'ptype': 'user_list',
                    'users': {
                        ckey: user['name']
                        for ckey, user in users_same_game_not_new_guy.items()
                    }
                })

                #tell everyone else the new guy joined
                for user in users_same_game_not_new_guy.values():
                    self.send(user['key'], {
                        'ptype':'user_join',
                        'key': msg['client']['key'],
                        'name': msg['name']
                    })



            elif mtype == "connection_request":
                #Alice wants to connect to Bob. store this on Alice.

                self.users[ msg['client'] ]['current_request'] = msg['to_client']

                self.send(msg['to_client'], {
                    'ptype': 'connection_requested',
                    'from_client': msg['client']
                })



            elif mtype == "connection_accept":
                #Bob accepts Alice's previous request.

                if self.users[ msg['from_client'] ]['current_request'] == msg['client']:

                    print("CONNECT!", msg['client'], msg['from_client'])
                    #from_client is the one requesting, client is accepting.
                    #this means client has authority... whatever that means.

                    client_addr = self.users[msg['client']]['pub_address']
                    from_client_addr = self.users[msg['from_client']]['pub_address']

                    # if they have the same IP, send them their local IPs instead
                    if client_addr[0] == from_client_addr[0]:
                        client_addr = self.users[msg['client']]['priv_address']
                        from_client_addr = self.users[msg['from_client']]['priv_address']

                    self.send(msg['client'], {
                        'ptype':'peer_connection',
                        'authority': True,
                        'to': from_client_addr
                    })

                    self.send(msg['from_client'], {
                        'ptype':'peer_connection',
                        'authority': False,
                        'to': client_addr
                    })

                    self.removeConnectedUser(msg['client'])
                    self.removeConnectedUser(msg['from_client'])



                else:
                    #sorry pal, she's moved on already
                    self.send(msg['client'], {
                        'ptype': 'connection_rejected',
                        'from_client': msg['from_client']
                    })



            elif mtype == "connection_cancel":
                #Alice cancels her request to Bob

                if self.users[ msg['client'] ]['current_request'] == msg['to_client']:
                    del(self.users[ msg['client'] ]['current_request'])


                self.send(msg['to_client'], {
                    'ptype': 'connection_cancelled',
                    'from_client': msg['client']
                })



            elif mtype == "connection_reject":
                #Bob isn't interested thanks

                if self.users[ msg['to_client'] ]['current_request'] == msg['client']:
                    del(self.users[ msg['to_client'] ]['current_request'])


                #sorry pal, she's moved on already
                self.send(msg['client'], {
                    'ptype': 'connection_rejected',
                    'from_client': msg['to_client']
                })




    def send(self, client_key, msg):
        """ Encode a JSON message and send it to the client. """
        try:
            self.users[client_key]['client'].send(bytes(json.dumps(msg)+"\n", "utf8"))

        except OSError:
            #OSError: [Errno 9] Bad file descriptor
            #socket ded
            self.conn_listener.markDisconnected(client_key)
            self.deleteUserAndAnnounce(client_key, "Connection lost")



    def sendAll(self, msg):
        """ Broadcast a message to all clients. """
        for client_key in self.users.keys():
            self.send(client_key, msg)



    def deleteUserAndAnnounce(self, client_key, reason="Disconnected"):
        """ When a user leaves, tell anyone who needs to know. """

        leaving_user = self.users[client_key]

        del(self.users[client_key])

        users_same_game = {
            k: v
            for k, v in self.users.items()
            if v['game'].startswith(leaving_user['game'])
        }

        #tell everyone else the new guy left
        for user in users_same_game.values():
            self.send(user['key'], {
                'ptype':'user_left',
                'key': leaving_user['key'],
                'reason': reason
            })


    def removeConnectedUser(self, client_key):
        """ A user got connected, so they're off the matchmaker now. """
        self.users[client_key]['client'].close()

        self.deleteUserAndAnnounce(client_key, "Connected to peer")



    def stop(self):
        """ Stop everything. """
        STOP.set()






if __name__ == '__main__':


    print ('Use --port=y or you get 3333' )

    kwargs = {}
    for arg in sys.argv:
        if '=' in arg:
            k,v = arg.split('=')
            if "--" in k:
                k = k.strip('-')
            kwargs[k] = v

    if 'port' in kwargs and type(kwargs['port']) != int:
        kwargs['port'] = int(kwargs['port'])


    matchmaker = Matchmaker(*kwargs)

    try:
        while True:
            command = input("> ")

            if command == "exit":
                matchmaker.stop()
                break

            elif command == "":
                continue


            elif command == "users":
                print(matchmaker.client_count, "connections,", len(matchmaker.users), "users:")

                show_keys = ["key", "name", "game", "pub_address"]


                longests = {k:len(k) for k in show_keys}
                for user, show_key in itertools.product(matchmaker.users.values(), show_keys):
                    longests[show_key] = max(longests[show_key], len(str(user[show_key])))


                for i,key in enumerate(show_keys):
                    print(key.ljust(longests[key]), end=' | ')
                print("")
                for i,key in enumerate(show_keys):
                    print("-" * longests[key], end='-+-')
                print("")

                for user in matchmaker.users.values():
                    for key in show_keys:
                        print(str(user[key]).ljust(longests[key]), end=' | ')
                    print("")



            elif command.startswith("say"):
                matchmaker.sendAll({
                    'ptype':'server_message',
                    'message': ' '.join(command.split(' ')[1:])
                })


            elif command.startswith("tell"):
                werds = command.split(' ')
                matchmaker.send(
                    werds[1],
                    {
                        'ptype': 'server_message',
                        'message': ' '.join(werds[2:])
                    }
                )


            elif command == "help":
                print("\thelp - this")
                print("\texit - clean shutdown (ctrl+c also fine)")
                print("\tusers - list connected users")
                print("\tsay - message all users")
                print("\ttell X  - message client X directly")

            else:
                print("\tCMD \""+command+"\" not recognised!")


    except KeyboardInterrupt:
        print("^C, stop")
        matchmaker.stop()


    print( "done!")
    os._exit(0)