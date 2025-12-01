from tkinter import *
import tkinter.messagebox as tkMessageBox
from PIL import Image, ImageTk
import socket, threading, sys, traceback, os
import time

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
        
        # Network Statistics
        self.totalPackets = 0
        self.packetsLost = 0
        self.lastSeqNum = 0
        
    def createWidgets(self):
        """Build GUI."""
        self.setup = Button(self.master, width=20, padx=3, pady=3, bg="#A7C7E7")
        self.setup["text"] = "Setup"
        self.setup["command"] = self.setupMovie
        self.setup.grid(row=1, column=0, padx=2, pady=2)

        self.start = Button(self.master, width=20, padx=3, pady=3, bg="#BCEBCB")
        self.start["text"] = "Play"
        self.start["command"] = self.playMovie
        self.start.grid(row=1, column=1, padx=2, pady=2)

        self.pause = Button(self.master, width=20, padx=3, pady=3, bg="#F7C5CC")
        self.pause["text"] = "Pause"
        self.pause["command"] = self.pauseMovie
        self.pause.grid(row=1, column=2, padx=2, pady=2)

        self.teardown = Button(self.master, width=20, padx=3, pady=3, bg="#FFD8B1")
        self.teardown["text"] = "Teardown"
        self.teardown["command"] = self.exitClient
        self.teardown.grid(row=1, column=3, padx=2, pady=2)
        
        self.label = Label(self.master, height=19)
        self.label.grid(row=0, column=0, columnspan=4, sticky=W+E+N+S, padx=5, pady=5) 
        
        self.statusLabel = Label(self.master, text="State: INIT - Waiting for Setup", bd=1, relief=SUNKEN, anchor=W)
        self.statusLabel.grid(row=2, column=0, columnspan=4, sticky=W+E)
        
        self.updateButtonStates()

    def updateButtonStates(self):
        """Enables/Disables buttons and updates status text based on current state."""
        if self.state == self.INIT:
            self.setup['state'] = 'normal'
            self.start['state'] = 'disabled'
            self.pause['state'] = 'disabled'
            self.teardown['state'] = 'disabled'
            self.statusLabel.configure(text="State: INIT (Setup required)")
            
        elif self.state == self.READY:
            self.setup['state'] = 'disabled'
            self.start['state'] = 'normal'
            self.pause['state'] = 'disabled'
            self.teardown['state'] = 'normal'
            self.statusLabel.configure(text="State: READY (Ready to play)")
            
        elif self.state == self.PLAYING:
            self.setup['state'] = 'disabled'
            self.start['state'] = 'disabled'
            self.pause['state'] = 'normal'
            self.teardown['state'] = 'normal'
            self.statusLabel.configure(text="State: PLAYING (Playing...)")

    def setupMovie(self):
        if self.state == self.INIT:
            self.sendRtspRequest(self.SETUP)
    
    def exitClient(self):
        self.sendRtspRequest(self.TEARDOWN)        
        # Wait a moment to send the packet before destroying the window
        self.master.after(100, self._destroy_window)

    def _destroy_window(self):
        self.master.destroy() 
        try:
            os.remove(CACHE_FILE_NAME + str(self.sessionId) + CACHE_FILE_EXT)
        except OSError:
            pass

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
        """Listen for RTP packets."""
        while True:
            try:
                data = self.rtpSocket.recv(20480)
                if data:
                    rtpPacket = RtpPacket()
                    rtpPacket.decode(data)
                    
                    currSeqNum = rtpPacket.seqNum()
                    
                    # Packet Loss Logic
                    if self.totalPackets > 0:
                        diff = currSeqNum - self.lastSeqNum
                        if diff > 1:
                            self.packetsLost += (diff - 1)

                    self.lastSeqNum = currSeqNum
                    self.totalPackets += 1
                    
                    # Update Window Title with Statistics
                    if self.totalPackets > 0:
                        loss_rate = (float(self.packetsLost) / self.totalPackets) * 100
                        title_info = f"StreamingService | Seq: {currSeqNum} | Loss: {loss_rate:.2f}%"
                        # Execute GUI update on main thread to avoid crash
                        self.master.after(0, lambda: self.master.title(title_info))

                    currFrameNbr = currSeqNum 
                                        
                    if currFrameNbr > self.frameNbr: # Discard late packets
                        self.frameNbr = currFrameNbr
                        self.updateMovie(self.writeFrame(rtpPacket.getPayload()))
            except:
                if self.playEvent.isSet(): 
                    break
                
                if self.teardownAcked == 1:
                    try:
                        self.rtpSocket.shutdown(socket.SHUT_RDWR)
                        self.rtpSocket.close()
                    except:
                        pass
                    break
                    
    def writeFrame(self, data):
        """Write the received frame to a temp image file."""
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
        """Connect to the Server."""
        self.rtspSocket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.rtspSocket.connect((self.serverAddr, self.serverPort))
        except:
            tkMessageBox.showwarning('Connection Failed', 'Connection to \'%s\' failed.' %self.serverAddr)
    
    def sendRtspRequest(self, requestCode):
        """Send RTSP request to the server."""
        if requestCode == self.SETUP and self.state == self.INIT:
            threading.Thread(target=self.recvRtspReply).start()
            self.rtspSeq += 1
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
            request += "Accept: application/sdp\r\n" 
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
                
                if reply:
                    self.parseRtspReply(reply.decode('utf-8'))
                
                if self.requestSent == self.TEARDOWN:
                    self.rtspSocket.shutdown(socket.SHUT_RDWR)
                    self.rtspSocket.close()
                    break
            except:
                break

    def parseRtspReply(self, data):
        """Parse the RTSP reply from the server."""
        print("Data received:\n" + data)
        lines = data.splitlines()
        if not lines: return

        try:
            status_code = int(lines[0].split(' ')[1])
        except:
            status_code = 0

        seq_num = 0
        session_id = 0
        
        # Dynamic search for headers
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
                    
                    # Schedule button update on main thread
                    self.master.after(0, self.updateButtonStates)
    
    def openRtpPort(self):
        """Open RTP socket binded to a specified port."""
        self.rtpSocket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.rtpSocket.settimeout(0.5)
        
        try:
            self.state = self.READY
            # Bind to all interfaces to avoid address problems
            self.rtpSocket.bind(("", self.rtpPort))
        except:
            tkMessageBox.showwarning('Unable to Bind', 'Unable to bind PORT=%d' %self.rtpPort)

    def handler(self):
        """Handler on explicitly closing the GUI window."""
        self.pauseMovie()
        if tkMessageBox.askokcancel("Quit?", "Are you sure you want to quit?"):
            self.exitClient()
        else: 
            if self.state == self.PLAYING:
                self.playMovie()