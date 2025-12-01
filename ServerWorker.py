from random import randint
import sys, traceback, threading, socket

from VideoStream import VideoStream
from RtpPacket import RtpPacket

class ServerWorker:
    SETUP = 'SETUP'
    PLAY = 'PLAY'
    PAUSE = 'PAUSE'
    TEARDOWN = 'TEARDOWN'
    DESCRIBE = 'DESCRIBE'
    
    INIT = 0
    READY = 1
    PLAYING = 2
    state = INIT

    OK_200 = 0
    FILE_NOT_FOUND_404 = 1
    CON_ERR_500 = 2
    
    clientInfo = {}
    
    def __init__(self, clientInfo):
        self.clientInfo = clientInfo
        
    def run(self):
        threading.Thread(target=self.recvRtspRequest).start()
        
    def recvRtspRequest(self):
        """Receive RTSP request from the client."""
        connSocket = self.clientInfo['rtspSocket'][0]
        while True:            
            data = connSocket.recv(256)
            if data:
                # Decode bytes to string for processing
                data_str = data.decode('utf-8')
                print("Data received:\n" + data_str)
                self.processRtspRequest(data_str)
    
    def processRtspRequest(self, data):
        """Process RTSP request sent from the client."""
        # Get the request type - use splitlines() which is more robust
        request = data.splitlines()
        line1 = request[0].split(' ')
        requestType = line1[0]
        
        # Get the media file name
        filename = line1[1]

        # Get the RTSP sequence number 
        seq = request[1].split(' ')
        
        # Process SETUP request
        if requestType == self.SETUP:
            if self.state == self.INIT:
                # Update state
                print("processing SETUP\n")
                
                try:
                    self.clientInfo['videoStream'] = VideoStream(filename)
                    self.state = self.READY
                except IOError:
                    self.replyRtsp(self.FILE_NOT_FOUND_404, seq[1])
                
                # Generate a randomized RTSP session ID
                self.clientInfo['session'] = randint(100000, 999999)
                
                # Send RTSP reply
                self.replyRtsp(self.OK_200, seq[1])
                
                # Get the RTP/UDP port from the last line - robust extraction
                try:
                    for line in request:
                        if "client_port" in line:
                            # Get value after client_port= and remove ; or spaces
                            self.clientInfo['rtpPort'] = line.split("client_port=")[1].split(';')[0].strip()
                except:
                    print("Error parsing RTP port")
        
        # Process PLAY request         
        elif requestType == self.PLAY:
            if self.state == self.READY:
                print("processing PLAY\n")
                self.state = self.PLAYING
                
                # Create a new socket for RTP/UDP
                self.clientInfo["rtpSocket"] = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                
                self.replyRtsp(self.OK_200, seq[1])
                
                # Create a new thread and start sending RTP packets
                self.clientInfo['event'] = threading.Event()
                self.clientInfo['worker']= threading.Thread(target=self.sendRtp) 
                self.clientInfo['worker'].start()
        
        # Process PAUSE request
        elif requestType == self.PAUSE:
            if self.state == self.PLAYING:
                print("processing PAUSE\n")
                self.state = self.READY
                
                self.clientInfo['event'].set()
            
                self.replyRtsp(self.OK_200, seq[1])
        
        # Process TEARDOWN request
        elif requestType == self.TEARDOWN:
            print("processing TEARDOWN\n")

            self.clientInfo['event'].set()
            
            self.replyRtsp(self.OK_200, seq[1])
            
            # Close the RTP socket
            try:
                self.clientInfo['rtpSocket'].close()
            except:
                pass
        
        # Process DESCRIBE request
        elif requestType == self.DESCRIBE:
            print("processing DESCRIBE\n")
            self.replyRtsp(self.OK_200, seq[1], is_describe=True)
            
    def sendRtp(self):
        """Send RTP packets over UDP."""
        while True:
            self.clientInfo['event'].wait(0.05) 
            
            # Stop sending if request is PAUSE or TEARDOWN
            if self.clientInfo['event'].isSet(): 
                break 
                
            data = self.clientInfo['videoStream'].nextFrame()
            if data: 
                frameNumber = self.clientInfo['videoStream'].frameNbr()
                try:
                    address = self.clientInfo['rtspSocket'][1][0]
                    port = int(self.clientInfo['rtpPort'])
                    self.clientInfo['rtpSocket'].sendto(self.makeRtp(data, frameNumber),(address,port))
                except:
                    print("Connection Error")

    def makeRtp(self, payload, frameNbr):
        """RTP-packetize the video data."""
        version = 2
        padding = 0
        extension = 0
        cc = 0
        marker = 0
        pt = 26 # MJPEG type
        seqnum = frameNbr
        ssrc = 0 
        
        rtpPacket = RtpPacket()
        
        rtpPacket.encode(version, padding, extension, cc, seqnum, marker, pt, ssrc, payload)
        
        return rtpPacket.getPacket()
        
    def replyRtsp(self, code, seq, is_describe=False):
        """Send RTSP reply to the client."""
        connSocket = self.clientInfo['rtspSocket'][0]
        
        if code == self.OK_200:
            reply = 'RTSP/1.0 200 OK\r\nCSeq: ' + seq + '\r\nSession: ' + str(self.clientInfo['session']) + '\r\n'
            
            if is_describe:
                # Generate SDP (Session Description Protocol)
                # v=0 (version)
                # o (owner/creator and session identifier)
                # s (session name)
                # c (connection information)
                # t (time session is active - 0 0 means permanent)
                # m (media: video <port> RTP/AVP <format>)
                # a (attribute: control)
                
                host = self.clientInfo['rtspSocket'][1][0]
                port = self.clientInfo.get('rtpPort', '0')
                
                sdp_body = f"v=0\r\n"
                sdp_body += f"o=- {self.clientInfo['session']} 1 IN IP4 {host}\r\n"
                sdp_body += f"s=RTSP Session\r\n"
                sdp_body += f"c=IN IP4 {host}\r\n"
                sdp_body += f"t=0 0\r\n"
                sdp_body += f"m=video {port} RTP/AVP 26\r\n"
                sdp_body += f"a=control:streamid=0\r\n"
                
                reply += f"Content-Base: {self.clientInfo.get('videoStream', 'movie.Mjpeg')}\r\n"
                reply += f"Content-Type: application/sdp\r\n"
                reply += f"Content-Length: {len(sdp_body)}\r\n\r\n"
                reply += sdp_body
            else:
                reply += '\r\n'  # Finalize normal header
            
            # Encode string to bytes for Python 3
            connSocket.send(reply.encode('utf-8'))
        
        # Error messages
        elif code == self.FILE_NOT_FOUND_404:
            print("404 NOT FOUND")
        elif code == self.CON_ERR_500:
            print("500 CONNECTION ERROR")