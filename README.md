# Python TCP NAT Holepunch Demo

A demonstration of the NAT Holepunch networking technique, over TCP, in Python.

I'm not 100% sure *why* it works, but it does.


## Requirements

This system requires the following:
* A publicy-accessible host server (e.g. you can connect to it at yoursite.net or a static IP)...
* ... Capable of running Python 3 programs.

Most connections from a computer are from behind a firewall (the problem this system solves). To host it yourself, you will need to set up your router to forward the server's port to your computer.

If you can't rely on a static IP address, [FreeDNS](https://freedns.afraid.org/) offers free subdomains, but they require updating every time your IP changes.

Other options might be free-tier Amazon AWS or Google Cloud hosting.


## Testing and Hairpinning

The best way to test this is with the following:
* Your public server running
* Your own computer behind a router and firewall
* A friend/acquaintance/enemy's computer, in a different location, behind their own router and firewall

I've added some code to help prevent "hairpinning" - when you send packets to a computer on the same router over the internet, errors can occur if the router can't work out where to send the packets. However, YMMV.


## The Theory

Holepunching as a technique is detailed in [Section 3.4 of Peer-to-Peer Communication Across Network Address Translators](https://bford.info/pub/net/p2pnat/#SECTION00034000000000000000) by Bryan Ford, Pyda Srisuresh and Dan Kegel. My own understanding is fairly vague and, despite the code working, doesn't entirely follow the procedure laid out.

Clients A and B connect to the internet-exposed server, where they are given each others' public IP address and outgoing port. They then bind their ports for listening, and attempt to connect directly to each other, each with both an outgoing and incoming connection.

Meanwhile, their routers want to delete the packet routing entry from the NAT table when a connection to an external server ends. But, if the new connection is made fast enough, the ports stay open/routed and A and B can connect independently of the middleman server.

The Peer-to-Peer Communication paper describes the process of starting the P2P connection, indicating that both clients should attempt to *send* packets to each other first, which may not arrive, but will *punch the hole* for subsequent packets.

However, this implementation works without that, simply leaving ports/connections open and re-binding them quick enough that the NAT table remains in place. 🤷‍♂️

I'm just a hobbyist, not a software engineer, and that paper gave me a headache, so working out the *how* is an exercise left to the user.


## Console commands

Users receive a unique key upon joining, use this for `tell` etc.

Square brackets are just for the template, don't inculde them (e.g. `tell 123abc hello there`)

### Server

* `help` - a list of commands
* `exit` - clean exit. ^C is also fine.
* `users` - list connected users
* `say [message]` - broadcast a message to all connected users
* `tell [user key] [message]` - send a message to specific user

### Client

* `help` - a list of commands
* `exit` - clean exit. ^C is also fine
* `connect [user key]` - ask to connect to this user
* `accept [user key]` - accept a connection request from this user
* `cancel [user key]` - cancel a previous connection request to this user
* `reject [user key]` - reject a connection request from this user