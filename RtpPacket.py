from time import time
HEADER_SIZE = 12

class RtpPacket:    
    header = bytearray(HEADER_SIZE)
    
    def __init__(self):
        pass
        
    def encode(self, version, padding, extension, cc, seqnum, marker, pt, ssrc, payload):
        """Codifica pacote RTP (cabeçalho + payload)."""
        timestamp = int(time())
        header = bytearray(HEADER_SIZE)
        
        # Byte 0: versão | padding | extension | cc
        header[0] = ((version & 0x03) << 6) | ((padding & 0x01) << 5) | ((extension & 0x01) << 4) | (cc & 0x0F)
        
        # Byte 1: marker (1 bit) | payload type (7 bits)
        header[1] = ((marker & 0x01) << 7) | (pt & 0x7F)
        
        # Bytes 2-3: número de sequência (16 bits)
        header[2] = (seqnum >> 8) & 0xFF
        header[3] = seqnum & 0xFF
        
        # Bytes 4-7: timestamp (32 bits)
        header[4] = (timestamp >> 24) & 0xFF
        header[5] = (timestamp >> 16) & 0xFF
        header[6] = (timestamp >> 8) & 0xFF
        header[7] = timestamp & 0xFF
        
        # Bytes 8-11: SSRC (32 bits)
        header[8] = (ssrc >> 24) & 0xFF
        header[9] = (ssrc >> 16) & 0xFF
        header[10] = (ssrc >> 8) & 0xFF
        header[11] = ssrc & 0xFF
        
        self.header = header
        self.payload = payload
        
    def decode(self, byteStream):
        """Decodifica pacote RTP a partir de bytes."""
        self.header = bytearray(byteStream[:HEADER_SIZE])
        self.payload = byteStream[HEADER_SIZE:]
    
    def version(self):
        return int(self.header[0] >> 6)
    
    def seqNum(self):
        seqNum = self.header[2] << 8 | self.header[3]
        return int(seqNum)
    
    def timestamp(self):
        timestamp = self.header[4] << 24 | self.header[5] << 16 | self.header[6] << 8 | self.header[7]
        return int(timestamp)
    
    def payloadType(self):
        pt = self.header[1] & 127
        return int(pt)
    
    def getPayload(self):
        return self.payload
        
    def getPacket(self):
        return self.header + self.payload