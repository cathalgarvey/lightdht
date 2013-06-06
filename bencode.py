# The contents of this file are subject to the BitTorrent Open Source License
# Version 1.1 (the License).  You may not copy or use this file, in either
# source code or executable form, except in compliance with the License.  You
# may obtain a copy of the License at http://www.bittorrent.com/license/.
#
# Software distributed under the License is distributed on an AS IS basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied.  See the License
# for the specific language governing rights and limitations under the
# License.

# Written by Petru Paler

class BTFailure(Exception):
    pass

def decode_int(x, f):
    f += 1
    newf = x.index(b'e', f)
    n = int(x[f:newf])
    if x[f] == '-':
        if x[f + 1] == b'0'[0]:
            raise ValueError
    elif x[f] == b'0' and newf != f+1:
        raise ValueError
    return (n, newf+1)

def decode_string(x, f):
    colon = x.index(b':', f)
    n = int(x[f:colon])
    str_end = colon+n
    if x[f] == b'0' and colon != f+1:
        raise ValueError("Error decoding string: bad length descriptor?")
    return (x[colon+1:str_end+1], str_end+1)

def decode_list(x, f):
    r, f = [], f+1
    while x[f] != b'e'[0]:
        v, f = decode_func[x[f]](x, f)
        r.append(v)
    return (r, f + 1)

def decode_dict(x, f):
    r, f = {}, f+1
    while x[f] != b'e'[0]:
        k, f = decode_string(x, f)
        # Try to use string keys if possible.
        try:    k = k.decode('utf8')
        except: pass
        r[k], f = decode_func[x[f]](x, f)
    return (r, f + 1)

decode_func = {
        # In py3k, bytes objects, when indexed singly, return ints.
        # So, b'd'[0] == 100, but b'd' != 100. So, decode_func is indexed by
        # integer, not by bytes, but for clarity the byte values are presented
        # here and zero-indexed.
        b'l'[0]: decode_list,
        b'd'[0]: decode_dict,
        b'i'[0]: decode_int,
        b'0'[0]: decode_string,
        b'1'[0]: decode_string,
        b'2'[0]: decode_string,
        b'3'[0]: decode_string,
        b'4'[0]: decode_string,
        b'5'[0]: decode_string,
        b'6'[0]: decode_string,
        b'7'[0]: decode_string,
        b'8'[0]: decode_string,
        b'9'[0]: decode_string }

def bdecode(x):
    try:
        r, l = decode_func[x[0]](x, 0)
    except (IndexError, KeyError, ValueError) as e:
        raise BTFailure("{0}; Not a valid bencoded string:\n".format(type(e))+str(e))
    if l != len(x):
        raise BTFailure("Invalid bencoded value (data after valid prefix)")
    return r

class Bencached(object):

    __slots__ = ['bencoded']

    def __init__(self, s):
        self.bencoded = s

def encode_bencached(x,r):
    r.append(x.bencoded)

def encode_int(x, r):
    r.extend((b'i', str(x).encode('utf8'), b'e'))

def encode_bool(x, r):
    if x:
        encode_int(1, r)
    else:
        encode_int(0, r)
        
def encode_string(x, r):
    r.extend((str(len(x)).encode('utf8'), b':', x.encode('utf8')))

def encode_list(x, r):
    r.append(b'l')
    for i in x:
        encode_func[type(i)](i, r)
    r.append(b'e')

def encode_dict(x,r):
    r.append(b'd')
    ilist = sorted(x.items())
    ilist.sort()
    for k, v in ilist:
        r.extend((str(len(k)).encode('utf8'), b':', k.encode('utf8')))
        encode_func[type(v)](v, r)
    r.append(b'e')

encode_func = {
            Bencached:  encode_bencached,
            int:        encode_int,
            str:        encode_string,
            list:       encode_list,
            tuple:      encode_list,
            dict:       encode_dict,
            bool:       encode_bool }

def bencode(x):
    r = []
    encode_func[type(x)](x, r)
    return b''.join(r)
