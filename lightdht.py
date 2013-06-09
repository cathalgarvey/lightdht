"""
LightDHT - A lightweight python implementation of the Bittorrent distributed
           hashtable.


The aim of LightDHT is to provide a simple, flexible implementation of the
Bittorrent DHT for use in research applications. If you want to trade files,
you have come to the wrong place. LightDHT does not implement the actual
file transfer parts of the bittorrent protocol. It only takes part in the
DHT.

Read README.md for more information.
"""

import socket
import os
import time
import hashlib
import hmac
import struct
import threading
import traceback
import logging
import random
from binhex import binascii

from krpcserver import KRPCServer, KRPCTimeout, KRPCError
from routingtable import PrefixRoutingTable

# See http://docs.python.org/library/logging.html
logger = logging.getLogger(__name__)


#
# Utility functions
def dottedQuadToNum(ip):
    """convert decimal dotted quad string to long integer"""
    # Replace with ip package?
    hexn = ''.join(["%02X" % int(i) for i in ip.split('.')])
    return int(hexn, 16)


def numToDottedQuad(n):
    """convert long int to dotted quad string"""
    d = 256 * 256 * 256
    q = []
    while d > 0:
        m, n = divmod(n, d)
        q.append(str(m))
        d //= 256

    return '.'.join(q)


def decode_nodes(nodes):
    """ Decode node_info into a list of id, connect_info """
    nrnodes = len(nodes) // 26
    nodes = struct.unpack("!" + "20sIH" * nrnodes, nodes)
    for i in range(nrnodes):
        id_, ip, port = nodes[i * 3], numToDottedQuad(nodes[i * 3 + 1]), nodes[i * 3 + 2]
        logger.info("decode_nodes yielding: " + str(id_) + str((ip, port)))
        yield id_, (ip, port)


def encode_nodes(nodes):
    """ Encode a list of (id, connect_info) pairs into a node_info """
    n = []
    for node in nodes:
        # node.c[0] is ip, node.c[1] is port.
        n.extend([node[0], dottedQuadToNum(node[1].c[0]), node[1].c[1]])
    return struct.pack("!" + "20sIH" * len(nodes), *n)


class Node(object):
    def __init__(self, c):
        self.c = c
        self.treq = 0
        self.trep = 0
        self.t = set()
    def __repr__(self):
        return "Node({})".format(self.c)
    __str__ = __repr__

class NotFoundError(RuntimeError):
    pass

class DHT(object):
    def __init__(self, port, id_, version):
        self._id = id_
        self._version = version
        self._server = KRPCServer(port, self._version)

        self._rt = PrefixRoutingTable()

        # Thread details
        self._shutdown_flag = False
        self._thread = None

        # default handler
        self.handler = self.default_handler

        # Behaviour configuration
        #   Am I actively seeking out other nodes?
        self.active_discovery = True
        #   After how many seconds should i do another self-lookup?
        self.self_find_delay = 180.0
        #   How many active node discovery attempts between self-lookups?
        self.active_discoveries = 10

        # Session key
        self._key = os.urandom(20) # 20 random bytes == 160 bits

        #print("Finished __init__.")

    def _get_id(self, target):
        # Retrieve ID to use to communicate with target node
        return self._id

    def start(self):
        """
            Start the DHT node
        """
        #print("In start.")
        self._server.start()
        self._server.handler = self.handler

        # Add the default nodes
        # socket.gethostbyaddr returns (hostname, aliaslist, ipaddrlist)
        # So, this uses the first alternate ip address of router.bittorrent.com
        # according to DNS resolution.
        AltIPs = socket.gethostbyaddr("router.bittorrent.com")[2]
