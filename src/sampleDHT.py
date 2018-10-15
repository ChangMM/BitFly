#!/usr/bin/env python
# encoding: utf-8

import socket
from hashlib import sha1
from random import randint
from struct import unpack
from socket import inet_ntoa
from threading import Timer, Thread
from time import sleep
from collections import deque

from bencode import bencode, bdecode

BOOTSTRAP_NODES = (
    ("router.bittorrent.com", 6881),
    ("dht.transmissionbt.com", 6881),
    ("router.utorrent.com", 6881)
)
TID_LENGTH = 2
RE_JOIN_DHT_INTERVAL = 3
TOKEN_LENGTH = 2


def entropy(length):
    return "".join(chr(randint(0, 255)) for _ in xrange(length))


def random_id():  # 随机生成160位的 node ID
    h = sha1()
    h.update(entropy(20))
    return h.digest()


def decode_nodes(nodes):  # 解析 KRPC 协议中返回的node
    n = []
    length = len(nodes)
    if (length % 26) != 0:
        return n

    for i in range(0, length, 26):
        nid = nodes[i:i+20]
        ip = inet_ntoa(nodes[i+20:i+24])
        port = unpack("!H", nodes[i+24:i+26])[0]
        n.append((nid, ip, port))

    return n


def timer(t, f):  # 设置一个定时器
    Timer(t, f).start()


def get_neighbor(target, nid, end=10):  # 并未实现DHT协议中的找最近节点的Kademila算法
    return target[:end]+nid[end:]


class KNode(object):  # 并未实现DHT中的router table
    def __init__(self, nid, ip, port):
        self.nid = nid
        self.ip = ip
        self.port = port


class DHTClient(Thread):
    def __init__(self, bind_ip, bind_port, max_node_qsize):
        Thread.__init__(self)
        self.setDaemon(True)
        self.max_node_qsize = max_node_qsize
        self.nid = random_id()
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        self.udp.bind((self.bind_ip, self.bind_port))
        self.nodes = deque(maxlen=max_node_qsize)

    def send_krpc(self, msg, address):  # 发送KRPC消息
        try:
            self.udp.sendto(bencode(msg), address)
        except Exception as e:
            print e

    def send_find_node(self, address, nid=None):  # 寻找节点的请求
        nid = get_neighbor(nid, self.nid) if nid else self.nid
        tid = entropy(TID_LENGTH)
        msg = {
            "t": tid,
            "y": "q",
            "q": "find_node",
            "a": {
                "id": nid,
                "target": random_id()
            }
        }
        self.send_krpc(msg, address)

    def join_dht(self):  # 从根节点加入DHT网络中
        if len(self.nodes) == 0:
            for address in BOOTSTRAP_NODES:
                self.send_find_node(address)
        timer(RE_JOIN_DHT_INTERVAL, self.join_dht)

    def auto_send_find_node(self):  # 自动寻找节点
        wait = 1.0 / self.max_node_qsize
        while True:
            try:
                node = self.nodes.popleft()
                self.send_find_node((node.ip, node.port), node.nid)
            except IndexError:
                pass
            sleep(wait)

    def process_find_node_response(self, msg, address):  # 接收查找节点发来的response
        # print "Get find_node response from ", address
        nodes = decode_nodes(msg["r"]["nodes"])
        for node in nodes:
            (nid, ip, port) = node
            if len(nid) != 20:
                continue
            if ip == self.bind_ip:
                continue
            if port < 1 or port > 65535:
                continue
            n = KNode(nid, ip, port)
            # print "the address has node ", nid.encode("hex"), ip, port
            self.nodes.append(n)


class DHTServer(DHTClient):
    def __init__(self, master, bind_ip, bind_port, max_node_qsize):
        DHTClient.__init__(self, bind_ip, bind_port, max_node_qsize)
        
        self.master = master
        self.process_request_actions = {
            "get_peers": self.on_get_peers_request,
            "announce_peer": self.on_announce_peer_request,
        }

        timer(RE_JOIN_DHT_INTERVAL, self.join_dht)

    def run(self):
        self.join_dht()
        while True:
            try:
                (data, address) = self.udp.recvfrom(65536)  # 不断接受来自其他节点的请求
                msg = bdecode(data)
                self.on_message(msg, address)
            except Exception as e:
                print e

    def on_message(self, msg, address):
        try:
            if msg["y"] == "r":
                if "nodes" in msg["r"]:
                    self.process_find_node_response(msg, address)
            elif msg["y"] == "q":
                try:
                    self.process_request_actions[msg["q"]](msg, address)
                except KeyError:
                    self.play_dead(msg, address)
        except KeyError:
            pass

    def on_get_peers_request(self, msg, address):  # 接收到其他节点请求peers的请求
        try:
            print "Get get_peers request from", address
            info_hash = msg["a"]["info_hash"]
            tid = msg["t"]
            _nid = msg["a"]["id"]
            token = info_hash[:TOKEN_LENGTH]  # token 关键字在今后的 announce_peer 请求中必须要携带。
            msg = {
                "t": tid,
                "y": "r",
                "r": {
                    "id": get_neighbor(info_hash, self.nid),
                    "nodes": "",
                    "token": token
                }
            }
            print "The torrent infohash is", info_hash.encode("hex")
            self.send_krpc(msg, address)
        except KeyError:
            pass

    def on_announce_peer_request(self, msg, address):  # 接收announce_peer请求
        # announce_peer请求表明发出该请求的节点正在某个端口下载 torrent文件
        try:
            print "Get announce_peer request from", address
            info_hash = msg["a"]["info_hash"]  # 正在加载的 torrent 文件的 infohash
            token = msg["a"]["token"]
            _nid = msg["a"]["id"]  # 发出请求的节点
            _tid = msg["t"]
            # 第四个参数数是 token，这是在之前的get_peers请求中收到的回复中包含的。
            # 收到announce_peer请求的节点必须检查这个token与之前我们回复给这个节点get_peers的token是否相同。
            # 如果相同，将节点的IP和请求中包含的port端口号在peer联系信息中对应的infohash下。

            if info_hash[:TOKEN_LENGTH] == token:
                if "implied_port" in msg["a"] and msg["a"]["implied_port"] != 0:
                    port = address[1]
                else:
                    port = msg["a"]["port"]
                    if port < 1 or port > 65535:
                        return
                self.master.log(info_hash, (address[0], port))
        except Exception as e:
            print e
        finally:
            self.ok(msg, address)

    def play_dead(self, msg, address):
        try:
            tid = msg["t"]
            msg = {
                "t": tid,
                "y": "e",
                "e": [202, "Server Error"]
            }
            self.send_krpc(msg, address)
        except KeyError:
            pass

    def ok(self, msg, address):
        try:
            tid = msg["t"]
            nid = msg["a"]["id"]
            msg = {
                "t": tid,
                "y": "r",
                "r": {
                    "id": get_neighbor(nid, self.nid)
                }
            }
            self.send_krpc(msg, address)
        except KeyError:
            pass


class Master(object):
    def log(self, info_hash, address=None):
        print "%s from %s:%s" % (
            info_hash.encode("hex"), address[0], address[1]
        )


# using example
if __name__ == "__main__":
    dht = DHTServer(Master(), "0.0.0.0", 6882, max_node_qsize=20)
    dht.start()
    dht.auto_send_find_node()
