from random import randint
import sys, traceback, threading, socket
import time
from VideoStream import VideoStream
from RtpPacket import RtpPacket

class ServerWorker:
    # Tipos de requisição RTSP
    SETUP = 'SETUP'
    PLAY = 'PLAY'
    PAUSE = 'PAUSE'
    TEARDOWN = 'TEARDOWN'
    DESCRIBE = 'DESCRIBE'
    
    # Estados da Máquina de Estados (FSM)
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    # Códigos de resposta
    OK_200 = 0
    FILE_NOT_FOUND_404 = 1
    CON_ERR_500 = 2
    
    # Tamanho máximo da carga útil RTP (MTU Ethernet seguro ~1400 bytes)
    MAX_RTP_PAYLOAD = 1400 

    clientInfo = {}
    
    def __init__(self, clientInfo):
        self.clientInfo = clientInfo
        
    def run(self):
        """Inicia thread que recebe requisições RTSP do cliente."""
        threading.Thread(target=self.recvRtspRequest).start()
        
    def recvRtspRequest(self):
        """Loop que lê dados RTSP do socket TCP do cliente."""
        connSocket = self.clientInfo['rtspSocket'][0]
        while True:            
            try:
                data = connSocket.recv(256)
                if data:
                    data_str = data.decode('utf-8')
                    print("-" * 20)
                    print(f"RTSP Recebido:\n{data_str}")
                    self.processRtspRequest(data_str)
                else:
                    break
            except:
                break
    
    def processRtspRequest(self, data):
        """Processa requisição RTSP e responde conforme FSM."""
        lines = data.splitlines()
        if not lines: return
        
        line1 = lines[0].split(' ')
        requestType = line1[0]
        filename = line1[1]
        
        # extrai CSeq do cabeçalho
        seq = "0"
        for line in lines:
            if "CSeq" in line:
                try: seq = line.split("CSeq:")[1].strip()
                except: pass
        
        # --- MÁQUINA DE ESTADOS ---

        # SETUP
        if requestType == self.SETUP:
            if self.state == self.INIT:
                print("Processando SETUP...")
                try:
                    self.clientInfo['videoStream'] = VideoStream(filename)
                    self.state = self.READY
                except IOError:
                    self.replyRtsp(self.FILE_NOT_FOUND_404, seq)
                
                self.clientInfo['session'] = randint(100000, 999999)
                self.replyRtsp(self.OK_200, seq)
                
                # extrai porta RTP informada pelo cliente
                try:
                    for line in lines:
                        if "client_port=" in line:
                            self.clientInfo['rtpPort'] = line.split("client_port=")[1].split(';')[0].strip()
                except: 
                    print("Erro ao ler porta RTP")
        
        # PLAY
        elif requestType == self.PLAY:
            if self.state == self.READY:
                print("Processando PLAY...")
                self.state = self.PLAYING
                self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.replyRtsp(self.OK_200, seq)
                
            # inicia thread de envio RTP
                self.clientInfo['event'] = threading.Event()
                self.clientInfo['worker'] = threading.Thread(target=self.sendRtp) 
                self.clientInfo['worker'].start()
        
        # PAUSE
        elif requestType == self.PAUSE:
            if self.state == self.PLAYING:
                print("Processando PAUSE...")
                self.state = self.READY
                self.clientInfo['event'].set()
                self.replyRtsp(self.OK_200, seq)
        
        # TEARDOWN
        elif requestType == self.TEARDOWN:
            print("Processando TEARDOWN...")
            self.clientInfo['event'].set()
            self.replyRtsp(self.OK_200, seq)
            try: self.clientInfo['rtpSocket'].close()
            except: pass
            self.state = self.INIT

        # DESCRIBE (pode ser chamado em qualquer estado)
        elif requestType == self.DESCRIBE:
            print("Processando DESCRIBE...")
            # monta corpo SDP simulado
            sdp_body = "v=0\r\n"
            sdp_body += "o=- " + str(self.clientInfo.get('session', 123456)) + " 1 IN IP4 " + str(self.clientInfo['rtspSocket'][1][0]) + "\r\n"
            sdp_body += "s=Mjpeg Stream Python\r\n"
            sdp_body += "i=Filme MJPEG\r\n"
            sdp_body += "m=video " + str(self.clientInfo.get('rtpPort', 0)) + " RTP/AVP 26\r\n"
            sdp_body += "a=control:streamid=0\r\n"
            
            # Cabeçalho da resposta
            reply = 'RTSP/1.0 200 OK\r\nCSeq: ' + str(seq) + '\r\n'
            reply += 'Content-Type: application/sdp\r\n'
            reply += 'Content-Base: ' + filename + '\r\n'
            reply += 'Content-Length: ' + str(len(sdp_body)) + '\r\n\r\n'
            reply += sdp_body
            
            self.clientInfo['rtspSocket'][0].send(reply.encode('utf-8'))

    def sendRtp(self):
        """Envia frames RTP com fragmentação para suportar UDP."""
        while True:
            self.clientInfo['event'].wait(0.05) # Controle simples de taxa (aprox 20 FPS)
            
            if self.clientInfo['event'].isSet(): 
                break 
            
            # Obtém o quadro inteiro (pode ser grande)
            frame_data = self.clientInfo['videoStream'].nextFrame()
            
            if frame_data: 
                frameNumber = self.clientInfo['videoStream'].frameNbr()
                address = self.clientInfo['rtspSocket'][1][0]
                port = int(self.clientInfo['rtpPort'])
                
                # --- Fragmentação do Quadro ---
                total_len = len(frame_data)
                offset = 0
                
                # Loop para quebrar o quadro em pedaços (Chunks)
                while offset < total_len:
                    end = min(offset + self.MAX_RTP_PAYLOAD, total_len)
                    chunk = frame_data[offset : end]
                    
                    # Define bit de Marcador: 1 se for o último pedaço do quadro, 0 caso contrário
                    marker = 1 if end >= total_len else 0
                    
                    try:
                        packet = self.makeRtp(chunk, frameNumber, marker)
                        self.clientInfo['rtpSocket'].sendto(packet, (address, port))
                        
                        # Pausa minúscula para evitar estouro de buffer no SO (Anti-burst)
                        time.sleep(0.0005) 
                    except Exception as e:
                        print("Erro envio RTP:", e)
                        
                    offset += self.MAX_RTP_PAYLOAD

    def makeRtp(self, payload, frameNbr, marker=0):
        """Empacota dados com cabeçalho RTP."""
        version = 2
        padding = 0
        extension = 0
        cc = 0
        pt = 26 # Payload Type MJPEG
        seqnum = frameNbr
        ssrc = 0 
        
        rtpPacket = RtpPacket()
        rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
        return rtpPacket.getPacket()
            
    def replyRtsp(self, code, seq):
        """Envia resposta RTSP ao cliente."""
        if code == self.OK_200:
            reply = 'RTSP/1.0 200 OK\r\nCSeq: ' + str(seq) + '\r\nSession: ' + str(self.clientInfo['session']) + '\r\n\r\n'
            self.clientInfo['rtspSocket'][0].send(reply.encode('utf-8'))
        elif code == self.FILE_NOT_FOUND_404:
            print("404 NOT FOUND")
        elif code == self.CON_ERR_500:
            print("500 CONNECTION ERROR")