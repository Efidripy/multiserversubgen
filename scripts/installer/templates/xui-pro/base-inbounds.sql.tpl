DELETE FROM settings WHERE "key" IN (
  'subPort','subPath','subURI','subJsonPath','subJsonURI','subEnable'
);

INSERT INTO settings ("key", "value") VALUES ('subPort', '__SUB_PORT__');
INSERT INTO settings ("key", "value") VALUES ('subPath', '/__SUB_PATH__/');
INSERT INTO settings ("key", "value") VALUES ('subURI', '__SUB_URI__');
INSERT INTO settings ("key", "value") VALUES ('subJsonPath', '__JSON_PATH__');
INSERT INTO settings ("key", "value") VALUES ('subJsonURI', '__JSON_URI__');
INSERT INTO settings ("key", "value") VALUES ('subEnable', 'true');

DELETE FROM client_traffics WHERE email IN ('first', 'first_1', 'firstX', 'firstT');
DELETE FROM inbounds WHERE tag IN ('inbound-8443', 'inbound-__WS_PORT__', 'inbound-/dev/shm/uds2023.sock,0666:0|', 'inbound-__TROJAN_PORT__');

INSERT INTO client_traffics ("inbound_id","enable","email","up","down","all_time","expiry_time","total","reset","last_online")
VALUES
  (1,1,'first',0,0,0,0,0,0,0),
  (2,1,'first_1',0,0,0,0,0,0,0),
  (3,1,'firstX',0,0,0,0,0,0,0),
  (4,1,'firstT',0,0,0,0,0,0,0);

INSERT INTO inbounds ("user_id","up","down","total","all_time","remark","enable","expiry_time","traffic_reset","last_traffic_reset_time","listen","port","protocol","settings","stream_settings","tag","sniffing")
VALUES (
  1,0,0,0,0,'reality',1,0,'never',0,'',8443,'vless',
  '{
    "clients":[{"id":"__UUID_REALITY__","flow":"xtls-rprx-vision","email":"first","limitIp":0,"totalGB":0,"expiryTime":0,"enable":true,"tgId":"","subId":"first","reset":0}],
    "decryption":"none",
    "fallbacks":[]
  }',
  '{
    "network":"tcp",
    "security":"reality",
    "externalProxy":[{"forceTls":"same","dest":"__DOMAIN__","port":443,"remark":""}],
    "realitySettings":{
      "show":false,
      "xver":0,
      "target":"127.0.0.1:9443",
      "serverNames":["__REALITY_DOMAIN__"],
      "privateKey":"__PRIVATE_KEY__",
      "minClient":"",
      "maxClient":"",
      "maxTimediff":0,
      "shortIds":__SHORT_IDS_JSON__,
      "settings":{"publicKey":"__PUBLIC_KEY__","fingerprint":"random","serverName":"","spiderX":"/"}
    },
    "tcpSettings":{"acceptProxyProtocol":true,"header":{"type":"none"}}
  }',
  'inbound-8443',
  '{"enabled":false,"destOverride":["http","tls","quic","fakedns"],"metadataOnly":false,"routeOnly":false}'
);

INSERT INTO inbounds ("user_id","up","down","total","all_time","remark","enable","expiry_time","traffic_reset","last_traffic_reset_time","listen","port","protocol","settings","stream_settings","tag","sniffing")
VALUES (
  1,0,0,0,0,'ws',1,0,'never',0,'',__WS_PORT__,'vless',
  '{
    "clients":[{"id":"__UUID_WS__","flow":"","email":"first_1","limitIp":0,"totalGB":0,"expiryTime":0,"enable":true,"tgId":"","subId":"first","reset":0}],
    "decryption":"none",
    "fallbacks":[]
  }',
  '{
    "network":"ws",
    "security":"none",
    "externalProxy":[{"forceTls":"tls","dest":"__DOMAIN__","port":443,"remark":""}],
    "wsSettings":{"acceptProxyProtocol":false,"path":"/__WS_PORT__/__WS_PATH__","host":"__DOMAIN__","headers":{}}
  }',
  'inbound-__WS_PORT__',
  '{"enabled":false,"destOverride":["http","tls","quic","fakedns"],"metadataOnly":false,"routeOnly":false}'
);

INSERT INTO inbounds ("user_id","up","down","total","all_time","remark","enable","expiry_time","traffic_reset","last_traffic_reset_time","listen","port","protocol","settings","stream_settings","tag","sniffing")
VALUES (
  1,0,0,0,0,'xhttp',1,0,'never',0,'/dev/shm/uds2023.sock,0666',0,'vless',
  '{
    "clients":[{"id":"__UUID_XHTTP__","flow":"","email":"firstX","limitIp":0,"totalGB":0,"expiryTime":0,"enable":true,"tgId":"","subId":"first","reset":0}],
    "decryption":"none",
    "fallbacks":[]
  }',
  '{
    "network":"xhttp",
    "security":"none",
    "externalProxy":[{"forceTls":"tls","dest":"__DOMAIN__","port":443,"remark":""}],
    "xhttpSettings":{"path":"/__XHTTP_PATH__","host":"","headers":{},"scMaxBufferedPosts":30,"scMaxEachPostBytes":"1000000","noSSEHeader":false,"xPaddingBytes":"100-1000","mode":"packet-up"},
    "sockopt":{"acceptProxyProtocol":false,"tcpFastOpen":true,"mark":0,"tproxy":"off","tcpMptcp":true,"tcpNoDelay":true,"domainStrategy":"UseIP","tcpMaxSeg":1440,"dialerProxy":"","tcpKeepAliveInterval":0,"tcpKeepAliveIdle":300,"tcpUserTimeout":10000,"tcpcongestion":"bbr","V6Only":false,"tcpWindowClamp":600,"interface":""}
  }',
  'inbound-/dev/shm/uds2023.sock,0666:0|',
  '{"enabled":true,"destOverride":["http","tls","quic","fakedns"],"metadataOnly":false,"routeOnly":false}'
);

INSERT INTO inbounds ("user_id","up","down","total","all_time","remark","enable","expiry_time","traffic_reset","last_traffic_reset_time","listen","port","protocol","settings","stream_settings","tag","sniffing")
VALUES (
  1,0,0,0,0,'trojan-grpc',1,0,'never',0,'',__TROJAN_PORT__,'trojan',
  '{
    "clients":[{"comment":"","email":"firstT","enable":true,"expiryTime":0,"limitIp":0,"password":"__TROJAN_PASS__","reset":0,"subId":"first","tgId":0,"totalGB":0}],
    "fallbacks":[]
  }',
  '{
    "network":"grpc",
    "security":"none",
    "externalProxy":[{"forceTls":"tls","dest":"__DOMAIN__","port":443,"remark":""}],
    "grpcSettings":{"serviceName":"/__TROJAN_PORT__/__TROJAN_PATH__","authority":"__DOMAIN__","multiMode":false}
  }',
  'inbound-__TROJAN_PORT__',
  '{"enabled":false,"destOverride":["http","tls","quic","fakedns"],"metadataOnly":false,"routeOnly":false}'
);
