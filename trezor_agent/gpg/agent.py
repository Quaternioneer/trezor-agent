"""GPG-agent utilities."""
import binascii
import contextlib
import logging
import os

from . import decode, encode, keyring
from .. import server, util

log = logging.getLogger(__name__)


def yield_connections(sock):
    """Run a server on the specified socket."""
    while True:
        log.debug('waiting for connection on %s', sock.getsockname())
        conn, _ = sock.accept()
        conn.settimeout(None)
        log.debug('accepted connection on %s', sock.getsockname())
        yield conn


def serialize(data):
    """Serialize data according to ASSUAN protocol."""
    for c in ['%', '\n', '\r']:
        data = data.replace(c, '%{:02X}'.format(ord(c)))
    return data


def sig_encode(r, s):
    """Serialize ECDSA signature data into GPG S-expression."""
    r = serialize(util.num2bytes(r, 32))
    s = serialize(util.num2bytes(s, 32))
    return '(7:sig-val(5:ecdsa(1:r32:{})(1:s32:{})))\n'.format(r, s)


def pksign(keygrip, digest, algo):
    """Sign a message digest using a private EC key."""
    assert algo == '8'
    pubkey = decode.load_public_key(keyring.export_public_key(user_id=None),
                                    use_custom=True)
    f = encode.Factory.from_public_key(pubkey=pubkey,
                                       user_id=pubkey['user_id'])
    with contextlib.closing(f):
        assert f.pubkey.keygrip == binascii.unhexlify(keygrip)
        r, s = f.conn.sign(binascii.unhexlify(digest))
        result = sig_encode(r, s)
        log.debug('result: %r', result)
        return result


def handle_connection(conn):
    """Handle connection from GPG binary using the ASSUAN protocol."""
    keygrip = None
    digest = None
    algo = None

    conn.sendall('OK\n')
    while True:
        line = keyring.recvline(conn)
        parts = line.split(' ')
        command = parts[0]
        args = parts[1:]
        if command in {'RESET', 'OPTION', 'HAVEKEY', 'SETKEYDESC'}:
            pass  # reply with OK
        elif command == 'GETINFO':
            conn.sendall('D 2.1.11\n')
        elif command == 'AGENT_ID':
            conn.sendall('D TREZOR\n')
        elif command == 'SIGKEY':
            keygrip, = args
        elif command == 'SETHASH':
            algo, digest = args
        elif command == 'PKSIGN':
            sig = pksign(keygrip, digest, algo)
            conn.sendall('D ' + sig)
        else:
            log.error('unknown request: %r', line)
            return

        conn.sendall('OK\n')


def main():
    """Run a simple GPG-agent server."""
    logging.basicConfig(level=logging.INFO,
                        format='%(asctime)s %(levelname)-10s %(message)s')

    sock_path = os.path.expanduser('~/.gnupg/S.gpg-agent')
    with server.unix_domain_socket_server(sock_path) as sock:
        for conn in yield_connections(sock):
            with contextlib.closing(conn):
                try:
                    handle_connection(conn)
                except EOFError:
                    break


if __name__ == '__main__':
    main()
