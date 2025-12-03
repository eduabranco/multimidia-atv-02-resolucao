from tkinter import *
import tkinter.messagebox as tkMessageBox
from PIL import Image, ImageTk
import socket, threading, sys, os
from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class Client:
    # Constantes de Estado
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT
    
    # Constantes de Requisição RTSP
    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3
    DESCRIBE = 4
    
    def __init__(self, master, serveraddr, serverport, rtpport, filename):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.handler)
        self.createWidgets()
        self.serverAddr = serveraddr
        self.serverPort = int(serverport)
        self.rtpPort = int(rtpport)
        self.fileName = filename
        self.rtspSeq = 0
        self.sessionId = 0
        self.requestSent = -1
        self.teardownAcked = 0
        self.connectToServer()
        self.frameNbr = 0
        
        # Buffer e Estatísticas
        self.buffer = b"" 
        self.packetsLost = 0
        self.totalPackets = 0
        self.lastSeqNum = 0
        # Mapeia CSeq -> requestCode para corresponder replies independentemente da ordem
        self.requests = {}
        
    def createWidgets(self):
        """Inicializa widgets da interface."""
        # Botão Setup
        self.setup = Button(self.master, width=15, padx=3, pady=3, bg="#A7C7E7", text="Setup", command=self.setupMovie)
        self.setup.grid(row=1, column=0, padx=2, pady=2)

        # Botão Describe
        self.describe = Button(self.master, width=15, padx=3, pady=3, bg="#E1C4FF", text="Describe", command=self.describeMovie)
        self.describe.grid(row=1, column=1, padx=2, pady=2)

        # Botão Play
        self.start = Button(self.master, width=15, padx=3, pady=3, bg="#BCEBCB", text="Play", command=self.playMovie)
        self.start.grid(row=1, column=2, padx=2, pady=2)

        # Botão Pause
        self.pause = Button(self.master, width=15, padx=3, pady=3, bg="#F7C5CC", text="Pause", command=self.pauseMovie)
        self.pause.grid(row=1, column=3, padx=2, pady=2)

        # Botão Teardown
        self.teardown = Button(self.master, width=15, padx=3, pady=3, bg="#FFD8B1", text="Teardown", command=self.exitClient)
        self.teardown.grid(row=1, column=4, padx=2, pady=2)
        
        # Área do vídeo
        self.label = Label(self.master, height=19)
        self.label.grid(row=0, column=0, columnspan=5, sticky=W+E+N+S, padx=5, pady=5) 
        
        # Barra de status
        self.statusLabel = Label(self.master, text="Estado: INIT - Aguardando Setup", bd=1, relief=SUNKEN, anchor=W)
        self.statusLabel.grid(row=2, column=0, columnspan=5, sticky=W+E)
        
        self.updateButtonStates()

    def updateButtonStates(self):
        """Atualiza estados dos botões conforme a máquina de estados."""
        if self.state == self.INIT:
            self.setup['state'] = 'normal'
            self.describe['state'] = 'normal'
            self.start['state'] = 'disabled'
            self.pause['state'] = 'disabled'
            self.teardown['state'] = 'disabled'
            self.statusLabel.configure(text="Estado: INIT (Setup necessário)")
        elif self.state == self.READY:
            self.setup['state'] = 'disabled'
            self.describe['state'] = 'normal'
            self.start['state'] = 'normal'
            self.pause['state'] = 'disabled'
            self.teardown['state'] = 'normal'
            self.statusLabel.configure(text="Estado: READY (Pronto)")
        elif self.state == self.PLAYING:
            self.setup['state'] = 'disabled'
            self.describe['state'] = 'disabled'
            self.start['state'] = 'disabled'
            self.pause['state'] = 'normal'
            self.teardown['state'] = 'normal'
            self.statusLabel.configure(text="Estado: PLAYING (Reproduzindo...)")

    def setupMovie(self):
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)
    
    def describeMovie(self):
        """Envia DESCRIBE ao servidor."""
        self.sendRtspRequest(self.DESCRIBE)

    def exitClient(self):
        self.sendRtspRequest(self.TEARDOWN)        
        self.master.after(100, self._destroy_window)
        
    def _destroy_window(self):
        try:
            self.master.destroy()
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)
        except: pass

    def pauseMovie(self):
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)
    
    def playMovie(self):
        if self.state == self.READY:
            threading.Thread(target=self.listenRtp).start()
            self.playEvent = threading.Event()
            self.playEvent.clear()
            self.sendRtspRequest(self.PLAY)
    
    def listenRtp(self):        
        """Recebe pacotes RTP e reconstrói quadros JPEG."""
        while True:
            try:
                # recebe pacote RTP
                data = self.rtpSocket.recv(20480)
                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)
                    
                    # anexa payload ao buffer
                    self.buffer += rtpPacket.getPayload()
                    
                    # procura marcadores JPEG (SOI/EOI)
                    start = self.buffer.find(b'\xff\xd8')
                    end = self.buffer.find(b'\xff\xd9')
                    
                    if start != -1 and end != -1 and end > start:
                        # quadro completo: recorta, salva e atualiza GUI
                        complete_frame = self.buffer[start : end + 2]
                        self.buffer = self.buffer[end + 2:]
                        self.updateMovie(self.writeFrame(complete_frame))
                        
                        # estatísticas de perda (baseado em seqNum)
                        currSeq = rtpPacket.seqNum()
                        if self.totalPackets > 0 and (currSeq - self.lastSeqNum) > 1:
                             self.packetsLost += (currSeq - self.lastSeqNum - 1)
                        self.lastSeqNum = currSeq
                        self.totalPackets += 1
                        
                        loss = (self.packetsLost/self.totalPackets)*100 if self.totalPackets > 0 else 0
                        # atualiza título com taxa de perda (thread-safe)
                        self.master.after(0, lambda: self.master.title(f"RTP Video Player | Perda: {loss:.1f}%"))
                        
                    # limpa buffer se crescer demais
                    if len(self.buffer) > 500000: 
                        print("Limpando buffer sujo.")
                        self.buffer = b""

            except:
                if self.playEvent.isSet(): break
                if self.teardownAcked == 1:
                    try:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                        self.rtpSocket.close()
                    except: pass
                    break
                    
    def writeFrame(self, data):
        """Grava quadro JPEG em arquivo temporário e retorna o caminho."""
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
        try:
            file = open(cachename, "wb")
            file.write(data)
            file.close()
        except: pass
        return cachename
    
    def updateMovie(self, imageFile):
        """Atualiza `Label` com a imagem do arquivo dado."""
        try:
            photo = ImageTk.PhotoImage(Image.open(imageFile))
            self.label.configure(image = photo, height=720) 
            self.label.image = photo
        except: pass
        
    def connectToServer(self):
        """Abre conexão TCP com o servidor RTSP e inicia listener."""
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
            # inicia thread para ler respostas RTSP
            threading.Thread(target=self.recvRtspReply, daemon=True).start()
        except:
            tkMessageBox.showwarning('Falha na Conexão', 'Conexão com \'%s\' falhou.' %self.serverAddr)
    
    def sendRtspRequest(self, requestCode):
        """Envia requisição RTSP e registra o CSeq para corresponder replies."""
        if requestCode == self.SETUP and self.state == self.INIT:
            # thread de recepção já iniciada em connectToServer
            self.rtspSeq += 1
            request = f"SETUP {self.fileName} RTSP/1.0\r\nCSeq: {self.rtspSeq}\r\nTransport: RTP/AVP;unicast;client_port={self.rtpPort}\r\n"
            self.requests[self.rtspSeq] = self.SETUP
            
        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1
            request = f"PLAY {self.fileName} RTSP/1.0\r\nCSeq: {self.rtspSeq}\r\nSession: {self.sessionId}\r\n"
            self.requests[self.rtspSeq] = self.PLAY
            
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1
            request = f"PAUSE {self.fileName} RTSP/1.0\r\nCSeq: {self.rtspSeq}\r\nSession: {self.sessionId}\r\n"
            self.requests[self.rtspSeq] = self.PAUSE
            
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            self.rtspSeq += 1
            request = f"TEARDOWN {self.fileName} RTSP/1.0\r\nCSeq: {self.rtspSeq}\r\nSession: {self.sessionId}\r\n"
            self.requests[self.rtspSeq] = self.TEARDOWN
            
        # Implementação do DESCRIBE
        elif requestCode == self.DESCRIBE:
            self.rtspSeq += 1
            request = f"DESCRIBE {self.fileName} RTSP/1.0\r\nCSeq: {self.rtspSeq}\r\nAccept: application/sdp\r\n"
            self.requests[self.rtspSeq] = self.DESCRIBE
            
        else: return
        
        self.rtspSocket.send(request.encode('utf-8'))
        print('\nDados enviados:\n' + request)
    
    def recvRtspReply(self):
        """Loop que lê respostas RTSP do servidor."""
        while True:
            try:
                reply = self.rtspSocket.recv(4096)
                if reply: self.parseRtspReply(reply.decode('utf-8'))
                
                if self.requestSent == self.TEARDOWN:
                    self.rtspSocket.shutdown(socket.SHUT_RDWR)
                    self.rtspSocket.close()
                    break
            except: break

    def parseRtspReply(self, data):
        """Analisa resposta RTSP e atualiza estado e GUI."""
        print("Dados recebidos:\n" + data)
        lines = data.splitlines()
        if not lines: return
        
        try: status_code = int(lines[0].split(' ')[1])
        except: status_code = 0
        
        seq_num = 0
        session_id = 0
        
        # extrai CSeq e Session
        for line in lines:
            if "CSeq" in line:
                try: seq_num = int(line.split("CSeq:")[1])
                except: pass
            if "Session" in line:
                try: session_id = int(line.split("Session:")[1])
                except: pass

        # Use the CSeq from the reply to identify which request this reply corresponds to.
        if seq_num in self.requests:
            req = self.requests.pop(seq_num)

            # Armazena session se fornecido (SETUP)
            if session_id != 0 and self.sessionId == 0:
                self.sessionId = session_id

            if status_code == 200:
                if req == self.SETUP:
                    self.state = self.READY
                    self.openRtpPort()
                elif req == self.PLAY:
                    # Requer sessão válida
                    if session_id == self.sessionId or self.sessionId == 0:
                        self.state = self.PLAYING
                elif req == self.PAUSE:
                    if session_id == self.sessionId:
                        self.state = self.READY
                        try: self.playEvent.set()
                        except: pass
                elif req == self.TEARDOWN:
                    if session_id == self.sessionId:
                        self.state = self.INIT
                        self.teardownAcked = 1
                elif req == self.DESCRIBE:
                    # Exibe SDP (DESCRIBE não requer Session)
                    parts = data.split('\r\n\r\n')
                    if len(parts) > 1:
                        sdp_body = parts[1]
                        tkMessageBox.showinfo("Session Description (SDP)", sdp_body)
                    else:
                        parts = data.split('\n\n')
                        if len(parts) > 1:
                            sdp_body = parts[1]
                            tkMessageBox.showinfo("Session Description (SDP)", sdp_body)

            # Atualiza botões na Thread principal
            self.master.after(0, self.updateButtonStates)
    
    def openRtpPort(self):
        """Abre socket UDP para receber vídeo."""
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Aumenta buffer do Kernel para 2MB para evitar perda em vídeo HD
        self.rtpSocket.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 2 * 1024 * 1024) 
        
        self.rtpSocket.settimeout(0.5)
        try:
            self.state = self.READY
            self.rtpSocket.bind(("", self.rtpPort))
        except:
            tkMessageBox.showwarning('Erro de Bind', f'Não foi possível usar a PORTA={self.rtpPort}')

    def handler(self):
        """Trata o fechamento da janela."""
        self.pauseMovie()
        if tkMessageBox.askokcancel("Sair?", "Tem certeza que deseja sair?"):
            self.exitClient()
        elif self.state == self.PLAYING:
            self.playMovie()