#        DEFAULT_CONNECT_INFO = (random.choice(AltIPs), 6881)
#        # Default_Node is assigned a tuple of (ip, port)
#        DEFAULT_NODE = Node(DEFAULT_CONNECT_INFO)
#        DEFAULT_ID = self._server.ping(os.urandom(20), DEFAULT_NODE)['id']
#        self._rt.update_entry(DEFAULT_ID, DEFAULT_NODE)
        # Prior behaviour was to pick one of the router's alt-ips, this adds
        # all of them..
        for ip in AltIPs:
            Connect_Info = (ip, 6881)
            # Default_Node is assigned a tuple of (ip, port)
            IP_Node = Node(Connect_Info)
            IP_ID = self._server.ping(os.urandom(20), IP_Node)['id']
            logger.info("Adding bootstrap alt-ip from router.bittorrent.com: IP: {0}, NodeID: {1}".format(IP_Node, IP_ID))
            self._rt.update_entry(IP_ID, IP_Node)

        # Start our event thread
        self._thread = threading.Thread(target=self._pump)
        self._thread.daemon = True
        self._thread.start()
        #print("Finished start.")

    def shutdown(self):
        self._server.shutdown()

    def __enter__(self):
        #print("In __enter__.")
        self.start()
        
    def __exit__(self, type_, value, traceback):
        self.shutdown()

    def _pump(self):
        """
            Thread that maintains DHT connectivity and does
            routing table housekeeping.
            Started by self.start()

            The very first thing this function does, is look up itself
            in the DHT. This connects it to neighbouring nodes and enables
            it to give reasonable answers to incoming queries.

            Afterward we look up random nodes to increase our connectedness
            and gather information about the DHT as a whole

        """
        #print("Started _pump thread.")
        # Try to establish links to close nodes
        logger.info("Establishing connections to DHT")
        found_self = False
        while not found_self:
            try:
                self.find_node(self._id)
                found_self = True
            except:
                logger.critical("Exception while starting DHT Maintainence thread:\n\n" + traceback.format_exc())
                time.sleep(1)

        delay = self.self_find_delay

        if self.active_discovery:
            delay //= (self.active_discoveries + 1)

        logger.info("Finished establishing connections to DHT, beginning maintenance.")

        iteration = 0
        while True:
            try:
                time.sleep(delay)
                iteration += 1
                if self.active_discovery and iteration % (self.active_discoveries + 1) != 0:
                    target = hashlib.sha1("this is my salt 2348724" + str(iteration) + self._id).digest()
                    self.find_node(target)
                    logger.info("Tracing done, routing table contains %d nodes", self._rt.node_count())
                else:
                    # Regular maintenance:
                    #  Find N random nodes. Execute a find_node() on them.
                    #  toss them if they come up empty.
                    n = self._rt.sample(self._id, 10, 1)
                    for node_id, c in n:
                        try:
                            #print("In _pump: calling self._server.find_node()")
                            r = self._server.find_node(self._id, c, self._id)
                            #print("In _pump: finished self._server.find_node()")
                            if "nodes" in r:
                                self._process_incoming_nodes(r["nodes"])
                        except KRPCTimeout:
                            # The node did not reply.
                            # Blacklist it.
                            self._rt.bad_node(node_id, c)
                    logger.info("Cleanup, routing table contains {0} nodes".format(self._rt.node_count()))
            except:
                # This loop should run forever. If we get into trouble, log
                # the exception and carry on.
                logger.critical("Exception in DHT maintenance thread:\n\n" + traceback.format_exc())

    def _process_incoming_nodes(self, bnodes):
        # Add them to the routing table
        for node_id, node_c in decode_nodes(bnodes):
            self._rt.update_entry(node_id, Node(node_c))

    def _recurse(self, target, function, max_attempts=10, result_key=None):
        """
            Recursively query the DHT, following "nodes" replies
            until we hit the desired key

            This is the workhorse function used by all recursive queries.
        """
        #print("In _recurse.")
        if isinstance(target, bytes):
            target_hex = binascii.hexlify(target).decode()
        else:
            target_hex = target
        logger.debug("Recursing to target {0}".format(target))
        attempts = 0
        while attempts < max_attempts:
            close_nodes = self._rt.get_close_nodes(target)
            if not close_nodes:
                raise NotFoundError("No close nodes found with self.rt.get_close_nodes for "+str(target)+\
                                    " Current routing table: "+str(self._rt._nodes))
            for id_, node in close_nodes:
                try:
                    #print("Calling function", function, "in _recurse.")
                    r = function(self._get_id(id_), node, target)
                    #print("Finished calling function in _recurse.")
                    logger.debug("Recursion results from %r ", node.c)
                    attempts += 1
                    if result_key and result_key in r:
                        return r[result_key]
                    if "nodes" in r:
                        self._process_incoming_nodes(r["nodes"])
                except KRPCTimeout:
                    # The node did not reply.
                    # Blacklist it.
                    if self._rt.node_count() > 8:
                        logger.error("Node timed out: blacklisting {0}".format(node.c))
                        self._rt.bad_node(id_, node)
                    else:
                        logger.error("Node timed out: Would blacklist, but only 8 nodes known. Node: {0}".format(node.c))
                    continue
                except KRPCError:
                    # Sometimes we just flake out due to UDP being unreliable
                    # Don't sweat it, just log and carry on.
                    logger.error("KRPC Error:\n\n" + traceback.format_exc())

        if result_key:
            # We were expecting a result, but we did not find it!
            # Raise the NotFoundError exception instead of returning None
            raise NotFoundError
        #print("Finished _recurse.")

    def find_node(self, target, attempts=10):
        """
            Recursively call the find_node function to get as
            close as possible to the target node
        """
        if isinstance(target, bytes):
            target_hex = binascii.hexlify(target).decode()
        else:
            target_hex = target
        logger.debug("Tracing to {0}".format(target_hex))
        self._recurse(target, self._server.find_node, max_attempts=attempts)

    def get_peers(self, info_hash, attempts=10):
        """
            Recursively call the get_peers function to fidn peers
            for the given info_hash
        """
        if isinstance(info_hash, bytes):
            info_hash_hex = binascii.hexlify(info_hash).decode()
        else:
            info_hash_hex = info_hash
        logger.debug("Finding peers for {0}".format(info_hash_hex))
        return self._recurse(info_hash, self._server.get_peers, result_key="values", max_attempts=attempts)

    def default_handler(self, rec, c):
        """
            Process incoming requests
        """
        logger.info("REQUEST: %r %r" % (c, rec))
        # Use the request to update the routing table
        peer_id = rec["a"]["id"]
        self._rt.update_entry(peer_id, Node(c))
        # Skeleton response
        resp = {"y": "r", "t": rec["t"], "r": {"id": self._get_id(peer_id)}, "v": self._version}
        if rec["q"] == b"ping":
            self._server.send_krpc_reply(resp, c)
        elif rec["q"] == b"find_node":
            target = rec["a"]["target"]
            resp["r"]["id"] = self._get_id(target)
            resp["r"]["nodes"] = encode_nodes(self._rt.get_close_nodes(target))
            self._server.send_krpc_reply(resp, c)
        elif rec["q"] == b"get_peers":
            # Provide a token so we can receive announces
            # The token is generated using HMAC and a secret
            # session key, so we don't have to remember it.
            # Token is based on nodes id, connection details
            # torrent infohash to avoid clashes in NAT scenarios.
            info_hash = rec["a"]["info_hash"]
            resp["r"]["id"] = self._get_id(info_hash)
            token = hmac.new(self._key, info_hash + peer_id + str(c), hashlib.sha1).digest()
            resp["r"]["token"] = token
            # We don't actually keep any peer administration, so we
            # always send back the closest nodes
            resp["r"]["nodes"] = encode_nodes(self._rt.get_close_nodes(info_hash))
            self._server.send_krpc_reply(resp, c)
        elif rec["q"] == b"announce_peer":
            # First things first, validate the token.
            info_hash = rec["a"]["info_hash"]
            resp["r"]["id"] = self._get_id(info_hash)
            peer_id = rec["a"]["id"]
            token = hmac.new(self._key, info_hash + peer_id + str(c), hashlib.sha1).digest()
            if token != rec["a"]["token"]:
                return  # Ignore the request
            else:
                # We don't actually keep any peer administration, so we
                # just acknowledge.
                self._server.send_krpc_reply(resp, c)
        else:
            logger.error("Unknown request in query %r" % rec)


if __name__ == "__main__":

    # Enable logging:
    # Tell the module's logger to log at level DEBUG
    logger.setLevel(logging.DEBUG)
    logger.addHandler(logging.StreamHandler())
    logging.getLogger("krpcserver").setLevel(logging.DEBUG)
    logging.getLogger("krpcserver").addHandler(logging.StreamHandler())

    # Create a DHT node.
    dht1 = DHT(port=54767, id_=hashlib.sha1(
        "Change this to avoid getting ID clashes").digest(), version="XN\x00\x00")
    # Start it!
    with dht1:
        # Look up peers that are sharing one of the Ubuntu 12.04 ISO torrents
        print(dht1.get_peers("8ac3731ad4b039c05393b5404afa6e7397810b41".decode("hex")))
        # Go to sleep and let the DHT service requests.
        while True:
            time.sleep(1)

