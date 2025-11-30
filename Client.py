from tkinter import *
import tkinter.messagebox as tkMessageBox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os

from RtpPacket import RtpPacket

CACHE_FILE_NAME = "cache-"
CACHE_FILE_EXT = ".jpg"

class Client:
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT
    
    SETUP = 0
    PLAY = 1
    PAUSE = 2
    TEARDOWN = 3
    DESCRIBE = 4 
    # Initiation..
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
        
    def createWidgets(self):
        """Build GUI."""
        # Create Setup button
        self.setup = Button(self.master, width=20, padx=3, pady=3)
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2)
        
        # Create Play button        
        self.start = Button(self.master, width=20, padx=3, pady=3)
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2)
        
        # Create Pause button            
        self.pause = Button(self.master, width=20, padx=3, pady=3)
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2)
        
        # Create Teardown button
        self.teardown = Button(self.master, width=20, padx=3, pady=3)
        self.teardown["text"] = "Teardown"
        self.teardown["command"] =  self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2)
        
        # Create a label to display the movie
        self.label = Label(self.master, height=19)
        self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5) 
    
    def setupMovie(self):
        """Setup button handler."""
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)
    
    def exitClient(self):
        """Teardown button handler."""
        self.sendRtspRequest(self.TEARDOWN)        
        self.master.destroy() # Close the gui window
        try:
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT) # Delete the cache image from video
        except OSError:
            pass

    def pauseMovie(self):
        """Pause button handler."""
        if self.state == self.PLAYING:
            self.sendRtspRequest(self.PAUSE)
    
    def playMovie(self):
        """Play button handler."""
        if self.state == self.READY:
            # Create a new thread to listen for RTP packets
            threading.Thread(target=self.listenRtp).start()
            self.playEvent = threading.Event()
            self.playEvent.clear()
            self.sendRtspRequest(self.PLAY)
    
    def listenRtp(self):        
        """Listen for RTP packets."""
        while True:
            try:
                data = self.rtpSocket.recv(20480)
                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)
                    
                    currFrameNbr = rtpPacket.seqNum()
                    # print("Current Seq Num: " + str(currFrameNbr))
                                        
                    if currFrameNbr > self.frameNbr: # Discard the late packet
                        self.frameNbr = currFrameNbr
                        self.updateMovie(self.writeFrame(rtpPacket.getPayload()))
            except:
                # Stop listening upon requesting PAUSE or TEARDOWN
                if self.playEvent.isSet(): 
                    break
                
                # Upon receiving ACK for TEARDOWN request,
                # close the RTP socket
                if self.teardownAcked == 1:
                    try:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                        self.rtpSocket.close()
                    except:
                        pass
                    break
                    
    def writeFrame(self, data):
        """Write the received frame to a temp image file. Return the image file."""
        cachename = CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT
        file = open(cachename, "wb")
        file.write(data)
        file.close()
        
        return cachename
    
    def updateMovie(self, imageFile):
        """Update the image file as video frame in the GUI."""
        photo = ImageTk.PhotoImage(Image.open(imageFile))
        self.label.configure(image = photo, height=288) 
        self.label.image = photo
        
    def connectToServer(self):
        """Connect to the Server. Start a new RTSP/TCP session."""
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
        except:
            tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
    
    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""
        
        # Setup request
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply).start()
            self.rtspSeq += 1
            
            # MELHORIA: Uso de \r\n conforme RFC 2326
            request = "SETUP " + self.fileName + " RTSP/1.0\r\n"
            request += "CSeq: " + str(self.rtspSeq) + "\r\n"
            request += "Transport: RTP/AVP;unicast;client_port=" + str(self.rtpPort) + "\r\n"
            
            self.requestSent = self.SETUP
            
        elif requestCode == self.PLAY and self.state == self.READY:
            self.rtspSeq += 1
            request = "PLAY " + self.fileName + " RTSP/1.0\r\n"
            request += "CSeq: " + str(self.rtspSeq) + "\r\n"
            request += "Session: " + str(self.sessionId) + "\r\n"
            self.requestSent = self.PLAY
            
        elif requestCode == self.PAUSE and self.state == self.PLAYING:
            self.rtspSeq += 1
            request = "PAUSE " + self.fileName + " RTSP/1.0\r\n"
            request += "CSeq: " + str(self.rtspSeq) + "\r\n"
            request += "Session: " + str(self.sessionId) + "\r\n"
            self.requestSent = self.PAUSE
            
        elif requestCode == self.TEARDOWN and not self.state == self.INIT:
            self.rtspSeq += 1
            request = "TEARDOWN " + self.fileName + " RTSP/1.0\r\n"
            request += "CSeq: " + str(self.rtspSeq) + "\r\n"
            request += "Session: " + str(self.sessionId) + "\r\n"
            self.requestSent = self.TEARDOWN
        elif requestCode == self.DESCRIBE:
            self.rtspSeq += 1
            request = "DESCRIBE " + self.fileName + " RTSP/1.0\r\n"
            request += "CSeq: " + str(self.rtspSeq) + "\r\n"
            request += "Accept: application/sdp\r\n" # Cabeçalho típico
            self.requestSent = self.DESCRIBE
        else:
            return
        
        
        self.rtspSocket.send(request.encode('utf-8'))
        print('\nData sent:\n' + request)
    
    def recvRtspReply(self):
        """Receive RTSP reply from the server."""
        while True:
            try:
                reply = self.rtspSocket.recv(1024)
                
                # MELHORIA: Detectar se o servidor fechou a conexão
                if not reply:
                    break
                
                self.parseRtspReply(reply.decode('utf-8'))
            except:
                break # Encerra se houver erro de socket
            
            # Fecha se foi um Teardown
            if self.requestSent == self.TEARDOWN:
                try:
                    self.rtspSocket.shutdown(socket.SHUT_RDWR)
                    self.rtspSocket.close()
                except:
                    pass
                break

    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server robustly."""
        print("Data received:\n" + data)
        # MELHORIA: splitlines lida com \r\n e \n automaticamente
        lines = data.splitlines()
        if not lines: return

        # Parse seguro do código de status
        try:
            status_code = int(lines[0].split(' ')[1])
        except:
            status_code = 0

        # MELHORIA: Busca dinâmica pelos cabeçalhos em vez de posições fixas
        seq_num = 0
        session_id = 0
        
        for line in lines[1:]:
            parts = line.split(':')
            if len(parts) >= 2:
                header_name = parts[0].strip().lower()
                header_val = parts[1].strip()
                
                if header_name == 'cseq':
                    try: seq_num = int(header_val)
                    except: pass
                elif header_name == 'session':
                    try: session_id = int(header_val)
                    except: pass

        if seq_num == self.rtspSeq:
            if self.sessionId == 0:
                self.sessionId = session_id
            
            if self.sessionId == session_id:
                if status_code == 200: 
                    if self.requestSent == self.SETUP:
                        self.state = self.READY
                        self.openRtpPort() 
                    elif self.requestSent == self.PLAY:
                        self.state = self.PLAYING
                    elif self.requestSent == self.PAUSE:
                        self.state = self.READY
                        self.playEvent.set()
                    elif self.requestSent == self.TEARDOWN:
                        self.state = self.INIT
                        self.teardownAcked = 1
    
    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtpSocket.settimeout(0.5)
        
        try:
            self.state = self.READY
            # Bind em todas as interfaces para evitar problemas de endereço
            self.rtpSocket.bind(("", self.rtpPort))
        except:
            tkMessageBox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else: # When the user presses cancel, resume playing.
            self.playMovie()

    def describeMovie(self):
        self.sendRtspRequest(self.DESCRIBE)