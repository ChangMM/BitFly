# BT协议规范BEP9 (BEP9-Extension for peers to Send Metadata Files)

[英文原文](http://www.bittorrent.org/beps/bep_0009.html)

此扩展的目的是允许客户端在无需先下载 .torrent 文件的情况下加入一个 swarm 并完成文件的下载。 此扩展允许客户端从 peer 下载 metadata。 这让支持支持manage link成了可能，manage link 是一种 web 页上的链接，只包含足够加入 swarm 的信息（info hash）。

##metadata
这个扩展仅仅传输.torrent文件的info-字典字段，这个部分可以由infohash来验证。在这篇文档中，.torrent的这个部分被称为metadata。

metadata 被分块，每个块有16KB(16384字节)，metadata 块从0开始索引，所有块的大小都是16KB，除了最后一个块可能比16KB小。

##extension header
metadata 扩展使用 extension protocol(详见[BEP0010](http://www.bittorrent.org/beps/bep_0010.html))来声称它的存在。它在 extension 握手消息的头部 m 字典加入 ut_metadata 项。它标识了这个消息可以使用这个消息码，同时也可以在握手消息中加入 metadata_size 这个整型字段(不是在 m 字典中)来指定 metadata 的字节数。

Example extension handshake message:

```
{'m': {'ut_metadata', 3}, 'metadata_size': 31235}
```

##extension message
Extension消息都是bencode编码，这里有3类不同的消息：
```
0.request
1.data
2.reject
```
bencode 消息有一个整型关键字字段 msg_type ，与其消息类型对应，同时还有一个关键字段 piece 来表示这个消息说的是 metadata 的哪个块。

为了将来协议的扩展，未识别的消息ID要忽略掉。

##Request
请求消息并不在字典中附加任何关键字，这个消息的回复应当来自支持这个扩展的 peer ，是一个 reject 或者 data 消息，回复必须和请求所指出的片相同。

peer 必须保证它所发送的每个片都通过了 infohash 的检测。即直到 peer 获得了整个 metadata 并通过了 infohash 的验证，才能够发送片。peer 没有获得整个 metadata 时，对收到的所有 metadata 请求都必须直接回复 reject 消息。

example：
```
{'msg_type': 0, 'piece': 0}
d8:msg_typei0e5:piecei0ee
```
这代表请求消息在请求 metadata 的第一片。

###data
这个 data 消息需要在字典中添加一个新的字段，"total_size"。这个关键字段和 extension 头的 "metadata_size" 有相同的含义，这是一个整型。

metadata 片被添加到 bencode字典后面，他不是字典的一部分，但是是消息的一部分(必须包括长度前缀)。

如果这个片是metadata的最后一个片，他可能小于16KB。如果它不是metadata的最后一片，那大小必须是16KB。

example：
```
{'msg_type': 1, 'piece': 0, 'total_size': 3425}
d8:msg_typei1e5:piecei0e10:total_sizei34256eexxxxxxxx...
```
x表示二进制数据(metadata)。

###reject
reject消息没有附件的关键字。它的意思是 peer 没有请求的这个 metadata 片信息。

在客户端收到收到一定数目的消息后，可以通过拒绝请求消息来进行洪泛攻击保护。尤其在 metadata 的数目乘上一个因子时。

example：
```
{'msg_type': 2, 'piece': 0}
d8:msg_typei1e5:piecei0ee
```
##magnet URI format
magnet URI 格式如下：
```
v1: magnet:?xt=urn:btih:<info-hash>&dn=<name>&tr=<tracker-url>&x.pe=<peer-address>
v2: magnet:?xt=urn:btmh:<tagged-info-hash>&dn=<name>&tr=<tracker-url>&x.pe=<peer-address>
```
###<info-hash>
infohash的16进制编码，共40字符。为了与其它的编码兼容，客户端应当也支持32字符的infohash [base32](http://www.ietf.org/rfc/rfc3548.txt)编码。

###<tagged-info-hash>
Is the [multihash](https://github.com/multiformats/multihash) formatted, hex encoded full infohash for torrents in the new metadata format. 'btmh' and 'btih' exact topics may exist in the same magnet if they describe the same hybrid torrent.

###<peer-address>
A peer address expressed as hostname:port, ipv4-literal:port or [ipv6-literal]:port. This parameter can be included to initiate a direct metadata transfer between two clients while reducing the need for external peer sources. It should only be included if the client can discover its public IP address and determine its reachability. Note: Since no URI scheme identifier has been allocated for bittorrent xs= is not used for this purpose.

xt 是唯一强制的参数; dn 是在等待 metadata 时可能供客户端显示的名字。如果只有一个 tr，tr 是 tracker 的 url，如果有很多的 tracker，那么多个 tr 字段会被包含进去。x.pe 也是如此。

dn，tr 和 x.pe 都是可选的。

如果没有指定tracker，客户端应使用DHT [BEP0005]((http://www.bittorrent.org/beps/bep_0010.html))来获取peers
