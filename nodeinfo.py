"""
    Basic program to show the useage of lightdht.
    
    We run a dht node and log all incoming queries.
"""
import logging
import time
import os
from binhex import binascii

import lightdht


# Enable logging:
loglevel = logging.DEBUG
req_handler = logging.StreamHandler(open("incoming-requests.log","a"))
req_handler.setLevel(loglevel)
formatter = logging.Formatter("[%(levelname)s@%(created)s] %(message)s")
req_handler.setFormatter(formatter)
stdout_handler = logging.StreamHandler()
stdout_handler.setFormatter(formatter)
logging.getLogger("krpcserver").setLevel(loglevel)
logging.getLogger("krpcserver").addHandler(req_handler)
logging.getLogger("krpcserver").addHandler(stdout_handler)
logging.getLogger("lightdht").setLevel(loglevel)
logging.getLogger("lightdht").addHandler(req_handler)
logging.getLogger("lightdht").addHandler(stdout_handler)

# Create a DHT node.
id_ = os.urandom(20)
dht = lightdht.DHT(port=54768, id_=id_, version="XN\x00\x00") 

# where to put our product
outf = open("get-peers.{}.log".format(binascii.hexlify(id_).decode()), "a")

# handler
def myhandler(rec, c):
    try:    
        if rec["y"] == b"q":
            if rec["q"] == b"get_peers":
                print(";".join(
                    [   str(time.time()),
                        binascii.hexlify(rec["a"].get("id")       ).decode(),
                        binascii.hexlify(rec["a"].get("info_hash")).decode(),
                        repr(c),
                    ]), file=outf)
                outf.flush()
                        
    finally:
        # always ALWAYS pass it off to the real handler
        dht.default_handler(rec,c) 

dht.handler = myhandler
dht.active_discovery = False
dht.self_find_delay = 30

# Start it!
with dht:
    # Debian install DVD:
    target_infohash = binascii.unhexlify("96534331d2d75acf14f8162770495bd5b05a17a9")
    found_infohash = False

    # Go to sleep and let the DHT service requests.
    elapsed = 0
    while True:
        time.sleep(1)
        elapsed += 1
        # Debian install iso: 96534331d2d75acf14f8162770495bd5b05a17a9
        try:
            # Give find_node two minutes to populate..
            if elapsed < 120: continue
            if not found_infohash:
                dht.find_node(target_infohash)
            torrent_peers = dht.get_peers(target_infohash)
            if torrent_peers:
                found_infohash = True
                print("Got peers:\n", torrent_peers)
        except:
            pass
